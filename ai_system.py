import random
import heapq
import re
from game_logic import (
    is_in_forward_arc, get_ai_lock_status, _is_adjacent, _is_tile_locked_by_opponent,
    _get_distance
)


# --- AI 评估辅助函数 ---

def _parse_dice_string_for_eval(dice_str):
    """(辅助函数) 解析骰子字符串，返回黄红计数。"""
    yellow, red = 0, 0
    if not dice_str: return 0, 0
    match_y = re.search(r'(\d+)\s*黄', dice_str)
    match_r = re.search(r'(\d+)\s*红', dice_str)
    if match_y: yellow = int(match_y.group(1))
    if match_r: red = int(match_r.group(1))
    return yellow, red


def _evaluate_action_strength(action, available_s_action_count, is_in_range):
    """
    [v2 修改]
    根据骰子、成本、射程和效果，评估一个攻击动作的相对强度。
    使用期望值 (EV) 代替任意权重。
    假设处于“攻击姿态”（空心=命中）。
    """
    if not action: return 0
    if action.action_type not in ['近战', '射击']: return 0

    yellow, red = _parse_dice_string_for_eval(action.dice)

    # --- 期望值计算 (假设攻击姿态) ---
    # 黄骰: 8面, 2x[轻*2], 2x[轻*1], 1x[空心轻*1], 1x[闪电], 1x[眼], 1x[空]
    # EV(黄) = (2*2 + 2*1 + 1*1) / 8 = 7/8 = 0.875
    ev_yellow = yellow * 0.875

    # 红骰: 8面, 4x[重*1], 1x[空心重*1], 1x[空心轻*1], 1x[闪电], 1x[眼]
    # EV(红) = (4*1.5 + 1*1.5) / 8 [重击] + (1*1.0) / 8 [轻击]
    # EV(红) = (7.5 + 1) / 8 = 8.5 / 8 = 1.0625
    # (我们给重击 1.5 权重, 轻击 1.0 权重)
    ev_red = red * ((5 / 8 * 1.5) + (1 / 8 * 1.0))  # 1.0625

    strength = ev_yellow + ev_red

    # 检查【频闪武器】(闪电->重击)
    if action.effects and action.effects.get("convert_lightning_to_crit"):
        # 1/8 概率的闪电现在变成了重击 (1.5 权重)
        # 黄骰 EV 增加: (1/8 * 1.5) = 0.1875
        strength += yellow * (1 / 8 * 1.5)
        # 红骰 EV 增加: (1/8 * 1.5) - (1/8 * 1.0) (替换掉原来的轻击权重)
        # 不对，红骰的闪电没有替换轻击，是独立的。
        # 红骰 EV 增加: (1/8 * 1.5) = 0.1875
        strength += red * (1 / 8 * 1.5)

    # --- 成本和效果调整 ---
    if action.cost == 'S':
        strength *= 1.2  # S动作更灵活
        # 如果这是最后一个S动作，价值降低
        if available_s_action_count == 1:
            strength *= 0.7
    elif action.cost == 'L':
        strength *= 0.8  # L动作成本高
        if is_in_range:
            strength *= 1.5  # 如果在射程内，L动作很有价值

    if action.effects:
        # 穿甲 (AP)
        ap_bonus = action.effects.get("armor_piercing", 0) * 0.5  # 每次穿甲增加 0.5 强度
        strength += ap_bonus
        # 毁伤/霰射/顺劈 (增加额外伤害的潜力)
        if action.effects.get("devastating", False):
            strength += 1.0
        if action.effects.get("scattershot", False):
            strength += 0.8
        if action.effects.get("cleave", False):
            strength += 0.8
        # “双手”效果的评估
        if action.effects.get("two_handed_devastating", False):
            strength += 1.0  # 假设它能触发
        if action.effects.get("two_handed_sniper", False):
            strength += 0.5  # 狙击效果

    return strength


# --- AI 动作成本辅助函数 ---
def _get_action_cost(action):
    """(辅助函数) 获取动作的 AP/TP 成本。"""
    cost_ap = action.cost.count('M') * 2 + action.cost.count('S') * 1
    cost_tp = 0
    if action.cost == 'L':
        cost_ap = 2
        cost_tp = 1
    return cost_ap, cost_tp


# --- AI 辅助函数 ---

def _get_orientation_to_target(start_pos, target_pos):
    """计算朝向目标的最佳方向。"""
    dx = target_pos[0] - start_pos[0]
    dy = target_pos[1] - start_pos[1]

    if abs(dx) > abs(dy):
        return 'E' if dx > 0 else 'W'
    else:
        return 'S' if dy > 0 else 'N'


def _calculate_ai_attack_range(game, action, start_pos, orientation, target_pos, current_tp=0):
    """
    模拟计算AI在特定位置和朝向下，能否攻击到目标。
    处理近战范围、射击视线和【静止】等效果。
    """
    targets = []
    sx, sy = start_pos
    tx, ty = target_pos

    is_valid_target = False

    if action.action_type == '近战':
        valid_melee_cells = []
        if orientation == 'N':
            valid_melee_cells = [(sx, sy - 1), (sx - 1, sy - 1), (sx + 1, sy - 1)]
        elif orientation == 'S':
            valid_melee_cells = [(sx, sy + 1), (sx - 1, sy + 1), (sx + 1, sy + 1)]
        elif orientation == 'E':
            valid_melee_cells = [(sx + 1, sy), (sx + 1, sy - 1), (sx + 1, sy + 1)]
        elif orientation == 'W':
            valid_melee_cells = [(sx - 1, sy), (sx - 1, sy - 1), (sx - 1, sy + 1)]
        is_valid_target = (target_pos in valid_melee_cells)

    elif action.action_type == '射击':
        # 1. 检查视线
        if not is_in_forward_arc(start_pos, orientation, target_pos):
            return []

        # 2. 计算最终射程
        final_range = action.range_val
        if action.effects:
            # 检查【静止】
            static_bonus = action.effects.get("static_range_bonus", 0)
            if static_bonus > 0 and current_tp >= 1:  # 必须有TP才能触发
                final_range += static_bonus

            # 检查【双手】
            two_handed_bonus = action.effects.get("two_handed_range_bonus", 0)
            if two_handed_bonus > 0:
                attacker_mech = game.ai_mech
                # 找到这个动作来自哪个部件
                part_slot_of_action = None
                for slot, part in attacker_mech.parts.items():
                    if part and part.status != 'destroyed' and any(a.name == action.name for a in part.actions):
                        part_slot_of_action = slot
                        break

                other_arm_part = None
                if part_slot_of_action == 'left_arm':
                    other_arm_part = attacker_mech.parts.get('right_arm')
                elif part_slot_of_action == 'right_arm':
                    other_arm_part = attacker_mech.parts.get('left_arm')

                # 检查另一只手是否有【空手】标签
                if other_arm_part and other_arm_part.status != 'destroyed' and "【空手】" in other_arm_part.tags:
                    final_range += two_handed_bonus

        # 3. 检查距离
        dist = _get_distance(start_pos, target_pos)
        is_valid_target = (dist <= final_range)

    if is_valid_target:
        targets.append({'pos': target_pos})
    return targets


# --- [性能重构] ---

def _find_all_reachable_positions(game):
    """
    [性能核心]
    在AI回合开始时运行一次，使用 Dijkstra 算法计算到所有格子的最小成本。
    返回一个字典: {(x, y): cost}
    """
    start_pos = game.ai_pos
    locker_mech = game.player_mech
    locker_pos = game.player_pos
    locker_can_lock = (locker_mech and locker_mech.has_melee_action() and
                       locker_mech.parts.get('core') and locker_mech.parts['core'].status != 'destroyed')

    pq = [(0, start_pos)]  # (cost, pos)
    visited = {start_pos: 0}  # {pos: cost}

    while pq:
        cost, (x, y) = heapq.heappop(pq)

        current_pos = (x, y)

        # --- 探索邻居 ---
        current_is_locked = False
        if locker_can_lock:
            current_is_locked = _is_tile_locked_by_opponent(
                game, current_pos, game.ai_mech, locker_pos, locker_mech
            )

        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            nx, ny = x + dx, y + dy
            next_pos = (nx, ny)

            # 检查边界
            if not (1 <= nx <= game.board_width and 1 <= ny <= game.board_height):
                continue
            # 路径不能穿过玩家
            if next_pos == game.player_pos:
                continue

            move_cost = 1
            if current_is_locked:
                move_cost += 1  # 脱离成本
            new_cost = cost + move_cost

            # 注意：这里不检查 move_distance，我们计算所有可能的路径
            if next_pos not in visited or new_cost < visited[next_pos]:
                visited[next_pos] = new_cost
                heapq.heappush(pq, (new_cost, next_pos))

    return visited  # 返回所有已访问点及其成本


def _find_best_move_position(game, move_distance, ideal_range_min, ideal_range_max, goal, all_reachable_costs):
    """
    [性能重构]
    不再执行寻路。而是快速迭代预先计算的 all_reachable_costs 字典。
    """
    target_pos = game.player_pos

    # 筛选出所有在 move_distance 内可达的格子
    valid_moves = []
    for pos, cost in all_reachable_costs.items():
        if cost <= move_distance:
            valid_moves.append(pos)

    if not valid_moves:
        return None  # 无法移动

    best_spot = None

    if goal == 'closest':
        # 目标：找到距离玩家最近的点
        min_dist_found = float('inf')
        min_cost_found = float('inf')
        for pos in valid_moves:
            dist = _get_distance(pos, target_pos)
            cost = all_reachable_costs[pos]
            if dist < min_dist_found:
                min_dist_found = dist
                min_cost_found = cost
                best_spot = pos
            elif dist == min_dist_found:
                if cost < min_cost_found:  # 距离相同时，选成本更低的
                    min_cost_found = cost
                    best_spot = pos
        return best_spot

    # 筛选出在理想射程内的点
    moves_in_range = []
    for pos in valid_moves:
        dist = _get_distance(pos, target_pos)
        if ideal_range_min <= dist <= ideal_range_max:
            moves_in_range.append(pos)

    if not moves_in_range:
        return None  # 没有在理想射程内的点

    if goal == 'ideal':
        # 目标：找到最接近理想距离中点，且成本最低的点
        ideal_mid = (ideal_range_min + ideal_range_max) / 2
        best_spot = min(moves_in_range, key=lambda pos: (
            abs(_get_distance(pos, target_pos) - ideal_mid),  # 优先：最接近中点
            all_reachable_costs[pos]  # 其次：成本最低
        ))
    elif goal == 'farthest_in_range':
        # 目标：找到距离玩家最远，且成本最低的点
        best_spot = max(moves_in_range, key=lambda pos: (
            _get_distance(pos, target_pos),  # 优先：距离最远
            -all_reachable_costs[pos]  # 其次：成本最低 (用负号来反转)
        ))

    return best_spot


def _find_farthest_move_position(game, move_distance, all_reachable_costs):
    """
    [性能重构]
    不再执行寻路。而是快速迭代预先计算的 all_reachable_costs 字典。
    """
    target_pos = game.player_pos

    # 筛选出所有在 move_distance 内且 *不是* 起始点的格子
    valid_moves = []
    for pos, cost in all_reachable_costs.items():
        if 0 < cost <= move_distance:  # 成本必须 > 0 (即必须移动)
            valid_moves.append(pos)

    if not valid_moves:
        return None

        # 找到距离玩家最远的位置
    farthest_pos = max(valid_moves, key=lambda pos: (
        _get_distance(pos, target_pos),  # 优先：距离最远
        -all_reachable_costs[pos]  # 其次：成本最低
    ))
    return farthest_pos


# --- AI 主逻辑 ---

def run_ai_turn(game):
    """
    AI回合的决策主函数。
    [性能重构] 现已优化为在回合开始时只寻路一次。
    [v2] 使用期望伤害评估。
    [v3] 狙击手AI会主动拉开距离。
    [v4] 修复了【静止】动作的TP消耗Bug。
    """
    log = []
    ap = 2
    tp = 1
    game.ai_actions_used_this_turn = []
    attacks_to_resolve_list = []

    # --- [性能核心] ---
    # 在回合开始时，计算一次所有可达路径。
    all_reachable_costs = _find_all_reachable_positions(game)
    # ---

    # --- 阶段 0: 状态分析 ---
    is_ai_locked = get_ai_lock_status(game)[0]
    if is_ai_locked: log.append("> AI 被玩家近战锁定！")

    total_evasion = game.ai_mech.get_total_evasion()
    log.append(f"> AI 总闪避值: {total_evasion}")

    # 检查关键部件损坏
    core_damaged = game.ai_mech.parts.get('core') and game.ai_mech.parts['core'].status == 'damaged'
    legs_part = game.ai_mech.parts.get('legs')
    legs_damaged = legs_part and legs_part.status == 'damaged'
    is_damaged = core_damaged or legs_damaged
    if is_damaged:
        log.append("> AI 关键部件 (核心或腿部) 已受损。")

    is_player_adjacent = _is_adjacent(game.ai_pos, game.player_pos)
    player_core = game.player_mech.parts.get('core')
    player_is_damaged = player_core and player_core.status == 'damaged'
    if player_is_damaged:
        log.append("> [AI 侦测] 玩家核心受损！")

    # 0a. 获取所有可用动作
    all_actions_raw = game.ai_mech.get_all_actions()
    available_actions = []
    for action, part_slot in all_actions_raw:
        action_id = (part_slot, action.name)
        if action_id not in game.ai_actions_used_this_turn:
            part_obj = game.ai_mech.parts.get(part_slot)
            if part_obj and part_obj.status != 'destroyed':
                available_actions.append((action, part_slot))

    # 0b. 模拟分析：如果我现在转向目标，我能用什么？
    sim_orientation = _get_orientation_to_target(game.ai_pos, game.player_pos)
    available_s_actions_count = sum(1 for a, s in available_actions if a.cost == 'S')

    # 计算当前位置可用的最佳 近战/射击 动作 (S, M)
    melee_actions_now = [
        (a, slot) for (a, slot) in available_actions if
        a.action_type == '近战' and _calculate_ai_attack_range(game, a, game.ai_pos, sim_orientation,
                                                               game.player_pos, current_tp=tp)
    ]
    shoot_actions_now = [
        (a, slot) for (a, slot) in available_actions if
        a.action_type == '射击' and _calculate_ai_attack_range(game, a, game.ai_pos, sim_orientation,
                                                               game.player_pos, current_tp=tp) and not is_ai_locked
    ]
    best_melee_tuple = max(
        melee_actions_now,
        key=lambda item: _evaluate_action_strength(item[0], available_s_actions_count, is_in_range=True),
        default=None
    )
    best_shoot_tuple = max(
        shoot_actions_now,
        key=lambda item: _evaluate_action_strength(item[0], available_s_actions_count, is_in_range=True),
        default=None
    )

    # 检查是否有更强的 L 动作 (即使当前不在射程内)
    best_l_melee_tuple = max(
        [(a, slot) for (a, slot) in available_actions if a.action_type == '近战' and a.cost == 'L'],
        key=lambda item: _evaluate_action_strength(item[0], available_s_actions_count,
                                                   is_in_range=bool(melee_actions_now)),
        default=None
    )
    best_l_shoot_tuple = max(
        [(a, slot) for (a, slot) in available_actions if a.action_type == '射击' and a.cost == 'L'],
        key=lambda item: _evaluate_action_strength(item[0], available_s_actions_count,
                                                   is_in_range=bool(shoot_actions_now)),
        default=None
    )

    # [v2 修复] 确保在比较前处理 None
    current_best_melee_strength = _evaluate_action_strength(best_melee_tuple[0] if best_melee_tuple else None,
                                                            available_s_actions_count, True)
    l_melee_strength = _evaluate_action_strength(best_l_melee_tuple[0] if best_l_melee_tuple else None,
                                                 available_s_actions_count, bool(melee_actions_now))

    if (l_melee_strength or 0) > (current_best_melee_strength or 0):
        best_melee_tuple = best_l_melee_tuple  # L 动作更强，设为首选

    current_best_shoot_strength = _evaluate_action_strength(best_shoot_tuple[0] if best_shoot_tuple else None,
                                                            available_s_actions_count, True)
    l_shoot_strength = _evaluate_action_strength(best_l_shoot_tuple[0] if best_l_shoot_tuple else None,
                                                 available_s_actions_count, bool(shoot_actions_now))

    if (l_shoot_strength or 0) > (current_best_shoot_strength or 0):
        best_shoot_tuple = best_l_shoot_tuple  # L 动作更强，设为首选

    # 最终的最佳强度
    best_melee_strength = _evaluate_action_strength(best_melee_tuple[0] if best_melee_tuple else None,
                                                    available_s_actions_count,
                                                    bool(melee_actions_now or best_melee_tuple))
    best_shoot_strength = _evaluate_action_strength(best_shoot_tuple[0] if best_shoot_tuple else None,
                                                    available_s_actions_count,
                                                    bool(shoot_actions_now or best_shoot_tuple))

    # 0c. 决定人格和时机
    ai_personality = 'brawler'
    if (best_shoot_strength or 0) > (best_melee_strength or 0):
        ai_personality = 'sniper'

    melee_actions = sorted(
        melee_actions_now,
        key=lambda item: _evaluate_action_strength(item[0], available_s_actions_count, is_in_range=True),
        reverse=True
    )
    shoot_actions = sorted(
        shoot_actions_now,
        key=lambda item: _evaluate_action_strength(item[0], available_s_actions_count, is_in_range=True),
        reverse=True
    )
    move_action_tuple = next(((a, slot) for (a, slot) in available_actions if a.action_type == '移动'), None)

    timing = '移动'  # 默认时机
    stance = 'agile'  # 默认姿态
    best_attack_action_tuple = None
    is_in_attack_range = bool(melee_actions) or bool(shoot_actions)

    # --- [v3 狙击手逻辑修改] ---
    # 检查狙击手是否处于不良位置 (被锁定或太近)
    sniper_is_in_bad_spot = False
    if ai_personality == 'sniper':
        current_dist_to_player = _get_distance(game.ai_pos, game.player_pos)
        # 阈值 3: 距离 1, 2 都算太近
        if is_ai_locked or current_dist_to_player < 3:
            sniper_is_in_bad_spot = True
            log.append(f"> AI (狙击手) 处于不良位置 (锁定: {is_ai_locked} / 距离: {current_dist_to_player})。")
    # --- [v3 修改结束] ---

    if ai_personality == 'brawler':
        # 格斗者：优先近战
        if melee_actions or (best_melee_tuple and best_melee_tuple[0].cost == 'L'):
            timing = '近战'
            stance = 'attack'
            best_attack_action_tuple = best_melee_tuple
        else:
            timing = '移动'
            stance = 'agile'
    elif ai_personality == 'sniper':
        # [v3 修改] 如果处于不良位置，强制“移动”时机
        if sniper_is_in_bad_spot:
            timing = '移动'
            stance = 'agile'  # 确保是机动姿态来逃跑
            log.append("> [AI 狙击手] 优先选择 [移动] 时机来拉开距离。")
        # 狙击手：优先射击
        elif shoot_actions or (best_shoot_tuple and best_shoot_tuple[0].cost == 'L'):
            timing = '射击'
            stance = 'attack'
            best_attack_action_tuple = best_shoot_tuple
        else:
            timing = '移动'
            stance = 'agile'

    log.append(f"> AI ({ai_personality}) 选择了时机: [{timing}]。")

    # 0d. 修正姿态
    if player_is_damaged and is_in_attack_range:
        # 如果玩家已受损且在射程内，不顾一切地进攻
        stance = 'attack'
        log.append("> AI 侦测到玩家受损且在射程内，强制切换到 [攻击] 姿态！")
    elif is_ai_locked and not is_in_attack_range:
        # 如果被锁定且无法反击，保命
        stance = 'agile' if total_evasion > 5 else 'defense'
        log.append(f"> AI 被锁定且无法反击，切换到 [{stance}] 姿态。")
    elif is_damaged and is_player_adjacent:
        # 如果自己受损且玩家逼近，保命
        stance = 'agile' if total_evasion > 5 else 'defense'
        log.append(f"> AI 受损且玩家逼近，切换到 [{stance}] 姿态。")
    elif stance == 'attack' and total_evasion > 5:
        # 如果AI闪避很高，没必要用攻击姿态（除非是为了L动作）
        if not (best_attack_action_tuple and best_attack_action_tuple[0].cost == 'L'):
            stance = 'agile'
            log.append(f"> AI 闪避值 ({total_evasion}) > 5，倾向于 [机动] 姿态。")
    elif timing == '移动' and stance != 'defense':
        # 如果计划移动，用机动姿态
        stance = 'agile'
        log.append("> AI 计划移动，切换到 [机动] 姿态。")

    # --- 阶段 2: 切换姿态 ---
    game.ai_mech.stance = stance
    log.append(f"> AI 切换姿态至: [{game.ai_mech.stance}]。")

    # --- 阶段 2.5: 调整移动 "预演" (TP) ---
    adjust_move_val = 0
    if legs_part and legs_part.status != 'destroyed':
        adjust_move_val = legs_part.adjust_move
        if stance == 'agile':
            adjust_move_val *= 2

    potential_adjust_move_pos = None
    potential_attack_timing = timing  # 攻击时机可能因调整移动而改变

    if tp >= 1 and adjust_move_val > 0:
        log.append(f"> AI 正在评估 (TP) 调整移动... (范围: {adjust_move_val})")

        is_in_range_now = is_in_attack_range

        # 检查是否可以通过TP移动来发动 S/M 攻击
        if not potential_adjust_move_pos:
            log.append(f"> AI 正在评估 '接近/定位' 移动...")

            # 评估近战
            potential_melee_target = max(
                [(a, slot) for (a, slot) in available_actions if a.action_type == '近战' and a.cost != 'L'],
                key=lambda item: _evaluate_action_strength(item[0], available_s_actions_count, False), default=None
            )
            if potential_melee_target:
                # [性能重构] 传入 all_reachable_costs
                ideal_pos_melee = _find_best_move_position(game, adjust_move_val, 1, 1, 'ideal', all_reachable_costs)
                if ideal_pos_melee:
                    potential_adjust_move_pos = ideal_pos_melee
                    potential_attack_timing = '近战'
                    log.append(f"> AI 发现可以通过调整移动到 {ideal_pos_melee} 来发动近战。")

            # [v3 修改] 狙击手 TP 移动逻辑
            if not potential_adjust_move_pos and not is_ai_locked:
                potential_shoot_target = max(
                    [(a, slot) for (a, slot) in available_actions if a.action_type == '射击' and a.cost != 'L'],
                    key=lambda item: _evaluate_action_strength(item[0], available_s_actions_count, False), default=None
                )
                if potential_shoot_target:
                    # 检查是否太近
                    current_dist = _get_distance(game.ai_pos, game.player_pos)
                    if ai_personality == 'sniper' and current_dist < 3:
                        log.append("> AI (狙击手) 尝试使用 TP 拉开距离...")
                        # 尝试移动到理想范围的 *最远* 点
                        ideal_pos_shoot = _find_best_move_position(game, adjust_move_val, 5, 8, 'farthest_in_range',
                                                                   all_reachable_costs)
                    else:
                        # 正常寻找理想位置
                        ideal_range_min_shoot, ideal_range_max_shoot = (5, 8) if ai_personality == 'sniper' else (2, 5)
                        ideal_pos_shoot = _find_best_move_position(game, adjust_move_val, ideal_range_min_shoot,
                                                                   ideal_range_max_shoot, 'ideal', all_reachable_costs)

                    if ideal_pos_shoot:
                        potential_adjust_move_pos = ideal_pos_shoot
                        potential_attack_timing = '射击'
                        log.append(f"> AI 发现可以通过调整移动到 {ideal_pos_shoot} 来发动射击。")

            if not potential_adjust_move_pos:
                log.append(f"> AI 未找到合适的 (TP) 调整移动位置 (或需为 L 动作保留 TP)。")

    # --- 阶段 3: 调整动作 (TP) ---
    if potential_adjust_move_pos and potential_adjust_move_pos != game.ai_pos:  # [BUG 修复] 增加检查，不要在原地"移动"
        log.append(f"> AI 决定执行调整移动！")
        game.ai_pos = potential_adjust_move_pos
        game.last_ai_pos = game.ai_pos  # [新增] 记录移动前的位置
        tp -= 1
        # 如果调整移动是为了攻击，更新时机
        if timing != potential_attack_timing:
            log.append(f"> AI 将时机从 [{timing}] 更改为 [{potential_attack_timing}]！")
            timing = potential_attack_timing
        # 调整移动后自动转向
        target_orientation = _get_orientation_to_target(game.ai_pos, game.player_pos)
        if game.ai_mech.orientation != target_orientation:
            log.append(f"> AI 调整移动后立即转向 {target_orientation}。")
            game.ai_mech.orientation = target_orientation
    else:
        # 如果不移动，检查是否需要转向
        target_orientation = _get_orientation_to_target(game.ai_pos, game.player_pos)
        if game.ai_mech.orientation != target_orientation and tp >= 1:

            # [BUG 修复 v4] 检查TP是否是射击所必需的
            tp_needed_for_shot = False
            if timing == '射击' and best_shoot_tuple:
                action_obj = best_shoot_tuple[0]
                if action_obj and action_obj.effects.get("static_range_bonus", 0) > 0:
                    # 检查是否 *没有* 这个TP加成就会射程不足
                    base_range = action_obj.range_val
                    dist = _get_distance(game.ai_pos, game.player_pos)
                    if dist > base_range:
                        tp_needed_for_shot = True
                        log.append(f"> AI 侦测到 TP 必须用于 [{action_obj.name}] 的【静止】射程加成。")

            if tp_needed_for_shot:
                log.append(f"> AI 决定保留 TP 用于射击，本回合放弃转向。")
            else:
                log.append(f"> AI 消耗1 TP进行转向, 朝向从 {game.ai_mech.orientation} 变为 {target_orientation}。")
                game.ai_mech.orientation = target_orientation
                tp -= 1

    # --- 阶段 4: 主要动作 (AP) 循环 ---
    opening_move_taken = False
    while ap > 0:
        # 4a. 刷新当前可用动作列表
        current_available_actions_tuples = []
        for action, part_slot in all_actions_raw:
            action_id = (part_slot, action.name)
            if action_id not in game.ai_actions_used_this_turn:
                part_obj = game.ai_mech.parts.get(part_slot)
                if part_obj and part_obj.status != 'destroyed':
                    current_available_actions_tuples.append((action, part_slot))

        if not current_available_actions_tuples:
            log.append("> AI 已无可用动作。")
            break  # AP > 0 但没有动作了

        current_available_s_count = sum(1 for a, s in current_available_actions_tuples if a.cost == 'S')
        current_orientation = game.ai_mech.orientation
        is_ai_locked_now = get_ai_lock_status(game)[0]

        # 4b. 评估当前位置所有可执行的动作
        possible_now_melee = sorted(
            [(a, slot) for (a, slot) in current_available_actions_tuples if
             a.action_type == '近战' and _calculate_ai_attack_range(game, a, game.ai_pos, current_orientation,
                                                                    game.player_pos, current_tp=tp)],
            key=lambda item: _evaluate_action_strength(item[0], current_available_s_count, is_in_range=True),
            reverse=True
        )
        possible_now_shoot = sorted(
            [(a, slot) for (a, slot) in current_available_actions_tuples if
             a.action_type == '射击' and _calculate_ai_attack_range(game, a, game.ai_pos, current_orientation,
                                                                    game.player_pos,
                                                                    current_tp=tp) and not is_ai_locked_now],
            key=lambda item: _evaluate_action_strength(item[0], current_available_s_count, is_in_range=True),
            reverse=True
        )
        possible_now_move = sorted(
            [(a, slot) for (a, slot) in current_available_actions_tuples if a.action_type == '移动'],
            key=lambda item: item[0].range_val, reverse=True
        )

        action_to_perform_tuple = None
        action_log_prefix = ""

        # --- 4c. 决策：执行什么动作？ ---

        if not opening_move_taken:
            # --- 4c-1. 寻找起手动作 ---
            action_log_prefix = "起手动作"
            log.append(f"> AI 正在寻找时机为 [{timing}] 的起手动作...")

            # 1. 收集所有符合时机的潜在起手动作
            potential_openers = []
            if timing == '近战':
                potential_openers.extend(possible_now_melee)  # S/M 动作
                if best_melee_tuple and best_melee_tuple[0].cost == 'L':  # L 动作
                    potential_openers.append(best_melee_tuple)
            elif timing == '射击':
                potential_openers.extend(possible_now_shoot)  # S/M 动作
                if best_shoot_tuple and best_shoot_tuple[0].cost == 'L':  # L 动作
                    potential_openers.append(best_shoot_tuple)
            elif timing == '移动':
                potential_openers.extend(possible_now_move)

            # 2. 筛选出当前 AP/TP 负担得起的动作
            affordable_openers = []
            for (action, slot) in potential_openers:
                cost_ap_check, cost_tp_check = _get_action_cost(action)
                if ap >= cost_ap_check and tp >= cost_tp_check:
                    affordable_openers.append((action, slot))

            # 3. 从负担得起的动作中，选择最强/最好的一个
            if affordable_openers:
                if timing == '移动':
                    # 如果是移动时机，优先选距离最远的移动
                    action_to_perform_tuple = max(
                        affordable_openers,
                        key=lambda item: item[0].range_val
                    )
                else:
                    # 如果是攻击时机，选伤害期望最高的
                    action_to_perform_tuple = max(
                        affordable_openers,
                        key=lambda item: _evaluate_action_strength(item[0], current_available_s_count, True)
                    )
            else:
                action_to_perform_tuple = None  # 找不到负担得起的起手动作

            if not action_to_perform_tuple:
                log.append(f"> AI 无法找到或负担得起时机为 [{timing}] 的起手动作！回合结束。")
                break  # 退出 while ap > 0 循环

        else:
            # --- 4c-2. 寻找额外动作 (非起手) ---
            action_log_prefix = "额外动作"
            log.append(f"> AI 尚有 {ap}AP {tp}TP，正在寻找额外动作...")

            # 汇集所有当前可用的 S/M 动作
            all_possible_now = possible_now_melee + possible_now_shoot + possible_now_move
            valid_extra_actions = []
            for (action, slot) in all_possible_now:
                cost_ap_check, cost_tp_check = _get_action_cost(action)
                if ap >= cost_ap_check and tp >= cost_tp_check:
                    # [修复] 额外动作不能是 L 动作
                    if action.cost != 'L':
                        valid_extra_actions.append((action, slot))

            if not valid_extra_actions:
                log.append("> AI 无成本足够的额外动作。")
                break

            # 优先攻击，其次移动
            action_to_perform_tuple = max(
                valid_extra_actions,
                key=lambda item: _evaluate_action_strength(item[0], current_available_s_count, True) if item[
                                                                                                            0].action_type in [
                                                                                                            '近战',
                                                                                                            '射击']
                else (0.5 if item[0].action_type == '移动' else 0),  # 移动给一个很低的基础分
                default=None
            )

        if not action_to_perform_tuple:
            log.append(f"> AI 找不到可执行的 {action_log_prefix}。")
            break  # 找不到额外动作

        # --- 4d. 执行动作 ---
        (action_obj, action_slot) = action_to_perform_tuple
        cost_ap, cost_tp_action = _get_action_cost(action_obj)

        # (安全防护：如果成本检查失败)
        if ap < cost_ap or tp < cost_tp_action:
            log.append(
                f"> [成本检查失败] AI 试图执行 [{action_obj.name}] (需 {cost_ap}AP {cost_tp_action}TP) 但只有 ( {ap}AP {tp}TP)。")
            # 标记为已用，防止无限循环
            game.ai_actions_used_this_turn.append((action_slot, action_obj.name))
            if not opening_move_taken:
                log.append("> AI 无法执行起手动作，回合结束。")
                break
            else:
                continue  # 只是这个额外动作失败了，继续寻找下一个

        # --- 确认执行动作 ---
        log.append(
            f"> AI 执行 [{action_log_prefix}] [{action_obj.name}] (来自 {action_slot}, 消耗 {cost_ap}AP, {cost_tp_action}TP)。")

        # 消耗资源
        action_id = (action_slot, action_obj.name)
        game.ai_actions_used_this_turn.append(action_id)
        ap -= cost_ap
        tp -= cost_tp_action
        opening_move_taken = True  # [v2 修复] 移到外面

        # 按类型处理
        if action_obj.action_type == '移动':
            log.append(f"> AI 正在为 [{action_obj.name}] 寻找移动目标...")
            move_target_pos = None
            move_distance_val = action_obj.range_val
            current_dist_to_player = _get_distance(game.ai_pos, game.player_pos)

            # 根据人格决定移动目标
            if ai_personality == 'brawler':
                # 格斗者：冲锋
                # [性能重构] 传入 all_reachable_costs
                move_target_pos = _find_best_move_position(game, move_distance_val, 1, 1, 'closest',
                                                           all_reachable_costs)
            else:  # 狙击手
                if is_ai_locked_now:
                    log.append("> AI (狙击手) 被锁定，尝试逃离！")
                    # [性能重构] 传入 all_reachable_costs
                    move_target_pos = _find_farthest_move_position(game, move_distance_val, all_reachable_costs)
                elif current_dist_to_player < 5:
                    log.append("> AI (狙击手) 距离过近，尝试拉开距离...")
                    # [性能重构] 传入 all_reachable_costs
                    move_target_pos = _find_best_move_position(game, move_distance_val, 5, 8, 'farthest_in_range',
                                                               all_reachable_costs)
                else:
                    log.append("> AI (狙击手) 尝试寻找理想射击位置...")
                    # [性能重构] 传入 all_reachable_costs
                    move_target_pos = _find_best_move_position(game, move_distance_val, 5, 8, 'ideal',
                                                               all_reachable_costs)

            # 如果主要目标失败，寻找任意移动点
            if not move_target_pos:
                log.append("> AI 未找到理想移动位置，尝试寻找任意可移动位置...")
                # [性能重构] 传入 all_reachable_costs
                move_target_pos = _find_best_move_position(game, move_distance_val, 0,
                                                           game.board_width + game.board_height, 'closest',
                                                           all_reachable_costs)

            # 执行移动
            if move_target_pos and move_target_pos != game.ai_pos:
                game.last_ai_pos = game.ai_pos  # [新增] 记录移动前的位置
                game.ai_pos = move_target_pos
                log.append(f"> AI 移动到 {game.ai_pos}。")
                # 移动后自动转向
                target_orientation = _get_orientation_to_target(game.ai_pos, game.player_pos)
                if game.ai_mech.orientation != target_orientation:
                    game.ai_mech.orientation = target_orientation
                    log.append(f"> AI 移动后转向 {target_orientation}。")
            else:
                log.append(f"> AI 未找到合适的移动位置，动作 [{action_obj.name}] 被跳过。")

        elif action_obj.action_type in ['近战', '射击']:
            # [v2 修复] 将攻击动作加入队列
            attacks_to_resolve_list.append(action_obj)

        if ap == 0:
            log.append("> AI 已耗尽 AP。")
            break
        elif action_obj.cost == 'S' and current_available_s_count <= 1:
            log.append("> AI 已执行唯一的 S 动作。")
            break  # 规则：一次激活只能执行一次短动作 (这里假设是 S)
            # TODO: 规则是 "一次激活只能执行一次短动作" 还是 "S 动作后只能再接 S 动作"？
            # 当前实现：S 动作后可以接 S 或 M (如果AP够)
            pass

    if not opening_move_taken and not attacks_to_resolve_list:
        log.append("> AI 结束回合，未执行任何主要动作。")

    return log, attacks_to_resolve_list

