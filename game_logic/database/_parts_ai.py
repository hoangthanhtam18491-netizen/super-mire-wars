"""
【数据库 - AI部件】

定义所有AI专用的部件 (AI_ONLY_...)。

依赖于:
- ..data_models (导入 Part 类)
- ._actions (导入 AI 需要的 ACTION_... 常量)
"""
from . import ACTION_CIJI, ACTION_LAUNCH_GUIDED_MISSILE
# 导入数据模型
from ..data_models import Part

# 导入动作
from ._actions import (ACTION_BENPAO, ACTION_JINGJU, ACTION_PAOJI, ACTION_BATLLETYPE, ACTION_TUIJING, ACTION_DIANSHE_RF,
                       ACTION_LIANSHE_RF, ACTION_LAUNCH_GRENADE_SONG, ACTION_CIJI_PB,
                       ACTION_CHUANCI_PB, ACTION_LAUNCH_GUIDED_MISSILE_PB, ACTION_ARMOR_ASSULT, ACTION_DUNJI,
                       ACTION_BENPAO_231, ACTION_DIANSHE_IGX106, ACTION_DIANSHE_R7K, ACTION_SUSHE_R7K
                       )


# === AI专用部件 - 核心 ===

AI_ONLY_CORES = {
    'GK-09 "壁垒"核心': Part(name='GK-09 "壁垒"核心', armor=8, structure=3, electronics=1),
    'GK-08 "哨兵"核心': Part(name='GK-08 "哨兵"核心', armor=5, structure=1, electronics=1, evasion=3),
    'HC-2000/BC “渡鸦”核心': Part(name='HC-2000/BC “渡鸦”核心', armor=5, structure=3, electronics=3, evasion=3, actions=[ACTION_BATLLETYPE]),
    'TM31Q “野猫”主战核心': Part(name='TM31Q “野猫”主战核心', armor=4, structure=4, electronics=1, evasion=3, actions=[]),
}

# === AI专用部件 - 下肢 ===

AI_ONLY_LEGS = {
    'TK-05 坦克履带': Part(name='TK-05 坦克履带', armor=6, structure=3, evasion=0, adjust_move=1, actions=[ACTION_BENPAO]),
    '2C-2000 探查型双足': Part(name='2C-2000 探查型双足', armor=4, structure=0, evasion=3, adjust_move=1, actions=[ACTION_TUIJING]),
    'LM231 标准下肢': Part(name='LM231 标准下肢', armor=4, structure=0, evasion=4, adjust_move=1, actions=[ACTION_BENPAO_231]),
}

# === AI专用部件 - 左臂 ===

AI_ONLY_LEFT_ARMS = {
    'LH-8 早期型霰弹破片炮': Part(name='LH-8 早期型霰弹破片炮', armor=5, structure=0, parry=0, actions=[ACTION_JINGJU]),
    'RF-025 突击步枪 + SONGBIRDS 榴弹加农炮': Part(name='RF-025 突击步枪 + SONGBIRDS 榴弹加农炮', armor=4, structure=0, parry=0, actions=[ACTION_DIANSHE_RF, ACTION_LIANSHE_RF, ACTION_LAUNCH_GRENADE_SONG]),
    'S9 “流星”盾 + IGX106 离子炮': Part(name='S9 “流星”盾 + IGX106 离子炮', armor=4, structure=0, parry=2, evasion=1, actions=[ACTION_DUNJI, ACTION_DIANSHE_IGX106])
}

# === AI专用部件 - 右臂 ===

AI_ONLY_RIGHT_ARMS = {
    'LGP-80 长程火炮': Part(name='LGP-80 长程火炮', armor=3, structure=0, actions=[ACTION_PAOJI]),
    'PB-033M 打桩机 + BML-G1 双向飞弹': Part(name='PB-033M 打桩机 + BML-G1 双向飞弹', armor=5, structure=0, parry=2, actions=[ACTION_CIJI_PB, ACTION_CHUANCI_PB, ACTION_LAUNCH_GUIDED_MISSILE_PB]),
    'R7K 战术步枪': Part(name='R7K 战术步枪', armor=4, structure=0, parry=2, evasion=1, actions=[ACTION_DIANSHE_R7K, ACTION_SUSHE_R7K]),
}

# === AI专用部件 - 背包 ===

AI_ONLY_BACKPACKS = {
    'EB-03 扩容电池': Part(name='EB-03 扩容电池', armor=2, structure=0, electronics=3),
    'ASSAULT 突击装甲': Part(name='ASSAULT 突击装甲', armor=3, structure=0, electronics=3, actions=[ACTION_ARMOR_ASSULT]),
    'JP5 机动提升包': Part(name='JP5 机动提升包', armor=3, structure=0, evasion=2, actions=[]),
}