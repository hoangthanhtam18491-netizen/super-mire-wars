from data_models import Action, Part

# --- 动作库 ---

# 近战 (Melee)
ACTION_CIJI = Action(name="刺击", action_type="近战", cost="S", dice="3黄1红", range_val=1)
ACTION_JINGJU = Action(name='近距开火', action_type='近战', cost='S', dice='5黄', range_val=1)
ACTION_HUIZHAN = Action(name='挥斩', action_type='近战', cost='S', dice='4黄1红', range_val=1)
ACTION_DUNJI = Action(name="盾击", action_type="近战", cost="S", dice="5黄", range_val=1)

# 射击 (Ranged)
ACTION_DIANSHE = Action(name="点射", action_type="射击", cost="M", dice="1黄3红", range_val=6)
ACTION_DIANSHE_CI = Action(name="点射【磁】", action_type="射击", cost="S", dice="3红", range_val=6, effects={"armor_piercing": 1, "static_range_bonus": 2})
ACTION_JUJI = Action(name="狙击", action_type="射击", cost="M", dice="2黄2红", range_val=12)
ACTION_PAOJI = Action(name="炮击", action_type="射击", cost="L", dice="1黄4红", range_val=12)
ACTION_SUSHE_BIPAO = Action(name="速射", action_type="射击", cost="S", dice="4黄", range_val=6)
ACTION_SUSHE = Action(name="速射", action_type="射击", cost="M", dice="4黄1红", range_val=6)
ACTION_DIANSHE_ZHAN = Action(name="点射(战)", action_type="射击", cost="S", dice="1黄2红", range_val=6)

# 移动 (Movement)
ACTION_BENPAO = Action(name="奔跑", action_type="移动", cost="M", dice="", range_val=4)
ACTION_TIAOYUE = Action(name="跳跃", action_type="移动", cost="S", dice="", range_val=2)
ACTION_BENPAO_MA = Action(name="奔跑（马）", action_type="移动", cost="M", dice="", range_val=5)

# 被动 (Passive)
ACTION_NONE = Action(name="无动作", action_type="被动", cost="", dice="", range_val=0)


# --- [新] 玩家可用部件 ---

PLAYER_CORES = {
    'RT-06 "泥沼"核心': Part(name='RT-06 "泥沼"核心', armor=6, structure=2, electronics=2),
    #'FT-12 "幽灵"核心': Part(name='FT-12 "幽灵"核心', armor=4, structure=1, electronics=1, evasion=2),
}

PLAYER_LEGS = {
    'RL-06 标准下肢': Part(name='RL-06 标准下肢', armor=5, structure=0, evasion=3, adjust_move=1, actions=[ACTION_BENPAO]),
    'RL-03D “快马”高速下肢': Part(name='RL-03D “快马”高速下肢', armor=4, structure=0, evasion=4, adjust_move=2, actions=[ACTION_BENPAO_MA]),
    'RL-08C 重甲下肢': Part(name='RL-08C 重甲下肢', armor=5, structure=1, evasion=3, adjust_move=1, actions=[ACTION_BENPAO]),
}

PLAYER_LEFT_ARMS = {
    'CC-3 格斗刀': Part(name='CC-3 格斗刀', armor=4, structure=0, parry=1, actions=[ACTION_CIJI]),
    'R-20 肩置磁轨炮（左）': Part(name='R-20 肩置磁轨炮（左）', armor=4, structure=0, parry=0, actions=[ACTION_DIANSHE_CI]),
    '62型 臂盾 + 未完成的CC-20 单手剑（左）': Part(name='62型 臂盾 + 未完成的CC-20 单手剑（左）', armor=5, structure=0, parry=3, actions=[ACTION_HUIZHAN]),
    '55型 轻盾': Part(name='55型 轻盾', armor=5, structure=0, parry=2, actions=[ACTION_DUNJI]),
}

PLAYER_RIGHT_ARMS = {
    'AC-32 自动步枪': Part(name='AC-32 自动步枪', armor=4, structure=0, actions=[ACTION_DIANSHE]),
    '猴版AC-35 狙击步枪': Part(name='猴版AC-35 狙击步枪', armor=4, structure=0, actions=[ACTION_JUJI]),
    'R-20 肩置磁轨炮（右）': Part(name='R-20 肩置磁轨炮（右）', armor=4, structure=0, parry=0, actions=[ACTION_DIANSHE_CI]),
    'AC-39 战术步枪': Part(name='AC-39 战术步枪', armor=4, structure=0, actions=[ACTION_SUSHE, ACTION_DIANSHE_ZHAN]),
    '63型 臂炮 + 未完成CC-20 单手剑（右）': Part(name='63型 臂炮 + 未完成CC-20 单手剑（右）', armor=4, structure=0, parry=2, actions=[ACTION_HUIZHAN, ACTION_SUSHE_BIPAO]),
}

PLAYER_BACKPACKS = {
    'AMS-190 主动防御': Part(name='AMS-190 主动防御', armor=3, structure=0, electronics=1),
    '未完成的TB-600 跳跃背包': Part(name='未完成的TB-600 跳跃背包', armor=3, structure=0, evasion=2,actions=[ACTION_TIAOYUE]),
}

# --- [新] AI 专用部件 ---

AI_ONLY_CORES = {
    'GK-09 "壁垒"核心': Part(name='GK-09 "壁垒"核心', armor=8, structure=3, electronics=1),
    'GK-08 "哨兵"核心': Part(name='GK-08 "哨兵"核心', armor=5, structure=1, electronics=1, evasion=3),
}

AI_ONLY_LEGS = {
    'TK-05 坦克履带': Part(name='TK-05 坦克履带', armor=7, structure=2, evasion=0, adjust_move=1, actions=[ACTION_BENPAO]),
}

AI_ONLY_LEFT_ARMS = {
    'LH-8 早期型霰弹破片炮': Part(name='LH-8 早期型霰弹破片炮', armor=5, structure=0, parry=0, actions=[ACTION_JINGJU]),
}

AI_ONLY_RIGHT_ARMS = {
    'LGP-70 长程火炮': Part(name='LGP-70 长程火炮', armor=3, structure=0, actions=[ACTION_PAOJI]),
}

AI_ONLY_BACKPACKS = {
    'EB-03 扩容电池': Part(name='EB-03 扩容电池', armor=2, structure=0, electronics=3),
}


# --- [新] 合并字典 ---
# (供后端逻辑使用，例如 AI 创建机甲或验证部件时)

CORES = {**PLAYER_CORES, **AI_ONLY_CORES}
LEGS = {**PLAYER_LEGS, **AI_ONLY_LEGS}
LEFT_ARMS = {**PLAYER_LEFT_ARMS, **AI_ONLY_LEFT_ARMS}
RIGHT_ARMS = {**PLAYER_RIGHT_ARMS, **AI_ONLY_RIGHT_ARMS}
BACKPACKS = {**PLAYER_BACKPACKS, **AI_ONLY_BACKPACKS}

# --- 整合到一个字典中，方便按名称查找 ---
# [修正] 确保 ALL_PARTS 包含所有部件
ALL_PARTS = {**CORES, **LEGS, **LEFT_ARMS, **RIGHT_ARMS, **BACKPACKS}


