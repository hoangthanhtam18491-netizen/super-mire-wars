"""
测试 data_models.py — 数据模型序列化/反序列化。
游戏状态通过 to_dict()/from_dict() 持久化到 Flask Session，
序列化的一致性是整个游戏状态持久化的生命线。
"""
import pytest
from game_logic.data_models import (
    Action, Part, Pilot, Mech, Projectile, Drone, GameEntity
)


# ============================================================
# Action 序列化
# ============================================================

class TestActionSerialization:

    def test_to_dict_round_trip_minimal(self):
        """最小字段的 Action 序列化往返"""
        action = Action(name="测试", action_type="近战", cost="S", dice="1黄")
        d = action.to_dict()
        restored = Action.from_dict(d)
        assert restored.name == action.name
        assert restored.action_type == action.action_type
        assert restored.cost == action.cost
        assert restored.dice == action.dice

    def test_to_dict_round_trip_full(self):
        """全字段 Action 序列化往返"""
        action = Action(
            name="【导弹发射器】",
            action_type="抛射",
            cost="L",
            dice="0黄0红",
            range_val=8,
            effects={"salvo": 3, "armor_piercing": 2},
            action_style="curved",
            aoe_range=1,
            projectile_to_spawn="standard_missile",
            ammo=6
        )
        d = action.to_dict()
        restored = Action.from_dict(d)
        assert restored.name == "【导弹发射器】"
        assert restored.action_type == "抛射"
        assert restored.cost == "L"
        assert restored.range_val == 8
        assert restored.effects == {"salvo": 3, "armor_piercing": 2}
        assert restored.action_style == "curved"
        assert restored.aoe_range == 1
        assert restored.projectile_to_spawn == "standard_missile"
        assert restored.ammo == 6

    def test_from_dict_defaults(self):
        """旧存档缺失字段时使用默认值"""
        minimal = {"name": "旧动作", "action_type": "移动", "cost": "S", "dice": "0黄"}
        restored = Action.from_dict(minimal)
        assert restored.range_val == 0
        assert restored.effects == {}
        assert restored.action_style == "direct"
        assert restored.aoe_range == 0
        assert restored.projectile_to_spawn is None
        assert restored.ammo == 0

    def test_effects_with_action_style_compat(self):
        """兼容旧的 effects 内嵌 action_style"""
        data = {
            "name": "旧式", "action_type": "抛射", "cost": "L", "dice": "0黄",
            "effects": {"action_style": "curved"}
        }
        restored = Action.from_dict(data)
        assert restored.action_style == "curved"


# ============================================================
# Part 序列化
# ============================================================

class TestPartSerialization:

    def test_to_dict_round_trip_minimal(self):
        """最小字段的 Part 序列化往返"""
        part = Part(name="测试核心", armor=3, structure=5)
        d = part.to_dict()
        restored = Part.from_dict(d)
        assert restored.name == "测试核心"
        assert restored.armor == 3
        assert restored.structure == 5
        assert restored.parry == 0  # 默认值
        assert restored.status == "ok"
        assert restored.tags == []
        assert restored.actions == []

    def test_to_dict_round_trip_with_actions(self):
        """带动作的 Part 序列化往返"""
        action = Action(name="斩击", action_type="近战", cost="S", dice="1黄2红")
        part = Part(
            name="测试手臂", armor=2, structure=3, parry=2, evasion=1,
            actions=[action], tags=["【手持】", "【测试】"], status="damaged"
        )
        d = part.to_dict()
        restored = Part.from_dict(d)
        assert restored.name == "测试手臂"
        assert restored.status == "damaged"
        assert len(restored.actions) == 1
        assert restored.actions[0].name == "斩击"
        assert restored.tags == ["【手持】", "【测试】"]
        assert restored.parry == 2
        assert restored.evasion == 1

    def test_from_dict_defaults(self):
        """旧存档缺失字段时使用默认值"""
        minimal = {"name": "旧部件", "armor": 1, "structure": 2}
        restored = Part.from_dict(minimal)
        assert restored.parry == 0
        assert restored.evasion == 0
        assert restored.electronics == 0
        assert restored.adjust_move == 0
        assert restored.status == "ok"
        assert restored.tags == []
        assert restored.actions == []


# ============================================================
# Pilot 序列化
# ============================================================

class TestPilotSerialization:

    def test_to_dict_round_trip(self):
        """Pilot 序列化往返"""
        pilot = Pilot(
            name="王牌驾驶员",
            link_points=5,
            speed_stats={"快速": 6, "近战": 7},
            skills=["pursuit"]
        )
        d = pilot.to_dict()
        restored = Pilot.from_dict(d)
        assert restored.name == "王牌驾驶员"
        assert restored.link_points == 5
        assert restored.speed_stats["快速"] == 6
        assert "pursuit" in restored.skills

    def test_from_dict_none(self):
        """None 数据创建空 Pilot"""
        assert Pilot.from_dict(None) is None

    def test_from_dict_empty(self):
        """空字典（falsy）返回 None"""
        assert Pilot.from_dict({}) is None

    def test_from_dict_missing_fields(self):
        """缺失字段使用默认值"""
        pilot = Pilot.from_dict({"name": "无名"})
        assert pilot.name == "无名"
        assert pilot.link_points == 5
        assert pilot.skills == []
        assert pilot.speed_stats["快速"] == 5  # 默认速度


# ============================================================
# GameEntity / Mech 序列化 (核心测试)
# ============================================================

class TestMechSerialization:

    def test_full_round_trip(self, player_mech, sample_pilot):
        """完整机甲序列化往返 — 这是最重要的测试"""
        # 设置一些可变状态
        player_mech.stance = "attack"
        player_mech.player_ap = 1
        player_mech.turn_phase = "main"
        player_mech.timing = "近战"
        player_mech.opening_move_taken = True
        player_mech.actions_used_this_turn = [("left_arm", "【光束剑】")]
        player_mech.pending_combat = {"stage": "AWAITING_ATTACK_REROLL", "dummy": True}
        player_mech.has_acted_early = False
        player_mech.last_pos = (5, 4)

        d = player_mech.to_dict()
        restored = Mech.from_dict(d)

        # 基础属性
        assert restored.id == "player_1"
        assert restored.controller == "player"
        assert restored.name == "玩家机甲"
        assert restored.pos == (5, 5)
        assert restored.orientation == "E"

        # 部件
        assert len(restored.parts) == 5
        assert restored.parts["core"].name == "试作型核心"
        assert restored.parts["left_arm"].actions[0].name == "【光束剑】"

        # 驾驶员
        assert restored.pilot.name == "测试驾驶员"
        assert restored.pilot.link_points == 5

        # 回合状态
        assert restored.stance == "attack"
        assert restored.player_ap == 1
        assert restored.turn_phase == "main"
        assert restored.timing == "近战"
        assert restored.opening_move_taken is True
        # to_dict→from_dict 循环中 tuple 会被序列化为 list（JSON 兼容性）
        assert restored.actions_used_this_turn == [["left_arm", "【光束剑】"]]

        # 中断状态
        assert restored.pending_combat == {"stage": "AWAITING_ATTACK_REROLL", "dummy": True}
        assert restored.has_acted_early is False
        assert restored.last_pos == (5, 4)

    def test_from_dict_default_state(self):
        """新机甲 with_dict 有合理的默认值"""
        data = {
            "id": "mech_1", "controller": "player", "pos": (1, 1),
            "orientation": "N", "name": "默认机甲",
            "parts": {"core": {"name": "测试核心", "armor": 2, "structure": 3}}
        }
        mech = Mech.from_dict(data)
        assert mech.stance == "defense"
        assert mech.player_ap == 2
        assert mech.player_tp == 1
        assert mech.turn_phase == "timing"
        assert mech.timing is None
        assert mech.opening_move_taken is False
        assert mech.actions_used_this_turn == []
        assert mech.pending_combat is None
        assert mech.has_acted_early is False

    def test_from_dict_parts_with_missing_slots(self):
        """某些部件槽位缺失也不崩溃"""
        data = {
            "id": "mech_1", "controller": "player", "pos": (1, 1),
            "orientation": "N", "name": "不完整机甲",
            "parts": {"core": {"name": "核心", "armor": 1, "structure": 1}}
        }
        mech = Mech.from_dict(data)
        assert mech.parts["core"] is not None
        # 缺失的槽位应为 None (safe_part_load 返回 None)
        assert mech.parts.get("legs") is None

    def test_double_serialization(self, player_mech):
        """多次序列化/反序列化一致性"""
        d1 = player_mech.to_dict()
        r1 = Mech.from_dict(d1)
        d2 = r1.to_dict()
        r2 = Mech.from_dict(d2)
        # 两次往返后应一致
        assert r2.name == r1.name
        assert r2.stance == r1.stance
        assert r2.pilot.link_points == r1.pilot.link_points


# ============================================================
# Projectile 序列化
# ============================================================

class TestProjectileSerialization:

    def test_round_trip(self, simple_projectile):
        """抛射物序列化往返"""
        simple_projectile.has_acted = True
        d = simple_projectile.to_dict()
        restored = Projectile.from_dict(d)

        assert restored.id == "proj_1"
        assert restored.entity_type == "projectile"
        assert restored.controller == "player"
        assert restored.name == "【导弹】"
        assert restored.evasion == 2
        assert restored.stance == "agile"
        assert restored.life_span == 2
        assert restored.electronics == 0
        assert restored.move_range == 3
        assert restored.has_acted is True
        assert restored.parts["core"].name == "【导弹】 核心"

    def test_from_dict_defaults(self):
        """旧存档中缺失 has_acted"""
        data = {
            "id": "proj_1", "controller": "player", "pos": (3, 5),
            "name": "导弹", "evasion": 2, "stance": "agile",
            "parts": {"core": {"name": "核心", "armor": 0, "structure": 1, "actions": []}},
            "life_span": 2, "electronics": 0, "move_range": 3
        }
        restored = Projectile.from_dict(data)
        assert restored.has_acted is False


# ============================================================
# GameEntity.from_dict() 多态
# ============================================================

class TestGameEntityPolymorphism:

    def test_deserialize_mech(self, player_mech):
        """from_dict 根据 entity_type 自动反序列化为 Mech"""
        d = player_mech.to_dict()
        entity = GameEntity.from_dict(d)
        assert isinstance(entity, Mech)
        assert entity.id == "player_1"
        assert entity.name == "玩家机甲"

    def test_deserialize_projectile(self, simple_projectile):
        """from_dict 根据 entity_type 自动反序列化为 Projectile"""
        d = simple_projectile.to_dict()
        entity = GameEntity.from_dict(d)
        assert isinstance(entity, Projectile)
        assert entity.id == "proj_1"

    def test_deserialize_unknown_type(self):
        """未知类型回退到基础 GameEntity"""
        data = {
            "entity_type": "unknown_type", "id": "u1",
            "controller": "neutral", "pos": (1, 1), "name": "未知"
        }
        entity = GameEntity.from_dict(data)
        assert isinstance(entity, GameEntity)
        assert not isinstance(entity, Mech)
        assert entity.name == "未知"


# ============================================================
# Mech 接口方法
# ============================================================

class TestMechMethods:

    def test_get_total_evasion(self, player_mech):
        """总闪避值 = 所有未摧毁部件的 evasion 之和"""
        # 试作型左臂 evasion=0, 右臂 evasion=1, 腿部 evasion=2, 背包 evasion=1
        expected = player_mech.parts["legs"].evasion + \
                   player_mech.parts["right_arm"].evasion + \
                   player_mech.parts["backpack"].evasion
        assert player_mech.get_total_evasion() == expected  # 2 + 1 + 1 = 4

    def test_get_total_evasion_excludes_destroyed(self, player_mech):
        """被摧毁的部件不计入闪避"""
        player_mech.parts["legs"].status = "destroyed"
        expected = player_mech.parts["right_arm"].evasion + player_mech.parts["backpack"].evasion
        assert player_mech.get_total_evasion() == expected  # 1 + 1 = 2

    def test_get_total_electronics(self, player_mech):
        """总电子值计算"""
        assert player_mech.get_total_electronics() == 2  # 只有 core 有 electronics=2

    def test_get_active_parts_count(self, player_mech):
        assert player_mech.get_active_parts_count() == 5

    def test_get_active_parts_count_destroyed(self, player_mech):
        player_mech.parts["left_arm"].status = "destroyed"
        assert player_mech.get_active_parts_count() == 4

    def test_has_melee_action(self, player_mech):
        """有光束剑，所以有近战"""
        assert player_mech.has_melee_action() is True

    def test_has_melee_action_generic(self, player_mech):
        """GENERIC_ACTIONS 提供拳打脚踢，所以即使清除所有部件动作也有近战"""
        player_mech.parts["left_arm"].actions = []
        player_mech.parts["right_arm"].actions = []
        # 拳打脚踢需要 left_arm, right_arm, 或 legs — legs 还在
        assert player_mech.has_melee_action() is True

    def test_get_action_by_name_and_slot(self, player_mech):
        """通过部件槽和名称获取动作"""
        action = player_mech.get_action_by_name_and_slot("【光束剑】", "left_arm")
        assert action is not None
        assert action.name == "【光束剑】"
        assert action.action_type == "近战"

    def test_get_action_by_name_and_slot_not_found(self, player_mech):
        """找不到动作返回 None"""
        assert player_mech.get_action_by_name_and_slot("不存在", "left_arm") is None

    def test_get_part_by_name(self, player_mech):
        """通过显示名称获取部件"""
        part = player_mech.get_part_by_name("试作型核心")
        assert part is not None
        assert part.armor == 3
        assert part.structure == 4

    def test_get_part_by_slot_name(self, player_mech):
        """通过槽位名称获取部件"""
        part = player_mech.get_part_by_name("core")
        assert part is not None
        assert part.name == "试作型核心"

    def test_get_all_actions(self, player_mech):
        """获取所有动作"""
        actions = player_mech.get_all_actions()
        # 左臂有【光束剑】，右臂有【步枪】
        action_names = [a[0].name for a in actions]
        assert "【光束剑】" in action_names
        assert "【步枪】" in action_names

    def test_get_passive_effects_empty(self, player_mech):
        """当前机甲没有被动效果"""
        assert player_mech.get_passive_effects() == []

    def test_get_interceptor_actions_empty(self, player_mech):
        """当前机甲没有拦截动作"""
        assert player_mech.get_interceptor_actions() == []
