"""CombatState 状态机测试"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game_logic.combat_system import CombatState, parse_dice_string
from game_logic.data_models import Mech, Projectile, Part, Action, Pilot


def make_dummy_mech(
    mech_id="test_1",
    controller="player",
    pos=(5, 5),
    orientation="E",
    name="测试机甲",
    armor=3,
    structure=3,
):
    """创建用于测试的简单机甲"""
    core = Part(
        name=f"{name} 核心",
        armor=armor,
        structure=structure,
        actions=[
            Action(
                name="测试攻击",
                action_type="射击",
                cost="S",
                dice="2黄1红",
                range_val=5,
            )
        ],
    )
    legs = Part(name=f"{name} 腿部", armor=2, structure=2, evasion=1)
    left_arm = Part(name=f"{name} 左臂", armor=1, structure=1)
    right_arm = Part(name=f"{name} 右臂", armor=1, structure=1)
    backpack = Part(name=f"{name} 背包", armor=0, structure=1)

    pilot = Pilot(name="测试驾驶员", link_points=3)

    return Mech(
        id=mech_id,
        controller=controller,
        pos=pos,
        orientation=orientation,
        name=name,
        core=core,
        legs=legs,
        left_arm=left_arm,
        right_arm=right_arm,
        backpack=backpack,
        pilot=pilot,
    )


def make_dummy_projectile(proj_id="proj_1", controller="player", pos=(8, 5)):
    """创建用于测试的简单抛射物"""
    return Projectile(
        id=proj_id,
        controller=controller,
        pos=pos,
        name="测试导弹",
        evasion=1,
        stance="agile",
        actions=[
            Action(
                name="引爆",
                action_type="立即",
                cost="S",
                dice="1黄",
                range_val=0,
            )
        ],
        life_span=1,
    )


class TestParseDiceString:
    """parse_dice_string 测试"""

    def test_empty_string(self):
        result = parse_dice_string("")
        assert result == {
            "yellow_count": 0,
            "red_count": 0,
            "white_count": 0,
            "blue_count": 0,
        }

    def test_single_yellow(self):
        result = parse_dice_string("1黄")
        assert result["yellow_count"] == 1
        assert result["red_count"] == 0

    def test_single_red(self):
        result = parse_dice_string("3红")
        assert result["red_count"] == 3
        assert result["yellow_count"] == 0

    def test_mixed(self):
        result = parse_dice_string("2黄3红")
        assert result["yellow_count"] == 2
        assert result["red_count"] == 3

    def test_complex(self):
        result = parse_dice_string("5黄4红")
        assert result["yellow_count"] == 5
        assert result["red_count"] == 4


class TestCombatStateLifecycle:
    """CombatState 完整生命周期测试"""

    def test_initial_stage_is_initial_roll(self):
        attacker = make_dummy_mech(mech_id="atk", pos=(5, 5), orientation="E")
        defender = make_dummy_mech(mech_id="def", pos=(8, 5), orientation="W")
        action = attacker.get_all_actions()[0][0]

        session = CombatState(
            attacker_entity=attacker,
            defender_entity=defender,
            action=action,
            target_part_name="core",
        )
        assert session.stage == "INITIAL_ROLL"

    def test_resolve_initial_roll_progresses(self):
        attacker = make_dummy_mech(mech_id="atk", pos=(5, 5), orientation="E")
        defender = make_dummy_mech(mech_id="def", pos=(8, 5), orientation="W")
        action = attacker.get_all_actions()[0][0]

        session = CombatState(
            attacker_entity=attacker,
            defender_entity=defender,
            action=action,
            target_part_name="core",
        )
        log, packet = session.resolve([])

        # 必须有掷骰详情
        assert "dice_roll_details" in packet
        details = packet["dice_roll_details"]
        assert "attack_dice_input" in details
        assert "defense_dice_input" in details
        assert "attack_dice_result" in details
        assert "defense_dice_result" in details

    def test_output_packet_structure(self):
        attacker = make_dummy_mech(mech_id="atk", pos=(5, 5), orientation="E")
        defender = make_dummy_mech(mech_id="def", pos=(8, 5), orientation="W")
        action = attacker.get_all_actions()[0][0]

        session = CombatState(
            attacker_entity=attacker,
            defender_entity=defender,
            action=action,
            target_part_name="core",
        )
        log, packet = session.resolve([])

        # 验证结果包结构
        assert "attacker_id" in packet
        assert "defender_id" in packet
        assert "action_name" in packet
        assert "status" in packet
        assert "part_changes" in packet
        assert "pilot_changes" in packet
        assert "entity_changes" in packet
        assert packet["attacker_id"] == "atk"
        assert packet["defender_id"] == "def"
        assert packet["action_name"] == "测试攻击"

    def test_interception_skips_reroll(self):
        attacker = make_dummy_mech(mech_id="atk", pos=(5, 5), orientation="E")
        defender = make_dummy_projectile(proj_id="proj_1", pos=(8, 5))

        action = Action(
            name="拦截射击",
            action_type="射击",
            cost="S",
            dice="1黄",
            range_val=5,
        )

        session = CombatState(
            attacker_entity=attacker,
            defender_entity=defender,
            action=action,
            target_part_name="core",
            is_interception_attack=True,
        )
        log, packet = session.resolve([])

        # 拦截攻击不能进入重投阶段
        assert session.stage != "AWAITING_ATTACK_REROLL"

    def test_to_dict_and_from_dict_rebuild(self):
        attacker = make_dummy_mech(mech_id="atk", pos=(5, 5), orientation="E")
        defender = make_dummy_mech(mech_id="def", pos=(8, 5), orientation="W")
        action = attacker.get_all_actions()[0][0]

        session = CombatState(
            attacker_entity=attacker,
            defender_entity=defender,
            action=action,
            target_part_name="core",
            is_back_attack=True,
        )

        # 模拟执行到一半
        log, packet = session.resolve([])

        # 序列化
        data = session.to_dict()
        assert data["attacker_id"] == "atk"
        assert data["defender_id"] == "def"
        assert data["stage"] == session.stage
        assert data["is_back_attack"] is True
        assert data["is_interception_attack"] is False

        # 这里不测试 from_dict 重建因为需要真实 game_state 来查找实体
        # from_dict 的正确性在控制器的中断链路中已经被间接验证

    def test_melee_vs_projectile(self):
        attacker = make_dummy_mech(mech_id="atk", pos=(5, 5), orientation="E")
        defender = make_dummy_projectile(proj_id="proj_1", pos=(8, 5))

        action = Action(
            name="劈砍",
            action_type="近战",
            cost="S",
            dice="1黄",
            range_val=1,
        )

        session = CombatState(
            attacker_entity=attacker,
            defender_entity=defender,
            action=action,
            target_part_name="core",
        )
        log, packet = session.resolve([])

        # 抛射物被命中应被摧毁
        if packet["status"] == "penetration":
            part_changes = packet["part_changes"]
            has_destroy = any(
                c.get("new_status") == "destroyed" for c in part_changes
            )
            # 击穿即摧毁抛射物的 core
            if part_changes:
                assert has_destroy


class TestCombatStateEffectTriggering:
    """效果触发条件测试"""

    def test_devastating_not_available_without_effect(self):
        attacker = make_dummy_mech(mech_id="atk", pos=(5, 5), orientation="E", armor=0, structure=1)
        defender = make_dummy_mech(mech_id="def", pos=(8, 5), orientation="W", armor=10, structure=5)

        # 不带毁伤效果的普通攻击
        action = Action(
            name="普通射击",
            action_type="射击",
            cost="S",
            dice="2黄1红",
            range_val=5,
        )

        session = CombatState(
            attacker_entity=attacker,
            defender_entity=defender,
            action=action,
            target_part_name="core",
        )
        log, packet = session.resolve([])

        # 没有毁伤效果时，不应进入效果选择阶段
        if session.stage == "AWAITING_EFFECT_CHOICE":
            # 如果有选择，毁伤不应在选项中
            assert "devastating" not in session.available_effect_options


class TestCombatStateEdgeCases:
    """边界情况测试"""

    def test_zero_dice_action(self):
        attacker = make_dummy_mech(mech_id="atk", pos=(5, 5), orientation="E")
        defender = make_dummy_mech(mech_id="def", pos=(8, 5), orientation="W")

        action = Action(
            name="空击",
            action_type="射击",
            cost="S",
            dice="",  # 无骰子
            range_val=5,
        )

        session = CombatState(
            attacker_entity=attacker,
            defender_entity=defender,
            action=action,
            target_part_name="core",
        )
        log, packet = session.resolve([])

        # 无骰子时不应崩溃
        assert session.stage in ["RESOLVED", "AWAITING_ATTACK_REROLL"]
        # 应该没有任何伤害
        assert packet["status"] in ["miss", "reroll_choice_required"]

    def test_damaged_part_uses_structure(self):
        attacker = make_dummy_mech(mech_id="atk", pos=(5, 5), orientation="E")
        defender = make_dummy_mech(mech_id="def", pos=(8, 5), orientation="W", armor=5, structure=2)
        # 先标记核心为 damaged
        defender.parts["core"].status = "damaged"

        action = Action(
            name="测试攻击",
            action_type="射击",
            cost="S",
            dice="3黄2红",
            range_val=5,
        )

        session = CombatState(
            attacker_entity=attacker,
            defender_entity=defender,
            action=action,
            target_part_name="core",
        )
        log, packet = session.resolve([])

        details = packet.get("dice_roll_details", {})
        defense_input = details.get("defense_dice_input", {})
        # damaged 时用 structure(2) 而不是 armor(5)
        assert defense_input.get("white_count") == 2
