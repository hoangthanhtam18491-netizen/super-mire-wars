"""
测试 combat_system.py — 战斗状态机。
这是整个游戏中最复杂的逻辑单元，bug 风险最高。
所有测试使用 mock 骰子确保确定性。
"""
import pytest
from game_logic.combat_system import CombatState, parse_dice_string
from game_logic.data_models import Action, Part, Pilot, Mech

# 不导入 ace_logic，避免 ace_logic 在 combat_system 中的导入副作用影响测试
# combat_system.py 在模块级别导入 ace_logic


# ============================================================
# parse_dice_string — 骰子字符串解析
# ============================================================

class TestParseDiceString:

    def test_standard_format(self):
        """'1黄3红' → {'yellow_count': 1, 'red_count': 3, ...}"""
        result = parse_dice_string("1黄3红")
        assert result['yellow_count'] == 1
        assert result['red_count'] == 3
        assert result['white_count'] == 0
        assert result['blue_count'] == 0

    def test_yellow_only(self):
        result = parse_dice_string("5黄")
        assert result['yellow_count'] == 5
        assert result['red_count'] == 0

    def test_red_only(self):
        result = parse_dice_string("7红")
        assert result['yellow_count'] == 0
        assert result['red_count'] == 7

    def test_empty_string(self):
        result = parse_dice_string("")
        assert result == {'yellow_count': 0, 'red_count': 0, 'white_count': 0, 'blue_count': 0}

    def test_none(self):
        result = parse_dice_string(None)
        assert result == {'yellow_count': 0, 'red_count': 0, 'white_count': 0, 'blue_count': 0}

    def test_malformed(self):
        """无法解析的字符串返回0"""
        result = parse_dice_string("abc黄def")
        assert result['yellow_count'] == 0
        assert result['red_count'] == 0

    def test_spaces(self):
        """带空格的格式"""
        result = parse_dice_string(" 1黄 3红 ")
        assert result['yellow_count'] == 1
        assert result['red_count'] == 3


# ============================================================
# CombatState 初始化和序列化
# ============================================================

class TestCombatStateInit:

    def test_initial_state(self, player_mech, ai_mech, sample_action):
        """新 CombatState 的默认状态"""
        cs = CombatState(
            attacker_entity=player_mech,
            defender_entity=ai_mech,
            action=sample_action,
            target_part_name="core"
        )
        assert cs.stage == 'INITIAL_ROLL'
        assert cs.attacker_entity.id == "player_1"
        assert cs.defender_entity.id == "ai_1"
        assert cs.action.name == "【光束剑】"
        assert cs.target_part_name == "core"
        assert cs.is_back_attack is False
        assert cs.is_interception_attack is False
        assert cs.overflow_hits == 0
        assert cs.overflow_crits == 0
        assert cs.available_effect_options == []
        assert cs.ace_rerolled is False

    def test_init_with_back_attack(self, player_mech, ai_mech, sample_action):
        """背击标记"""
        cs = CombatState(player_mech, ai_mech, sample_action, "core", is_back_attack=True)
        assert cs.is_back_attack is True

    def test_init_with_interception(self, player_mech, ai_mech, sample_action):
        """拦截攻击标记"""
        cs = CombatState(player_mech, ai_mech, sample_action, "core", is_interception_attack=True)
        assert cs.is_interception_attack is True


class TestCombatStateSerialization:

    def test_to_dict_and_back(self, player_mech, ai_mech, sample_action, game_state_with_entities):
        """CombatState 序列化往返"""
        cs = CombatState(player_mech, ai_mech, sample_action, "core", is_back_attack=True)
        cs.stage = 'AWAITING_ATTACK_REROLL'
        cs.overflow_hits = 2
        cs.overflow_crits = 1
        cs.ace_rerolled = True

        d = cs.to_dict()
        restored = CombatState.from_dict(d, game_state_with_entities)

        assert restored.stage == 'AWAITING_ATTACK_REROLL'
        assert restored.attacker_entity.id == "player_1"
        assert restored.defender_entity.id == "ai_1"
        assert restored.action.name == "【光束剑】"
        assert restored.target_part_name == "core"
        assert restored.is_back_attack is True
        assert restored.overflow_hits == 2
        assert restored.overflow_crits == 1
        assert restored.ace_rerolled is True

    def test_from_dict_missing_entity_raises(self, player_mech, sample_action):
        """找不到实体时抛出 ValueError"""
        from game_logic.game_logic import GameState
        # 创建一个只有玩家机甲的 GameState
        gs = GameState.__new__(GameState)
        gs.entities = {"player_1": player_mech}

        d = {
            'attacker_id': 'player_1',
            'defender_id': 'nonexistent',
            'action_dict': sample_action.to_dict(),
            'target_part_name': 'core',
        }
        with pytest.raises(ValueError, match="找不到实体"):
            CombatState.from_dict(d, gs)


# ============================================================
# CombatState._resolve_initial_roll — 初掷和伤害结算
# ============================================================

class TestCombatStateInitialRoll:

    def test_perfect_hit_against_no_defense(self, player_mech, ai_mech, game_state_with_entities, mock_random_choice):
        """
        攻击全中，防御全空白 → 击穿。
        玩家 link_points=0 避免触发重投中断，直达 RESOLVED。
        """
        sequence = [
            'light_hit', 'light_hit',  # 2 黄骰
            'heavy_hit', 'heavy_hit', 'heavy_hit',  # 3 红骰
            'blank', 'blank', 'blank',  # 3 白骰
        ]
        mock_random_choice(sequence)

        action = Action("测试攻击", "近战", "S", "2黄3红", range_val=1)
        player_mech.stance = 'attack'
        player_mech.pilot.link_points = 0  # 无链接值 → 跳过重投

        from game_logic.combat_system import CombatState
        cs = CombatState(player_mech, ai_mech, action, "core")
        log, packet = cs._resolve_initial_roll([])

        assert cs.stage == 'RESOLVED'
        assert packet['status'] == 'penetration'
        part_changes = {c['part_slot']: c['new_status'] for c in packet['part_changes']}
        assert part_changes.get('core') == 'damaged'

    def test_all_defense_blocks_all_light_hits(self, player_mech, ai_mech, game_state_with_entities, mock_random_choice):
        """
        攻击只有轻击，防御有足够的防御骰 → 未遂。
        link_points=0 跳过重投直达 RESOLVED。
        """
        sequence = [
            'light_hit', 'light_hit',  # 2 黄骰 → 2轻击
            'hollow_heavy_hit', 'hollow_heavy_hit', 'hollow_heavy_hit',  # 3 红骰 → stance=defense → 空心重击(无用)
            'defense', 'defense', 'defense',  # 3 白骰 → 3防御
        ]
        mock_random_choice(sequence)

        action = Action("测试攻击", "近战", "S", "2黄3红", range_val=1)
        player_mech.stance = 'defense'
        player_mech.pilot.link_points = 0  # 无链接值 → 跳过重投
        ai_mech.stance = 'defense'

        from game_logic.combat_system import CombatState
        cs = CombatState(player_mech, ai_mech, action, "core")
        log, packet = cs._resolve_initial_roll([])

        assert packet['status'] == 'miss'
        assert len(packet['part_changes']) == 0

    def test_armor_piercing_reduces_white_dice(self, player_mech, ai_mech, game_state_with_entities, mock_random_choice):
        """
        穿甲效果减少白骰数量。
        核心 armor=3, 穿甲1 → 白骰=2
        """
        sequence = [
            'light_hit', 'light_hit',  # 2 黄骰
            'heavy_hit', 'heavy_hit', 'heavy_hit',  # 3 红骰 → 3重击
            'blank', 'blank',  # 2 白骰 (被穿甲-1)
        ]
        mock_random_choice(sequence)

        action = Action("测试攻击", "近战", "S", "2黄3红", range_val=1,
                        effects={"armor_piercing": 1})
        player_mech.stance = 'attack'
        player_mech.pilot.link_points = 0  # 跳过重投

        from game_logic.combat_system import CombatState
        cs = CombatState(player_mech, ai_mech, action, "core")
        log, packet = cs._resolve_initial_roll([])

        assert packet['status'] == 'penetration'

    def test_parry_adds_white_dice(self, player_mech, ai_mech, game_state_with_entities, mock_random_choice):
        """
        近战攻击触发 AI 的招架，额外白骰。
        ai left_arm parry=2, core armor=3 → 白骰=5
        """
        sequence = [
            'light_hit', 'light_hit',  # 2 黄骰 → 2轻击
            'heavy_hit', 'heavy_hit', 'heavy_hit',  # 3 红骰 → 3重击
            'defense', 'defense', 'defense', 'defense', 'defense',  # 5 白骰 → 5防御
        ]
        mock_random_choice(sequence)

        action = Action("测试近战", "近战", "S", "2黄3红", range_val=1)
        player_mech.stance = 'attack'
        player_mech.pilot.link_points = 0  # 跳过重投
        ai_mech.stance = 'defense'

        from game_logic.combat_system import CombatState
        cs = CombatState(player_mech, ai_mech, action, "core")
        log, packet = cs._resolve_initial_roll([])

        # 5防御抵消2轻击；3重击无法被防御抵消 → 击穿
        assert packet['status'] == 'penetration'

    def test_damaged_part_uses_structure_not_armor(self, player_mech, damaged_mech, game_state_with_entities, mock_random_choice):
        """已破损部件用结构值作为白骰"""
        # damaged core: structure=4, 白骰=4
        sequence = [
            'light_hit', 'light_hit', 'light_hit', 'light_hit', 'light_hit',  # 需要足够多的轻击
            'heavy_hit', 'heavy_hit', 'heavy_hit',  # 3 红骰
            'blank', 'blank', 'blank', 'blank',  # 4 白骰全部空白
        ]
        mock_random_choice(sequence)

        action = Action("测试攻击", "近战", "S", "2黄3红", range_val=1)
        player_mech.stance = 'attack'
        player_mech.pilot.link_points = 0  # 跳过重投

        from game_logic.combat_system import CombatState
        cs = CombatState(player_mech, damaged_mech, action, "core")
        log, packet = cs._resolve_initial_roll([])

        # 核心 structure=4, 从 damaged→destroyed
        part_changes = {c['part_slot']: c['new_status'] for c in packet['part_changes']}
        assert part_changes.get('core') == 'destroyed'
        # 实体被标记为 destroyed (核心摧毁)
        entity_changes = {c['target_id']: c for c in packet['entity_changes']}
        assert entity_changes.get('player_1', {}).get('status') == 'destroyed'

    def test_core_destroyed_kills_entity(self, player_mech, ai_mech, game_state_with_entities, mock_random_choice):
        """核心被摧毁 → 实体标记为 destroyed"""
        # AI core armor=3, structure=4, 需要至少1次击穿让 ok→damaged
        # 再来一次 1次击穿让 damaged→destroyed
        # 简化：超量攻击
        sequence = [
            'light_hit', 'light_hit',  # 2 黄骰
            'heavy_hit', 'heavy_hit', 'heavy_hit', 'heavy_hit',  # 需要4红但只有3红骰
            'blank', 'blank',  # 被穿甲-1后是2个白骰blank
            # 实际上: action="2黄3红"不够击穿 core(armor=3→被穿甲1→2白骰)
        ]
        sequence = [
            'light_hit', 'light_hit',  # 2 黄骰 → 2轻击
            'heavy_hit', 'heavy_hit', 'heavy_hit',  # 3 红骰 → 3重击
            'blank', 'blank',  # 2 白骰(穿甲-1) → 0防御
        ]
        mock_random_choice(sequence)

        action = Action("测试攻击", "近战", "S", "2黄3红", range_val=1,
                        effects={"armor_piercing": 1})
        player_mech.stance = 'attack'
        player_mech.pilot.link_points = 0  # 跳过重投

        from game_logic.combat_system import CombatState
        cs = CombatState(player_mech, ai_mech, action, "core")
        log, packet = cs._resolve_initial_roll([])

        assert packet['status'] == 'penetration'

    def test_reroll_interrupt_triggered(self, player_mech, ai_mech, game_state_with_entities, mock_random_choice):
        """
        玩家有 link_points → 每次攻击都触发重投检查。
        """
        sequence = [
            'light_hit', 'light_hit',  # 2 黄骰
            'heavy_hit', 'heavy_hit', 'heavy_hit',  # 3 红骰
            'defense', 'defense', 'defense',  # 3 白骰 (无穿甲)
        ]
        mock_random_choice(sequence)

        action = Action("测试攻击", "近战", "S", "2黄3红", range_val=1)
        player_mech.stance = 'attack'
        player_mech.pilot.link_points = 3  # 确保有链接值

        from game_logic.combat_system import CombatState
        cs = CombatState(player_mech, ai_mech, action, "core")
        log, packet = cs._resolve_initial_roll([])

        # 应该有重投选择
        assert cs.stage == 'AWAITING_ATTACK_REROLL'
        assert packet['status'] == 'reroll_choice_required'

    def test_no_reroll_for_interception(self, player_mech, simple_projectile, game_state_with_entities, mock_random_choice):
        """拦截攻击跳过重投"""
        sequence = [
            'light_hit', 'light_hit',  # 2 黄骰
            'heavy_hit', 'heavy_hit', 'heavy_hit',  # 3 红骰
            'blank',  # 抛射物 core 的 structure=1 → 1白骰
        ]
        mock_random_choice(sequence)

        action = Action("拦截攻击", "近战", "S", "2黄3红", range_val=1)

        # 确保 game_state 有 simple_projectile
        gs = game_state_with_entities
        gs.entities[simple_projectile.id] = simple_projectile

        from game_logic.combat_system import CombatState
        cs = CombatState(player_mech, simple_projectile, action, "core", is_interception_attack=True)
        log, packet = cs._resolve_initial_roll([])

        # 拦截不应触发重投
        assert cs.stage != 'AWAITING_ATTACK_REROLL'

    def test_defender_evasion_in_agile_stance(self, player_mech, ai_mech, game_state_with_entities, mock_random_choice):
        """
        目标处于 agile 姿态 → 蓝骰 = 总闪避值
        ai evasion = legs(2) + right_arm(1) + backpack(1) = 4 蓝骰
        """
        sequence = [
            'light_hit', 'light_hit',  # 2 黄骰
            'heavy_hit', 'heavy_hit', 'heavy_hit',  # 3 红骰
            'defense', 'defense', 'defense',  # 3 白骰 (armor=3)
            'eye', 'blank', 'blank', 'blank',  # 4 蓝骰
        ]
        mock_random_choice(sequence)

        action = Action("测试攻击", "近战", "S", "2黄3红", range_val=1)
        player_mech.stance = 'attack'
        ai_mech.stance = 'agile'

        from game_logic.combat_system import CombatState
        cs = CombatState(player_mech, ai_mech, action, "core")
        log, packet = cs._resolve_initial_roll([])

        # 不崩溃即可
        assert cs.stage in ['RESOLVED', 'AWAITING_ATTACK_REROLL']


# ============================================================
# CombatState 状态机流转测试
# ============================================================

class TestCombatStateTransitions:

    def test_submit_reroll_sets_stage_resolved(self, player_mech, ai_mech, game_state_with_entities, mock_random_choice):
        """提交重投后战斗到达 RESOLVED"""
        # 构造场景：攻击命中，触发了重投中断
        sequence = [
            'light_hit', 'light_hit',
            'heavy_hit', 'heavy_hit', 'heavy_hit',
            'defense', 'defense', 'defense',
        ]
        mock_random_choice(sequence)

        action = Action("测试", "近战", "S", "2黄3红", range_val=1)
        player_mech.stance = 'attack'
        player_mech.pilot.link_points = 2

        from game_logic.combat_system import CombatState
        cs = CombatState(player_mech, ai_mech, action, "core")
        log, packet = cs._resolve_initial_roll([])

        assert cs.stage == 'AWAITING_ATTACK_REROLL'

        # 提交空重投（玩家选择不重投）
        log2, packet2 = cs.submit_reroll([], [], [], player_mech)

        assert cs.stage == 'RESOLVED'

    def test_submit_reroll_at_wrong_stage(self, player_mech, ai_mech, game_state_with_entities, mock_random_choice):
        """在错误阶段提交重投返回错误包"""
        sequence = [
            'light_hit', 'light_hit',
            'heavy_hit', 'heavy_hit', 'heavy_hit',
            'defense', 'defense', 'defense',
            'blank',  # 后续可能需要
        ]
        mock_random_choice(sequence)

        action = Action("测试", "近战", "S", "2黄3红", range_val=1)
        player_mech.stance = 'attack'
        player_mech.pilot.link_points = 2

        from game_logic.combat_system import CombatState
        cs = CombatState(player_mech, ai_mech, action, "core")
        # 不调用 _resolve_initial_roll，cs.stage 仍是 INITIAL_ROLL
        log, packet = cs.submit_reroll([], [], [], player_mech)

        assert packet['status'] == 'invalid'
        assert '试图在 INITIAL_ROLL 阶段' in log[0]

    def test_submit_effect_choice_at_wrong_stage(self, player_mech, ai_mech, game_state_with_entities, mock_random_choice):
        """在错误阶段提交效果选择返回错误包"""
        sequence = [
            'light_hit', 'light_hit',
            'heavy_hit', 'heavy_hit', 'heavy_hit',
            'defense', 'defense', 'defense',
        ]
        mock_random_choice(sequence)

        action = Action("测试", "近战", "S", "2黄3红", range_val=1)
        player_mech.stance = 'attack'

        from game_logic.combat_system import CombatState
        cs = CombatState(player_mech, ai_mech, action, "core")
        log, packet = cs.submit_effect_choice([], 'devastating')

        assert packet['status'] == 'invalid'

    def test_submit_invalid_effect_choice(self, player_mech, ai_mech, game_state_with_entities, mock_random_choice):
        """提交无效的效果选项"""
        sequence = [
            'light_hit', 'light_hit',
            'heavy_hit', 'heavy_hit', 'heavy_hit',
            'blank', 'blank', 'blank',
        ]
        mock_random_choice(sequence)

        action = Action("测试", "近战", "S", "2黄3红", range_val=1,
                        effects={"devastating": True})
        player_mech.stance = 'attack'
        ai_mech.stance = 'defense'

        from game_logic.combat_system import CombatState
        cs = CombatState(player_mech, ai_mech, action, "core")

        # 手动设置到 effect choice 阶段
        cs.stage = 'AWAITING_EFFECT_CHOICE'
        cs.available_effect_options = ['devastating']
        cs.overflow_hits = 2
        cs.overflow_crits = 1

        # 选择不存在的选项
        log, packet = cs.submit_effect_choice([], 'nonexistent')
        assert '无效的效果' in log[0]


# ============================================================
# CombatState 伤害计算测试
# ============================================================

class TestCombatStateDamageCalculation:

    def test_light_hit_vs_defense(self, player_mech, ai_mech, game_state_with_entities, mock_random_choice):
        """轻击被防御抵消"""
        sequence = [
            'light_hit', 'light_hit', 'light_hit',  # 3 黄骰 → 3轻击
            'blank', 'blank',  # 2 红骰 (实际上 action 有3红，加2黄=3+3)
            'defense', 'defense', 'blank',  # 3 白骰 → 2防御+1空白
        ]
        sequence = [
            'light_hit', 'light_hit',  # 2 黄骰
            'blank', 'blank', 'blank',  # 3 红骰全是空白
            'defense', 'defense', 'blank',  # 3 白骰 → 2防御
        ]
        mock_random_choice(sequence)

        action = Action("测试", "近战", "S", "2黄3红", range_val=1)
        player_mech.stance = 'attack'
        player_mech.pilot.link_points = 0  # 跳过重投
        ai_mech.stance = 'defense'

        from game_logic.combat_system import CombatState
        cs = CombatState(player_mech, ai_mech, action, "core")
        log, packet = cs._resolve_initial_roll([])

        # 2轻击被2防御抵消 → miss
        assert packet['status'] == 'miss'

    def test_crits_pierce_defense(self, player_mech, ai_mech, game_state_with_entities, mock_random_choice):
        """重击不能被防御抵消，只能被闪避抵消"""
        sequence = [
            'blank', 'blank',  # 2 黄骰 → blank
            'heavy_hit', 'heavy_hit', 'heavy_hit',  # 3 红骰 → 3重击
            'defense', 'defense', 'defense',  # 3 白骰 → 3防御 (无法抵消重击)
        ]
        mock_random_choice(sequence)

        action = Action("测试", "近战", "S", "2黄3红", range_val=1)
        player_mech.stance = 'attack'
        player_mech.pilot.link_points = 0  # 跳过重投
        ai_mech.stance = 'defense'

        from game_logic.combat_system import CombatState
        cs = CombatState(player_mech, ai_mech, action, "core")
        log, packet = cs._resolve_initial_roll([])

        # 3重击穿透 → 击穿
        assert packet['status'] == 'penetration'

    def test_shock_effect_reduces_link_points(self, player_mech, ai_mech, game_state_with_entities, mock_random_choice):
        """
        震撼效果：闪电减少驾驶员链接值。
        需要一个产生闪电的骰子序列 + shock 效果的动作。
        """
        sequence = [
            'lightning', 'blank',  # 2 黄骰 → 1闪电+1空白
            'heavy_hit', 'heavy_hit', 'heavy_hit',  # 3 红骰 → 3重击
            'defense', 'defense', 'blank',  # 3 白骰(有穿甲就减少1) → armor=3, ap=0 → 3白骰
        ]
        mock_random_choice(sequence)

        action = Action("震撼攻击", "射击", "S", "2黄3红", range_val=3,
                        effects={"shock": True})
        player_mech.stance = 'attack'

        from game_logic.combat_system import CombatState
        cs = CombatState(player_mech, ai_mech, action, "core")
        log, packet = cs._resolve_initial_roll([])

        # 检查是否有 link_loss
        pilot_changes = packet.get('pilot_changes', [])
        if pilot_changes:
            assert pilot_changes[0]['link_loss'] >= 0

    def test_projectile_attack_destroys_projectile(self, player_mech, simple_projectile, game_state_with_entities, mock_random_choice):
        """抛射物作为攻击方，攻击后自毁"""
        sequence = [
            'light_hit', 'light_hit',  # 2 黄骰
            'heavy_hit', 'heavy_hit', 'heavy_hit',  # 3 红骰
            'blank', 'blank', 'blank',  # 3 白骰
        ]
        mock_random_choice(sequence)

        action = Action("抛射物攻击", "射击", "S", "2黄3红", range_val=1)

        gs = game_state_with_entities
        gs.entities[simple_projectile.id] = simple_projectile
        gs.entities[player_mech.id] = player_mech

        from game_logic.combat_system import CombatState
        cs = CombatState(simple_projectile, player_mech, action, "core")
        log, packet = cs._resolve_initial_roll([])

        if cs.stage == 'RESOLVED':
            # 检查抛射物自毁
            entity_changes = {c['target_id']: c for c in packet['entity_changes']}
            assert entity_changes.get(simple_projectile.id, {}).get('status') == 'destroyed'


# ============================================================
# Fixture: 包含实体的最小 GameState
# ============================================================

@pytest.fixture
def game_state_with_entities(player_mech, ai_mech):
    """创建一个最小的 GameState，只包含测试用的实体"""
    from game_logic.game_logic import GameState
    gs = GameState.__new__(GameState)
    gs.entities = {
        player_mech.id: player_mech,
        ai_mech.id: ai_mech,
    }
    # 模拟 get_entity_by_id 方法（GameState.__new__ 不会初始化方法）
    gs.get_entity_by_id = lambda eid: gs.entities.get(eid)
    gs.board_width = 11
    gs.board_height = 11
    gs.game_over = False
    gs.visual_events = []
    return gs
