import random
import heapq  # 导入 heapq 用于 A* 寻路
from game_logic import (
    is_in_forward_arc, get_ai_lock_status, _is_adjacent, _is_tile_locked_by_opponent,
    _get_distance  # [新增] 导入 _get_distance
)


# --- AI 辅助函数 ---

def _get_orientation_to_target(start_pos, target_pos):
    """计算朝向目标的最佳方向。"""
    dx = target_pos[0] - start_pos[0]
    dy = target_pos[1] - start_pos[1]

    if abs(dx) > abs(dy):
        return 'E' if dx > 0 else 'W'
    else:
        return 'S' if dy > 0 else 'N'


# [修改] _calculate_ai_attack_range 现在接受 start_pos 和 orientation
def _calculate_ai_attack_range(game, action, start_pos, orientation, target_pos):
    """
    [修改] 从AI的视角计算攻击范围，分离近战和射击。
    此版本接受 start_pos 和 orientation 以便“预演”。
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
        dist = _get_distance(start_pos, target_pos)
        is_valid_target = (dist <= action.range_val)

    if is_valid_target:
        targets.append({'pos': target_pos})

    return targets


def _find_best_move_position(game, move_distance, ideal_range_min, ideal_range_max, goal='ideal', action_to_check=None):
    """
    [重大修改] 使用 A* 寻路算法为 AI 寻找最佳移动位置。

    Args:
        game (GameState): 当前游戏状态。
        move_distance (int): 最大移动距离。
        ideal_range_min (int): 理想距离下限。
        ideal_range_max (int): 理想距离上限。
        goal (str): 搜索目标:
            'ideal': (默认) 寻找在理想范围内、成本最低的格子。
            'closest': 寻找所有可达格子中，离玩家最近的格子 (用于 "全力接近")。
            'farthest_in_range': 寻找在理想范围内、成本最低且离玩家最远的格子 (用于 "风筝")。
        action_to_check (Action): (可选) 移动后必须能成功执行的动作。
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

    best_spot_closest = start_pos  # 默认为起始点
    min_dist_found = _get_distance(start_pos, target_pos)

    while pq:
        cost, (x, y) = heapq.heappop(pq)

        if cost > move_distance:
            continue

        current_pos = (x, y)
        current_dist = _get_distance(current_pos, target_pos)

        # --- [新增] "预演" 检查 ---
        # 检查这个格子是否满足 action_to_check (如果提供了)
        is_action_valid = True
        if action_to_check:
            # 模拟朝向
            sim_orientation = _get_orientation_to_target(current_pos, target_pos)

            # 模拟被锁定
            # (注意: _is_tile_locked_by_opponent 假设 a_mech 在 current_pos)
            is_locked_at_new_spot = _is_tile_locked_by_opponent(
                game, current_pos, game.ai_mech, locker_pos, locker_mech
            )

            if action_to_check.action_type == '射击' and is_locked_at_new_spot:
                is_action_valid = False
            else:
                # 检查攻击范围
                is_action_valid = bool(_calculate_ai_attack_range(
                    game, action_to_check, current_pos, sim_orientation, target_pos
                ))
        # --- "预演" 结束 ---

        if is_action_valid:
            # 目标 1: 'ideal' 或 'farthest_in_range'
            if ideal_range_min <= current_dist <= ideal_range_max:
                if cost < min_cost_in_range:
                    # 找到成本更低的点
                    min_cost_in_range = cost
                    best_spot_in_range = current_pos
                    dist_from_ideal_mid = abs(current_dist - (ideal_range_min + ideal_range_max) / 2)
                    dist_for_farthest = current_dist

                elif cost == min_cost_in_range:
                    # 成本相同，使用 goal 作为决胜局
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
            if current_dist < min_dist_found:
                min_dist_found = current_dist
                best_spot_closest = current_pos
            elif current_dist == min_dist_found:
                if cost < visited[best_spot_closest]:  # 同样近，选成本低的
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
        return best_spot_in_range  # 找到了就返回，没找到返回 None

    if goal == 'closest':
        return best_spot_closest  # 总是返回一个点（至少是 start_pos）

    return None  # 默认


# --- AI 主逻辑 ---

def run_ai_turn(game):
    """
    [优化] 运行AI的完整回合，遵循与玩家相同的四阶段行动规则。
    """
    log = []
    ap = 2
    tp = 1
    game.ai_actions_used_this_turn = []

    # --- 阶段 0: 状态分析 ---
    is_ai_locked = get_ai_lock_status(game)[0]
    if is_ai_locked: log.append("> AI 被玩家近战锁定！")

    all_actions_raw = game.ai_mech.get_all_actions()
    available_actions = []
    for action, part_slot in all_actions_raw:
        action_id = (part_slot, action.name)
        if action_id not in game.ai_actions_used_this_turn:
            available_actions.append((action, part_slot))

    # "预演" 朝向
    original_orientation = game.ai_mech.orientation
    sim_orientation = _get_orientation_to_target(game.ai_pos, game.player_pos)

    # "预演" 在当前位置是否能攻击
    melee_actions = [(a, slot) for (a, slot) in available_actions if
                     a.action_type == '近战' and _calculate_ai_attack_range(game, a, game.ai_pos, sim_orientation,
                                                                            game.player_pos)]
    shoot_actions = [(a, slot) for (a, slot) in available_actions if
                     a.action_type == '射击' and _calculate_ai_attack_range(game, a, game.ai_pos, sim_orientation,
                                                                            game.player_pos) and not is_ai_locked]

    # 恢复朝向
    # game.ai_mech.orientation = original_orientation # 暂时不需要恢复，因为只是本地变量

    move_action_tuple = next(((a, slot) for (a, slot) in available_actions if a.action_type == '移动'), None)
    move_action = move_action_tuple[0] if move_action_tuple else None

    best_melee_tuple = max([(a, slot) for (a, slot) in available_actions if a.action_type == '近战'],
                           key=lambda item: len(item[0].dice), default=None)
    best_shoot_tuple = max([(a, slot) for (a, slot) in available_actions if a.action_type == '射击'],
                           key=lambda item: len(item[0].dice), default=None)

    best_melee_dice = len(best_melee_tuple[0].dice) if best_melee_tuple else 0
    best_shoot_dice = len(best_shoot_tuple[0].dice) if best_shoot_tuple else 0

    ai_personality = 'brawler'
    if best_shoot_dice > best_melee_dice:
        ai_personality = 'sniper'

    # --- 阶段 1: 决策与时机 ---
    timing = '移动'
    stance = 'agile'
    best_attack_action_tuple = None

    if ai_personality == 'brawler':
        if melee_actions:
            best_attack_action_tuple = best_melee_tuple
            timing = '近战'
            stance = 'attack'
        else:
            timing = '移动'
            stance = 'agile'
    elif ai_personality == 'sniper':
        if shoot_actions:
            best_attack_action_tuple = best_shoot_tuple
            timing = '射击'
            stance = 'attack'
        else:
            timing = '移动'
            stance = 'agile'

    if is_ai_locked and not best_attack_action_tuple:
        stance = 'defense'

    log.append(f"> AI ({ai_personality}) 选择时机: [{timing}]。")

    # --- 阶段 2: 切换姿态 ---
    game.ai_mech.stance = stance
    log.append(f"> AI 切换姿态至: [{game.ai_mech.stance}]。")

    # --- 阶段 2.5: [修改] 调整移动 "预演" (TP) ---
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

        # 逻辑 1: "风筝" (Kiting)
        planned_attack_action = best_attack_action_tuple[0] if best_attack_action_tuple else None
        is_attack_planned = planned_attack_action is not None
        is_in_range_now = bool(melee_actions) or bool(shoot_actions)

        # [修正] 只有在计划的攻击不是L动作时，才能用TP来"风筝"
        if is_attack_planned and is_in_range_now and planned_attack_action.cost != 'L' and not is_ai_locked:
            log.append(f"> AI 正在评估 '风筝' (Kiting) 移动...")

            attack_range_min, attack_range_max = (1, 1)
            if planned_attack_action.action_type == '射击':
                attack_range_min = 1
                attack_range_max = planned_attack_action.range_val

            kiting_pos = _find_best_move_position(game, adjust_move_val,
                                                  attack_range_min, attack_range_max,
                                                  goal='farthest_in_range',
                                                  action_to_check=planned_attack_action)

            if kiting_pos and _get_distance(kiting_pos, game.player_pos) > _get_distance(game.ai_pos, game.player_pos):
                potential_adjust_move_pos = kiting_pos
                potential_attack_timing = timing  # 保持原时机
                log.append(f"> AI 发现 '风筝' 位置: {kiting_pos}。")
            else:
                log.append(f"> AI 未找到比当前更远的 '风筝' 位置。")

        # 逻辑 2: "接近" (Approaching)
        if not potential_adjust_move_pos:
            log.append(f"> AI 正在评估 '接近' (Approaching) 移动...")

            # [修正] 只有在最佳近战动作不是L动作时，才能用TP来"接近"
            if best_melee_tuple and best_melee_tuple[0].cost != 'L':
                ideal_pos_for_melee = _find_best_move_position(game, adjust_move_val, 1, 1, 'ideal',
                                                               best_melee_tuple[0])
                if ideal_pos_for_melee:
                    potential_adjust_move_pos = ideal_pos_for_melee
                    potential_attack_timing = '近战'
                    log.append(f"> AI 发现可以通过调整移动到 {ideal_pos_for_melee} 来发动近战。")

            # [修正] 只有在最佳射击动作不是L动作时，才能用TP来"接近"
            if not potential_adjust_move_pos and best_shoot_tuple and not is_ai_locked and best_shoot_tuple[
                0].cost != 'L':
                ideal_range_min, ideal_range_max = (5, 8) if ai_personality == 'sniper' else (2, 5)
                ideal_pos_for_shoot = _find_best_move_position(game, adjust_move_val, ideal_range_min, ideal_range_max,
                                                               'ideal', best_shoot_tuple[0])
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

    # --- 阶段 4: 主要动作 (AP) ---
    action_to_resolve = None
    action_ap_cost = 0
    action_tp_cost = 0

    # 1. 执行攻击
    if timing in ['射击', '近战']:
        # 重新评估攻击
        current_orientation = game.ai_mech.orientation

        if timing == '近战':
            melee_actions_after_turn = [(a, slot) for (a, slot) in available_actions if
                                        a.action_type == '近战' and _calculate_ai_attack_range(game, a, game.ai_pos,
                                                                                               current_orientation,
                                                                                               game.player_pos)]
            if melee_actions_after_turn:
                best_attack_action_tuple = max(melee_actions_after_turn, key=lambda item: len(item[0].dice),
                                               default=None)
            else:
                best_attack_action_tuple = None  # [修复] 如果调整后没法攻击了，清空

        elif timing == '射击':
            shoot_actions_after_turn = [(a, slot) for (a, slot) in available_actions if
                                        a.action_type == '射击' and _calculate_ai_attack_range(game, a, game.ai_pos,
                                                                                               current_orientation,
                                                                                               game.player_pos) and not is_ai_locked]
            if shoot_actions_after_turn:
                best_attack_action_tuple = max(shoot_actions_after_turn, key=lambda item: len(item[0].dice),
                                               default=None)
            else:
                best_attack_action_tuple = None  # [修复]

        if best_attack_action_tuple:
            best_attack_action, best_attack_slot = best_attack_action_tuple

            action_ap_cost = best_attack_action.cost.count('M') * 2 + best_attack_action.cost.count('S') * 1
            action_tp_cost = 0
            if best_attack_action.cost == 'L':
                action_ap_cost = 2
                action_tp_cost = 1

            if ap >= action_ap_cost and tp >= action_tp_cost:
                action_to_resolve = best_attack_action
                ap -= action_ap_cost
                tp -= action_tp_cost

                action_id = (best_attack_slot, action_to_resolve.name)
                game.ai_actions_used_this_turn.append(action_id)
                if best_attack_action_tuple in available_actions:
                    available_actions.remove(best_attack_action_tuple)

                log.append(
                    f"> AI 使用起手动作 [{action_to_resolve.name}] (消耗 {action_ap_cost}AP, {action_tp_cost}TP) 攻击玩家！")
            else:
                log.append(
                    f"> AI 动作 [{best_attack_action.name}] 因资源不足 (需要 {action_ap_cost}AP, {action_tp_cost}TP) 而取消。")
                best_attack_action_tuple = None
        else:
            log.append(f"> AI 调整后丢失目标或无法执行 [{timing}] 动作。")

    # 2. 执行移动
    if not action_to_resolve and timing == '移动':
        move_action_cost = 0

        if not move_action_tuple:
            move_action_tuple = next(((a, slot) for (a, slot) in available_actions if a.action_type == '移动'), None)
            move_action = move_action_tuple[0] if move_action_tuple else None

        if move_action:
            move_action_cost = move_action.cost.count('M') * 2 + move_action.cost.count('S') * 1
            move_action, move_slot = move_action_tuple

        if move_action and ap >= move_action_cost:

            ideal_move_pos = None
            if ai_personality == 'brawler':
                # [修正] 确保 AP 移动时，也能为 L 动作预留 TP
                # (虽然目前没有 L 近战，但这是个好习惯)
                planned_melee_action = best_melee_tuple[0] if best_melee_tuple else None
                if planned_melee_action and planned_melee_action.cost == 'L' and tp < 1:
                    log.append("> AI (Brawler) 无法移动并执行 L 动作 (TP 不足)。")
                else:
                    ideal_move_pos = _find_best_move_position(game, move_action.range_val, 1, 1, 'ideal',
                                                              planned_melee_action)

            else:  # sniper
                planned_shoot_action = best_shoot_tuple[0] if best_shoot_tuple else None
                # [修正] 检查 AP 移动后，是否还有 1 TP (如果需要)
                if planned_shoot_action and planned_shoot_action.cost == 'L' and tp < 1:
                    log.append("> AI (Sniper) 无法移动并执行 L 动作 (TP 不足)。")
                else:
                    ideal_move_pos = _find_best_move_position(game, move_action.range_val, 5, 8, 'ideal',
                                                              planned_shoot_action)

                if not ideal_move_pos and is_ai_locked:
                    ideal_move_pos = _find_best_move_position(game, move_action.range_val, 3, 15, 'farthest_in_range',
                                                              None)  # Flee

            if ideal_move_pos:
                game.ai_pos = ideal_move_pos
                log.append(f"> AI 使用 [{move_action.name}] 移动到 {game.ai_pos}。")
                ap -= move_action_cost
                action_id = (move_slot, move_action.name)
                game.ai_actions_used_this_turn.append(action_id)
                if move_action_tuple in available_actions:
                    available_actions.remove(move_action_tuple)
            else:
                # [新增] 逻辑 1: "全力接近" (Approaching)
                log.append(f"> AI 未找到理想移动位置，尝试 '全力接近'...")
                # 目标：在移动范围内，找到离玩家最近的点
                approach_pos = _find_best_move_position(game, move_action.range_val, 0, 0, 'closest', None)

                if approach_pos and approach_pos != game.ai_pos:
                    game.ai_pos = approach_pos
                    log.append(f"> AI 使用 [{move_action.name}] (全力接近) 移动到 {game.ai_pos}。")
                    ap -= move_action_cost
                    action_id = (move_slot, move_action.name)
                    game.ai_actions_used_this_turn.append(action_id)
                    if move_action_tuple in available_actions:
                        available_actions.remove(move_action_tuple)
                else:
                    log.append("> AI 无法移动 (全力接近失败)。")
        else:
            log.append("> AI 无法移动 (没有移动动作或AP不足)。")

    if not action_to_resolve and not any("移动到" in s for s in log):
        log.append("> AI 结束回合，未执行主要动作。")

    return log, action_to_resolve


