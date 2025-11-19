import random
import copy
from .game_logic import (
    _get_distance, _is_adjacent, get_ai_lock_status,
    _is_tile_locked_by_opponent, _get_orientation_to_target
)
from .ai_system import (
    _evaluate_action_strength, _find_all_reachable_positions,
    _calculate_ai_attack_range
)
from .database import PROJECTILE_TEMPLATES

"""
【Ace AI 系统 2.0 - 战术规划器】

不再是简单的条件反射，Ace 现在使用 "模拟-评分-执行" (Simulate-Score-Execute) 架构。
它会生成多个符合规则的 "方案 (Plan)"，然后选择最优解。

特性：
1. 严格遵守 [时机-起手动作] 约束。
2. 智能管理 [TP] 资源 (用于调整移动 vs 长动作)。
3. 战术意图驱动 (斩杀/压制/消耗)。
"""


class CombatPlan:
    """
    描述一个完整的回合行动方案。
    """

    def __init__(self):
        self.intent = "IDLE"  # 意图: EXECUTION, SHOCK, DAMAGE, MANEUVER
        self.score = 0  # 评分: 越高越好

        # --- 决策参数 ---
        self.timing = "移动"  # Phase 1: 时机
        self.stance = "defense"  # Phase 2: 姿态

        # --- 动作序列 ---
        # Phase 3: 调整 (None 或 ('move', pos, ori) 或 ('rotate', ori))
        self.tp_action = None
        self.tp_cost = 0

        # Phase 4: 主动作
        self.opening_action = None  # (action_obj, slot, target_entity)
        self.opening_cost_ap = 0
        self.opening_cost_tp = 0

        self.extra_actions = []  # List of (action_obj, slot, target_entity)

        self.description = ""  # 调试日志描述


class AceTacticalPlanner:
    """
    Ace 的大脑。负责生成和评估 CombatPlan。
    """

    def __init__(self, ace_mech, game_state):
        self.ace = ace_mech
        self.game_state = game_state
        self.player = game_state.get_player_mech()
        self.log = []

        # 预计算数据
        self.dist_to_player = _get_distance(self.ace.pos, self.player.pos) if self.player else 999
        self.reachable_tiles_tp = {}  # 仅 TP 可达
        self.reachable_tiles_ap = {}  # AP 可达

        # 初始化资源
        self.initial_ap = self.ace.player_ap
        self.initial_tp = self.ace.player_tp

    def generate_best_plan(self):
        if not self.player or self.player.status == 'destroyed':
            return self._create_idle_plan()

        self._precompute_movement()

        candidate_plans = []

        # 1. 尝试生成 [攻击] 方案 (遍历所有可用武器)
        available_weapons = self._get_available_weapons()
        for action, slot in available_weapons:
            # 尝试路径 A: 原地/调整攻击 (Timing = 攻击类型)
            plan_a = self._create_adjust_attack_plan(action, slot)
            if plan_a: candidate_plans.append(plan_a)

            # 尝试路径 B: 移动后攻击 (Timing = 移动, 仅当 Weapon 是 S 动作且 AP 足够时)
            # (Ace 很少用这招，因为通常 M 移动后没 AP 了，除非有 S 移动)
            # plan_b = self._create_move_attack_plan(action, slot)
            # if plan_b: candidate_plans.append(plan_b)

        # 2. 尝试生成 [突击装甲/战术] 方案
        # (已包含在上述循环中，因为战术也是 Action)

        # 3. 尝试生成 [纯机动] 方案 (Timing = 移动)
        maneuver_plan = self._create_maneuver_plan()
        if maneuver_plan: candidate_plans.append(maneuver_plan)

        # 4. 评分并择优
        if not candidate_plans:
            return self._create_idle_plan()

        # 根据意图修正评分
        for plan in candidate_plans:
            self._score_plan(plan)

        # 按分数降序排列
        best_plan = max(candidate_plans, key=lambda p: p.score)
        self.log.append(
            f"> [Ace规划] 生成了 {len(candidate_plans)} 个方案。最优: [{best_plan.intent}] {best_plan.description} (分: {best_plan.score})")

        return best_plan

    def _precompute_movement(self):
        """预计算 TP 和 AP 的移动范围"""
        # 1. TP 移动范围
        legs = self.ace.parts.get('legs')
        if legs and legs.status != 'destroyed' and self.initial_tp > 0:
            # 假设 Ace 总是愿意切机动姿态来最大化 TP 移动
            adjust_range = legs.adjust_move * 2
            # 这里的计算不考虑锁定带来的惩罚，因为调整移动通常较短且灵活
            # 使用简单的 BFS 获取范围
            self.reachable_tiles_tp = self._get_simple_reachable(self.ace.pos, adjust_range)
        else:
            self.reachable_tiles_tp = {self.ace.pos: 0}

    def _get_simple_reachable(self, start_pos, max_dist):
        """简单的曼哈顿距离范围获取 (忽略阻挡，仅用于快速筛选，实际 check_range 会严谨)"""
        tiles = {}
        w, h = self.game_state.board_width, self.game_state.board_height
        occupied = self.game_state.get_occupied_tiles(exclude_id=self.ace.id)

        for x in range(max(1, start_pos[0] - max_dist), min(w, start_pos[0] + max_dist) + 1):
            for y in range(max(1, start_pos[1] - max_dist), min(h, start_pos[1] + max_dist) + 1):
                pos = (x, y)
                dist = abs(x - start_pos[0]) + abs(y - start_pos[1])
                if dist <= max_dist and pos not in occupied:
                    tiles[pos] = dist
        return tiles

    def _create_adjust_attack_plan(self, action, slot):
        """
        尝试构建一个 [调整 -> 攻击] 的方案。
        Timing: 由 action.action_type 决定
        """
        cost_ap = self._get_ap_cost(action)
        cost_tp = 1 if action.cost == 'L' else 0

        # 资源预检查
        if self.initial_ap < cost_ap: return None
        if self.initial_tp < cost_tp: return None

        plan = CombatPlan()
        plan.timing = action.action_type
        # 修正：如果是 '抛射'，时机可以是 '射击' 或 '抛射'，这里简化为严格匹配

        plan.opening_action = (action, slot, self.player)
        plan.opening_cost_ap = cost_ap
        plan.opening_cost_tp = cost_tp

        # 检查是否需要 TP 调整
        # 如果是 L 动作，TP 被锁定，不能调整
        can_adjust = (cost_tp == 0 and self.initial_tp >= 1)

        best_pos = None
        best_ori = None

        # 1. 检查当前位置是否可行
        if self._is_attack_valid(self.ace.pos, self.ace.orientation, action, self.player.pos):
            best_pos = self.ace.pos
            best_ori = self.ace.orientation
            # 即使当前可行，如果能调整到更好的位置（例如背击），也可以尝试，这里简化为“能打就行”

        # 2. 如果当前不可行，且可以调整，寻找 TP 可达的最佳位置
        elif can_adjust:
            for pos in self.reachable_tiles_tp.keys():
                # 尝试朝向目标的最佳方向
                ideal_ori = _get_orientation_to_target(pos, self.player.pos)
                if self._is_attack_valid(pos, ideal_ori, action, self.player.pos):
                    best_pos = pos
                    best_ori = ideal_ori
                    plan.tp_action = ('move', pos, ideal_ori)
                    plan.tp_cost = 1
                    break  # 找到一个位置即可

        if best_pos:
            plan.description = f"{action.name} @ {best_pos}"
            # 设置意图
            if "打桩机" in action.name or action.cost == 'L':
                plan.intent = "EXECUTION"
            elif "突击装甲" in action.name or "震撼" in str(action.effects):
                plan.intent = "SHOCK"
            elif action.action_type == '抛射':
                plan.intent = "BARRAGE"
            else:
                plan.intent = "DAMAGE"
            return plan

        return None

    def _create_maneuver_plan(self):
        """构建一个纯机动方案 (Timing=移动)"""
        plan = CombatPlan()
        plan.intent = "MANEUVER"
        plan.timing = "移动"
        plan.stance = "agile"

        # 寻找最好的移动动作
        move_actions = []
        for action, slot in self._get_available_weapons():
            if action.action_type == '移动' and self.initial_ap >= self._get_ap_cost(action):
                move_actions.append((action, slot))

        if not move_actions: return None

        # 选移动距离最远的
        best_move = max(move_actions, key=lambda x: x[0].range_val)
        plan.opening_action = (best_move[0], best_move[1], None)  # Target None for move
        plan.opening_cost_ap = self._get_ap_cost(best_move[0])
        plan.description = f"机动: {best_move[0].name}"

        # Ace 总是喜欢保持 3-5 距离
        return plan

    def _score_plan(self, plan):
        """给方案打分"""
        score = 0

        # 1. 意图基础分
        if plan.intent == "EXECUTION":
            # 如果敌人濒死或宕机，处决分极高
            if self.player.stance == 'downed':
                score += 1000
            elif self.player.parts['core'].status == 'damaged':
                score += 500
            else:
                score += 100  # 普通状态打桩也很疼

        elif plan.intent == "SHOCK":
            # 距离近且有 AP 时爆发
            if self.dist_to_player <= 2:
                score += 300
            else:
                score += 50

        elif plan.intent == "BARRAGE":
            # 远程压制
            score += 200

        elif plan.intent == "DAMAGE":
            score += 150

        elif plan.intent == "MANEUVER":
            # 如果被锁定或太近，机动分提高
            if get_ai_lock_status(self.game_state, self.ace)[0]:
                score += 400
            elif self.dist_to_player <= 1:
                score += 200  # 拉开距离
            else:
                score += 10

        # 2. 伤害期望修正 (简单版)
        action = plan.opening_action[0]
        if action.action_type in ['近战', '射击', '抛射']:
            dmg_score = _evaluate_action_strength(action, 2, True) * 20
            score += dmg_score

        # 3. 资源惩罚
        if plan.tp_cost > 0: score -= 10  # 尽量省 TP
        if plan.opening_cost_ap >= 2: score -= 10  # 耗 AP 多略微惩罚

        plan.score = score

    # --- 辅助 ---

    def _get_available_weapons(self):
        weapons = []
        for slot, part in self.ace.parts.items():
            if part and part.status != 'destroyed':
                for action in part.actions:
                    if (slot, action.name) in self.ace.actions_used_this_turn: continue
                    # 弹药检查
                    if action.ammo > 0:
                        key = (self.ace.id, slot, action.name)
                        if self.game_state.ammo_counts.get(key, 0) <= 0: continue
                    weapons.append((action, slot))
        return weapons

    def _get_ap_cost(self, action):
        return action.cost.count('M') * 2 + action.cost.count('S') * 1 + (2 if action.cost == 'L' else 0)

    def _is_attack_valid(self, pos, ori, action, target_pos):
        """严格验证射程和朝向"""
        # 如果是战术动作(突击装甲)，视为 AOE，检查距离即可
        if action.action_type == '战术':
            dist = _get_distance(pos, target_pos)
            return dist <= action.range_val

        # [FIX] _calculate_ai_attack_range 只返回 targets 列表，不返回元组
        valid_targets = _calculate_ai_attack_range(
            self.game_state, self.ace, action,
            pos, ori,
            target_pos, self.initial_tp  # 这里传入 TP 是为了计算【静止】加成，但 Ace 逻辑中我们通常忽略静止加成以求稳
        )
        return len(valid_targets) > 0

    def _create_idle_plan(self):
        p = CombatPlan()
        p.description = "待机"
        return p


def run_ace_turn(ace_mech, game_state):
    """
    执行器：获取最佳方案并将其转化为实际的游戏操作。
    """

    log = []
    attacks_to_resolve_list = []

    # 1. 应用 Phase 0: 资源初始化 (应用技能)
    if ace_mech.stance == 'downed':
        log.append(f"> [Ace系统] {ace_mech.name} 强制重启... 系统恢复。")
        ace_mech.player_ap = 1
        ace_mech.player_tp = 0
        ace_mech.stance = 'defense'
    else:
        ace_mech.player_ap = 2
        ace_mech.player_tp = 1

        # [NEW] 技能：乘胜追击 (pursuit)
        if ace_mech.pilot and "pursuit" in ace_mech.pilot.skills:
            player_mech = game_state.get_player_mech()
            if player_mech:
                has_compromised = False
                for part in player_mech.parts.values():
                    if part and part.status in ['damaged', 'destroyed']:
                        has_compromised = True
                        break
                if has_compromised:
                    ace_mech.player_ap += 1
                    log.append(f"> [Ace技能: 冷酷] 侦测到敌方受损，AP+1 (当前: {ace_mech.player_ap})")

    # 2. 开始规划 (Planner 需要基于已经加了 AP 的状态来规划)
    planner = AceTacticalPlanner(ace_mech, game_state)
    best_plan = planner.generate_best_plan()

    # 合并 Planner 的日志
    log.extend(planner.log)
    log.append(f"> [Ace执行] 意图: {best_plan.intent} | 时机: {best_plan.timing}")

    # 3. 应用 Phase 1 & 2 (设置姿态)
    # 设置姿态
    # 如果计划中有调整移动，或者意图是机动，强制 Agile
    if best_plan.tp_action or best_plan.intent == "MANEUVER":
        ace_mech.stance = 'agile'
    else:
        ace_mech.stance = best_plan.stance

    # 4. 执行 Phase 3 (TP)
    if best_plan.tp_action:
        type_, pos, ori = best_plan.tp_action
        if type_ == 'move':
            ace_mech.last_pos = ace_mech.pos
            ace_mech.pos = pos
            ace_mech.orientation = ori  # 调整移动包含转向
            ace_mech.player_tp -= 1
            log.append(f"> [Ace] 战术机动 -> {pos}")

    # 5. 执行 Phase 4 (Opening)
    if best_plan.opening_action:
        action, slot, target = best_plan.opening_action

        # 扣费
        ace_mech.player_ap -= best_plan.opening_cost_ap
        ace_mech.player_tp -= best_plan.opening_cost_tp
        ace_mech.actions_used_this_turn.append((slot, action.name))

        # 执行逻辑
        if action.action_type == '移动':
            # 简单的移动逻辑：尝试保持距离 4
            pass

        elif action.action_type == '抛射':
            _execute_projectile_launch(ace_mech, action, slot, target, game_state, log, attacks_to_resolve_list)

        else:
            # 普通攻击
            attacks_to_resolve_list.append({
                'attacker': ace_mech,
                'defender': target,
                'action': action
            })
            _consume_ammo(ace_mech, action, slot, game_state)

    # 6. 执行连招 (Follow-up) - 简单贪婪填补
    # 如果还有 AP，尝试找一个能用的 S 动作
    while ace_mech.player_ap >= 1:
        extra = _find_extra_action(ace_mech, game_state, planner)
        if extra:
            action, slot = extra
            log.append(f"> [Ace] 连招: {action.name}")
            ace_mech.player_ap -= 1
            ace_mech.actions_used_this_turn.append((slot, action.name))

            if action.action_type == '抛射':
                _execute_projectile_launch(ace_mech, action, slot, game_state.get_player_mech(), game_state, log,
                                           attacks_to_resolve_list)
            else:
                attacks_to_resolve_list.append({
                    'attacker': ace_mech,
                    'defender': game_state.get_player_mech(),
                    'action': action
                })
                _consume_ammo(ace_mech, action, slot, game_state)
        else:
            break

    return log, attacks_to_resolve_list


# --- 执行辅助函数 ---

def _execute_projectile_launch(mech, action, slot, target, game_state, log, attacks_list):
    salvo = action.effects.get('salvo', 1)
    key = (mech.id, slot, action.name)
    current = game_state.ammo_counts.get(key, 0)
    count = min(salvo, current)

    if count > 0:
        game_state.ammo_counts[key] -= count
        log.append(f"> [Ace] 发射 {action.name} (x{count})")

        target_pos = target.pos if target else mech.pos

        for _ in range(count):
            pid, pobj = game_state.spawn_projectile(mech, target_pos, action.projectile_to_spawn)
            # 立即结算
            from .game_logic import run_projectile_logic
            plog, pattacks = run_projectile_logic(pobj, game_state, '立即')
            log.extend(plog)
            attacks_list.extend(pattacks)


def _consume_ammo(mech, action, slot, game_state):
    if action.ammo > 0:
        key = (mech.id, slot, action.name)
        if game_state.ammo_counts.get(key, 0) > 0:
            game_state.ammo_counts[key] -= 1


def _find_extra_action(mech, game_state, planner):
    """在回合末尾寻找可用的 S 动作填充"""
    player = game_state.get_player_mech()
    if not player: return None

    for action, slot in planner._get_available_weapons():
        if action.cost == 'S':
            if planner._is_attack_valid(mech.pos, mech.orientation, action, player.pos):
                return (action, slot)
    return None