"""
【数据库 - AI配置】

定义 AI 对手的预设配置 (AI_LOADOUTS)。

这个文件不依赖数据库中的其他文件，它使用“字符串名称”来定义配置。
这些字符串名称将在 __init__.py 文件中被用于从部件字典中查找部件。
"""

# === AI 配置 (AI Loadouts) ===
# 定义 AI 对手的预设配置

AI_LOADOUT_HEAVY = {
    'name': "AI机甲 (重火炮型)",
    'selection': {
        'core': 'GK-09 "壁垒"核心',
        'legs': 'TK-05 坦克履带',
        'left_arm': 'LH-8 早期型霰弹破片炮',
        'right_arm': 'LGP-80 长程火炮',
        'backpack': 'EB-03 扩容电池'
    }
}
AI_LOADOUT_HEAVY_M = {
    'name': "AI机甲 (重导弹型)",
    'selection': {
        'core': 'GK-09 "壁垒"核心',
        'legs': 'TK-05 坦克履带',
        'left_arm': 'ML-32 双联发射器 + CC-3 格斗刀',
        'right_arm': '63型 臂炮 + CC-20 单手剑（右）',
        'backpack': 'ML-94 四联导弹包'
    }
}
AI_LOADOUT_STANDARD = {
    'name': "AI机甲 (标准泥沼型)",
    'selection': {
        'core': 'RT-06 "泥沼"核心',
        'legs': 'RL-06 标准下肢',
        'left_arm': '55型 轻盾 + CC-6 格斗刀',
        'right_arm': 'AC-32 自动步枪',
        'backpack': 'AMS-190 主动防御'
    }
}
AI_LOADOUT_LIGHTA = {
    'name': "AI机甲 (高速射手型)",
    'selection': {
        'core': 'GK-08 "哨兵"核心',
        'legs': 'RL-03D “快马”高速下肢',
        'left_arm': 'R-20 肩置磁轨炮（左）',
        'right_arm': 'R-20 肩置磁轨炮（右）',
        'backpack': 'TB-600 跳跃背包'
    }
}
AI_LOADOUT_LIGHTB = {
    'name': "AI机甲 (高速近战型)",
    'selection': {
        'core': 'GK-08 "哨兵"核心',
        'legs': 'RL-03D “快马”高速下肢',
        'left_arm': '62型 臂盾 + CC-20 单手剑（左）',
        'right_arm': '63型 臂炮 + CC-20 单手剑（右）',
        'backpack': 'TB-600 跳跃背包'
    }
}

# AI 加载项的主字典
AI_LOADOUTS = {
    "heavy": AI_LOADOUT_HEAVY,
    "heavy_m": AI_LOADOUT_HEAVY_M,
    "standard": AI_LOADOUT_STANDARD,
    "lighta": AI_LOADOUT_LIGHTA,
    "lightb": AI_LOADOUT_LIGHTB,
}