"""
【数据库 - AI部件】

定义所有AI专用的部件 (AI_ONLY_...)。

依赖于:
- ..data_models (导入 Part 类)
- ._actions (导入 AI 需要的 ACTION_... 常量)
"""

# 导入数据模型
from ..data_models import Part

# 导入动作
from ._actions import (
    ACTION_BENPAO,
    ACTION_JINGJU,
    ACTION_PAOJI
)


# === AI专用部件 - 核心 ===

AI_ONLY_CORES = {
    'GK-09 "壁垒"核心': Part(name='GK-09 "壁垒"核心', armor=8, structure=3, electronics=1),
    'GK-08 "哨兵"核心': Part(name='GK-08 "哨兵"核心', armor=5, structure=1, electronics=1, evasion=3),
}

# === AI专用部件 - 下肢 ===

AI_ONLY_LEGS = {
    'TK-05 坦克履带': Part(name='TK-05 坦克履带', armor=6, structure=3, evasion=0, adjust_move=1,
                           actions=[ACTION_BENPAO]),
}

# === AI专用部件 - 左臂 ===

AI_ONLY_LEFT_ARMS = {
    'LH-8 早期型霰弹破片炮': Part(name='LH-8 早期型霰弹破片炮', armor=5, structure=0, parry=0, actions=[ACTION_JINGJU]),
}

# === AI专用部件 - 右臂 ===

AI_ONLY_RIGHT_ARMS = {
    'LGP-80 长程火炮': Part(name='LGP-80 长程火炮', armor=3, structure=0, actions=[ACTION_PAOJI]),
}

# === AI专用部件 - 背包 ===

AI_ONLY_BACKPACKS = {
    'EB-03 扩容电池': Part(name='EB-03 扩容电池', armor=2, structure=0, electronics=3),
}