"""
【数据库 - 无人机模板】

定义所有无人机实体 (DRONE_TEMPLATES)。

依赖于:
- ._actions (导入无人机动作)
"""
from ._actions import (
    ACTION_DRONE_MOVE,
    ACTION_DRONE_SWEEP,
    ACTION_DRONE_SWEEP_INTERCEPT,
)

DRONE_TEMPLATES = {
    "DTG_30M_HYENA": {
        "name": "DTG-30M 鬣狗 机枪型",
        "armor": 5,
        "structure": 2,
        "electronics": 2,
        "move_range": 5,
        "evasion": 0,
        "stance": "defense",
        "actions": [
            ACTION_DRONE_SWEEP_INTERCEPT.to_dict(),
            ACTION_DRONE_SWEEP.to_dict(),
            ACTION_DRONE_MOVE.to_dict(),
        ]
    }
}
