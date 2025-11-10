# [v_REFACTOR]
# 更新导入，从新的 game_logic 包中导入
from game_logic.data_models import Action, Part, Projectile, Pilot # [MODIFIED v2.2] 导入 Pilot

# --- 效果构建辅助函数 ---
def build_effects(*effects_list):
    final_effects = {}
    display_list = []
    for effect in effects_list:
        final_effects.update(effect.get("logic", {}))
        if "name" in effect:
            display_list.append(effect["name"])
    if display_list:
        final_effects["display_effects"] = display_list
    return final_effects



# --- 效果库 (Effect Library) ---
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
# [新增] 弃置效果
EFFECT_JETTISON = {
    "logic": {"jettison_part": True},
    "name": "【弃置】"
}
# [新增] 抛射效果
EFFECT_SALVO_2 = {
    "logic": {"salvo": 2},
    "name": "【齐射2】"
}
# [新增] 曲射 (注意: 也在 Action 构造函数中设置 action_style)
EFFECT_CURVED_FIRE = {
    "logic": {"action_style": "curved"},
    "name": "【曲射】"
}
# [新增] 拦截效果
EFFECT_INTERCEPTOR_3 = {
    "logic": {"interceptor": 3, "intercept_range": 3},
    "name": "【拦截3】"
}
# --- 效果库结束 ---


# --- 动作库 ---

# 近战 (Melee)
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
ACTION_DUNJI = Action(name="盾击", action_type="近战", cost="S", dice="5黄", range_val=1)

# 射击 (Ranged)
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

# [新增] 快速动作 (Quick)
ACTION_JETTISON = Action(name="【弃置】", action_type="快速", cost="S", dice="", range_val=0,
                         effects=build_effects(EFFECT_JETTISON))

# 移动 (Movement)
ACTION_BENPAO = Action(name="奔跑", action_type="移动", cost="M", dice="", range_val=4)
ACTION_TIAOYUE = Action(name="跳跃", action_type="移动", cost="S", dice="", range_val=2,
                        effects=build_effects(EFFECT_FLIGHT_MOVEMENT))
ACTION_BENPAO_MA = Action(name="奔跑（马）", action_type="移动", cost="M", dice="", range_val=5)


# 被动 (Passive)
ACTION_NONE = Action(name="无动作", action_type="被动", cost="", dice="", range_val=0)
ACTION_ENHANCED_COOLING = Action(name="增强冷却", action_type="被动", cost="", dice="", range_val=0,
                                 effects=build_effects(EFFECT_PASSIVE_COOLING))

# [新增] 拦截动作
ACTION_AUTO_INTERCEPT = Action(
    name="自动拦截",
    action_type="被动",
    cost="",
    dice="3黄", # 拦截时投掷 3 个黄骰
    range_val=3, # 拦截触发范围
    ammo=3,      # 每回合 3 次 (拦截3)
    effects=build_effects(EFFECT_INTERCEPTOR_3)
)


# --- [v1.17 新增] 抛射物动作 ---
ACTION_LAUNCH_ROCKET = Action(
    name="火箭弹",
    action_type="抛射", # [v1.17] 新类型
    cost="M",
    dice="", # 发射动作本身不造成伤害
    range_val=12,
    action_style='direct', # 直射
    projectile_to_spawn='RA_81_ROCKET', # 要生成的实体
    ammo=2 # 弹药量
)

# [新增] 延迟-制导导弹（发射动作）
ACTION_LAUNCH_GUIDED_MISSILE = Action(
    name="导弹",
    action_type="抛射",
    cost="M",
    dice="", # 发射动作本身不造成伤害
    range_val=3, # 发射器射程 (玩家选择落点的范围)
    action_style='curved', # 曲射
    projectile_to_spawn='MC_3_SWORD_MISSILE', # 要生成的实体
    ammo=2, # 弹药量
    effects=build_effects(EFFECT_SALVO_2, EFFECT_CURVED_FIRE) # 齐射2, 曲射
)

# --- [v1.17 新增] 抛射物“立即”动作 ---
ACTION_IMMEDIATE_EXPLOSION = Action(
    name="多级串联战斗部",
    action_type="立即", # [v1.17] 新类型: '立即'
    cost="", # 立即动作无消耗
    dice="3红", # 伤害
    range_val=0, # 总是 0, 攻击自己所在的格子
    aoe_range=0 # 仅限本格
)

# [新增] 抛射物“延迟”动作
ACTION_DELAYED_GUIDED_ATTACK = Action(
    name="制导攻击",
    action_type="延迟", # [新增] 新类型: '延迟'
    cost="",
    dice="1黄3红", # 爆炸伤害
    range_val=0, # 攻击自己所在的格子
    aoe_range=0 # 仅限本格
)


# --- [v1.17 新增] 抛射物模板库 ---
PROJECTILE_TEMPLATES = {
    "RA_81_ROCKET": {
        "name": "RA-81火箭弹",
        "entity_type": "projectile",
        "evasion": 4,
        "stance": "agile", # 处于机动姿态
        "structure": 1, # 1 点生命值 (用于被拦截)
        "armor": 0,
        "life_span": 1, # '立即' 动作会在 1 回合内结算
        "actions": [ACTION_IMMEDIATE_EXPLOSION.to_dict()], # 携带的动作
        "electronics": 0,
        "move_range": 0 # 不会移动
    },
    # [新增] MC-3 利剑导弹
    "MC_3_SWORD_MISSILE": {
        "name": "MC-3 “利剑”导弹",
        "entity_type": "projectile",
        "evasion": 6,
        "electronics": 1,
        "stance": "agile",
        "structure": 1, # 1 点生命值
        "armor": 0,
        "life_span": 99, # 存活直到 '延迟' 动作被触发
        "actions": [ACTION_DELAYED_GUIDED_ATTACK.to_dict()],
        "move_range": 3 # 关键：导弹自己的移动力 (来自图片R3)
    }
}


# --- [新增] 通用动作 (Generic Actions) ---
# [v_MODIFIED] 动作定义移回 parts_database.py
ACTION_PUNCH_KICK = Action(
    name="拳打脚踢",
    action_type="近战",
    cost="M",
    dice="2红",
    range_val=1
)

# 定义通用动作及其解锁所需的部件槽位
# 格式: {ActionObject: ['required_slot_1', 'required_slot_2', ...]}
# 机甲 *至少需要一个* 列表中的部件 (且未被摧毁) 才能使用该动作。
GENERIC_ACTIONS = {
    ACTION_PUNCH_KICK: ['left_arm', 'right_arm', 'legs']
}
# --- 通用动作结束 ---


# --- [MODIFIED v2.2] 驾驶员数据库 ---
# 定义【测试驾驶员】，使用 Pilot 类的默认值 (全 5 速度, 5 链接值)
PILOT_TEST = Pilot(name="【测试驾驶员】")

# 玩家可用的驾驶员 (目前为空，但为了让 game_logic.py 中的导入能工作)
PLAYER_PILOTS = {
    "【测试驾驶员】": PILOT_TEST # [MODIFIED v2.2] 添加测试驾驶员供玩家选择
}

# [MODIFIED v2.2 AI无驾驶员] AI不再需要驾驶员
AI_PILOTS = {}
# --- 驾驶员数据库结束 ---


# --- 玩家可用部件 ---
PLAYER_CORES = {
    'RT-06 "泥沼"核心': Part(name='RT-06 "泥沼"核心', armor=6, structure=2, electronics=2,
                            image_url='static/images/parts/RT-06.png'),
}
PLAYER_LEGS = {
    'RL-06 标准下肢': Part(name='RL-06 标准下肢', armor=5, structure=0, evasion=3, adjust_move=1,
                           actions=[ACTION_BENPAO],
                           image_url='static/images/parts/RL-06.png'),
    'RL-03D “快马”高速下肢': Part(name='RL-03D “快马”高速下肢', armor=4, structure=0, evasion=4, adjust_move=2,
                                  actions=[ACTION_BENPAO_MA],
                           image_url='static/images/parts/RL-03D.png'),
    'RL-08 重甲下肢': Part(name='RL-08 重甲下肢', armor=6, structure=1, evasion=3, adjust_move=1,
                            actions=[ACTION_BENPAO],
                           image_url='static/images/parts/RL-08.png'),
}
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
}

# --- AI 专用部件 ---
AI_ONLY_CORES = {
    'GK-09 "壁垒"核心': Part(name='GK-09 "壁垒"核心', armor=8, structure=3, electronics=1),
    'GK-08 "哨兵"核心': Part(name='GK-08 "哨兵"核心', armor=5, structure=1, electronics=1, evasion=3),
}
AI_ONLY_LEGS = {
    'TK-05 坦克履带': Part(name='TK-05 坦克履带', armor=6, structure=3, evasion=0, adjust_move=1,
                           actions=[ACTION_BENPAO]),
}
AI_ONLY_LEFT_ARMS = {
    'LH-8 早期型霰弹破片炮': Part(name='LH-8 早期型霰弹破片炮', armor=5, structure=0, parry=0, actions=[ACTION_JINGJU]),
}
AI_ONLY_RIGHT_ARMS = {
    'LGP-80 长程火炮': Part(name='LGP-80 长程火炮', armor=3, structure=0, actions=[ACTION_PAOJI]),
}
AI_ONLY_BACKPACKS = {
    'EB-03 扩容电池': Part(name='EB-03 扩容电池', armor=2, structure=0, electronics=3),
}


# --- [v1.22 修复] AI 配置 ---
# AI_LOADOUTS 字典现在被定义在这里

# [MODIFIED v2.2 AI无驾驶员] 移除所有 'pilot' 键
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

AI_LOADOUTS = {
    "heavy": AI_LOADOUT_HEAVY,
    "standard": AI_LOADOUT_STANDARD,
    "lighta": AI_LOADOUT_LIGHTA,
    "lightb": AI_LOADOUT_LIGHTB,
}
# --- AI 配置结束 ---


# --- 合并字典 ---
CORES = {**PLAYER_CORES, **AI_ONLY_CORES}
LEGS = {**PLAYER_LEGS, **AI_ONLY_LEGS}
LEFT_ARMS = {**PLAYER_LEFT_ARMS, **AI_ONLY_LEFT_ARMS}
RIGHT_ARMS = {**PLAYER_RIGHT_ARMS, **AI_ONLY_RIGHT_ARMS}
BACKPACKS = {**PLAYER_BACKPACKS, **AI_ONLY_BACKPACKS}

ALL_PARTS = {**CORES, **LEGS, **LEFT_ARMS, **RIGHT_ARMS, **BACKPACKS}