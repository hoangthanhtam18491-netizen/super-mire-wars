import random
import copy
from .game_logic import (
    _get_distance, _is_adjacent, get_ai_lock_status,
    _is_tile_locked_by_opponent, _get_orientation_to_target
)
from .ai_system import (
    _evaluate_action_strength, _find_all_reachable_positions,
    _calculate_ai_attack_range, _find_best_move_position,
    _find_farthest_move_position, _get_action_cost
)
from .database import PROJECTILE_TEMPLATES

"""
【Ace AI 系统 2.5 - 机动大师版】

更新内容：
1. _score_plan: 严格执行“平时机动，大招攻击”的姿态策略。
"""


class CombatPlan:
    """
    描述一个完整的回合行动方案。
    """

    def __init__(self):
        self.intent = "IDLE"  # 意图: EXECUTION, SHOCK, DAMAGE, MANEUVER, BARRAGE, PURSUIT
        self.score = -9999  # 评分: 越高越好

        # --- 决策参数 (Phase 1 & 2) ---
        self.timing = "移动"  # Phase 1: 时机 (严格由 action_sequence[0] 决定)
        self.stance = "agile"  # Phase 2: 姿态 (默认为机动)

        # --- 动作序列 ---
        # Phase 3: 调整
        # 格式: ('move', pos, ori) 或 ('rotate', ori) 或 None
        self.tp_action = None
        self.tp_cost = 0

        # Phase 4: 主动作链
        # 格式: List of tuples -> [(action_obj, part_slot, target_entity_or_pos), ...]
        self.action_sequence = []
        self.total_ap_cost = 0

        self.description = ""  # 调试日志描述


class AceTacticalPlanner:
    """
    Ace 的大脑。负责生成和评估动作链 (Action Chains)。
    """

    def __init__(self, ace_mech, game_state):
        self.ace = ace_mech
        self.game_state = game_state
        self.player = game_state.get_player_mech()
        self.log = []

        # 预计算数据
        self.dist_to_player = _get_distance(self.ace.pos, self.player.pos) if self.player else 999
        self.reachable_tiles_tp = {}  # 仅 TP 可达
        self.all_reachable_costs = {}  # 所有格子移动成本 (用于移动规划)

        # 初始化资源
        self.initial_ap = self.ace.player_ap
        self.initial_tp = self.ace.player_tp

        # 收集可用武器 (缓存)
        self.available_weapons = self._get_available_weapons()

    def generate_best_plan(self):
        if not self.player or self.player.status == 'destroyed':
            return self._create_idle_plan()

        self._precompute_movement()

        candidate_plans = []

        # === 核心逻辑：生成动作链 ===

        # 1. 尝试以【武器/战术攻击】起手
        for action, slot in self.available_weapons:
            self._try_add_attack_chains(candidate_plans, action, slot, is_first_step=True)

        # 2. 尝试以【移动】起手 (仅当有 S/M AP 时)
        move_candidates = self._get_tactical_move_candidates()
        move_action_data = self._get_move_action_data()  # 获取 "奔跑" 或 "推进" 动作

        if move_action_data:
            move_action, move_slot = move_action_data
            for move_pos in move_candidates:
                self._try_add_move_chains(candidate_plans, move_action, move_slot, move_pos)

        # 3. 评分并择优
        if not candidate_plans:
            self.log.append("> [Ace规划] 未找到有效方案，生成待机方案。")
            return self._create_idle_plan()

        # 评分
        for plan in candidate_plans:
            self._score_plan(plan)

        # 排序
        # 优先分数高，其次 AP 消耗高 (优先做更多事的)，最后随机打破平局
        best_plan = max(candidate_plans, key=lambda p: (p.score, p.total_ap_cost, random.random()))

        self.log.append(
            f"> [Ace规划] 最优方案: [{best_plan.intent}] {best_plan.description} (分: {best_plan.score:.1f}, 耗: {best_plan.total_ap_cost}AP)")

        return best_plan

    # --- 链生成逻辑 ---

    def _try_add_attack_chains(self, plans_list, action, slot, is_first_step=True):
        """
        尝试构建以 <action> 为第一步的动作链。
        """
        ap_cost, tp_cost_action = _get_action_cost(action)

        # 资源检查
        if self.initial_ap < ap_cost: return
        # L 动作需要 1 TP，或者某些特殊动作需要 TP
        total_tp_needed = tp_cost_action
        if self.initial_tp < total_tp_needed: return

        # L 动作如果耗尽 TP，就不能进行 adjustment 移动
        can_adjust_tp = (self.initial_tp - total_tp_needed) >= 1

        # 寻找可行的攻击位置 (当前位置 或 TP调整位置)
        valid_launch_configs = []  # [(pos, ori, tp_action_needed)]

        # A. 检查当前位置
        if self._is_attack_valid(self.ace.pos, self.ace.orientation, action, self.player.pos):
            valid_launch_configs.append((self.ace.pos, self.ace.orientation, None))

        # B. 如果当前不可行，且有 TP，尝试寻找 adjustment 位置
        elif can_adjust_tp:
            for pos in self.reachable_tiles_tp.keys():
                # 理想朝向
                ideal_ori = _get_orientation_to_target(pos, self.player.pos)
                if self._is_attack_valid(pos, ideal_ori, action, self.player.pos):
                    tp_act = ('move', pos, ideal_ori)
                    valid_launch_configs.append((pos, ideal_ori, tp_act))
                    break  # 找到一个就行

        # 对每个可行的发射配置，生成计划
        for (pos, ori, tp_act) in valid_launch_configs:
            # --- 基础计划 (链长=1) ---
            plan = CombatPlan()
            plan.timing = action.action_type  # 关键：时机由第一步决定
            plan.tp_action = tp_act
            plan.tp_cost = 1 if tp_act else 0
            plan.action_sequence.append((action, slot, self.player))
            plan.total_ap_cost = ap_cost
            plan.description = f"{action.name}"
            if tp_act: plan.description = f"调整 -> {action.name}"

            # 如果是 L 动作或 M 动作 (耗尽 AP)，链条结束
            if ap_cost >= 2:
                plans_list.append(plan)
                continue

            # --- 尝试扩展链 (链长=2) ---
            # 只有当消耗是 1 AP (S 动作) 时，我们才尝试找第二步
            sim_pos = pos
            sim_ori = ori
            has_follow_up = False

            # 1. 尝试接 S 攻击
            for next_action, next_slot in self.available_weapons:
                if next_action == action and next_slot == slot: continue

                next_ap, next_tp = _get_action_cost(next_action)
                if next_ap == 1 and next_tp == 0:
                    if self._is_attack_valid(sim_pos, sim_ori, next_action, self.player.pos):
                        chain_plan = copy.deepcopy(plan)
                        chain_plan.action_sequence.append((next_action, next_slot, self.player))
                        chain_plan.total_ap_cost += next_ap
                        chain_plan.description += f" -> {next_action.name}"
                        plans_list.append(chain_plan)
                        has_follow_up = True

            # 2. 尝试接 移动
            move_action_data = self._get_move_action_data()
            if move_action_data:
                move_act, move_sl = move_action_data
                mv_ap, _ = _get_action_cost(move_act)
                if mv_ap == 1:
                    best_move_pos = self._find_best_tactical_move(sim_pos, move_act.range_val)
                    if best_move_pos:
                        chain_plan = copy.deepcopy(plan)
                        chain_plan.action_sequence.append((move_act, move_sl, best_move_pos))
                        chain_plan.total_ap_cost += mv_ap
                        chain_plan.description += f" -> 移动"
                        plans_list.append(chain_plan)
                        has_follow_up = True

            # 如果找不到连招，保留原始的单步计划
            if not has_follow_up:
                plans_list.append(plan)

    def _try_add_move_chains(self, plans_list, move_action, slot, target_pos):
        """
        尝试构建以【移动】为第一步的动作链。
        [Move (1AP)] -> [Attack (1AP)]
        """
        ap_cost, _ = _get_action_cost(move_action)

        # 资源检查
        if self.initial_ap < ap_cost: return

        # 构建基础移动计划
        plan = CombatPlan()
        plan.timing = "移动"  # 关键：起手是移动
        plan.action_sequence.append((move_action, slot, target_pos))
        plan.total_ap_cost = ap_cost
        plan.description = f"移动({target_pos})"

        # 如果移动耗尽 AP，结束
        if ap_cost >= 2:
            plans_list.append(plan)
            return

        # --- 尝试接 S 攻击 ---
        sim_pos = target_pos
        # 移动后，假设 AI 会自动转向玩家
        sim_ori = _get_orientation_to_target(sim_pos, self.player.pos)
        has_follow_up = False

        for next_action, next_slot in self.available_weapons:
            next_ap, next_tp = _get_action_cost(next_action)
            if next_ap == 1 and self.initial_ap >= (ap_cost + next_ap):
                if self._is_attack_valid(sim_pos, sim_ori, next_action, self.player.pos):
                    chain_plan = copy.deepcopy(plan)
                    chain_plan.action_sequence.append((next_action, next_slot, self.player))
                    chain_plan.total_ap_cost += next_ap
                    chain_plan.description += f" -> {next_action.name}"
                    plans_list.append(chain_plan)
                    has_follow_up = True

        if not has_follow_up:
            plans_list.append(plan)

    # --- 辅助计算 ---

    def _precompute_movement(self):
        self.all_reachable_costs = _find_all_reachable_positions(self.game_state, self.ace, self.player)
        legs = self.ace.parts.get('legs')
        tp_range = 0
        if legs and legs.status != 'destroyed' and self.initial_tp > 0:
            tp_range = legs.adjust_move * 2

        self.reachable_tiles_tp = {
            pos: cost for pos, cost in self.all_reachable_costs.items()
            if cost <= tp_range
        }
        self.reachable_tiles_tp[self.ace.pos] = 0

    def _get_tactical_move_candidates(self):
        candidates = []
        if not self.player: return []
        p1 = _find_best_move_position(self.game_state, 4, 1, 1, 'closest', self.all_reachable_costs, self.player.pos)
        if p1: candidates.append(p1)
        p2 = _find_best_move_position(self.game_state, 4, 5, 8, 'ideal', self.all_reachable_costs, self.player.pos)
        if p2: candidates.append(p2)
        p3 = _find_farthest_move_position(self.game_state, 4, self.all_reachable_costs, self.player.pos)
        if p3: candidates.append(p3)
        return list(set(candidates))

    def _find_best_tactical_move(self, start_pos, move_range):
        dx = self.player.pos[0] - start_pos[0]
        dy = self.player.pos[1] - start_pos[1]
        dist = abs(dx) + abs(dy)
        if dist == 0: return start_pos
        step_x = int(dx / dist * move_range) if dist > 0 else 0
        step_y = int(dy / dist * move_range) if dist > 0 else 0
        target_x = max(1, min(10, start_pos[0] + step_x))
        target_y = max(1, min(10, start_pos[1] + step_y))
        return (target_x, target_y)

    def _get_available_weapons(self):
        weapons = []
        for slot, part in self.ace.parts.items():
            if part and part.status != 'destroyed':
                for action in part.actions:
                    if (slot, action.name) in self.ace.actions_used_this_turn: continue
                    if action.action_type not in ['近战', '射击', '抛射', '战术']: continue
                    if action.ammo > 0:
                        key = (self.ace.id, slot, action.name)
                        if self.game_state.ammo_counts.get(key, 0) <= 0: continue
                    weapons.append((action, slot))
        return weapons

    def _get_move_action_data(self):
        for slot, part in self.ace.parts.items():
            if part and part.status != 'destroyed':
                for action in part.actions:
                    if action.action_type == '移动':
                        return (action, slot)
        return None

    def _score_plan(self, plan):
        """
        [v2.5 优化] 给方案打分。
        包含姿态逻辑更新：默认 Agile，仅在使用 L 动作时切换 Attack。
        """
        score = 0

        # Pilot Skill Context
        skills = self.ace.pilot.skills if self.ace.pilot else []
        has_pursuit = "pursuit" in skills

        # Player Context
        player_compromised = any(p.status in ['damaged', 'destroyed'] for p in self.player.parts.values() if p)

        # 1. 伤害评分 (Damage Score)
        for (action, slot, target) in plan.action_sequence:
            if action.action_type in ['近战', '射击', '抛射', '战术']:
                # 基础强度
                dmg_score = _evaluate_action_strength(action, 2, True) * 20

                # [Skill Synergy] 乘胜追击
                if has_pursuit:
                    if dmg_score > 30:
                        dmg_score *= 1.2
                    if player_compromised:
                        dmg_score += 15
                        plan.intent = "PURSUIT"

                score += dmg_score

                if "打桩机" in action.name or action.cost == 'L':
                    plan.intent = "EXECUTION"
                elif "突击装甲" in action.name or "震撼" in str(action.effects):
                    plan.intent = "SHOCK"

        if not plan.action_sequence: return 0

        # 2. 位置评分 (Positioning Score)
        final_pos = self.ace.pos

        # 先看 TP 移动
        if plan.tp_action and plan.tp_action[0] == 'move':
            final_pos = plan.tp_action[1]

        # 再看主动作移动 (会覆盖 TP 移动)
        for (action, slot, target) in plan.action_sequence:
            if action.action_type == '移动' and target:
                final_pos = target

        dist = _get_distance(final_pos, self.player.pos)

        if 2 <= dist <= 5:
            score += 10

        # 3. 资源惩罚 (Resource Penalty)
        if plan.tp_cost > 0: score -= 5
        if plan.total_ap_cost < 2: score -= 15

        plan.score = score

        # 4. 姿态选择 (Stance Selection) [NEW LOGIC]
        # 默认: 机动姿态 (Agile)
        plan.stance = 'agile'

        # 只有当使用 L 动作时才切换到攻击姿态 (为了最大化大招收益)
        # 或者当意图明确为“处决”时
        has_l_action = any(a.cost == 'L' for a, s, t in plan.action_sequence)
        if has_l_action or plan.intent == "EXECUTION":
            plan.stance = 'attack'

    def _is_attack_valid(self, pos, ori, action, target_pos):
        if action.action_type == '战术':
            dist = _get_distance(pos, target_pos)
            return dist <= action.range_val
        valid_targets = _calculate_ai_attack_range(
            self.game_state, self.ace, action,
            pos, ori,
            target_pos, self.initial_tp
        )
        return len(valid_targets) > 0

    def _create_idle_plan(self):
        p = CombatPlan()
        p.description = "待机"
        return p


def run_ace_turn(ace_mech, game_state):
    """
    执行器：获取最佳方案并将其转化为实际的游戏操作。
    包含 Filler Logic 以用尽剩余 AP。
    """

    log = []
    attacks_to_resolve_list = []

    # 1. 资源初始化
    if ace_mech.stance == 'downed':
        log.append(f"> [Ace系统] {ace_mech.name} 强制重启... 系统恢复。")
        ace_mech.player_ap = 1
        ace_mech.player_tp = 0
        ace_mech.stance = 'defense'
    else:
        ace_mech.player_ap = 2
        ace_mech.player_tp = 1
        # [Skill] 乘胜追击 (Pursuit) 回合初检查
        if ace_mech.pilot and "pursuit" in ace_mech.pilot.skills:
            player_mech = game_state.get_player_mech()
            if player_mech:
                has_compromised = any(p.status in ['damaged', 'destroyed'] for p in player_mech.parts.values() if p)
                if has_compromised:
                    ace_mech.player_ap += 1
                    log.append(f"> [Ace技能: 乘胜追击] 侦测到敌方受损，AP+1 (当前: {ace_mech.player_ap})")

    # 2. 获取计划 (优先读取缓存)
    # [关键] 检查是否有缓存的计划
    if hasattr(ace_mech, 'cached_ace_plan') and ace_mech.cached_ace_plan:
        best_plan = ace_mech.cached_ace_plan
        ace_mech.cached_ace_plan = None  # 使用后清除
        log.append(f"> [Ace系统] 执行拼刀阶段预设战术: {best_plan.description}")
    else:
        planner = AceTacticalPlanner(ace_mech, game_state)
        best_plan = planner.generate_best_plan()
        log.extend(planner.log)

    log.append(f"> [Ace执行] 意图: {best_plan.intent} | 时机: {best_plan.timing}")

    # 3. 应用时机和姿态
    ace_mech.timing = best_plan.timing
    ace_mech.stance = best_plan.stance

    # 4. 执行调整
    if best_plan.tp_action:
        type_, pos, ori = best_plan.tp_action
        if type_ == 'move':
            ace_mech.last_pos = ace_mech.pos
            ace_mech.pos = pos
            ace_mech.orientation = ori
            ace_mech.player_tp -= 1
            log.append(f"> [Ace] 战术机动 -> {pos}")

    # 5. 执行主动作序列
    for (action, slot, target) in best_plan.action_sequence:
        cost_ap, cost_tp = _get_action_cost(action)
        if ace_mech.player_ap < cost_ap or ace_mech.player_tp < cost_tp:
            log.append(f"> [Ace错误] 计划执行中断: 资源不足 ({action.name})")
            break

        ace_mech.player_ap -= cost_ap
        ace_mech.player_tp -= cost_tp
        ace_mech.actions_used_this_turn.append((slot, action.name))

        if action.action_type == '移动':
            if isinstance(target, tuple):
                ace_mech.last_pos = ace_mech.pos
                ace_mech.pos = target
                log.append(f"> [Ace] 移动 -> {target}")
                player_mech = game_state.get_player_mech()
                if player_mech:
                    ace_mech.orientation = _get_orientation_to_target(ace_mech.pos, player_mech.pos)

        elif action.action_type == '抛射':
            _execute_projectile_launch(ace_mech, action, slot, target, game_state, log, attacks_to_resolve_list)

        else:
            attacks_to_resolve_list.append({
                'attacker': ace_mech,
                'defender': target,
                'action': action
            })
            _consume_ammo(ace_mech, action, slot, game_state)

    # 6. 填补逻辑 (Filler Logic)
    safety_counter = 0
    while ace_mech.player_ap > 0 and safety_counter < 5:
        safety_counter += 1
        extra = _find_extra_filler_action(ace_mech, game_state)

        if extra:
            action, slot = extra
            log.append(f"> [Ace连携] 剩余AP追击: {action.name}")
            ace_mech.player_ap -= 1
            ace_mech.actions_used_this_turn.append((slot, action.name))

            if action.action_type == '抛射':
                _execute_projectile_launch(ace_mech, action, slot, game_state.get_player_mech(), game_state, log,
                                           attacks_to_resolve_list)
            elif action.action_type == '移动':
                pass
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

        target_pos = target.pos if hasattr(target, 'pos') else mech.pos

        for _ in range(count):
            pid, pobj = game_state.spawn_projectile(mech, target_pos, action.projectile_to_spawn)
            from .game_logic import run_projectile_logic
            plog, pattacks = run_projectile_logic(pobj, game_state, '立即')
            log.extend(plog)
            attacks_list.extend(pattacks)


def _consume_ammo(mech, action, slot, game_state):
    if action.ammo > 0:
        key = (mech.id, slot, action.name)
        if game_state.ammo_counts.get(key, 0) > 0:
            game_state.ammo_counts[key] -= 1


def _find_extra_filler_action(mech, game_state):
    player = game_state.get_player_mech()
    if not player: return None

    candidates = []
    for slot, part in mech.parts.items():
        if part and part.status != 'destroyed':
            for action in part.actions:
                if (slot, action.name) in mech.actions_used_this_turn: continue
                if action.cost != 'S': continue

                if action.ammo > 0:
                    key = (mech.id, slot, action.name)
                    if game_state.ammo_counts.get(key, 0) <= 0: continue

                valid_targets = _calculate_ai_attack_range(
                    game_state, mech, action, mech.pos, mech.orientation, player.pos
                )
                if valid_targets:
                    candidates.append((action, slot))

    if candidates:
        return max(candidates, key=lambda x: _evaluate_action_strength(x[0], 1, True))

    return None