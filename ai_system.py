import random
import heapq  # 导入 heapq 用于 A* 寻路
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
    根据骰子、成本和射程，评估一个攻击动作的相对强度。
    - available_s_action_count (int): AI本回合总共可用的S动作数量。
    """
    if not action: return 0
    if action.action_type not in ['近战', '射击']: return 0

    yellow, red = _parse_dice_string_for_eval(action.dice)

    # 红骰 (重击概率高) 权重设为 1.5，黄骰 (轻击概率高) 权重设为 1
    strength = (yellow * 1.0) + (red * 1.5)

    # L/M/S 成本调整 (S 动作更有价值，L 动作成本高)
    if action.cost == 'S':
        strength *= 1.2  # S 动作（1AP）更灵活
        # [新增 v1.5] 如果AI只有一个S动作，其价值降低
        if available_s_action_count == 1:
            strength *= 0.7  # 惩罚：单独的S动作不如组合S动作

    elif action.cost == 'L':
        strength *= 0.8  # L 动作（2AP+1TP）成本高
        # [新增 v1.5] 如果L动作已经在射程内，价值提高
        if is_in_range:
            strength *= 1.5  # 奖励：L动作已就位

    return strength


# --- [新增 v1.4] AI 动作成本辅助函数 ---
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
        if not is_in_forward_arc(start_pos, orientation, target_pos):
            return []

        # AI的动态射程计算
        final_range = action.range_val
        if action.effects:
            bonus = action.effects.get("static_range_bonus", 0)
            if bonus > 0 and current_tp >= 1:
                final_range += bonus

        dist = _get_distance(start_pos, target_pos)
        is_valid_target = (dist <= final_range)

    if is_valid_target:
        targets.append({'pos': target_pos})

    return targets


def _find_best_move_position(game, move_distance, ideal_range_min, ideal_range_max, goal='ideal', action_to_check=None,
                             current_tp=0):
    """
    使用 A* 寻路算法为 AI 寻找最佳移动位置。
    根据 'goal' (ideal, farthest_in_range, closest) 来确定最佳落点。
    会考虑近战锁定带来的额外移动成本。
    """
    start_pos = game.ai_pos
    target_pos = game.player_pos

    # 锁定者 (玩家)
    locker_mech = game.player_mech
    locker_pos = game.player_pos
    locker_can_lock = locker_mech.has_melee_action() and locker_mech.parts['core'].status != 'destroyed'

    pq = [(0, start_pos)]  # (cost, pos)
    visited = {start_pos: 0}  # {pos: cost}

    # 记录找到的最佳位置
    best_spot_in_range = None
    min_cost_in_range = float('inf')
    dist_from_ideal_mid = float('inf')
    dist_for_farthest = -1

    best_spot_closest = None  # [优化] 默认为 None，以便区分“没找到”和“起始点就是最佳”
    min_dist_found = _get_distance(start_pos, target_pos)

    # [优化] 如果起始点满足要求，将其设为默认的 best_spot_closest
    start_pos_action_valid = True
    if action_to_check:
        sim_orientation = _get_orientation_to_target(start_pos, target_pos)
        is_locked_at_start = _is_tile_locked_by_opponent(game, start_pos, game.ai_mech, locker_pos, locker_mech)
        if action_to_check.action_type == '射击' and is_locked_at_start:
            start_pos_action_valid = False
        else:
            start_pos_action_valid = bool(
                # [修改] 传入 current_tp (代表AI不动时的TP)
                _calculate_ai_attack_range(game, action_to_check, start_pos, sim_orientation, target_pos, current_tp)
            )

    if start_pos_action_valid:
        best_spot_closest = start_pos

    while pq:
        cost, (x, y) = heapq.heappop(pq)

        if cost > move_distance:
            continue

        current_pos = (x, y)
        current_dist = _get_distance(current_pos, target_pos)

        # --- "预演" 检查 ---
        is_action_valid = True
        if action_to_check:
            sim_orientation = _get_orientation_to_target(current_pos, target_pos)
            is_locked_at_new_spot = _is_tile_locked_by_opponent(
                game, current_pos, game.ai_mech, locker_pos, locker_mech
            )
            if action_to_check.action_type == '射击' and is_locked_at_new_spot:
                is_action_valid = False
            else:
                is_action_valid = bool(_calculate_ai_attack_range(
                    game, action_to_check, current_pos, sim_orientation, target_pos,
                    current_tp=0  # [修改] 传入 0，因为AI移动到这里TP就没了
                ))

        if is_action_valid:
            # 目标 1: 'ideal' 或 'farthest_in_range'
            if ideal_range_min <= current_dist <= ideal_range_max:
                if cost < min_cost_in_range:
                    min_cost_in_range = cost
                    best_spot_in_range = current_pos
                    dist_from_ideal_mid = abs(current_dist - (ideal_range_min + ideal_range_max) / 2)
                    dist_for_farthest = current_dist
                elif cost == min_cost_in_range:
                    if goal == 'farthest_in_range':
                        if current_dist > dist_for_farthest:
                            best_spot_in_range = current_pos
                            dist_for_farthest = current_dist
                    else:  # 'ideal'
                        new_dist_from_mid = abs(current_dist - (ideal_range_min + ideal_range_max) / 2)
                        if new_dist_from_mid < dist_from_ideal_mid:
                            best_spot_in_range = current_pos
                            dist_from_ideal_mid = new_dist_from_mid

            # 目标 2: 'closest'
            # [优化] 确保 best_spot_closest 被初始化
            if best_spot_closest is None:
                best_spot_closest = current_pos
                min_dist_found = current_dist
            elif current_dist < min_dist_found:
                min_dist_found = current_dist
                best_spot_closest = current_pos
            elif current_dist == min_dist_found:
                # [优化] 检查 visited[best_spot_closest] 是否存在
                if best_spot_closest not in visited or cost < visited[best_spot_closest]:
                    best_spot_closest = current_pos

        # --- 探索邻居 ---
        current_is_locked = False
        if locker_can_lock:
            current_is_locked = _is_tile_locked_by_opponent(
                game, current_pos, game.ai_mech, locker_pos, locker_mech
            )

        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            nx, ny = x + dx, y + dy
            next_pos = (nx, ny)

            if not (1 <= nx <= game.board_width and 1 <= ny <= game.board_height):
                continue
            if next_pos == game.player_pos:
                continue

            move_cost = 1
            if current_is_locked:
                move_cost += 1
            new_cost = cost + move_cost

            if new_cost <= move_distance and (next_pos not in visited or new_cost < visited[next_pos]):
                visited[next_pos] = new_cost
                heapq.heappush(pq, (new_cost, next_pos))

    # --- 返回结果 ---
    if goal == 'ideal' or goal == 'farthest_in_range':
        return best_spot_in_range
    if goal == 'closest':
        return best_spot_closest
    return None


# --- AI 主逻辑 ---

def run_ai_turn(game):
    """
    AI回合的决策主函数。
    依次执行：状态分析 -> 姿态决策 -> 调整移动决策 -> 主动作循环。
    返回一个日志列表和一个待结算的攻击动作列表。
    """
    log = []
    ap = 2
    tp = 1
    game.ai_actions_used_this_turn = []

    # [v1.4] 这将存储所有需要 app.py 结算的攻击
    attacks_to_resolve_list = []

    # --- 阶段 0: 状态分析 ---
    is_ai_locked = get_ai_lock_status(game)[0]
    if is_ai_locked: log.append("> AI 被玩家近战锁定！")

    total_evasion = game.ai_mech.get_total_evasion()
    log.append(f"> AI 总闪避值: {total_evasion}")

    # [新增 v1.2] 分析 AI 自身状态
    core_damaged = game.ai_mech.parts['core'].status == 'damaged'
    legs_damaged = game.ai_mech.parts['legs'].status == 'damaged'
    is_damaged = core_damaged or legs_damaged
    if is_damaged:
        log.append("> AI 关键部件 (核心或腿部) 已受损。")

    # [新增 v1.2] 分析玩家威胁
    is_player_adjacent = _is_adjacent(game.ai_pos, game.player_pos)

    # [新增 v1.3] 分析玩家状态 (用于激进决策)
    player_core_status = game.player_mech.parts['core'].status
    player_is_damaged = player_core_status == 'damaged'
    if player_is_damaged:
        log.append("> [AI 侦测] 玩家核心受损！")

    all_actions_raw = game.ai_mech.get_all_actions()
    available_actions = []
    for action, part_slot in all_actions_raw:
        action_id = (part_slot, action.name)
        if action_id not in game.ai_actions_used_this_turn:
            available_actions.append((action, part_slot))

    # "预演" 朝向
    sim_orientation = _get_orientation_to_target(game.ai_pos, game.player_pos)

    # [优化 v1.1] 使用 _evaluate_action_strength 评估最佳动作
    # [修改 v1.5] 传递 S 动作数量和是否在射程内
    available_s_actions_count = sum(1 for a, s in available_actions if a.cost == 'S')

    # [修改] 评估时传入当前的tp (此时为1)
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

    # [修改 v1.5] L 动作加分 (如果不在射程内)
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

    # (合并评估)
    if best_l_melee_tuple and _evaluate_action_strength(best_l_melee_tuple[0], available_s_actions_count,
                                                        bool(melee_actions_now)) > _evaluate_action_strength(
            best_melee_tuple[0] if best_melee_tuple else None, available_s_actions_count, True):
        best_melee_tuple = best_l_melee_tuple

    if best_l_shoot_tuple and _evaluate_action_strength(best_l_shoot_tuple[0], available_s_actions_count,
                                                        bool(shoot_actions_now)) > _evaluate_action_strength(
            best_shoot_tuple[0] if best_shoot_tuple else None, available_s_actions_count, True):
        best_shoot_tuple = best_l_shoot_tuple

    best_melee_strength = _evaluate_action_strength(best_melee_tuple[0], available_s_actions_count,
                                                    True) if best_melee_tuple else 0
    best_shoot_strength = _evaluate_action_strength(best_shoot_tuple[0], available_s_actions_count,
                                                    True) if best_shoot_tuple else 0

    ai_personality = 'brawler'
    # [优化 v1.1] 使用 strength (强度) 而不是 dice 数量 (len)
    if best_shoot_strength > best_melee_strength:
        ai_personality = 'sniper'

    # [优化 v1.1] 在 "预演" 当前位置是否能攻击时，也使用 strength 排序
    melee_actions = sorted(
        melee_actions_now,  # [修改] 使用已计算的列表
        key=lambda item: _evaluate_action_strength(item[0], available_s_actions_count, is_in_range=True),
        reverse=True
    )
    shoot_actions = sorted(
        shoot_actions_now,  # [修改] 使用已计算的列表
        key=lambda item: _evaluate_action_strength(item[0], available_s_actions_count, is_in_range=True),
        reverse=True
    )

    move_action_tuple = next(((a, slot) for (a, slot) in available_actions if a.action_type == '移动'), None)
    move_action = move_action_tuple[0] if move_action_tuple else None

    # --- 阶段 1: 决策与时机 ---
    timing = '移动'
    stance = 'agile'  # [修改 v1.2] 默认姿态改为 'agile'
    best_attack_action_tuple = None
    is_in_attack_range = bool(melee_actions) or bool(shoot_actions)  # [修改] 使用 melee_actions

    if ai_personality == 'brawler':
        if melee_actions:
            best_attack_action_tuple = melee_actions[0]  # [优化 v1.1] 用排序后的最佳动作
            timing = '近战'
            stance = 'attack'  # 默认 'attack'
        else:
            timing = '移动'
            stance = 'agile'  # 默认 'agile'
    elif ai_personality == 'sniper':
        if shoot_actions:
            best_attack_action_tuple = shoot_actions[0]  # [优化 v1.1] 用排序后的最佳动作
            timing = '射击'
            stance = 'attack'  # 默认 'attack'
        else:
            timing = '移动'
            stance = 'agile'  # 默认 'agile'

    log.append(f"> AI ({ai_personality}) 选择了时机: [{timing}]。")

    # --- [修改 v1.3] 姿态决策 (Overrides) ---
    # 优先级 0: [激进] 玩家受损且 AI 能攻击 -> 攻击
    if player_is_damaged and is_in_attack_range:
        stance = 'attack'
        log.append("> AI 侦测到玩家受损且在射程内，强制切换到 [攻击] 姿态！")

    # 优先级 1: [防御] 被锁定且无法反击
    elif is_ai_locked and not is_in_attack_range:
        if total_evasion > 5:
            stance = 'agile'
            log.append("> AI 被锁定但闪避值高，切换到 [机动] 姿态以求生存。")
        else:
            stance = 'defense'
            log.append("> AI 被锁定且无法反击，切换到 [防御] 姿态。")

    # 优先级 2: [防御] AI 受损且被近身
    elif is_damaged and is_player_adjacent:
        if total_evasion > 5:
            stance = 'agile'
            log.append("> AI 受损但闪避值高，切换到 [机动] 姿态以求生存。")
        else:
            stance = 'defense'
            log.append("> AI 关键部件受损且玩家逼近，切换到 [防御] 姿态。")

    # 优先级 3: [机动] 高闪避 (覆盖 P0 之外的 'attack' 姿态)
    elif stance == 'attack' and total_evasion > 5:
        stance = 'agile'
        log.append(f"> AI 闪避值 ({total_evasion}) > 5，倾向于 [机动] 姿态。")

    # 优先级 4: 计划移动 (如果不是以上情况)
    elif timing == '移动':
        # 确保 stance 保持为 'agile' 以便移动
        stance = 'agile'
        # 仅在日志中记录（如果它没有被防御覆盖）
        if stance == 'agile':
            log.append("> AI 计划移动，切换到 [机动] 姿态。")

    # --- 阶段 2: 切换姿态 ---
    game.ai_mech.stance = stance
    log.append(f"> AI 切换姿态至: [{game.ai_mech.stance}]。")

    # --- 阶段 2.5: 调整移动 "预演" (TP) ---
    legs_part = game.ai_mech.parts.get('legs')
    adjust_move_val = 0
    if legs_part and legs_part.status != 'destroyed':
        adjust_move_val = legs_part.adjust_move
        if stance == 'agile':
            adjust_move_val *= 2

    potential_adjust_move_pos = None
    potential_attack_timing = None

    if tp >= 1 and adjust_move_val > 0:
        log.append(f"> AI 正在评估 (TP) 调整移动... (范围: {adjust_move_val})")

        planned_attack_action = best_attack_action_tuple[0] if best_attack_action_tuple else None
        is_attack_planned = planned_attack_action is not None
        is_in_range_now = bool(melee_actions) or bool(shoot_actions)  # [修改]

        if is_attack_planned and is_in_range_now and planned_attack_action.cost != 'L' and not is_ai_locked:
            log.append(f"> AI 正在评估 '风筝' (Kiting) 移动...")
            attack_range_min, attack_range_max = (1, 1)
            if planned_attack_action.action_type == '射击':
                attack_range_min = 1
                # [修改] 考虑【静止】效果
                effective_range = planned_attack_action.range_val
                if planned_attack_action.effects.get("static_range_bonus", 0) > 0 and tp >= 1:
                    effective_range += planned_attack_action.effects.get("static_range_bonus", 0)
                attack_range_max = effective_range

            kiting_pos = _find_best_move_position(game, adjust_move_val,
                                                  attack_range_min, attack_range_max,
                                                  goal='farthest_in_range',
                                                  action_to_check=planned_attack_action,
                                                  current_tp=tp)  # [修改] 传入tp
            if kiting_pos and _get_distance(kiting_pos, game.player_pos) > _get_distance(game.ai_pos, game.player_pos):
                potential_adjust_move_pos = kiting_pos
                potential_attack_timing = timing
                log.append(f"> AI 发现 '风筝' 位置: {kiting_pos}。")
            else:
                log.append(f"> AI 未找到比当前更远的 '风筝' 位置。")

        if not potential_adjust_move_pos:
            log.append(f"> AI 正在评估 '接近' (Approaching) 移动...")
            if best_melee_tuple and best_melee_tuple[0].cost != 'L':
                ideal_pos_for_melee = _find_best_move_position(game, adjust_move_val, 1, 1, 'ideal',
                                                               best_melee_tuple[0], current_tp=tp)  # [修改] 传入tp
                if ideal_pos_for_melee:
                    potential_adjust_move_pos = ideal_pos_for_melee
                    potential_attack_timing = '近战'
                    log.append(f"> AI 发现可以通过调整移动到 {ideal_pos_for_melee} 来发动近战。")
            if not potential_adjust_move_pos and best_shoot_tuple and not is_ai_locked and best_shoot_tuple[
                0].cost != 'L':
                ideal_range_min, ideal_range_max = (5, 8) if ai_personality == 'sniper' else (2, 5)
                ideal_pos_for_shoot = _find_best_move_position(game, adjust_move_val, ideal_range_min, ideal_range_max,
                                                               'ideal', best_shoot_tuple[0], current_tp=tp)  # [修改] 传入tp
                if ideal_pos_for_shoot:
                    potential_adjust_move_pos = ideal_pos_for_shoot
                    potential_attack_timing = '射击'
                    log.append(f"> AI 发现可以通过调整移动到 {ideal_pos_for_shoot} 来发动射击。")
            if not potential_adjust_move_pos:
                log.append(f"> AI 未找到合适的 (TP) 调整移动位置 (或需为 L 动作保留 TP)。")

    # --- 阶段 3: 调整动作 (TP) ---
    if potential_adjust_move_pos and potential_attack_timing:
        log.append(f"> AI 决定执行调整移动！")
        game.ai_pos = potential_adjust_move_pos
        tp -= 1
        if timing != potential_attack_timing:
            log.append(f"> AI 将时机从 [{timing}] 更改为 [{potential_attack_timing}]！")
            timing = potential_attack_timing
        target_orientation = _get_orientation_to_target(game.ai_pos, game.player_pos)
        if game.ai_mech.orientation != target_orientation:
            log.append(f"> AI 调整移动后立即转向 {target_orientation}。")
            game.ai_mech.orientation = target_orientation
    else:
        target_orientation = _get_orientation_to_target(game.ai_pos, game.player_pos)
        if game.ai_mech.orientation != target_orientation and tp >= 1:
            log.append(f"> AI 消耗1 TP进行转向, 朝向从 {game.ai_mech.orientation} 变为 {target_orientation}。")
            game.ai_mech.orientation = target_orientation
            tp -= 1

    # --- [修改 v1.4] 阶段 4: 主要动作 (AP) 循环 ---
    opening_move_taken = False

    while ap > 0:
        # 1. 获取当前可用的动作 (未在本回合使用过的)
        current_available_actions_tuples = []
        for action, part_slot in all_actions_raw:
            action_id = (part_slot, action.name)
            if action_id not in game.ai_actions_used_this_turn:
                current_available_actions_tuples.append((action, part_slot))

        if not current_available_actions_tuples:
            log.append("> AI 已无可用动作。")
            break  # 退出 while ap > 0 循环

        # [新增 v1.5] 在循环开始时重新计算可用的S动作数量
        current_available_s_count = sum(1 for a, s in current_available_actions_tuples if a.cost == 'S')

        # 2. 重新评估当前状况
        current_orientation = game.ai_mech.orientation
        is_ai_locked_now = get_ai_lock_status(game)[0]

        possible_now_melee = sorted(
            [(a, slot) for (a, slot) in current_available_actions_tuples if
             a.action_type == '近战' and _calculate_ai_attack_range(game, a, game.ai_pos, current_orientation,
                                                                    game.player_pos, current_tp=tp)],  # [修改] 传入tp
            key=lambda item: _evaluate_action_strength(item[0], current_available_s_count, is_in_range=True),
            reverse=True
        )
        possible_now_shoot = sorted(
            [(a, slot) for (a, slot) in current_available_actions_tuples if
             a.action_type == '射击' and _calculate_ai_attack_range(game, a, game.ai_pos, current_orientation,
                                                                    game.player_pos,
                                                                    current_tp=tp) and not is_ai_locked_now],
            # [修改] 传入tp
            key=lambda item: _evaluate_action_strength(item[0], current_available_s_count, is_in_range=True),
            reverse=True
        )
        possible_now_move = sorted(
            [(a, slot) for (a, slot) in current_available_actions_tuples if a.action_type == '移动'],
            key=lambda item: item[0].range_val, reverse=True  # 简单评估：移动距离越长越好
        )

        # 3. 决策逻辑
        action_to_perform_tuple = None

        if not opening_move_taken:
            # --- 3a. 必须执行起手动作 ---
            log.append(f"> AI 正在寻找时机为 [{timing}] 的起手动作...")
            if timing == '近战' and possible_now_melee:
                action_to_perform_tuple = possible_now_melee[0]
            elif timing == '射击' and possible_now_shoot:
                action_to_perform_tuple = possible_now_shoot[0]
            elif timing == '移动' and possible_now_move:
                action_to_perform_tuple = possible_now_move[0]

            if not action_to_perform_tuple:
                log.append(f"> AI 无法执行时机为 [{timing}] 的起手动作！回合结束。")
                break  # 退出 while ap > 0 循环

        else:
            # --- 3b. 起手动作已完成, 寻找额外动作 ---
            log.append(f"> AI 尚有 {ap}AP，正在寻找额外动作...")

            best_overall_action = None
            best_strength = -1

            # 优先攻击, 其次移动
            all_possible_actions = possible_now_melee + possible_now_shoot + possible_now_move

            for (action, slot) in all_possible_actions:
                cost_ap, cost_tp_cost = _get_action_cost(action)  # [修正] 避免与 tp 变量重名
                if ap < cost_ap or tp < cost_tp_cost:
                    continue  # 成本不足

                strength = 0
                if action.action_type in ['近战', '射击']:
                    strength = _evaluate_action_strength(action, current_available_s_count, is_in_range=True)
                elif action.action_type == '移动':
                    strength = 0.5  # 移动的优先级较低

                if strength > best_strength:
                    best_strength = strength
                    best_overall_action = (action, slot)

            action_to_perform_tuple = best_overall_action

        # --- 4. 执行动作 ---
        if not action_to_perform_tuple:
            log.append("> AI 找不到更多可执行的动作。")
            break  # 退出 while ap > 0 循环

        (action_obj, action_slot) = action_to_perform_tuple
        cost_ap, cost_tp = _get_action_cost(action_obj)

        # 最终成本检查
        if ap < cost_ap or tp < cost_tp:
            log.append(
                f"> [成本检查失败] AI 试图执行 [{action_obj.name}] (需 {cost_ap}AP {cost_tp}TP) 但只有 ( {ap}AP {tp}TP)。")
            # 将此动作标记为已用 (防止无限循环)
            game.ai_actions_used_this_turn.append((action_slot, action_obj.name))
            continue  # 继续 while 循环, 寻找更便宜的动作

        # --- 确认执行动作 ---
        log_msg_action_type = "起手动作" if not opening_move_taken else "额外动作"
        log.append(f"> AI 执行 [{log_msg_action_type}] [{action_obj.name}] (消耗 {cost_ap}AP, {cost_tp}TP)。")

        # 标记为已用
        action_id = (action_slot, action_obj.name)
        game.ai_actions_used_this_turn.append(action_id)

        # 扣除资源
        ap -= cost_ap
        tp -= cost_tp

        if not opening_move_taken:
            opening_move_taken = True

        # --- 处理动作效果 ---
        if action_obj.action_type in ['近战', '射击']:
            # [v1.4] 添加到待结算列表
            attacks_to_resolve_list.append(action_obj)

        elif action_obj.action_type == '移动':
            # AI 需要在此时 *真正* 移动
            log.append(f"> AI 正在为 [{action_obj.name}] 寻找目标...")
            ideal_move_pos = None

            if ai_personality == 'brawler':
                # 全力接近
                ideal_move_pos = _find_best_move_position(game, action_obj.range_val, 1, 1, 'closest', None,
                                                          current_tp=0)
            else:  # 'sniper'
                if is_ai_locked_now:
                    # 逃离
                    ideal_move_pos = _find_best_move_position(game, action_obj.range_val, 3, 15, 'farthest_in_range',
                                                              None, current_tp=0)
                else:
                    # 寻找理想距离
                    ideal_move_pos = _find_best_move_position(game, action_obj.range_val, 5, 8, 'ideal', None,
                                                              current_tp=0)

            if ideal_move_pos and ideal_move_pos != game.ai_pos:
                game.ai_pos = ideal_move_pos
                log.append(f"> AI 移动到 {game.ai_pos}。")
                # 移动后必须转向
                target_orientation = _get_orientation_to_target(game.ai_pos, game.player_pos)
                if game.ai_mech.orientation != target_orientation:
                    game.ai_mech.orientation = target_orientation
                    log.append(f"> AI 移动后转向 {target_orientation}。")
            else:
                log.append(f"> AI 未找到合适的移动位置，动作 [{action_obj.name}] 被跳过。")

        # while ap > 0 循环继续

    # --- 循环结束 ---
    if not opening_move_taken and not attacks_to_resolve_list:
        log.append("> AI 结束回合，未执行任何主要动作。")

    return log, attacks_to_resolve_list

