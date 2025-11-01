from data_models import Action, Part


# --- [新增] 效果构建辅助函数 ---
# ... (此函数无变化) ...
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



# --- [修改] 效果库 (Effect Library) ---
# ... (EFFECT_AP_1, EFFECT_STROBE_WEAPON, EFFECT_PASSIVE_COOLING, EFFECT_STATIC, EFFECT_STATIC_RANGE_2, EFFECT_STATIC_PLUS_YELLOW_DICE, EFFECT_TWO_HANDED_RANGE_2, EFFECT_TWO_HANDED_SNIPER, EFFECT_DEVASTATING, EFFECT_SCATTERSHOT, EFFECT_CLEAVE, EFFECT_FLIGHT_MOVEMENT 均无变化) ...
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
# [新增] 【双手】获得毁伤
EFFECT_TWO_HANDED_DEVASTATING = {
    "logic": {"two_handed_devastating": True},
    "name": "【【双手】获得毁伤】"
}
EFFECT_FLIGHT_MOVEMENT = {
    "logic": {"flight_movement": True},
    "name": "【空中移动】"
}
# --- 效果库结束 ---


# --- 动作库 ---

# 近战 (Melee)
ACTION_CIJI = Action(name="刺击", action_type="近战", cost="S", dice="3黄1红", range_val=1)
ACTION_JINGJU = Action(name='近距开火', action_type='近战', cost='S', dice='5黄', range_val=1)
ACTION_HUIZHAN = Action(name='挥斩', action_type='近战', cost='S', dice='4黄1红', range_val=1,
                        effects=build_effects(EFFECT_STROBE_WEAPON)
                        )
# [修改] 为 ACTION_HUIZHAN_ZHONG 添加【【双手】获得毁伤】
ACTION_HUIZHAN_ZHONG = Action(name='挥斩【重】', action_type='近战', cost='M', dice='2黄4红', range_val=1,
                        effects=build_effects(EFFECT_STROBE_WEAPON, EFFECT_CLEAVE, EFFECT_TWO_HANDED_DEVASTATING))
ACTION_DUNJI = Action(name="盾击", action_type="近战", cost="S", dice="5黄", range_val=1)

# 射击 (Ranged)
# ... (ACTION_DIANSHE, ACTION_DIANSHE_CI, ACTION_DIANSHE_XIAN, ACTION_JUJI, ACTION_PAOJI, ACTION_DIANSHE_HUOPAO, ACTION_SAOSHE, ACTION_SUSHE_BIPAO, ACTION_SUSHE, ACTION_DIANSHE_ZHAN 均无变化) ...
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


# 移动 (Movement)
# ... (ACTION_BENPAO, ACTION_TIAOYUE, ACTION_BENPAO_MA 均无变化) ...
ACTION_BENPAO = Action(name="奔跑", action_type="移动", cost="M", dice="", range_val=4)
ACTION_TIAOYUE = Action(name="跳跃", action_type="移动", cost="S", dice="", range_val=2,
                        effects=build_effects(EFFECT_FLIGHT_MOVEMENT))
ACTION_BENPAO_MA = Action(name="奔跑（马）", action_type="移动", cost="M", dice="", range_val=5)


# 被动 (Passive)
# ... (ACTION_NONE, ACTION_ENHANCED_COOLING 均无变化) ...
ACTION_NONE = Action(name="无动作", action_type="被动", cost="", dice="", range_val=0)
ACTION_ENHANCED_COOLING = Action(name="增强冷却", action_type="被动", cost="", dice="", range_val=0,
                                 effects=build_effects(EFFECT_PASSIVE_COOLING))


# --- [新] 玩家可用部件 ---
# [修改] 为有图片的部件添加 image_url (使用占位符)
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
    'CC-3 格斗刀': Part(name='CC-3 格斗刀', armor=4, structure=0, parry=1, actions=[ACTION_CIJI],
                       tags=["【空手】"],
                           image_url='static/images/parts/CC-3.png'),
    'R-20 肩置磁轨炮（左）': Part(name='R-20 肩置磁轨炮（左）', armor=4, structure=0, parry=0, actions=[ACTION_DIANSHE_CI],
                       tags=["【空手】"],
                           image_url='static/images/parts/R-20L.png'),
    '62型 臂盾 + CC-20 单手剑（左）': Part(name='62型 臂盾 + CC-20 单手剑（左）', armor=5, structure=0,
                       parry=3, actions=[ACTION_HUIZHAN],tags=["【空手】"],
                           image_url='static/images/parts/CC-20L.png'),
    '55型 轻盾': Part(name='55型 轻盾', armor=5, structure=0, parry=2, actions=[ACTION_DUNJI],
                       tags=["【空手】"],
                           image_url='static/images/parts/55.png'),
    '55 型轻盾 + PC-9 霰弹枪（左）': Part(name='55 型轻盾 + PC-9 霰弹枪（左）', armor=5, structure=0, parry=2, actions=[ACTION_DIANSHE_XIAN],
                       tags=["【手持】"],
                           image_url='static/images/parts/PC-9L.png'),
}
PLAYER_RIGHT_ARMS = {
    'AC-32 自动步枪': Part(name='AC-32 自动步枪', armor=4, structure=0, actions=[ACTION_DIANSHE],
                         tags=["【手持】"],
                           image_url='static/images/parts/AC-32.png'),
    'AC-35 狙击步枪': Part(name='AC-35 狙击步枪', armor=4, structure=0, actions=[ACTION_JUJI], tags=["【手持】"],
                           image_url='static/images/parts/AC-35.png'),
    'R-20 肩置磁轨炮（右）': Part(name='R-20 肩置磁轨炮（右）', armor=4, structure=0, parry=0, actions=[ACTION_DIANSHE_CI],
                         tags=["【空手】"],
                           image_url='static/images/parts/R-20R.png'),
    'AC-39 战术步枪': Part(name='AC-39 战术步枪', armor=4, structure=0, actions=[ACTION_SUSHE, ACTION_DIANSHE_ZHAN],
                         tags=["【手持】"],
                           image_url='static/images/parts/AC-39.png'),
    '63型 臂炮 + CC-20 单手剑（右）': Part(name='63型 臂炮 + CC-20 单手剑（右）', armor=4, structure=0, parry=2,
                         actions=[ACTION_HUIZHAN, ACTION_SUSHE_BIPAO],tags=["【空手】"],
                           image_url='static/images/parts/CC-20R.png'),
    '55 型轻盾 + PC-9 霰弹枪（右）': Part(name='55 型轻盾 + PC-9 霰弹枪（右）', armor=5, structure=0, parry=2, actions=[ACTION_DIANSHE_XIAN],
                       tags=["【手持】"],
                           image_url='static/images/parts/PC-9R.png'),
    'L-320 肩部机枪 + CC-90 重格斗刀': Part(name='L-320 肩部机枪 + CC-90 重格斗刀', armor=4, structure=0, parry=2,
                         actions=[ACTION_HUIZHAN_ZHONG, ACTION_SAOSHE],tags=["【手持】"],
                           image_url='static/images/parts/CC-90.png'),
}
PLAYER_BACKPACKS = {
    'AMS-190 主动防御': Part(name='AMS-190 主动防御', armor=3, structure=0, electronics=1,
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

# --- [新] AI 专用部件 ---
# ... (AI_ONLY_CORES, AI_ONLY_LEGS, AI_ONLY_LEFT_ARMS, AI_ONLY_RIGHT_ARMS, AI_ONLY_BACKPACKS 均无变化) ...
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


# --- [新] 合并字典 ---
CORES = {**PLAYER_CORES, **AI_ONLY_CORES}
LEGS = {**PLAYER_LEGS, **AI_ONLY_LEGS}
LEFT_ARMS = {**PLAYER_LEFT_ARMS, **AI_ONLY_LEFT_ARMS}
RIGHT_ARMS = {**PLAYER_RIGHT_ARMS, **AI_ONLY_RIGHT_ARMS}
BACKPACKS = {**PLAYER_BACKPACKS, **AI_ONLY_BACKPACKS}

ALL_PARTS = {**CORES, **LEGS, **LEFT_ARMS, **RIGHT_ARMS, **BACKPACKS}

