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

PLAYER_PILOTS = {
    "【测试驾驶员】": PILOT_TEST
}

AI_PILOTS = {
    "Raven": PILOT_RAVEN
}