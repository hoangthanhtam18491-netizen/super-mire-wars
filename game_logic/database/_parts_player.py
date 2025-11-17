"""
【数据库 - 玩家部件】

定义所有玩家可用的部件 (PLAYER_...)。

依赖于:
- ..data_models (导入 Part 类)
- ._actions (导入所有 ACTION_... 常量)
"""

# 导入数据模型
from ..data_models import Part

# 导入所有动作
# '.' 代表同一目录 (database)
from ._actions import *

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
    'RL-08 重甲下肢': Part(name='RL-08 重甲下肢', armor=6, structure=1, evasion=3, adjust_move=1,
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
    'AC-35 狙击步枪（弃置）': Part(name='AC-35 狙击步枪（弃置）', armor=4, structure=0, tags=["【空手】"],
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