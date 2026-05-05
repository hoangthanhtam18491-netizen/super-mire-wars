# CLAUDE.md — 超级泥沼大战 (Super Mire Wars)

## 项目本质

回合制机甲战棋游戏。Flask 后端 + 服务器端 Session + Jinja2 模板 + 原生 JS 前端。
玩家在机库组装机甲 → 10×10 棋盘对决 AI → 回合制战术战斗。

## 核心架构

```
routes/          → Flask 蓝图，接收 HTTP 请求，委托给 controller
game_controller  → 业务调度中心 + 共享辅助函数，具体实现在子模块中
  ├── player_actions   → 玩家回合阶段 1-4 处理器
  ├── ai_actions       → AI 回合编排 + 中断解决 + _resolve_queued_attack
  └── projectile_actions → 抛射物延迟阶段
game_logic/      → GameState 类（状态容器）+ 纯函数（射程/寻路/朝向计算）
combat_system    → CombatState 状态机，封装单次攻击的全生命周期
dice_roller      → 4色骰子系统 + 黑骰 + 重投
data_models      → Action / Part / Pilot / GameEntity / Mech / Projectile / Drone
config           → 共享常量 (MAX_LOG_ENTRIES, BOARD_WIDTH/HEIGHT) + Firebase 配置加载
ai_system        → 普通 AI 回合逻辑（Brawler/Sniper 人格）
ace_logic        → Ace AI 抢先手判定 + 重投决策
ace_ai_system    → Ace AI 战术规划器 + 执行器
database/        → 静态数据：部件、动作、效果、AI配置、抛射物模板
```

## 前端 JS 架构

```
static/js/
├── game.js         → 状态管理、API调用、事件绑定、初始化 (IIFE, S.xxx 命名空间)
├── game-board.js   → 棋盘渲染、动画、部件UI (IIFE, 读写 window.SMW)
└── game-combat.js  → 骰子弹窗、效果选择、重投、拼点UI (IIFE, 读写 window.SMW)
```

所有共享状态通过 `window.SMW` 命名空间暴露，各文件以 IIFE 包裹，不再污染全局作用域。

## 请求生命周期（核心理解）

```
session 加载 → from_dict() 反序列化 → controller 修改 GameState
→ to_dict() 序列化 → 保存回 session → 返回 JSON 或 redirect 刷新页面
```

每次 HTTP 请求都是一次完整的 **反序列化→处理→序列化** 循环。
状态通过 Flask 文件系统 Session 保持。

## 游戏回合循环

```
玩家回合 (4阶段: 时机→姿态→调整→主动作)
  → POST /end_turn
  → AI 机甲阶段
  → 抛射物延迟阶段 (AJAX /run_projectile_phase)
  → 重置玩家 AP/TP，新回合
```

## 最重要的文件（按修改频率排序）

| 文件 | 行数 | 角色 |
|------|------|------|
| `game_logic/game_controller.py` | ~180 | **门面**：共享辅助函数 + 重新导出所有公共接口 |
| `game_logic/player_actions.py` | ~350 | 玩家回合阶段1-4的所有处理器 |
| `game_logic/ai_actions.py` | ~290 | AI回合编排 + 中断解决 + 攻击队列结算 |
| `game_logic/projectile_actions.py` | ~100 | 抛射物延迟阶段 |
| `game_logic/combat_system.py` | 1077 | CombatState 状态机 |
| `static/js/game.js` | ~500 | 前端主入口：状态、API、事件 (IIFE) |
| `game_logic/ai_system.py` | 992 | 普通AI决策 |
| `game_logic/game_logic.py` | 842 | GameState类 + 工具函数 |
| `game_logic/data_models.py` | 636 | 所有数据类定义 |
| `routes/api_routes.py` | ~280 | 玩家动作 AJAX 端点 |
| `game_logic/config.py` | ~55 | 共享常量 + Firebase 配置 |

## 关键约定

- **不要相信 session 一定有效** — 每次从 session 加载都要用 `session.get()` 而非直接访问
- **`_handle_controller_response`** 是 session 持久化的唯一途径（`api_routes.py`）
- **中断优先** — 在 controller 中修改 game_state 前，必须先检查 `player_mech.pending_combat`
  - 在 API 路由中统一用 `_check_no_combat(player_mech)` 辅助函数，而非重复写检查
- **前端通过 `visual_feedback_events`** 获知骰子结果和中断弹窗
- **抛射物队列** (`pending_projectile_queue`) 支持中断后断点续传
- **所有 API 路由必须用 `@handle_errors` 装饰器** — 捕获未处理异常，返回 JSON 错误而非 500 页面
- **CombatState 不直接依赖 ace_logic** — 通过 `ace_reroll_callback` 回调注入，由 game_controller 在构造时传入
- **共享常量从 `game_logic.config` 导入** — `MAX_LOG_ENTRIES`、`load_firebase_config()` 等不要在各路由文件中重复定义

## 已知陷阱

1. ~~**`data_models.py` 有两份完全重复的！**~~ — 已删除 `database/data_models.py`，只保留 `game_logic/data_models.py`。
2. **`game_logic.py` 职责混淆** — 既是 `GameState` 类，又包含 `is_back_attack`、`run_projectile_logic` 等纯函数。新增纯函数考虑放 `game_controller.py` 或新文件。
3. **CombatState 跨请求恢复** — 状态机被序列化到 `Mech.pending_combat`，跨 HTTP 请求恢复。添加新状态时必须同时更新 `to_dict()` 和 `from_dict()`。
   - `ace_reroll_callback` 不会被序列化 — `from_dict()` 恢复后必须由调用者重新注入。
4. **AJAX vs 整页刷新** — `/api/*` 返回 JSON，`/game`、`/end_turn` 返回 redirect 或 HTML。不要混用。
5. **ammo_counts 的 key** — 格式是 `(entity_id, part_slot, action_name)` 三元组，不是简单的字符串。
6. **controller 返回值签名** — 统一为 `(game_state, log, result_data, error)`，`result_data` 用于中断通知前端。
7. **新增 CombatState 使用点** — 创建 `CombatState(...)` 时必须传入 `ace_reroll_callback=ace_logic.decide_reroll`，否则 Ace AI 的重投逻辑不会触发。

## 修改代码后

- 如果新增/删除/重命名文件、改变模块职责、引入新的中断类型，**请同时更新本文件**。
- 如果改变架构约定或发现新的陷阱，**请同时更新 `ARCHITECTURE.md`**。
