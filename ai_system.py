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
    根据骰子、成本、射程和效果，评估一个攻击动作的相对强度。
    - available_s_action_count (int): AI本回合总共可用的S动作数量。
    [优化 v1.6] 加入对穿甲和毁伤效果的评估。
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

    # [优化 v1.6] 效果强度加成
    if action.effects:
        # 穿甲效果 (每点穿甲增加 0.5 强度)
        ap_bonus = action.effects.get("armor_piercing", 0) * 0.5
        strength += ap_bonus

        # 毁伤效果 (增加 1.0 强度)
        if action.effects.get("devastating", False):
            strength += 1.0

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
        if not is_in_forward_arc(start_pos, orientation, target_pos):
            return []

        # AI的动态射程计算
        final_range = action.range_val
        if action.effects:
            # 1. 检查【静止】效果
            static_bonus = action.effects.get("static_range_bonus", 0)
            if static_bonus > 0 and current_tp >= 1:
                final_range += static_bonus

            # 2. 检查【双手】效果
            two_handed_bonus = action.effects.get("two_handed_range_bonus", 0)
            if two_handed_bonus > 0:
                attacker_mech = game.ai_mech
                part_slot_of_action = None
                for slot, part in attacker_mech.parts.items():
                    # 确保部件存在且未被摧毁
                    if part and part.status != 'destroyed' and any(a.name == action.name for a in part.actions):
                        part_slot_of_action = slot
                        break

                other_arm_part = None
                if part_slot_of_action == 'left_arm':
                    other_arm_part = attacker_mech.parts.get('right_arm')
                elif part_slot_of_action == 'right_arm':
                    other_arm_part = attacker_mech.parts.get('left_arm')

                # 检查另一只手是否有【空手】标签且未被摧毁
                if other_arm_part and other_arm_part.status != 'destroyed' and "【空手】" in other_arm_part.tags:
                    final_range += two_handed_bonus

        dist = _get_distance(start_pos, target_pos)
        is_valid_target = (dist <= final_range)

    if is_valid_target:
        targets.append({'pos': target_pos}) # AI 只需知道目标位置即可

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
    locker_can_lock = locker_mech and locker_mech.has_melee_action() and locker_mech.parts.get('core') and locker_mech.parts['core'].status != 'destroyed'

    pq = [(0, start_pos)]  # (cost, pos)
    visited = {start_pos: 0}  # {pos: cost}

    # 记录找到的最佳位置
    best_spot_in_range = None
    min_cost_in_range = float('inf')
    dist_from_ideal_mid = float('inf')
    dist_for_farthest = -1

    best_spot_closest = None
    min_dist_found = _get_distance(start_pos, target_pos)

    # 如果起始点满足要求，将其设为默认的 best_spot_closest
    start_pos_action_valid = True
    if action_to_check:
        sim_orientation = _get_orientation_to_target(start_pos, target_pos)
        is_locked_at_start = _is_tile_locked_by_opponent(game, start_pos, game.ai_mech, locker_pos, locker_mech)
        if action_to_check.action_type == '射击' and is_locked_at_start:
            start_pos_action_valid = False
        else:
            start_pos_action_valid = bool(
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
                    current_tp=0 # 移动后 TP 归零
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
            if best_spot_closest is None:
                best_spot_closest = current_pos
                min_dist_found = current_dist
            elif current_dist < min_dist_found:
                min_dist_found = current_dist
                best_spot_closest = current_pos
            elif current_dist == min_dist_found:
                # 如果距离相同，优先选择成本更低的位置
                if best_spot_closest not in visited or cost < visited.get(best_spot_closest, float('inf')):
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
            if next_pos == game.player_pos: # 不能移动到玩家位置
                continue

            move_cost = 1
            if current_is_locked:
                move_cost += 1 # 脱离锁定增加成本
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

# [优化 v1.6] 新增辅助函数：寻找最远的可移动位置
def _find_farthest_move_position(game, move_distance):
    """
    使用 BFS 寻找在移动距离内，离玩家最远的有效格子。
    """
    start_pos = game.ai_pos
    target_pos = game.player_pos
    queue = [(start_pos, 0)]  # (pos, cost)
    visited = {start_pos}
    reachable_positions = [] # 存储所有可达的位置及其成本

    # 确定锁定者 (玩家) - 用于计算移动成本
    locker_mech = game.player_mech
    locker_pos = game.player_pos
    locker_can_lock = locker_mech and locker_mech.has_melee_action() and locker_mech.parts.get('core') and locker_mech.parts['core'].status != 'destroyed'

    while queue:
        (x, y), cost = queue.pop(0)
        current_pos = (x, y)

        if cost > 0: # 必须是移动过的位置
            reachable_positions.append((current_pos, cost))

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
            if next_pos in visited:
                continue

            move_cost_step = 1
            if current_is_locked:
                move_cost_step += 1
            new_cost = cost + move_cost_step

            if new_cost <= move_distance:
                visited.add(next_pos)
                queue.append((next_pos, new_cost))

    if not reachable_positions:
        return None # 无法移动

    # 找到距离玩家最远的位置
    farthest_pos = max(reachable_positions, key=lambda item: (_get_distance(item[0], target_pos), -item[1]))[0] # 距离优先，然后成本低优先

    return farthest_pos


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
    # [修正] 确保AI动作在回合开始时清空
    game.ai_actions_used_this_turn = []

    attacks_to_resolve_list = []

    # --- 阶段 0: 状态分析 ---
    is_ai_locked = get_ai_lock_status(game)[0]
    if is_ai_locked: log.append("> AI 被玩家近战锁定！")

    total_evasion = game.ai_mech.get_total_evasion()
    log.append(f"> AI 总闪避值: {total_evasion}")

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

    all_actions_raw = game.ai_mech.get_all_actions()
    available_actions = []
    for action, part_slot in all_actions_raw:
        action_id = (part_slot, action.name)
        if action_id not in game.ai_actions_used_this_turn:
             # [新增] 检查部件是否被摧毁
             part_obj = game.ai_mech.parts.get(part_slot)
             if part_obj and part_obj.status != 'destroyed':
                available_actions.append((action, part_slot))


    # "预演" 朝向
    sim_orientation = _get_orientation_to_target(game.ai_pos, game.player_pos)

    available_s_actions_count = sum(1 for a, s in available_actions if a.cost == 'S')

    # 评估当前位置可用的攻击
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

    # 评估所有可用的 L 动作 (即使不在射程内)
    best_l_melee_tuple = max(
        [(a, slot) for (a, slot) in available_actions if a.action_type == '近战' and a.cost == 'L'],
        key=lambda item: _evaluate_action_strength(item[0], available_s_actions_count, is_in_range=bool(melee_actions_now)),
        default=None
    )
    best_l_shoot_tuple = max(
        [(a, slot) for (a, slot) in available_actions if a.action_type == '射击' and a.cost == 'L'],
        key=lambda item: _evaluate_action_strength(item[0], available_s_actions_count, is_in_range=bool(shoot_actions_now)),
        default=None
    )

    # 合并评估 L 动作和非 L 动作，选出最佳近战和射击
    current_best_melee_strength = _evaluate_action_strength(best_melee_tuple[0] if best_melee_tuple else None, available_s_actions_count, True)
    l_melee_strength = _evaluate_action_strength(best_l_melee_tuple[0] if best_l_melee_tuple else None, available_s_actions_count, bool(melee_actions_now))
    if l_melee_strength > current_best_melee_strength:
        best_melee_tuple = best_l_melee_tuple

    current_best_shoot_strength = _evaluate_action_strength(best_shoot_tuple[0] if best_shoot_tuple else None, available_s_actions_count, True)
    l_shoot_strength = _evaluate_action_strength(best_l_shoot_tuple[0] if best_l_shoot_tuple else None, available_s_actions_count, bool(shoot_actions_now))
    if l_shoot_strength > current_best_shoot_strength:
        best_shoot_tuple = best_l_shoot_tuple

    # 最终的最佳强度
    best_melee_strength = _evaluate_action_strength(best_melee_tuple[0] if best_melee_tuple else None, available_s_actions_count, bool(melee_actions_now or best_melee_tuple))
    best_shoot_strength = _evaluate_action_strength(best_shoot_tuple[0] if best_shoot_tuple else None, available_s_actions_count, bool(shoot_actions_now or best_shoot_tuple))


    # --- AI 个性与时机决策 ---
    ai_personality = 'brawler'
    if best_shoot_strength > best_melee_strength:
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

    timing = '移动'
    stance = 'agile'
    best_attack_action_tuple = None
    is_in_attack_range = bool(melee_actions) or bool(shoot_actions)

    if ai_personality == 'brawler':
        # 如果当前位置就能近战，或者有强力L近战动作
        if melee_actions or (best_melee_tuple and best_melee_tuple[0].cost == 'L'):
            timing = '近战'
            stance = 'attack'
            best_attack_action_tuple = best_melee_tuple # 用评估出的最佳（可能 L）
        else: # 需要移动才能近战
            timing = '移动'
            stance = 'agile'
    elif ai_personality == 'sniper':
        if shoot_actions or (best_shoot_tuple and best_shoot_tuple[0].cost == 'L'):
            timing = '射击'
            stance = 'attack'
            best_attack_action_tuple = best_shoot_tuple # 用评估出的最佳（可能 L）
        else: # 需要移动才能射击
            timing = '移动'
            stance = 'agile'

    log.append(f"> AI ({ai_personality}) 选择了时机: [{timing}]。")

    # --- 姿态决策 (Overrides) ---
    if player_is_damaged and is_in_attack_range:
        stance = 'attack'
        log.append("> AI 侦测到玩家受损且在射程内，强制切换到 [攻击] 姿态！")
    elif is_ai_locked and not is_in_attack_range:
        stance = 'agile' if total_evasion > 5 else 'defense'
        log.append(f"> AI 被锁定且无法反击，切换到 [{stance}] 姿态。")
    elif is_damaged and is_player_adjacent:
        stance = 'agile' if total_evasion > 5 else 'defense'
        log.append(f"> AI 受损且玩家逼近，切换到 [{stance}] 姿态。")
    elif stance == 'attack' and total_evasion > 5:
        stance = 'agile'
        log.append(f"> AI 闪避值 ({total_evasion}) > 5，倾向于 [机动] 姿态。")
    elif timing == '移动' and stance != 'defense': # 如果没被防御覆盖
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
    potential_attack_timing = timing # 默认维持原时机

    if tp >= 1 and adjust_move_val > 0:
        log.append(f"> AI 正在评估 (TP) 调整移动... (范围: {adjust_move_val})")

        planned_attack_action = best_attack_action_tuple[0] if best_attack_action_tuple else None
        is_in_range_now = is_in_attack_range # 是否在当前位置就能攻击

        # 尝试风筝 (仅当计划攻击且在射程内，且不是L动作，且未被锁定)
        if planned_attack_action and is_in_range_now and planned_attack_action.cost != 'L' and not is_ai_locked:
            log.append(f"> AI 正在评估 '风筝' 移动...")
            attack_range_min, attack_range_max = (1, 1) if planned_attack_action.action_type == '近战' else (1, planned_attack_action.range_val)
            # 考虑静止效果对风筝目标范围的影响
            if planned_attack_action.action_type == '射击' and planned_attack_action.effects.get("static_range_bonus", 0) > 0 and tp >= 1:
                attack_range_max += planned_attack_action.effects.get("static_range_bonus", 0)

            kiting_pos = _find_best_move_position(game, adjust_move_val,
                                                  attack_range_min, attack_range_max,
                                                  goal='farthest_in_range',
                                                  action_to_check=planned_attack_action,
                                                  current_tp=tp)
            if kiting_pos and _get_distance(kiting_pos, game.player_pos) > _get_distance(game.ai_pos, game.player_pos):
                potential_adjust_move_pos = kiting_pos
                # potential_attack_timing 保持不变
                log.append(f"> AI 发现 '风筝' 位置: {kiting_pos}。")
            else:
                log.append("> AI 未找到比当前更远的 '风筝' 位置。")

        # 如果不风筝，尝试通过调整移动进入攻击范围
        if not potential_adjust_move_pos:
            log.append(f"> AI 正在评估 '接近/定位' 移动...")
            # 检查是否有近战动作可以通过调整进入范围 (且不是L)
            potential_melee_target = max(
                [(a, slot) for (a, slot) in available_actions if a.action_type == '近战' and a.cost != 'L'],
                key=lambda item: _evaluate_action_strength(item[0], available_s_actions_count, False), default=None
            )
            if potential_melee_target:
                 ideal_pos_melee = _find_best_move_position(game, adjust_move_val, 1, 1, 'ideal', potential_melee_target[0], current_tp=tp)
                 if ideal_pos_melee:
                    potential_adjust_move_pos = ideal_pos_melee
                    potential_attack_timing = '近战'
                    log.append(f"> AI 发现可以通过调整移动到 {ideal_pos_melee} 来发动近战。")

            # 如果没找到近战机会，或者AI是狙击手，尝试射击
            if not potential_adjust_move_pos and not is_ai_locked:
                potential_shoot_target = max(
                    [(a, slot) for (a, slot) in available_actions if a.action_type == '射击' and a.cost != 'L'],
                    key=lambda item: _evaluate_action_strength(item[0], available_s_actions_count, False), default=None
                )
                if potential_shoot_target:
                    ideal_range_min_shoot, ideal_range_max_shoot = (5, 8) if ai_personality == 'sniper' else (2, 5)
                    ideal_pos_shoot = _find_best_move_position(game, adjust_move_val, ideal_range_min_shoot, ideal_range_max_shoot, 'ideal', potential_shoot_target[0], current_tp=tp)
                    if ideal_pos_shoot:
                        potential_adjust_move_pos = ideal_pos_shoot
                        potential_attack_timing = '射击'
                        log.append(f"> AI 发现可以通过调整移动到 {ideal_pos_shoot} 来发动射击。")

            if not potential_adjust_move_pos:
                log.append(f"> AI 未找到合适的 (TP) 调整移动位置 (或需为 L 动作保留 TP)。")

    # --- 阶段 3: 调整动作 (TP) ---
    adjustment_action_taken = False
    if potential_adjust_move_pos:
        log.append(f"> AI 决定执行调整移动！")
        game.ai_pos = potential_adjust_move_pos
        tp -= 1
        adjustment_action_taken = True
        if timing != potential_attack_timing:
            log.append(f"> AI 将时机从 [{timing}] 更改为 [{potential_attack_timing}]！")
            timing = potential_attack_timing
        target_orientation = _get_orientation_to_target(game.ai_pos, game.player_pos)
        if game.ai_mech.orientation != target_orientation:
            log.append(f"> AI 调整移动后立即转向 {target_orientation}。")
            game.ai_mech.orientation = target_orientation
    # 如果没移动，但可以转向
    else:
        target_orientation = _get_orientation_to_target(game.ai_pos, game.player_pos)
        if game.ai_mech.orientation != target_orientation and tp >= 1:
            log.append(f"> AI 消耗1 TP进行转向, 朝向从 {game.ai_mech.orientation} 变为 {target_orientation}。")
            game.ai_mech.orientation = target_orientation
            tp -= 1
            adjustment_action_taken = True # 转向也算调整动作

    # --- 阶段 4: 主要动作 (AP) 循环 ---
    opening_move_taken = False

    while ap > 0:
        # 1. 获取当前可用的动作
        current_available_actions_tuples = []
        for action, part_slot in all_actions_raw:
             action_id = (part_slot, action.name)
             if action_id not in game.ai_actions_used_this_turn:
                 part_obj = game.ai_mech.parts.get(part_slot)
                 if part_obj and part_obj.status != 'destroyed':
                     current_available_actions_tuples.append((action, part_slot))

        if not current_available_actions_tuples:
            log.append("> AI 已无可用动作。")
            break

        current_available_s_count = sum(1 for a, s in current_available_actions_tuples if a.cost == 'S')

        # 2. 重新评估当前状况
        current_orientation = game.ai_mech.orientation
        is_ai_locked_now = get_ai_lock_status(game)[0]

        possible_now_melee = sorted(
            [(a, slot) for (a, slot) in current_available_actions_tuples if
             a.action_type == '近战' and _calculate_ai_attack_range(game, a, game.ai_pos, current_orientation, game.player_pos, current_tp=tp)],
            key=lambda item: _evaluate_action_strength(item[0], current_available_s_count, is_in_range=True), reverse=True
        )
        possible_now_shoot = sorted(
            [(a, slot) for (a, slot) in current_available_actions_tuples if
             a.action_type == '射击' and _calculate_ai_attack_range(game, a, game.ai_pos, current_orientation, game.player_pos, current_tp=tp) and not is_ai_locked_now],
            key=lambda item: _evaluate_action_strength(item[0], current_available_s_count, is_in_range=True), reverse=True
        )
        possible_now_move = sorted(
            [(a, slot) for (a, slot) in current_available_actions_tuples if a.action_type == '移动'],
            key=lambda item: item[0].range_val, reverse=True
        )

        # 3. 决策逻辑
        action_to_perform_tuple = None
        action_log_prefix = ""

        if not opening_move_taken:
            # --- 3a. 必须执行起手动作 ---
            action_log_prefix = "起手动作"
            log.append(f"> AI 正在寻找时机为 [{timing}] 的起手动作...")
            if timing == '近战' and possible_now_melee:
                action_to_perform_tuple = possible_now_melee[0]
            elif timing == '射击' and possible_now_shoot:
                action_to_perform_tuple = possible_now_shoot[0]
            elif timing == '移动' and possible_now_move:
                action_to_perform_tuple = possible_now_move[0]
            # [新增] 如果起手动作是L动作，也允许执行
            elif timing == '近战' and best_melee_tuple and best_melee_tuple[0].cost == 'L':
                 action_to_perform_tuple = best_melee_tuple
            elif timing == '射击' and best_shoot_tuple and best_shoot_tuple[0].cost == 'L':
                 action_to_perform_tuple = best_shoot_tuple


            if not action_to_perform_tuple:
                log.append(f"> AI 无法执行时机为 [{timing}] 的起手动作！回合结束。")
                break # 无法执行起手，回合结束

        else:
            # --- 3b. 起手动作已完成, 寻找额外动作 ---
            action_log_prefix = "额外动作"
            log.append(f"> AI 尚有 {ap}AP {tp}TP，正在寻找额外动作...")

            best_overall_action_tuple = None
            best_strength = -1

            # 评估所有当前可用的、成本足够的动作
            all_possible_now = possible_now_melee + possible_now_shoot + possible_now_move
            valid_extra_actions = []
            for (action, slot) in all_possible_now:
                cost_ap_check, cost_tp_check = _get_action_cost(action)
                if ap >= cost_ap_check and tp >= cost_tp_check:
                    valid_extra_actions.append((action, slot))

            if not valid_extra_actions:
                 log.append("> AI 无成本足够的额外动作。")
                 break # 没有可执行的动作了

            # 从成本足够的动作中选择最优的
            action_to_perform_tuple = max(
                valid_extra_actions,
                key=lambda item: _evaluate_action_strength(item[0], current_available_s_count, True) if item[0].action_type in ['近战', '射击']
                                 else (0.5 if item[0].action_type == '移动' else 0), # 移动优先级较低
                default=None
            )


        # --- 4. 执行动作 ---
        if not action_to_perform_tuple:
            log.append(f"> AI 找不到可执行的 {action_log_prefix}。")
            # 如果是起手动作找不到，上面已经 break 了
            # 如果是额外动作找不到，则正常结束循环
            break

        (action_obj, action_slot) = action_to_perform_tuple
        cost_ap, cost_tp_action = _get_action_cost(action_obj) # 避免与外层 tp 重名

        # 最终成本检查 (理论上在额外动作选择时已检查过)
        if ap < cost_ap or tp < cost_tp_action:
            log.append(
                f"> [成本检查失败] AI 试图执行 [{action_obj.name}] (需 {cost_ap}AP {cost_tp_action}TP) 但只有 ( {ap}AP {tp}TP)。")
            # 标记为已用防止无限循环
            game.ai_actions_used_this_turn.append((action_slot, action_obj.name))
            continue # 尝试寻找其他动作

        # --- 确认执行动作 ---
        log.append(f"> AI 执行 [{action_log_prefix}] [{action_obj.name}] (来自 {action_slot}, 消耗 {cost_ap}AP, {cost_tp_action}TP)。")

        action_id = (action_slot, action_obj.name)
        game.ai_actions_used_this_turn.append(action_id)
        ap -= cost_ap
        tp -= cost_tp_action

        if not opening_move_taken:
            opening_move_taken = True

        # --- 处理动作效果 ---
        if action_obj.action_type in ['近战', '射击']:
            attacks_to_resolve_list.append(action_obj)

        elif action_obj.action_type == '移动':
            log.append(f"> AI 正在为 [{action_obj.name}] 寻找移动目标...")
            move_target_pos = None
            move_distance_val = action_obj.range_val

            # [优化 v1.6] 更精细的移动目标选择
            current_dist_to_player = _get_distance(game.ai_pos, game.player_pos)

            if ai_personality == 'brawler':
                # 斗殴者总是试图接近
                move_target_pos = _find_best_move_position(game, move_distance_val, 1, 1, 'closest', None, current_tp=0)
            else:  # 'sniper'
                if is_ai_locked_now:
                    # 被锁定时，全力逃离
                    log.append("> AI (狙击手) 被锁定，尝试逃离！")
                    move_target_pos = _find_farthest_move_position(game, move_distance_val)
                elif current_dist_to_player < 5:
                     # 距离太近 (<5)，尝试拉开到理想距离 (5-8)
                     log.append("> AI (狙击手) 距离过近，尝试拉开距离...")
                     move_target_pos = _find_best_move_position(game, move_distance_val, 5, 8, 'farthest_in_range', None, current_tp=0)
                else:
                    # 距离合适 (>=5)，尝试在理想距离 (5-8) 内找到最佳位置
                    log.append("> AI (狙击手) 尝试寻找理想射击位置...")
                    move_target_pos = _find_best_move_position(game, move_distance_val, 5, 8, 'ideal', None, current_tp=0)

            # 如果主要目标没找到，尝试找任何能移动的位置 (避免浪费AP)
            if not move_target_pos:
                 log.append("> AI 未找到理想移动位置，尝试寻找任意可移动位置...")
                 # 使用 A* 找一个成本最低的可达点 (相当于 BFS 找最近的可达点)
                 pq_any = [(0, game.ai_pos)]
                 visited_any = {game.ai_pos: 0}
                 found_any_move = False
                 # [新增] 在循环外定义锁定者信息
                 locker_mech = game.player_mech
                 locker_pos = game.player_pos
                 locker_can_lock = locker_mech and locker_mech.has_melee_action() and locker_mech.parts.get('core') and locker_mech.parts['core'].status != 'destroyed'
                 # --- Fix Indentation within this loop ---
                 while pq_any:
                     cost_any, pos_any = heapq.heappop(pq_any)
                     if cost_any > move_distance_val:
                         continue
                     # Check if this position is a valid move target (cost > 0 and not player pos)
                     if cost_any > 0 and pos_any != game.player_pos:
                         # We found *a* possible move, store it as a fallback
                         # We'll prioritize closer/cheaper moves found earlier by A* nature
                         if not found_any_move: # Only store the first valid one found
                             move_target_pos = pos_any
                             found_any_move = True
                             # Optional: break here if *any* move is acceptable
                             # break

                     # Calculate locking cost for pathfinding
                     is_locked_at_pos = False
                     if locker_can_lock: # Use locker_can_lock defined outside the loop
                         is_locked_at_pos = _is_tile_locked_by_opponent(game, pos_any, game.ai_mech, locker_pos, locker_mech)
                     step_cost = 1 + (1 if is_locked_at_pos else 0)

                     # Explore neighbors
                     for dx_any, dy_any in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
                         nx_any, ny_any = pos_any[0] + dx_any, pos_any[1] + dy_any
                         next_pos_any = (nx_any, ny_any)
                         # Check bounds and if already visited with lower cost
                         if 1 <= nx_any <= game.board_width and 1 <= ny_any <= game.board_height:
                             new_cost_any = cost_any + step_cost
                             if new_cost_any <= move_distance_val and (next_pos_any not in visited_any or new_cost_any < visited_any[next_pos_any]):
                                 # Don't add player position to visited/queue for pathfinding
                                 if next_pos_any != game.player_pos:
                                     visited_any[next_pos_any] = new_cost_any
                                     heapq.heappush(pq_any, (new_cost_any, next_pos_any))
                 # --- End of Indentation Fix ---

            # 执行移动
            if move_target_pos and move_target_pos != game.ai_pos:
                game.ai_pos = move_target_pos
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

