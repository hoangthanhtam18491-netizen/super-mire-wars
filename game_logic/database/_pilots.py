"""
【数据库 - 驾驶员】

定义所有玩家和AI的驾驶员。

依赖于:
- ..data_models (导入 Pilot 类)
"""

# 导入数据模型
from ..data_models import Pilot

# === 驾驶员数据库 (Pilot Database) ===

PILOT_TEST = Pilot(name="【测试驾驶员】") # 默认测试驾驶员

PILOT_RAVEN = Pilot(
    name="【Raven】",
    link_points=5,
    speed_stats={
        '快速': 3, '近战': 2, '抛射': 7,
        '射击': 4, '移动': 6, '战术': 6
    },
    skills=["pursuit"]  # pursuit = 乘胜追击
)

PILOT_HAMMERHEAD_04 = Pilot(
    name="【锤头鲨-04-内务能手】",
    link_points=4,
    speed_stats={
        '快速': 4, '近战': 3, '抛射': 2,
        '射击': 5, '移动': 2, '战术': 6
    },
    skills=["debug"],
    image_url="static/images/pilots/04-2.png"
)

PLAYER_PILOTS = {
    "【测试驾驶员】": PILOT_TEST,
    "【锤头鲨-04-内务能手】": PILOT_HAMMERHEAD_04
}

PILOT_CHALCEDONY = Pilot(
    name="【玉髓-温柔和弦】",
    link_points=5,
    speed_stats={
        '快速': 6, '近战': 2, '抛射': 3,
        '射击': 5, '移动': 4, '战术': 4
    },
    skills=["grace_note"],
    image_url="images/badge/Onyx Mellow Chord.png"
)

AI_PILOTS = {
    "Raven": PILOT_RAVEN,
    "Chalcedony": PILOT_CHALCEDONY
}