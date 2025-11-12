# 导入数据模型
from game_logic.data_models import Action, Part, Projectile, Pilot

# === 效果构建辅助函数 ===

def build_effects(*effects_list):
    """
    一个辅助函数，用于将多个效果字典合并为一个统一的 effects 对象。
    它会合并所有 "logic" 字典，并收集所有 "name" 到 "display_effects" 列表中。
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

# [新增] 喷射冲刺效果
EFFECT_JET_SPRINT = {
    "logic": {"straight_line_bonus": 2}, # 赋予 API 检查的逻辑密钥
    "name": "【直线移动】+2移动距离" # 赋予前端显示的名称
}


# === 动作定义 (Action Library) ===

# --- 近战 (Melee) ---
ACTION_CIJI = Action(name="刺击", action_type="近战", cost="S", dice="3黄1红", range_val=1)
ACTION_JINGJU = Action(name='近距开火', action_type='近战', cost='S', dice='5黄', range_val=1)
ACTION_HUIZHAN = Action(name='挥斩', action_type='近战', cost='S', dice='4黄1红', range_val=1,
                        effects=build_effects(EFFECT_STROBE_WEAPON)
                        )
ACTION_PIKAN = Action(name='劈砍', action_type='近战', cost='S', dice='3黄1红', range_val=1,
                        effects=build_effects(EFFECT_STROBE_WEAPON)
                        )
ACTION_HUIZHAN_ZHONG = Action(name='挥斩【重】', action_type='近战', cost='M', dice='2黄4红', range_val=1,
                        effects=build_effects(EFFECT_STROBE_WEAPON, EFFECT_CLEAVE, EFFECT_TWO_HANDED_DEVASTATING))
ACTION_DUNJI = Action(name="盾击", action_type="近战", cost="S", dice="5黄", range_val=1,
                        effects=build_effects(EFFECT_SHOCK))

# --- 射击 (Ranged) ---
ACTION_DIANSHE = Action(name="点射", action_type="射击", cost="M", dice="1黄3红", range_val=6,
                        effects=build_effects(EFFECT_TWO_HANDED_RANGE_2))
ACTION_DIANSHE_CI = Action(name="点射【磁】", action_type="射击", cost="S", dice="3红", range_val=6,
                           effects=build_effects(EFFECT_AP_1, EFFECT_STATIC_RANGE_2))
ACTION_DIANSHE_XIAN = Action(name="点射【霰射】", action_type="射击", cost="S", dice="2黄2红", range_val=3,
                           effects=build_effects(EFFECT_SCATTERSHOT))
ACTION_JUJI = Action(name="狙击", action_type="射击", cost="M", dice="2黄2红", range_val=12,
                     effects=build_effects(EFFECT_TWO_HANDED_SNIPER))
ACTION_PAOJI = Action(name="炮击", action_type="射击", cost="L", dice="1黄4红", range_val=12,
                      effects=build_effects(EFFECT_DEVASTATING))
ACTION_DIANSHE_HUOPAO = Action(name="点射", action_type="射击", cost="L", dice="1黄4红", range_val=12,
                      effects=build_effects(EFFECT_DEVASTATING))
ACTION_SAOSHE = Action(name="扫射", action_type="射击", cost="S", dice="4黄", range_val=4)
ACTION_SUSHE_BIPAO = Action(name="速射", action_type="射击", cost="S", dice="4黄", range_val=4)
ACTION_SUSHE = Action(name="速射", action_type="射击", cost="M", dice="4黄1红", range_val=6,
                        effects=build_effects(EFFECT_TWO_HANDED_RANGE_2))
ACTION_DIANSHE_ZHAN = Action(name="点射(战)", action_type="射击", cost="S", dice="1黄2红", range_val=6)

# --- 快速 (Quick) ---
ACTION_JETTISON = Action(name="【弃置】", action_type="快速", cost="S", dice="", range_val=0,
                         effects=build_effects(EFFECT_JETTISON))

# --- 移动 (Movement) ---
ACTION_BENPAO = Action(name="奔跑", action_type="移动", cost="M", dice="", range_val=4)
ACTION_TIAOYUE = Action(name="跳跃", action_type="移动", cost="S", dice="", range_val=2,
                        effects=build_effects(EFFECT_FLIGHT_MOVEMENT))
ACTION_BENPAO_MA = Action(name="奔跑（马）", action_type="移动", cost="M", dice="", range_val=5)

# [新增] 喷射冲刺动作
ACTION_JET_SPRINT = Action(
    name="喷射冲刺",
    action_type="移动",
    cost="M",
    dice="",
    range_val=3, # 基础移动 3 格
    effects=build_effects(EFFECT_JET_SPRINT) # 关联直线移动效果
)

# --- 被动 (Passive) ---
ACTION_NONE = Action(name="无动作", action_type="被动", cost="", dice="", range_val=0)
ACTION_ENHANCED_COOLING = Action(name="增强冷却", action_type="被动", cost="", dice="", range_val=0,
                                 effects=build_effects(EFFECT_PASSIVE_COOLING))

# --- 拦截 (Interceptor) ---
ACTION_AUTO_INTERCEPT = Action(
    name="自动拦截",
    action_type="被动", # 拦截动作是被动触发的
    cost="",
    dice="3黄", # 拦截时投掷 3 个黄骰
    range_val=3, # 拦截触发范围
    ammo=3,      # 弹药量
    effects=build_effects(EFFECT_INTERCEPTOR_3)
)

# --- 抛射物发射 (Projectile Launch) ---
ACTION_LAUNCH_ROCKET = Action(
    name="火箭弹",
    action_type="抛射",
    cost="M",
    dice="",
    range_val=12,
    action_style='direct',
    projectile_to_spawn='RA_81_ROCKET',
    ammo=2
)
ACTION_LAUNCH_GUIDED_MISSILE = Action(
    name="导弹",
    action_type="抛射",
    cost="M",
    dice="",
    range_val=3,
    action_style='curved',
    projectile_to_spawn='MC_3_SWORD_MISSILE',
    ammo=2,
    effects=build_effects(EFFECT_SALVO_2, EFFECT_CURVED_FIRE)
)
ACTION_LAUNCH_GUIDED_MISSILE_K = Action(
    name="导弹(红隼)",
    action_type="抛射",
    cost="M",
    dice="",
    range_val=6,
    action_style='curved',
    projectile_to_spawn='MR-10 RED KESTREL_MISSILE',
    ammo=4,
    effects=build_effects(EFFECT_SALVO_4, EFFECT_CURVED_FIRE)
)

# --- 抛射物内部动作 (Immediate / Delayed) ---
ACTION_IMMEDIATE_EXPLOSION = Action(
    name="多级串联战斗部",
    action_type="立即",
    cost="",
    dice="3红",
    range_val=0,
    aoe_range=0
)
ACTION_DELAYED_GUIDED_ATTACK = Action(
    name="制导攻击",
    action_type="延迟",
    cost="",
    dice="1黄3红",
    range_val=0,
    aoe_range=0
)
ACTION_DELAYED_GUIDED_ATTACK_K = Action(
    name="制导攻击_红隼",
    action_type="延迟",
    cost="",
    dice="2红",
    range_val=0,
    aoe_range=0
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
        "actions": [ACTION_DELAYED_GUIDED_ATTACK_K.to_dict()],
        "move_range": 6
    }
}


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


# === 驾驶员数据库 (Pilot Database) ===

PILOT_TEST = Pilot(name="【测试驾驶员】") # 默认测试驾驶员

PLAYER_PILOTS = {
    "【测试驾驶员】": PILOT_TEST
}

AI_PILOTS = {} # AI 目前不使用驾驶员


# === 玩家部件 - 核心 (Player Cores) ===

PLAYER_CORES = {
    'RT-06 "泥沼"核心': Part(name='RT-06 "泥沼"核心', armor=6, structure=2, electronics=2,
                            image_url='static/images/parts/RT-06.png'),
}

# === 玩家部件 - 下肢 (Player Legs) ===

PLAYER_LEGS = {
    'RL-06 标准下肢': Part(name='RL-06 标准下肢', armor=5, structure=0, evasion=3, adjust_move=1,
                           actions=[ACTION_BENPAO],
                           image_url='static/images/parts/RL-06.png'),
    'RL-03D “快马”高速下肢': Part(name='RL-03D “快马”高速下肢', armor=4, structure=0, evasion=4, adjust_move=2,
                                  actions=[ACTION_BENPAO_MA],
                           image_url='static/images/parts/RL-03D.png'),
    # [修改] RL-08 重甲下肢
    'RL-08 重甲下肢': Part(name='RL-08 重甲下肢', armor=6, structure=1, evasion=3, adjust_move=1,
                            # [修改] 动作从 ACTION_BENPAO 替换为 ACTION_JET_SPRINT
                            actions=[ACTION_JET_SPRINT],
                           image_url='static/images/parts/RL-08.png'),
}

# === 玩家部件 - 左臂 (Player Left Arms) ===

PLAYER_LEFT_ARMS = {
    'ML-32 双联发射器 + CC-3 格斗刀': Part(name='ML-32 双联发射器 + CC-3 格斗刀', armor=4, structure=0, parry=1,
                       actions=[ACTION_CIJI, ACTION_LAUNCH_GUIDED_MISSILE],  tags=["【空手】"],
                           image_url='static/images/parts/CC-3.png'),
    '55型 轻盾 + CC-6 格斗刀': Part(name='55型 轻盾 + CC-6 格斗刀', armor=5, structure=0, parry=2, actions=[ACTION_DUNJI, ACTION_PIKAN, ACTION_JETTISON],
                       tags=["【手持】"],
                           image_url='static/images/parts/CC-6.png'),
    '55型 轻盾 + CC-6 格斗刀（弃置）': Part(name='55型 轻盾 + CC-6 格斗刀（弃置）', armor=5, structure=0, parry=2, actions=[ACTION_DUNJI],
                       tags=["【空手】"],
                           image_url='static/images/parts/CC-6Q.png'),
    'R-20 肩置磁轨炮（左）': Part(name='R-20 肩置磁轨炮（左）', armor=4, structure=0, parry=0, actions=[ACTION_DIANSHE_CI],
                       tags=["【空手】"],
                           image_url='static/images/parts/R-20L.png'),
    '62型 臂盾 + CC-20 单手剑（左）': Part(name='62型 臂盾 + CC-20 单手剑（左）', armor=5, structure=0,
                       parry=3, actions=[ACTION_HUIZHAN],tags=["【空手】"],
                           image_url='static/images/parts/CC-20L.png'),
    '55型 轻盾': Part(name='55型 轻盾', armor=5, structure=0, parry=2, actions=[ACTION_DUNJI],
                       tags=["【空手】"],
                           image_url='static/images/parts/55.png'),
    '55 型轻盾 + PC-9 霰弹枪（左）': Part(name='55 型轻盾 + PC-9 霰弹枪（左）', armor=5, structure=0, parry=2, actions=[ACTION_DIANSHE_XIAN, ACTION_JETTISON],
                       tags=["【手持】"],
                           image_url='static/images/parts/PC-9L.png'),
    '55 型轻盾 + PC-9 霰弹枪（左）（弃置）': Part(name='55 型轻盾 + PC-9 霰弹枪（左）（弃置）', armor=5, structure=0, parry=2, actions=[ACTION_DUNJI],
                       tags=["【空手】"],
                           image_url='static/images/parts/PC-9LQ.png'),
    'G/AC-6 火箭筒': Part(name='G/AC-6 火箭筒', armor=4, structure=0, parry=0, actions=[ACTION_LAUNCH_ROCKET, ACTION_JETTISON],
                       tags=["【手持】"],
                           image_url='static/images/parts/GAC-6.png'),
    'G/AC-6 火箭筒（弃置）': Part(name='G/AC-6 火箭筒（弃置）', armor=4, structure=0, parry=0,
                       tags=["【空手】"],
                           image_url='static/images/parts/GAC-6Q.png'),
}

# === 玩家部件 - 右臂 (Player Right Arms) ===

PLAYER_RIGHT_ARMS = {
    'AC-32 自动步枪': Part(name='AC-32 自动步枪', armor=4, structure=0, actions=[ACTION_DIANSHE, ACTION_JETTISON],
                         tags=["【手持】"],
                           image_url='static/images/parts/AC-32.png'),
    'AC-32 自动步枪（弃置）': Part(name='AC-32 自动步枪（弃置）', armor=4, structure=0,
                         tags=["【空手】"],
                           image_url='static/images/parts/AC-32Q.png'),
    'AC-35 狙击步枪': Part(name='AC-35 狙击步枪', armor=4, structure=0, actions=[ACTION_JUJI, ACTION_JETTISON], tags=["【手持】"],
                           image_url='static/images/parts/AC-35.png'),
    'AC-35 狙击步枪（弃置）': Part(name='AC-35 狙击步枪', armor=4, structure=0, tags=["【空手】"],
                           image_url='static/images/parts/AC-35Q.png'),
    'R-20 肩置磁轨炮（右）': Part(name='R-20 肩置磁轨炮（右）', armor=4, structure=0, parry=0, actions=[ACTION_DIANSHE_CI],
                         tags=["【空手】"],
                           image_url='static/images/parts/R-20R.png'),
    'AC-39 战术步枪': Part(name='AC-39 战术步枪', armor=4, structure=0, actions=[ACTION_SUSHE, ACTION_DIANSHE_ZHAN, ACTION_JETTISON],
                         tags=["【手持】"],
                           image_url='static/images/parts/AC-39.png'),
    'AC-39 战术步枪（弃置）': Part(name='AC-39 战术步枪（弃置）', armor=4, structure=0,
                         tags=["【空手】"],
                           image_url='static/images/parts/AC-39Q.png'),
    '63型 臂炮 + CC-20 单手剑（右）': Part(name='63型 臂炮 + CC-20 单手剑（右）', armor=4, structure=0, parry=2,
                         actions=[ACTION_HUIZHAN, ACTION_SUSHE_BIPAO],tags=["【空手】"],
                           image_url='static/images/parts/CC-20R.png'),
    '55 型轻盾 + PC-9 霰弹枪（右）': Part(name='55 型轻盾 + PC-9 霰弹枪（右）', armor=5, structure=0, parry=2, actions=[ACTION_DIANSHE_XIAN, ACTION_JETTISON],
                       tags=["【手持】"],
                           image_url='static/images/parts/PC-9R.png'),
    '55 型轻盾 + PC-9 霰弹枪（右）（弃置）': Part(name='55 型轻盾 + PC-9 霰弹枪（右）（弃置）', armor=5, structure=0, parry=2, actions=[ACTION_DUNJI],
                       tags=["【空手】"],
                           image_url='static/images/parts/PC-9RQ.png'),
    'L-320 肩部机枪 + CC-90 重格斗刀': Part(name='L-320 肩部机枪 + CC-90 重格斗刀', armor=4, structure=0, parry=2,
                         actions=[ACTION_HUIZHAN_ZHONG, ACTION_SAOSHE, ACTION_JETTISON],tags=["【手持】"],
                           image_url='static/images/parts/CC-90.png'),
    'L-320 肩部机枪 + CC-90 重格斗刀（弃置）': Part(name='L-320 肩部机枪 + CC-90 重格斗刀（弃置）', armor=4, structure=0, parry=2,
                         actions=[ACTION_SAOSHE],tags=["【空手】"],
                           image_url='static/images/parts/CC-90Q.png'),
}

# === 玩家部件 - 背包 (Player Backpacks) ===

PLAYER_BACKPACKS = {
    'AMS-190 主动防御': Part(name='AMS-190 主动防御', armor=3, structure=0, electronics=1,actions=[ACTION_AUTO_INTERCEPT],
                           image_url='static/images/parts/AMS-190.png'),
    'TB-600 跳跃背包': Part(name='TB-600 跳跃背包', armor=3, structure=0, evasion=2,
                                    actions=[ACTION_TIAOYUE],
                           image_url='static/images/parts/TB-600.png'),
    'ECS-2 外置冷却器': Part(name='ECS-2 外置冷却器', armor=3, structure=0, evasion=1,
                             actions=[ACTION_ENHANCED_COOLING],
                           image_url='static/images/parts/ECS-2.png'),
    'LGP-80 长程火炮': Part(name='LGP-80 长程火炮', armor=3, structure=0, evasion=-2,
                                    actions=[ACTION_DIANSHE_HUOPAO],
                           image_url='static/images/parts/LGP-80.png'),
    'ML-94 四联导弹包': Part(name='ML-94 四联导弹包', armor=3, structure=0, evasion=0,
                                    actions=[ACTION_LAUNCH_GUIDED_MISSILE_K],
                           image_url='static/images/parts/ML-94.png'),
}

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
    "standard": AI_LOADOUT_STANDARD,
    "lighta": AI_LOADOUT_LIGHTA,
    "lightb": AI_LOADOUT_LIGHTB,
}


# === 最终部件数据库 ===
# 将玩家部件和 AI 专用部件合并为供游戏逻辑使用的总字典

CORES = {**PLAYER_CORES, **AI_ONLY_CORES}
LEGS = {**PLAYER_LEGS, **AI_ONLY_LEGS}
LEFT_ARMS = {**PLAYER_LEFT_ARMS, **AI_ONLY_LEFT_ARMS}
RIGHT_ARMS = {**PLAYER_RIGHT_ARMS, **AI_ONLY_RIGHT_ARMS}
BACKPACKS = {**PLAYER_BACKPACKS, **AI_ONLY_BACKPACKS}

# ALL_PARTS 字典包含了游戏中所有可用的部件
ALL_PARTS = {**CORES, **LEGS, **LEFT_ARMS, **RIGHT_ARMS, **BACKPACKS}