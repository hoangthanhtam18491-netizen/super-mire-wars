"""
共享测试夹具 (Fixtures)。
所有 test_*.py 文件中的测试函数均可使用这里定义的夹具。
"""
import sys
import os

# 确保项目根目录在 Python 路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from game_logic.data_models import Part, Action, Pilot, Mech, Projectile
from game_logic.dice_roller import DICE_FACES, roll_dice, process_rolls


# ============================================================
# 基础数据夹具
# ============================================================

@pytest.fixture
def sample_action():
    """一个标准的近战攻击动作"""
    return Action(
        name="【光束剑】",
        action_type="近战",
        cost="S",
        dice="2黄3红",
        range_val=2,
        effects={"armor_piercing": 1}
    )


@pytest.fixture
def sample_shoot_action():
    """一个标准的射击动作"""
    return Action(
        name="【步枪】",
        action_type="射击",
        cost="S",
        dice="1黄4红",
        range_val=5,
        effects={"shock": True}
    )


@pytest.fixture
def sample_action_with_devastating():
    """带毁伤效果的近战动作"""
    return Action(
        name="【重锤】",
        action_type="近战",
        cost="M",
        dice="3黄5红",
        range_val=1,
        effects={"devastating": True}
    )


@pytest.fixture
def sample_action_with_scattershot():
    """带霰射效果的射击动作"""
    return Action(
        name="【霰弹枪】",
        action_type="射击",
        cost="S",
        dice="2黄4红",
        range_val=3,
        effects={"scattershot": True}
    )


@pytest.fixture
def sample_core():
    """标准核心部件"""
    return Part(
        name="试作型核心",
        armor=3,
        structure=4,
        electronics=2,
        actions=[]
    )


@pytest.fixture
def sample_legs():
    """标准腿部部件"""
    return Part(
        name="试作型腿部",
        armor=2,
        structure=3,
        evasion=2,
        adjust_move=1,
        actions=[]
    )


@pytest.fixture
def sample_left_arm(sample_action):
    """标准左臂（带近战动作）"""
    return Part(
        name="试作型左臂",
        armor=1,
        structure=2,
        parry=2,
        actions=[sample_action]
    )


@pytest.fixture
def sample_right_arm(sample_shoot_action):
    """标准右臂（带射击动作）"""
    return Part(
        name="试作型右臂",
        armor=1,
        structure=2,
        evasion=1,
        actions=[sample_shoot_action]
    )


@pytest.fixture
def sample_backpack():
    """标准背包"""
    return Part(
        name="试作型背包",
        armor=1,
        structure=2,
        evasion=1,
        actions=[]
    )


@pytest.fixture
def sample_light_arm():
    """轻量空手部件（用于测试双手效果）"""
    return Part(
        name="试作型空手",
        armor=0,
        structure=1,
        evasion=2,
        tags=["【空手】"],
        actions=[]
    )


@pytest.fixture
def sample_pilot():
    """标准驾驶员"""
    return Pilot(
        name="测试驾驶员",
        link_points=5,
        speed_stats={'快速': 5, '近战': 5, '抛射': 5, '射击': 5, '移动': 5, '战术': 5},
        skills=[]
    )


@pytest.fixture
def sample_pilot_low_link():
    """低链接值驾驶员（用于宕机测试）"""
    return Pilot(
        name="新手驾驶员",
        link_points=1,
        speed_stats={'快速': 4, '近战': 4, '抛射': 4, '射击': 4, '移动': 4, '战术': 4},
        skills=[]
    )


@pytest.fixture
def sample_pilot_pursuit():
    """带乘胜追击技能的驾驶员"""
    return Pilot(
        name="王牌驾驶员",
        link_points=5,
        speed_stats={'快速': 6, '近战': 6, '抛射': 5, '射击': 6, '移动': 5, '战术': 5},
        skills=["pursuit"]
    )


@pytest.fixture
def player_mech(sample_core, sample_legs, sample_left_arm, sample_right_arm, sample_backpack, sample_pilot):
    """完整的玩家机甲"""
    return Mech(
        id="player_1",
        controller="player",
        pos=(5, 5),
        orientation="E",
        name="玩家机甲",
        core=sample_core,
        legs=sample_legs,
        left_arm=sample_left_arm,
        right_arm=sample_right_arm,
        backpack=sample_backpack,
        pilot=sample_pilot
    )


@pytest.fixture
def ai_mech(sample_core, sample_legs, sample_left_arm, sample_right_arm, sample_backpack, sample_pilot):
    """完整的 AI 机甲（与玩家对称）"""
    return Mech(
        id="ai_1",
        controller="ai",
        pos=(3, 5),
        orientation="W",
        name="AI机甲",
        core=sample_core,
        legs=sample_legs,
        left_arm=sample_left_arm,
        right_arm=sample_right_arm,
        backpack=sample_backpack,
        pilot=sample_pilot
    )


@pytest.fixture
def damaged_mech(player_mech):
    """部件已破损的机甲"""
    player_mech.parts["left_arm"].status = "damaged"
    player_mech.parts["core"].status = "damaged"
    return player_mech


@pytest.fixture
def simple_projectile():
    """简单抛射物"""
    return Projectile(
        id="proj_1",
        controller="player",
        pos=(3, 5),
        name="【导弹】",
        evasion=2,
        stance="agile",
        actions=[],
        life_span=2,
        electronics=0,
        move_range=3
    )


# ============================================================
# 骰子控制夹具 (用于确定性测试)
# ============================================================

class ControlledDiceRoller:
    """
    替换 random.choice，返回预设的骰子序列。
    使用方式:
        roller = ControlledDiceRoller(['heavy_hit', 'light_hit', ...])
        with monkeypatch...
    """

    def __init__(self, sequence):
        self.sequence = list(sequence)
        self.index = 0
        self.calls = []

    def choice(self, faces):
        if self.index >= len(self.sequence):
            # 循环使用序列（兜底）
            result = self.sequence[self.index % len(self.sequence)]
        else:
            result = self.sequence[self.index]
        self.index += 1
        self.calls.append((faces, result))
        return result


@pytest.fixture
def mock_random_choice(monkeypatch):
    """提供一个便捷方法，用预设序列替换 random.choice"""

    def _mock(sequence):
        roller = ControlledDiceRoller(sequence)
        monkeypatch.setattr("random.choice", roller.choice)
        return roller

    return _mock
