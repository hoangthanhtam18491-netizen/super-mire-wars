"""
【数据库 - 通用动作】

定义所有机甲都能使用的基础动作 (例如：拳打脚踢)。

依赖于:
- ..data_models (导入 Action 类)
"""

# 导入数据模型
from ..data_models import Action

# === 通用动作 (Generic Actions) ===
# 定义所有机甲都能使用的基础动作

ACTION_PUNCH_KICK = Action(
    name="拳打脚踢",
    action_type="近战",
    cost="M",
    dice="2红",
    range_val=1
)

# GENERIC_ACTIONS 定义了哪些部件槽位可以激活这些动作
GENERIC_ACTIONS = {
    ACTION_PUNCH_KICK: ['left_arm', 'right_arm', 'legs']
}