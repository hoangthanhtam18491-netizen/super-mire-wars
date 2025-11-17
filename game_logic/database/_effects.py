"""
【数据库 - 效果库】

定义所有游戏中可复用的特殊效果 (EFFECT_...)
以及用于构建它们的辅助函数。

这个文件是数据库包的基础，不依赖包内其他文件。
"""


# === 效果构建辅助函数 ===

def build_effects(*effects_list):
    """
    一个辅助函数，用于将多个效果字典合并为一个统一的 effects 对象。
    它会合并所有 "logic" 字典，并收集所有 "name" 到 "display_effects" 列表中。

    Args:
        *effects_list (dict): 任意数量的效果字典。

    Returns:
        dict: 一个合并后的 effects 字典。
    """
    final_effects = {}
    display_list = []
    for effect in effects_list:
        final_effects.update(effect.get("logic", {}))
        if "name" in effect:
            display_list.append(effect["name"])
    if display_list:
        final_effects["display_effects"] = display_list
    return final_effects


# === 效果定义 (Effect Library) ===
# 定义所有游戏中可能出现的特殊效果，以便复用。

EFFECT_AP_1 = {
    "logic": {"armor_piercing": 1},
    "name": "【穿甲1】"
}
EFFECT_STROBE_WEAPON = {
    "logic": {"convert_lightning_to_crit": True},
    "name": "【频闪武器】"
}
EFFECT_PASSIVE_COOLING = {
    "logic": {
        "passive_dice_boost": {
            "trigger_stance": "attack",
            "trigger_type": "射击",
            "ratio_base": 3,
            "ratio_add": 1,
            "dice_type": "yellow_count"
        }
    },
    "name": "【增强冷却】"
}
EFFECT_STATIC = {
    "logic": {"is_static": True},
    "name": "【静止】"
}
EFFECT_STATIC_RANGE_2 = {
    "logic": {
        "is_static": True,
        "static_range_bonus": 2
    },
    "name": "【静止 +2射程】"
}
EFFECT_STATIC_PLUS_YELLOW_DICE = {
    "logic": {
        "is_static": True,
        "yellow_dice_bonus": 1
    },
    "name": "【静止 +1黄骰子】"
}
EFFECT_TWO_HANDED_RANGE_2 = {
    "logic": {"two_handed_range_bonus": 2},
    "name": "【【双手】+2射程】"
}
EFFECT_TWO_HANDED_SNIPER = {
    "logic": {"two_handed_sniper": True},
    "name": "【【双手】获得狙击】"
}
EFFECT_DEVASTATING = {
    "logic": {"devastating": True},
    "name": "【毁伤】"
}
EFFECT_SCATTERSHOT = {
    "logic": {"scattershot": True},
    "name": "【霰射】"
}
EFFECT_CLEAVE = {
    "logic": {"cleave": True},
    "name": "【顺劈】"
}
EFFECT_TWO_HANDED_DEVASTATING = {
    "logic": {"two_handed_devastating": True},
    "name": "【【双手】获得毁伤】"
}
EFFECT_FLIGHT_MOVEMENT = {
    "logic": {"flight_movement": True},
    "name": "【空中移动】"
}
EFFECT_JETTISON = {
    "logic": {"jettison_part": True},
    "name": "【弃置】"
}
EFFECT_SALVO_2 = {
    "logic": {"salvo": 2},
    "name": "【齐射2】"
}
EFFECT_SALVO_4 = {
    "logic": {"salvo": 4},
    "name": "【齐射4】"
}
EFFECT_CURVED_FIRE = {
    "logic": {"action_style": "curved"},
    "name": "【曲射】"
}
EFFECT_INTERCEPTOR_3 = {
    "logic": {"interceptor": 3, "intercept_range": 3},
    "name": "【拦截3】"
}
EFFECT_SHOCK = {
    "logic": {"shock": True},
    "name": "【震撼】"
}

# 喷射冲刺效果
EFFECT_JET_SPRINT = {
    "logic": {"straight_line_bonus": 2},  # 赋予 API 检查的逻辑密钥
    "name": "【直线移动】+2移动距离"  # 赋予前端显示的名称
}