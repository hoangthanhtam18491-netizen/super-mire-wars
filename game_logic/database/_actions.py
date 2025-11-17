"""
【数据库 - 动作库】

定义所有游戏中可用的动作 (ACTION_...)。
这包括近战、射击、移动、抛射和被动动作。

依赖于:
- game_logic.data_models (导入 Action 类)
- ._effects (导入 build_effects 和所有 EFFECT_... 常量)
"""

# 导入数据模型
# '..' 代表上一级目录 (game_logic)
from ..data_models import Action

# 导入效果
# '.' 代表同一目录 (database)
from ._effects import *

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

# 喷射冲刺动作
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