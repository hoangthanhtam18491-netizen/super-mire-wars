"""
【数据库 - 包管家 (__init__.py)】

这个文件是 database 包的入口点。
它执行以下操作：
1. 从包内所有 `_*.py` 兄弟文件中导入所有数据常量。
2. 将玩家部件和AI部件重新组装成合并的字典 (CORES, LEGS, ALL_PARTS 等)。
3. 定义 `__all__` 列表，以指定哪些常量可以被外部代码
   (例如 game_logic.py) 通过 `from game_logic.database import ...` 来导入。

这是此重构方案的核心。
"""

# 1. 从包内的兄弟文件中导入所有数据
#    (效果、动作、抛射物、驾驶员、AI配置等)
from ._effects import *
from ._actions import *
from ._generic_actions import *
from ._projectiles import *
from ._pilots import *
from ._parts_player import *
from ._parts_ai import *
from ._ai_loadouts import *

# 2. 重新组装最终的合并字典
#    (这部分逻辑之前在 parts_database.py 的末尾)
CORES = {**PLAYER_CORES, **AI_ONLY_CORES}
LEGS = {**PLAYER_LEGS, **AI_ONLY_LEGS}
LEFT_ARMS = {**PLAYER_LEFT_ARMS, **AI_ONLY_LEFT_ARMS}
RIGHT_ARMS = {**PLAYER_RIGHT_ARMS, **AI_ONLY_RIGHT_ARMS}
BACKPACKS = {**PLAYER_BACKPACKS, **AI_ONLY_BACKPACKS}

ALL_PARTS = {**CORES, **LEGS, **LEFT_ARMS, **RIGHT_ARMS, **BACKPACKS}

# 3. 定义此包的 "公共 API"
#    只有在这里列出的变量才能被 `import *` 导入
__all__ = [
    # 合并后的部件字典
    "ALL_PARTS",
    "CORES",
    "LEGS",
    "LEFT_ARMS",
    "RIGHT_ARMS",
    "BACKPACKS",

    # 原始玩家部件 (用于机库)
    "PLAYER_CORES",
    "PLAYER_LEGS",
    "PLAYER_LEFT_ARMS",
    "PLAYER_RIGHT_ARMS",
    "PLAYER_BACKPACKS",

    # 原始AI部件 (几乎不用)
    "AI_ONLY_CORES",
    "AI_ONLY_LEGS",
    "AI_ONLY_LEFT_ARMS",
    "AI_ONLY_RIGHT_ARMS",
    "AI_ONLY_BACKPACKS",

    # 其他数据库
    "PROJECTILE_TEMPLATES",
    "AI_LOADOUTS",
    "PLAYER_PILOTS",
    "AI_PILOTS",
    "GENERIC_ACTIONS"
]