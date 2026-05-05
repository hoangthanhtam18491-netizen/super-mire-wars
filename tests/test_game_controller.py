"""game_controller 辅助函数和子模块测试"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import copy
from game_logic.game_logic import GameState
from game_logic.game_controller import (
    _execute_main_action, _apply_combat_packet, _clear_transient_state
)
from game_logic.data_models import Mech, Part, Action, Pilot, Projectile


def make_dummy_mech(mech_id="test_1", controller="player", pos=(5, 5)):
    """创建测试用机甲"""
    core = Part(name="测试核心", armor=3, structure=3, actions=[
        Action(name="测试射击", action_type="射击", cost="S", dice="2黄1红", range_val=5),
        Action(name="测试移动", action_type="移动", cost="M", dice="", range_val=4),
    ])
    legs = Part(name="测试腿部", armor=2, structure=2, evasion=1)
    left_arm = Part(name="测试左臂", armor=1, structure=1)
    right_arm = Part(name="测试右臂", armor=1, structure=1)
    backpack = Part(name="测试背包", armor=0, structure=1)

    return Mech(
        id=mech_id, controller=controller, pos=pos, orientation="E",
        name="测试机甲", core=core, legs=legs, left_arm=left_arm,
        right_arm=right_arm, backpack=backpack,
        pilot=Pilot(name="测试驾驶员", link_points=3)
    )


# === _execute_main_action 测试 ===

class TestExecuteMainAction:
    """测试核心资源验证和消耗逻辑"""

    def test_successful_action(self):
        """正常消耗 AP 执行动作"""
        mech = make_dummy_mech()
        mech.timing = "射击"
        action = mech.get_action_by_name_and_slot("测试射击", "core")
        game_state = GameState()

        game_state, log, success, msg = _execute_main_action(
            game_state, mech, action, "测试射击", "core"
        )

        assert success
        assert mech.player_ap == 1  # S = 1 AP
        assert mech.player_tp == 1  # 不变
        assert mech.opening_move_taken is True
        assert ("core", "测试射击") in mech.actions_used_this_turn

    def test_insufficient_ap(self):
        """AP不足"""
        mech = make_dummy_mech()
        mech.player_ap = 0
        mech.timing = "射击"
        action = mech.get_action_by_name_and_slot("测试射击", "core")
        game_state = GameState()

        game_state, log, success, msg = _execute_main_action(
            game_state, mech, action, "测试射击", "core"
        )

        assert not success
        assert "AP不足" in msg

    def test_already_used(self):
        """本回合已使用"""
        mech = make_dummy_mech()
        mech.timing = "射击"
        mech.actions_used_this_turn = [("core", "测试射击")]
        action = mech.get_action_by_name_and_slot("测试射击", "core")
        game_state = GameState()

        game_state, log, success, msg = _execute_main_action(
            game_state, mech, action, "测试射击", "core"
        )

        assert not success

    def test_wrong_timing_for_opening_move(self):
        """起手动作时机不匹配"""
        mech = make_dummy_mech()
        mech.timing = "近战"
        mech.opening_move_taken = False
        action = mech.get_action_by_name_and_slot("测试射击", "core")
        game_state = GameState()

        game_state, log, success, msg = _execute_main_action(
            game_state, mech, action, "测试射击", "core"
        )

        assert not success
        assert "起手动作错误" in msg

    def test_move_cost_M(self):
        """M 成本消耗 2 AP"""
        mech = make_dummy_mech()
        mech.timing = "移动"
        action = mech.get_action_by_name_and_slot("测试移动", "core")
        game_state = GameState()

        game_state, log, success, msg = _execute_main_action(
            game_state, mech, action, "测试移动", "core"
        )

        assert success
        assert mech.player_ap == 0  # M = 2 AP
        assert mech.player_tp == 1

    def test_ammo_consumption(self):
        """弹药消耗"""
        mech = make_dummy_mech()
        mech.timing = "射击"
        action = Action(name="测试弹药用", action_type="射击", cost="S",
                        dice="1红", range_val=5, ammo=3)
        game_state = GameState()
        ammo_key = (mech.id, "core", "测试弹药用")
        game_state.ammo_counts[ammo_key] = 3

        game_state, log, success, msg = _execute_main_action(
            game_state, mech, action, "测试弹药用", "core"
        )

        assert success
        assert game_state.ammo_counts[ammo_key] == 2


# === _apply_combat_packet 测试 ===

class TestApplyCombatPacket:
    """测试结果包应用到 game_state"""

    def test_part_damaged(self):
        """部件状态变更"""
        mech = make_dummy_mech()
        game_state = GameState()
        game_state.entities[mech.id] = mech
        log = []

        packet = {
            'part_changes': [{
                'target_id': mech.id,
                'part_slot': 'core',
                'new_status': 'damaged'
            }]
        }

        game_state = _apply_combat_packet(game_state, packet, log)
        assert mech.parts['core'].status == 'damaged'

    def test_part_destroyed(self):
        """部件摧毁"""
        mech = make_dummy_mech()
        game_state = GameState()
        game_state.entities[mech.id] = mech
        log = []

        packet = {
            'part_changes': [{
                'target_id': mech.id,
                'part_slot': 'left_arm',
                'new_status': 'destroyed'
            }]
        }

        game_state = _apply_combat_packet(game_state, packet, log)
        assert mech.parts['left_arm'].status == 'destroyed'

    def test_link_loss(self):
        """驾驶员链接值损失"""
        mech = make_dummy_mech()
        mech.pilot.link_points = 5
        game_state = GameState()
        game_state.entities[mech.id] = mech
        log = []

        packet = {
            'pilot_changes': [{
                'target_id': mech.id,
                'link_loss': 2
            }]
        }

        game_state = _apply_combat_packet(game_state, packet, log)
        assert mech.pilot.link_points == 3

    def test_entity_destroyed(self):
        """实体摧毁"""
        mech = make_dummy_mech()
        game_state = GameState()
        game_state.entities[mech.id] = mech
        log = []

        packet = {
            'entity_changes': [{
                'target_id': mech.id,
                'status': 'destroyed'
            }]
        }

        game_state = _apply_combat_packet(game_state, packet, log)
        assert mech.status == 'destroyed'

    def test_stance_change(self):
        """姿态变更 (宕机)"""
        mech = make_dummy_mech()
        mech.stance = 'attack'
        game_state = GameState()
        game_state.entities[mech.id] = mech
        log = []

        packet = {
            'entity_changes': [{
                'target_id': mech.id,
                'stance': 'downed'
            }]
        }

        game_state = _apply_combat_packet(game_state, packet, log)
        assert mech.stance == 'downed'

    def test_empty_packet(self):
        """空包不报错"""
        game_state = GameState()
        log = []
        result = _apply_combat_packet(game_state, None, log)
        assert result is game_state

    def test_combined_packet(self):
        """组合包：部件 + 驾驶员 + 实体"""
        mech = make_dummy_mech()
        mech.pilot.link_points = 3
        game_state = GameState()
        game_state.entities[mech.id] = mech
        log = []

        packet = {
            'part_changes': [{'target_id': mech.id, 'part_slot': 'core', 'new_status': 'damaged'}],
            'pilot_changes': [{'target_id': mech.id, 'link_loss': 1}],
            'entity_changes': [{'target_id': mech.id, 'stance': 'downed'}]
        }

        game_state = _apply_combat_packet(game_state, packet, log)
        assert mech.parts['core'].status == 'damaged'
        assert mech.pilot.link_points == 2
        assert mech.stance == 'downed'


# === _clear_transient_state 测试 ===

class TestClearTransientState:
    """测试瞬态状态清除"""

    def test_clears_last_pos(self):
        mech = make_dummy_mech()
        mech.last_pos = (4, 4)
        game_state = GameState()
        game_state.entities[mech.id] = mech

        game_state = _clear_transient_state(game_state)
        assert mech.last_pos is None

    def test_all_entities_cleared(self):
        mech1 = make_dummy_mech(mech_id="a", pos=(1, 1))
        mech2 = make_dummy_mech(mech_id="b", pos=(2, 2))
        mech1.last_pos = (0, 0)
        mech2.last_pos = (1, 1)
        game_state = GameState()
        game_state.entities[mech1.id] = mech1
        game_state.entities[mech2.id] = mech2

        game_state = _clear_transient_state(game_state)
        assert mech1.last_pos is None
        assert mech2.last_pos is None


# === ace_logic.decide_reroll 测试 ===

class TestAceRerollDecision:
    """测试 Ace AI 重投决策"""

    def test_no_link_points_no_reroll(self):
        """没有链接值时不应重投"""
        from game_logic import ace_logic
        mech = make_dummy_mech()
        mech.pilot.link_points = 0
        opponent = make_dummy_mech(mech_id="opp", controller="ai")
        action = Action(name="test", action_type="射击", cost="S", dice="1黄", range_val=3)

        attack_roll = {'轻击': 0, '重击': 0, '闪电': 0, '空白': 1}
        defense_roll = {'防御': 1, '闪避': 0, '空白': 0}
        attack_raw = {'yellow': [['空白']], 'red': [], 'white': [], 'blue': []}
        defense_raw = {'yellow': [], 'red': [], 'white': [['防御']], 'blue': []}

        result = ace_logic.decide_reroll(
            mech, opponent, action,
            attack_roll, defense_roll,
            attack_raw, defense_raw,
            is_attacker=True
        )
        assert result is None or len(result) == 0


# === GameState round-trip tests (extended) ===

class TestGameStateExtended:
    """扩展的 GameState 序列化测试"""

    def test_ammo_counts_round_trip(self):
        """弹药计数序列化往返"""
        mech = make_dummy_mech()
        state = GameState()
        state.entities[mech.id] = mech
        state.ammo_counts[('test_1', 'core', 'test_action')] = 5

        restored = GameState.from_dict(state.to_dict())
        assert restored.ammo_counts[('test_1', 'core', 'test_action')] == 5

    def test_entities_round_trip_with_mech(self):
        """带机甲的状态往返"""
        mech = make_dummy_mech()
        mech.stance = 'agile'
        mech.player_ap = 1
        state = GameState()
        state.entities[mech.id] = mech

        restored = GameState.from_dict(state.to_dict())
        restored_mech = restored.entities[mech.id]
        assert restored_mech.stance == 'agile'
        assert restored_mech.player_ap == 1
        assert restored_mech.id == mech.id

    def test_game_mode_preserved(self):
        """游戏模式被保留"""
        state = GameState(game_mode='horde')
        restored = GameState.from_dict(state.to_dict())
        assert restored.game_mode == 'horde'

    def test_ai_defeat_count_preserved(self):
        """AI 击败计数被保留"""
        state = GameState()
        state.ai_defeat_count = 5
        restored = GameState.from_dict(state.to_dict())
        assert restored.ai_defeat_count == 5

    def test_game_over_state_preserved(self):
        """游戏结束状态被保留"""
        state = GameState()
        state.game_over = 'player_win'
        restored = GameState.from_dict(state.to_dict())
        assert restored.game_over == 'player_win'
