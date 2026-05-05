# ARCHITECTURE.md — 超级泥沼大战 架构参考

> 本文档供开发者（人类和 AI）深入了解项目结构。日常开发请先阅读 `CLAUDE.md`。

---

## 一、全文件索引

### 项目入口

| 文件 | 行数 | 说明 |
|------|------|------|
| `app.py` | 32 | Flask 工厂。创建 app、配置 Session、注册 3 个蓝图 |
| `Procfile` | 1 | Heroku 部署：`gunicorn app:app` |
| `requirements.txt` | 8 | 依赖清单 |
| `update_deps.py` | 48 | 辅助脚本，在 venv 中安装/更新依赖 |

### 路由层 (`routes/`)

| 文件 | 行数 | 蓝图 | 端点 |
|------|------|------|------|
| `routes/main_routes.py` | 214 | `main` | `/`, `/analytics`, `/hangar`, `/start_game` |
| `routes/game_routes.py` | 287 | `game` | `/game`, `/end_turn`, `/reset_game`, `/run_projectile_phase`, `/respawn_ai` |
| `routes/api_routes.py` | 377 | `api` (`/api/*`) | 所有 AJAX：时机/姿态/调整/移动/攻击/弃置/重投/效果选择/范围获取 |

**关键设计**：
- `main_routes` 和 `game_routes` 返回 HTML（整页刷新），`api_routes` 返回 JSON
- `_handle_controller_response()` (`api_routes.py:40`) 是 session 持久化的唯一入口
- `_get_game_state_and_player()` (`api_routes.py:17`) 是每个 API 的第一步安全检查

### 控制器层

| 文件 | 行数 | 说明 |
|------|------|------|
| `game_logic/game_controller.py` | 1385 | **项目中最长的文件**。所有业务逻辑的调度入口 |

**函数清单**（按调用方分组）：

```
玩家回合:
  handle_select_timing()     → handle_confirm_timing()       # 阶段1: 时机（含 Ace 抢先手）
  handle_change_stance()     → handle_confirm_stance()       # 阶段2: 姿态
  handle_adjust_move()       → handle_change_orientation()    # 阶段3: 调整
  handle_skip_adjustment()
  handle_move_player()       → handle_execute_attack()       # 阶段4: 主动作
  handle_jettison_part()

中断处理:
  handle_resolve_effect_choice()                              # 玩家选择毁伤/霰射/顺劈
  handle_resolve_reroll()                                     # 玩家专注重投

系统阶段:
  handle_end_turn()                                           # AI回合 + 抛射物阶段入口
  handle_run_projectile_phase()                               # 抛射物延迟动作
  handle_respawn_ai()                                         # 靶场模式AI重生

内部辅助:
  _execute_main_action()      # 验证并消耗AP/TP/弹药
  _apply_combat_packet()      # 将 CombatState 结果包应用到 GameState
  _resolve_queued_attack()    # 结算单次队列攻击（共享逻辑）
  _run_interception_checks()  # 拦截系统
  _clear_transient_state()    # 清除 last_pos 动画状态
```

### 核心逻辑层

| 文件 | 行数 | 包含 |
|------|------|------|
| `game_logic/game_logic.py` | 842 | `GameState` 类 + 纯工具函数 |
| `game_logic/combat_system.py` | 1077 | `CombatState` 类（战斗状态机） |
| `game_logic/dice_roller.py` | 224 | 骰子：投掷、处理、重投 |
| `game_logic/data_models.py` | 636 | `Action`, `Part`, `Pilot`, `GameEntity`, `Mech`, `Projectile`, `Drone` |
| `game_logic/ai_system.py` | 992 | `run_ai_turn()` + 寻路/评估辅助 |
| `game_logic/ace_ai_system.py` | 557 | `AceTacticalPlanner` + `run_ace_turn()` |
| `game_logic/ace_logic.py` | 302 | `decide_ace_timing()`, `check_initiative()`, `decide_reroll()` |

**`game_logic.py` 内容明细**：
```
GameState 类 (~400行):
  __init__(), _spawn_horde_ai(), _spawn_range_ai()
  spawn_projectile(), check_game_over()
  get_player_mech(), get_ai_mech(), get_entity_by_id(), get_entities_at_pos()
  get_occupied_tiles(), get_all_renderable_entities()
  calculate_move_range(), calculate_attack_range()
  add_visual_event(), to_dict(), from_dict()

独立纯函数:
  _get_distance(), _get_orientation_to_target()
  is_in_forward_arc(), is_back_attack(), _is_adjacent()
  _is_tile_locked_by_opponent()
  get_player_lock_status(), get_ai_lock_status()
  run_projectile_logic(), run_drone_logic()
  create_mech_from_selection(), create_ai_mech()
```

### 数据库层 (`game_logic/database/`)

| 文件 | 行数 | 内容 |
|------|------|------|
| `__init__.py` | 65 | 包管家：重组部件字典、导出公共 API |
| ~~`data_models.py`~~ | — | **已删除**——原先与 `game_logic/data_models.py` 完全重复 |
| `_effects.py` | 不定 | 效果定义 |
| `_actions.py` | 不定 | 动作模板 |
| `_generic_actions.py` | 不定 | 通用动作（拳打脚踢等） |
| `_parts_player.py` | 129 | 玩家可用部件 |
| `_parts_ai.py` | 53 | AI 专用部件 |
| `_pilots.py` | 32 | 驾驶员数据 |
| `_ai_loadouts.py` | 84 | AI 预设配置 |
| `_projectiles.py` | 不定 | 抛射物模板 |

### 前端

| 文件 | 行数 | 说明 |
|------|------|------|
| `static/js/game.js` | 1445 | 游戏主逻辑：棋盘渲染、AJAX、骰子动画、弹窗 |
| `templates/game.html` | 1091 | 游戏界面 Jinja2 模板 |
| `templates/hangar.html` | 643 | 机库页面（Tailwind CSS） |
| `templates/index.html` | 不定 | 首页（规则展示） |
| `templates/analytics.html` | 不定 | 分析统计页（Firebase） |
| `templates/attack_test.html` | 不定 | 测试工具 |
| `templates/damage_test.html` | 不定 | 测试工具 |
| `templates/dice_test.html` | 不定 | 测试工具 |

---

## 二、类继承体系

```
GameEntity (基类，data_models.py:122)
├── Mech      (data_models.py:257)  — 机甲：5个部件槽位 + 驾驶员 + 回合状态
├── Projectile (data_models.py:497) — 抛射物：1个 core 部件 + 飞行/延迟逻辑
└── Drone     (data_models.py:604)  — 无人机（骨架，未实现）

Part       (data_models.py:65)   — 部件：属性 + Action 列表
Action     (data_models.py:7)    — 动作：骰子、射程、效果
Pilot      (data_models.py:210)  — 驾驶员：链接值 + 速度属性 + 技能

CombatState (combat_system.py:23) — 战斗状态机（不继承任何基类）
AceTacticalPlanner (ace_ai_system.py:49) — Ace 战术规划器
CombatPlan  (ace_ai_system.py:22) — 回合方案数据类
```

---

## 三、CombatState 状态机（核心系统）

这是整个项目最精巧的设计。一次攻击的生命周期：

```
              resolve()
                 │
    ┌────────────▼─────────────┐
    │    INITIAL_ROLL          │  投掷攻击骰 + 防御骰
    │    _resolve_initial_roll │  → Ace 可能自动重投
    └────────────┬─────────────┘  → 检查玩家是否可重投
                 │
          ┌──────┴──────┐
          │ 玩家可重投? │
          └──────┬──────┘
        No       │       Yes
     ┌───────────┘       └─────────────┐
     │                                  │
     ▼                                  ▼
┌────────────────────┐   ┌──────────────────────────┐
│ _resolve_rerolled_ │   │ AWAITING_ATTACK_REROLL   │
│     _attack        │   │ → 序列化到 pending_combat│
│  结算伤害+检查效果  │   │ → 前端弹窗等待玩家      │
└────────┬───────────┘   │ → submit_reroll()        │
         │               └───────────┬──────────────┘
         │                           │
         │    ┌──────────────────────┘
         │    ▼
         │  _resolve_rerolled_attack (重投后的骰子)
         │    │
         │    ├── 无效果触发 → RESOLVED
         │    │
         │    ├── 单一效果 → _resolve_chosen_effect → RESOLVED
         │    │
         │    └── 多重效果 (玩家选择):
         │         ┌────────────────────────────┐
         │         │ AWAITING_EFFECT_CHOICE     │
         │         │ → 前端弹窗（毁伤/霰射/顺劈）│
         │         │ → submit_effect_choice()   │
         │         └───────────┬────────────────┘
         │                     │
         │                     ▼
         │               _resolve_chosen_effect
         │                     │
         │                     ├── 效果防御方可重投?
         │                     │   └── AWAITING_EFFECT_REROLL
         │                     │       → submit_reroll()
         │                     │       → _resolve_rerolled_effect
         │                     │
         │                     └── RESOLVED
         │
         ▼
    RESOLVED (战斗完成)
```

**序列化要点**：`CombatState.to_dict()` 和 `from_dict()` 必须保持同步。所有内部状态（`stage`, `attack_raw_rolls`, `defense_raw_rolls`, `overflow_hits` 等）都需要序列化。

---

## 四、中断链路（跨层通信）

当 CombatState 需要玩家决策时，走以下路径：

```
CombatState.stage != 'RESOLVED'
  → player_mech.pending_combat = combat_state.to_dict()
  → result_data = { 'action_required': 'select_reroll' | 'select_effect', ... }
  → controller 返回 (game_state, log, None, result_data, None)
  → api_routes._handle_controller_response 将 result_data 合并到 JSON 响应
  → 前端 game.js 收到 JSON，检测 action_required
  → 弹出模态框（重投界面 / 效果选择界面）
  → 用户提交 → AJAX /api/resolve_reroll 或 /api/resolve_effect_choice
  → controller 用 from_dict() 恢复 CombatState → 推进状态机
```

**页面刷新时的中断保护**：
```
/end_turn (redirect) 中：
  → session['pending_interrupt_data'] = result_data
  → GET /game 读取 session 注入 visual_events
  → game.js 检测到中断事件 → 弹窗

/run_projectile_phase (AJAX) 中：
  → result_data 直接合并到 JSON 响应返回
```

---

## 五、数据流全景

```
┌─────────────────────────────────────────────────────────┐
│ hangar.html                                             │
│ 用户选择: core, legs, left_arm, right_arm, backpack,   │
│           pilot, ai_opponent, game_mode                 │
└───────────────────────┬─────────────────────────────────┘
                        │ POST /start_game
                        ▼
┌─────────────────────────────────────────────────────────┐
│ main_routes.start_game()                                │
│ 1. 创建 GameState (调用 create_mech_from_selection)      │
│ 2. 设置初始位置和弹药                                    │
│ 3. 存入 session['game_state']                           │
│ 4. 初始化 session['combat_log']                         │
│ 5. redirect → GET /game                                 │
└───────────────────────┬─────────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────┐
│ game_routes.game()                                      │
│ 1. GameState.from_dict(session['game_state'])            │
│ 2. 获取 player_mech, ai_mech, log, lock_status          │
│ 3. 检查 pending_interrupt_data, run_projectile_phase    │
│ 4. render_template('game.html', ...)                    │
│ 5. 清除 transient 状态 (last_pos, visual_events)        │
│ 6. 保存回 session                                       │
└───────────────────────┬─────────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────┐
│ game.html + game.js                                     │
│ 前端渲染棋盘 → 玩家操作 → AJAX /api/*                    │
│ 每步操作: 反序列化→controller→序列化→保存→返回JSON       │
└───────────────────────┬─────────────────────────────────┘
                        │ POST /end_turn
                        ▼
┌─────────────────────────────────────────────────────────┐
│ handle_end_turn()                                       │
│ 1. AI 机甲阶段 (run_ai_turn 或 run_ace_turn)            │
│ 2. 结算 AI 攻击队列 (_resolve_queued_attack)             │
│ 3. 设置 run_projectile_phase 标志                       │
│ 4. redirect → GET /game                                 │
└───────────────────────┬─────────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────┐
│ 前端检测 run_projectile_phase 标志                       │
│ → AJAX /run_projectile_phase                            │
│ → handle_run_projectile_phase()                          │
│ → 处理所有抛射物的延迟动作 + 拦截                        │
│ → 重置玩家 AP/TP，新回合开始                             │
└─────────────────────────────────────────────────────────┘
```

---

## 六、文件依赖关系

```
app.py
 ├─ routes/main_routes.py ──── game_logic.game_logic (GameState)
 │                              game_logic.database (部件/驾驶员/AI配置)
 ├─ routes/game_routes.py ─── game_logic.game_logic (GameState)
 │                             game_logic.data_models (Mech, Projectile)
 │                             game_logic.game_controller
 └─ routes/api_routes.py ─── game_logic.game_logic (GameState)
                               game_logic.data_models (Mech)
                               game_logic.game_controller

game_logic/game_controller.py
 ├─ game_logic/data_models.py   (Action, Mech, Projectile, Part, Drone, Pilot)
 ├─ game_logic/combat_system.py (CombatState)
 ├─ game_logic/dice_roller.py   (roll_black_die)
 ├─ game_logic/game_logic.py    (GameState + 所有纯函数)
 ├─ game_logic/ai_system.py     (run_ai_turn)
 ├─ game_logic/ace_logic.py     (decide_ace_timing, check_initiative, decide_reroll)
 ├─ game_logic/ace_ai_system.py (run_ace_turn)
 └─ game_logic/database/        (ALL_PARTS)

game_logic/combat_system.py
 ├─ game_logic/dice_roller.py   (roll_dice, process_rolls, reroll_specific_dice)
 ├─ game_logic/data_models.py   (Mech, Projectile, Part, Action)
 └─ game_logic/ace_logic.py     (decide_reroll)

game_logic/game_logic.py
 ├─ game_logic/data_models.py   (所有数据类)
 └─ game_logic/database/        (ALL_PARTS, PROJECTILE_TEMPLATES, AI_LOADOUTS, ...)

game_logic/database/__init__.py
 ├─ _effects.py
 ├─ _actions.py
 ├─ _generic_actions.py
 ├─ _projectiles.py
 ├─ _pilots.py
 ├─ _parts_player.py
 ├─ _parts_ai.py
 └─ _ai_loadouts.py
```

---

## 七、数据库（游戏内容）结构

### 部件类属

每个部件字典按槽位分类：
- **CORES** = PLAYER_CORES + AI_ONLY_CORES
- **LEGS** = PLAYER_LEGS + AI_ONLY_LEGS
- **LEFT_ARMS** / **RIGHT_ARMS** / **BACKPACKS**（同理）

所有部件最终合并到 `ALL_PARTS`，索引键为**部件中文名**（如 `"CC-6Q"`、`"AMS-190"`）。

### Action 属性

```python
Action(name, action_type, cost, dice, range_val, effects, action_style, aoe_range, projectile_to_spawn, ammo)
```

- `action_type`: `'近战'` | `'射击'` | `'移动'` | `'抛射'` | `'被动'` | `'快速'` | `'战术'`
- `cost`: `'S'` | `'M'` | `'L'`
- `dice`: `'2黄1红'` 格式字符串
- `effects`: 字典，如 `{"armor_piercing": 2, "devastating": True, "shock": True, "salvo": 3}`

### 常用效果键名

| 键 | 含义 |
|------|------|
| `armor_piercing` | 穿甲 N（减少白骰） |
| `devastating` | 毁伤（溢出伤害打结构值） |
| `scattershot` | 霰射（溢出伤害打随机部件） |
| `cleave` | 顺劈（同霰射，不同命名） |
| `shock` | 震撼（闪电→链接值损失） |
| `salvo` | 齐射数 |
| `convert_lightning_to_crit` | 频闪武器（闪电→重击） |
| `interceptor` | 可拦截抛射物 |
| `static_range_bonus` | 静止射程加成 |
| `two_handed_sniper` | 双手狙击（另一手空手→任意选部位） |
| `two_handed_devastating` | 双手毁伤 |
| `two_handed_range_bonus` | 双手射程加成 |
| `straight_line_bonus` | 喷射冲刺（直线额外移动） |
| `flight_movement` | 飞行移动模式 |

### ammo_counts 结构

```python
# Key: (entity_id, part_slot, action_name)
# Value: int
{ ('player_1', 'left_arm', '火箭弹'): 3,
  ('ai_1', 'backpack', '导弹'): 2, ... }
```

---

## 八、测试工具页面

项目包含 3 个测试工具（直接访问）：

| 路由 | 模板 | 用途 |
|------|------|------|
| `/attack_test` | `attack_test.html` | 攻击结算测试 |
| `/damage_test` | `damage_test.html` | 伤害结算测试 |
| `/dice_test` | `dice_test.html` | 骰子机制测试 |

---

## 九、版本历史（来自代码注释）

| 版本 | 变更 |
|------|------|
| v2.5 | 新增 Raven Ace AI、新部件、新效果、代码优化、拦截修复 |
| v2.4 | AI 优化：抛射物战术价值提升、智能瞄准 |
| 阶段2重构 | CombatState 状态机引入、重投机制、效果选择系统 |
| v_REFACTOR | 单体 app.py 拆分为三层架构、引入蓝图 |

---

## 十、修改提醒

- **新增部件/动作/效果** → 修改 `database/_parts_*.py` 或 `database/_effects.py`
- **新增动作类型** → 检查 `_execute_main_action()` 和 `CombatState._resolve_initial_roll()` 中的类型判断
- **新增中断类型** → 在 `CombatState` 添加新 stage、更新 `to_dict/from_dict`、前端 `game.js` 添加新弹窗
- **新增实体类型** → 在 `data_models.py` 新增类、`GameEntity.from_dict()` 添加分支
- **修改文件结构** → **同时更新本文档和 `CLAUDE.md`**
