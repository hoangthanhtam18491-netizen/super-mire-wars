"""
【数据库 - 抛射物】

定义所有抛射物实体 (PROJECTILE_TEMPLATES)。

依赖于:
- ..data_models (导入 Projectile - 尽管这里没直接用)
- ._actions (导入抛射物“内部”使用的动作，如 ACTION_IMMEDIATE_EXPLOSION)
"""

# 导入抛射物内部动作
# （注意：这些动作是在 _actions.py 中定义的）
from ._actions import (
    ACTION_IMMEDIATE_EXPLOSION,
    ACTION_DELAYED_GUIDED_ATTACK,
    ACTION_DELAYED_GUIDED_ATTACK_K
)

# === 抛射物模板 (Projectile Templates) ===
# 定义所有抛射物实体的数据

PROJECTILE_TEMPLATES = {
    "RA_81_ROCKET": {
        "name": "RA-81火箭弹",
        "entity_type": "projectile",
        "evasion": 4,
        "stance": "agile",
        "structure": 1,
        "armor": 0,
        "life_span": 1,
        # 使用导入的动作常量并转换为字典
        "actions": [ACTION_IMMEDIATE_EXPLOSION.to_dict()],
        "electronics": 0,
        "move_range": 0
    },
    "MC_3_SWORD_MISSILE": {
        "name": "MC-3 “利剑”导弹",
        "entity_type": "projectile",
        "evasion": 6,
        "electronics": 1,
        "stance": "agile",
        "structure": 1,
        "armor": 0,
        "life_span": 99,
        # 使用导入的动作常量并转换为字典
        "actions": [ACTION_DELAYED_GUIDED_ATTACK.to_dict()],
        "move_range": 3
    },
    "MR-10 RED KESTREL_MISSILE": {
        "name": "MR-10 “红隼”导弹",
        "entity_type": "projectile",
        "evasion": 4,
        "electronics": 1,
        "stance": "agile",
        "structure": 1,
        "armor": 0,
        "life_span": 99,
        # 使用导入的动作常量并转换为字典
        "actions": [ACTION_DELAYED_GUIDED_ATTACK_K.to_dict()],
        "move_range": 6
    }
}