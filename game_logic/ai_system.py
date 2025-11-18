import random
import heapq
import re
# [重构] 从 .game_logic 导入
from .game_logic import (
    is_in_forward_arc, get_ai_lock_status, _is_adjacent, _is_tile_locked_by_opponent,
    _get_distance,
    # [修复] 移除 'check_interception'，因为它已移至 controller
    run_projectile_logic,
)
from .data_models import Mech
# [新增] 导入抛射物模板以评估抛射动作强度
from .database import PROJECTILE_TEMPLATES


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
    使用期望值 (EV) 代替任意权重。
    假设处于“攻击姿态”（空心=命中）。
    """
    if not action: return 0
    if action.action_type not in ['近战', '射击', '抛射']: return 0

    strength = 0

    # [新增] 抛射动作的特殊评估逻辑
    # 抛射动作本身的 dice 通常为空字符串，伤害由生成的抛射物实体造成
    if action.action_type == '抛射' and action.projectile_to_spawn:
        template = PROJECTILE_TEMPLATES.get(action.projectile_to_spawn)
        if template:
            # 获取抛射物的主动作（通常是列表中的第一个）
            proj_actions = template.get('actions', [])
            if proj_actions:
                # 这是一个字典，因为 PROJECTILE_TEMPLATES 存储的是字典格式
                payload_action = proj_actions[0]
                p_dice = payload_action.get('dice', '')
                yellow, red = _parse_dice_string_for_eval(p_dice)

                # 计算单发抛射物的 EV (期望值)
                # 黄骰 EV: 0.875, 红骰 EV: 1.0625
                ev_yellow = yellow * 0.875
                ev_red = red * 1.0625
                base_strength = ev_yellow + ev_red

                # 考虑齐射 (Salvo)
                salvo = action.effects.get('salvo', 1)
                strength = base_strength * salvo

                # 考虑类型优势
                # '立即': 相当于直射，无额外加成
                # '延迟': 具有追踪和压制能力，给予战术加成
                payload_type = payload_action.get('action_type')
                if payload_type == '延迟':
                    strength *= 1.3  # 延迟导弹有很高的战术价值 (迫使玩家移动或拦截)
    else:
        # 常规动作评估逻辑 (直接读取 action.dice)
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
            strength += yellow * (1 / 8 * 1.5)
            strength += red * (1 / 8 * 1.5)

    # --- 通用：成本和效果调整 ---
    if action.cost == 'S':
        strength *= 1.2  # S动作更灵活
        if available_s_action_count == 1:
            strength *= 0.7
    elif action.cost == 'L':
        strength *= 0.8  # L动作成本高
        if is_in_range:
            strength *= 1.5

    if action.effects:
        # 穿甲 (AP)
        ap_bonus = action.effects.get("armor_piercing", 0) * 0.5
        strength += ap_bonus
        # 毁伤/霰射/顺劈 (增加额外伤害的潜力)
        if action.effects.get("devastating", False):
            strength += 1.0
        if action.effects.get("scattershot", False):
            strength += 0.8
        if action.effects.get("cleave", False):
            strength += 0.8
        if action.effects.get("two_handed_devastating", False):
            strength += 1.0  # 假设它能触发
        if action.effects.get("two_handed_sniper", False):
            strength += 0.5
        # 拦截动作本身没有强度 (是被动)
        if action.effects.get("interceptor", False):
            strength = 0

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


def _calculate_ai_attack_range(game_state, attacker_mech, action, start_pos, orientation, target_pos, current_tp=0):
    """
    模拟计算AI在特定位置和朝向下，能否攻击到目标。
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

    elif action.action_type == '射击' or action.action_type == '抛射':

        is_curved = (action.action_style == 'curved')

        # 1. 检查视线 (曲射跳过)
        if not is_curved and not is_in_forward_arc(start_pos, orientation, target_pos):
            return []

        # 2. 计算最终射程
        final_range = action.range_val
        if action.effects:
            # 检查【静止】
            static_bonus = action.effects.get("static_range_bonus", 0)
            if static_bonus > 0 and current_tp >= 1:  # 必须有TP才能触发
                final_range += static_bonus

            # 检查【双手】(仅机甲)
            if isinstance(attacker_mech, Mech):
                two_handed_bonus = action.effects.get("two_handed_range_bonus", 0)
                if two_handed_bonus > 0:
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

                    if other_arm_part and other_arm_part.status != 'destroyed' and "【空手】" in other_arm_part.tags:
                        final_range += two_handed_bonus

        # 3. 检查距离
        dist = _get_distance(start_pos, target_pos)
        is_valid_target = (dist <= final_range)

    if is_valid_target:
        targets.append({'pos': target_pos})
    return targets


# --- 寻路与位置评估 ---

def _find_all_reachable_positions(game, ai_mech, player_mech):
    """
    在AI回合开始时运行一次，使用 Dijkstra 算法计算到所有格子的最小成本。
    返回一个字典: {(x, y): cost}
    """
    start_pos = ai_mech.pos
    locker_mech = player_mech
    locker_pos = player_mech.pos if player_mech else None

    locker_can_lock = (
            locker_mech and
            locker_mech.status != 'destroyed' and
            locker_mech.has_melee_action()
    )

    pq = [(0, start_pos)]  # (cost, pos)
    visited = {start_pos: 0}  # {pos: cost}

    occupied_tiles = game.get_occupied_tiles(exclude_id=ai_mech.id)

    while pq:
        cost, (x, y) = heapq.heappop(pq)
        current_pos = (x, y)

        # 探索邻居
        current_is_locked = False
        if locker_can_lock:
            current_is_locked = _is_tile_locked_by_opponent(
                game, current_pos, ai_mech, locker_pos, locker_mech
            )

        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            nx, ny = x + dx, y + dy
            next_pos = (nx, ny)

            if not (1 <= nx <= game.board_width and 1 <= ny <= game.board_height):
                continue
            if next_pos in occupied_tiles:
                continue

            move_cost = 1
            if current_is_locked:
                move_cost += 1
            new_cost = cost + move_cost

            if next_pos not in visited or new_cost < visited[next_pos]:
                visited[next_pos] = new_cost
                heapq.heappush(pq, (new_cost, next_pos))

    return visited


def _find_best_move_position(game, move_distance, ideal_range_min, ideal_range_max, goal, all_reachable_costs,
                             player_pos):
    """
    不再执行寻路。而是快速迭代预先计算的 all_reachable_costs 字典。
    """
    if not player_pos:  # 如果玩家不存在
        return None

    # 筛选出所有在 move_distance 内可达的格子
    valid_moves = []
    for pos, cost in all_reachable_costs.items():
        if cost <= move_distance:
            valid_moves.append(pos)

    if not valid_moves:
        return None  # 无法移动

    best_spot = None

    if goal == 'closest':
        min_dist_found = float('inf')
        min_cost_found = float('inf')
        for pos in valid_moves:
            dist = _get_distance(pos, player_pos)
            cost = all_reachable_costs[pos]
            if dist < min_dist_found:
                min_dist_found = dist
                min_cost_found = cost
                best_spot = pos
            elif dist == min_dist_found:
                if cost < min_cost_found:
                    min_cost_found = cost
                    best_spot = pos
        return best_spot

    moves_in_range = []
    for pos in valid_moves:
        dist = _get_distance(pos, player_pos)
        if ideal_range_min <= dist <= ideal_range_max:
            moves_in_range.append(pos)

    if not moves_in_range:
        return None

    if goal == 'ideal':
        ideal_mid = (ideal_range_min + ideal_range_max) / 2
        best_spot = min(moves_in_range, key=lambda pos: (
            abs(_get_distance(pos, player_pos) - ideal_mid),
            all_reachable_costs[pos]
        ))
    elif goal == 'farthest_in_range':
        best_spot = max(moves_in_range, key=lambda pos: (
            _get_distance(pos, player_pos),
            -all_reachable_costs[pos]
        ))

    return best_spot


def _find_farthest_move_position(game, move_distance, all_reachable_costs, player_pos):
    """
    不再执行寻路。而是快速迭代预先计算的 all_reachable_costs 字典。
    """
    if not player_pos:  # 如果玩家不存在
        return None

    valid_moves = []
    for pos, cost in all_reachable_costs.items():
        if 0 < cost <= move_distance:
            valid_moves.append(pos)

    if not valid_moves:
        return None

    farthest_pos = max(valid_moves, key=lambda pos: (
        _get_distance(pos, player_pos),
        -all_reachable_costs[pos]
    ))
    return farthest_pos


# --- AI 主逻辑 ---

def run_ai_turn(ai_mech, game_state):
    """
    执行 AI 的完整回合逻辑。
    返回: (log, attacks_to_resolve_list)
    attacks_to_resolve_list 是一个字典列表，用于 game_controller 进行结算。
    """
    log = []

    # --- 阶段 0: 宕机恢复与回合初始化 ---
    if ai_mech.stance == 'downed':
        log.append(f"> [AI系统] {ai_mech.name} 链接恢复。 [宕机姿态] 解除。")
        log.append(f"> [AI警告] {ai_mech.name} 系统冲击！本回合 AP-1, TP-1！")
        ai_mech.player_ap = 1
        ai_mech.player_tp = 0
        ai_mech.stance = 'defense'  # 重置为默认姿态
    else:
        ai_mech.player_ap = 2
        ai_mech.player_tp = 1

    ap = ai_mech.player_ap
    tp = ai_mech.player_tp
    ai_mech.actions_used_this_turn = []
    attacks_to_resolve_list = []

    # --- 阶段 1: 状态分析 ---
    player_mech = game_state.get_player_mech()
    if not player_mech or player_mech.status == 'destroyed':
        log.append(f"> [AI] {ai_mech.name} 找不到玩家目标，跳过回合。")
        return log, []

    player_pos = player_mech.pos

    all_reachable_costs = _find_all_reachable_positions(game_state, ai_mech, player_mech)

    is_ai_locked = get_ai_lock_status(game_state, ai_mech)[0]
    if is_ai_locked: log.append(f"> AI {ai_mech.name} 被玩家近战锁定！")

    total_evasion = ai_mech.get_total_evasion()
    log.append(f"> AI {ai_mech.name} 总闪避值: {total_evasion}")

    core_damaged = ai_mech.parts.get('core') and ai_mech.parts['core'].status == 'damaged'
    legs_part = ai_mech.parts.get('legs')
    legs_damaged = legs_part and legs_part.status == 'damaged'
    is_damaged = core_damaged or legs_damaged
    if is_damaged:
        log.append(f"> AI {ai_mech.name} 关键部件 (核心或腿部) 已受损。")

    is_player_adjacent = _is_adjacent(ai_mech.pos, player_pos)
    player_core = player_mech.parts.get('core')
    player_is_damaged = player_core and player_core.status == 'damaged'
    if player_is_damaged:
        log.append(f"> [AI 侦测] {ai_mech.name} 发现玩家核心受损！")

    # 收集所有可用动作 (排除已使用、部件摧毁、被动)
    all_actions_raw = ai_mech.get_all_actions()
    available_actions = []
    for action, part_slot in all_actions_raw:
        action_id = (part_slot, action.name)
        if action_id not in ai_mech.actions_used_this_turn:
            part_obj = ai_mech.parts.get(part_slot)
            if part_obj and part_obj.status != 'destroyed':
                if not (action.action_type == '被动' and action.effects.get("interceptor")):
                    available_actions.append((action, part_slot))

    # --- 阶段 1.5: 评估当前位置的攻击选项 ---
    sim_orientation = _get_orientation_to_target(ai_mech.pos, player_pos)
    available_s_actions_count = sum(1 for a, s in available_actions if a.cost == 'S')

    melee_actions_now = [
        (a, slot) for (a, slot) in available_actions if
        a.action_type == '近战' and _calculate_ai_attack_range(game_state, ai_mech, a, ai_mech.pos, sim_orientation,
                                                               player_pos, current_tp=tp)
    ]
    shoot_actions_now = [
        (a, slot) for (a, slot) in available_actions if
        (a.action_type == '射击' or a.action_type == '抛射') and
        _calculate_ai_attack_range(game_state, ai_mech, a, ai_mech.pos, sim_orientation,
                                   player_pos, current_tp=tp) and (a.action_type == '抛射' or not is_ai_locked)
    ]

    # 查找最佳 L 动作 (因为它们可能无法立即使用，但仍需评估)
    best_l_melee_tuple = max(
        [(a, slot) for (a, slot) in available_actions if a.action_type == '近战' and a.cost == 'L'],
        key=lambda item: _evaluate_action_strength(item[0], available_s_actions_count,
                                                   bool(melee_actions_now)),
        default=None
    )
    best_l_shoot_tuple = max(
        [(a, slot) for (a, slot) in available_actions if
         (a.action_type == '射击' or a.action_type == '抛射') and a.cost == 'L'],
        key=lambda item: _evaluate_action_strength(item[0], available_s_actions_count,
                                                   bool(shoot_actions_now)),
        default=None
    )

    # 找出当前 S/M 动作中的最佳
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

    # 比较 S/M 和 L 动作，选出最强的
    if (best_l_melee_tuple and
            _evaluate_action_strength(best_l_melee_tuple[0], available_s_actions_count, bool(melee_actions_now)) >
            _evaluate_action_strength(best_melee_tuple[0] if best_melee_tuple else None, available_s_actions_count,
                                      True)):
        best_melee_tuple = best_l_melee_tuple

    if (best_l_shoot_tuple and
            _evaluate_action_strength(best_l_shoot_tuple[0], available_s_actions_count, bool(shoot_actions_now)) >
            _evaluate_action_strength(best_shoot_tuple[0] if best_shoot_tuple else None, available_s_actions_count,
                                      True)):
        best_shoot_tuple = best_l_shoot_tuple

    best_melee_strength = _evaluate_action_strength(best_melee_tuple[0] if best_melee_tuple else None,
                                                    available_s_actions_count,
                                                    bool(melee_actions_now or best_melee_tuple))
    best_shoot_strength = _evaluate_action_strength(best_shoot_tuple[0] if best_shoot_tuple else None,
                                                    available_s_actions_count,
                                                    bool(shoot_actions_now or best_shoot_tuple))

    # --- 阶段 2: 决定时机 (Timing) 和姿态 (Stance) ---
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

    timing = '移动'
    stance = 'agile'
    best_attack_action_tuple = None
    is_in_attack_range = bool(melee_actions) or bool(shoot_actions)

    sniper_is_in_bad_spot = False
    if ai_personality == 'sniper':
        current_dist_to_player = _get_distance(ai_mech.pos, player_pos)
        if is_ai_locked or current_dist_to_player < 3:
            sniper_is_in_bad_spot = True
            log.append(f"> AI (狙击手) 处于不良位置 (锁定: {is_ai_locked} / 距离: {current_dist_to_player})。")

    # 决定时机
    if ai_personality == 'brawler':
        if melee_actions or (best_melee_tuple and best_melee_tuple[0].cost == 'L'):
            timing = '近战'
            stance = 'attack'
            best_attack_action_tuple = best_melee_tuple
        else:
            timing = '移动'
            stance = 'agile'
    elif ai_personality == 'sniper':
        if sniper_is_in_bad_spot:
            timing = '移动'
            stance = 'agile'
            log.append(f"> [AI 狙击手] 优先选择 [移动] 时机来拉开距离。")
        elif shoot_actions or (best_shoot_tuple and best_shoot_tuple[0].cost == 'L'):
            timing = '射击'
            if best_shoot_tuple and best_shoot_tuple[0].action_type == '抛射':
                timing = '抛射'
            stance = 'attack'
            best_attack_action_tuple = best_shoot_tuple
        else:
            timing = '移动'
            stance = 'agile'

    log.append(f"> AI ({ai_personality}) 选择了时机: [{timing}]。")

    # 修正姿态
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
        if not (best_attack_action_tuple and best_attack_action_tuple[0].cost == 'L'):
            stance = 'agile'
            log.append(f"> AI 闪避值 ({total_evasion}) > 5，倾向于 [机动] 姿态。")
    elif timing == '移动' and stance != 'defense':
        stance = 'agile'
        log.append("> AI 计划移动，切换到 [机动] 姿态。")

    # 最终确定姿态
    ai_mech.stance = stance
    log.append(f"> AI 切换姿态至: [{ai_mech.stance}]。")

    # --- 阶段 3: 调整阶段 (TP) ---
    adjust_move_val = 0
    if legs_part and legs_part.status != 'destroyed':
        adjust_move_val = legs_part.adjust_move
        if stance == 'agile':
            adjust_move_val *= 2

    potential_adjust_move_pos = None
    potential_attack_timing = timing

    if tp >= 1 and adjust_move_val > 0:
        log.append(f"> AI 正在评估 (TP) 调整移动... (范围: {adjust_move_val})")

        # 尝试寻找一个 S/M 动作的攻击位置
        potential_melee_target = max(
            [(a, slot) for (a, slot) in available_actions if a.action_type == '近战' and a.cost != 'L'],
            key=lambda item: _evaluate_action_strength(item[0], available_s_actions_count, False), default=None
        )
        if potential_melee_target:
            ideal_pos_melee = _find_best_move_position(game_state, adjust_move_val, 1, 1, 'ideal',
                                                       all_reachable_costs, player_pos)
            if ideal_pos_melee:
                potential_adjust_move_pos = ideal_pos_melee
                potential_attack_timing = '近战'
                log.append(f"> AI 发现可以通过调整移动到 {ideal_pos_melee} 来发动近战。")

        if not potential_adjust_move_pos and not is_ai_locked:
            potential_shoot_target = max(
                [(a, slot) for (a, slot) in available_actions if
                 (a.action_type == '射击' or a.action_type == '抛射') and a.cost != 'L'],
                key=lambda item: _evaluate_action_strength(item[0], available_s_actions_count, False), default=None
            )
            if potential_shoot_target:
                current_dist = _get_distance(ai_mech.pos, player_pos)
                if ai_personality == 'sniper' and current_dist < 3:
                    log.append("> AI (狙击手) 尝试使用 TP 拉开距离...")
                    ideal_pos_shoot = _find_best_move_position(game_state, adjust_move_val, 5, 8,
                                                               'farthest_in_range',
                                                               all_reachable_costs, player_pos)
                else:
                    ideal_range_min_shoot, ideal_range_max_shoot = (5, 8) if ai_personality == 'sniper' else (2, 5)
                    ideal_pos_shoot = _find_best_move_position(game_state, adjust_move_val, ideal_range_min_shoot,
                                                               ideal_range_max_shoot, 'ideal', all_reachable_costs,
                                                               player_pos)

                if ideal_pos_shoot:
                    potential_adjust_move_pos = ideal_pos_shoot
                    potential_attack_timing = '射击'
                    if potential_shoot_target[0].action_type == '抛射':
                        potential_attack_timing = '抛射'
                    log.append(f"> AI 发现可以通过调整移动到 {ideal_pos_shoot} 来发动 {potential_attack_timing}。")

        if not potential_adjust_move_pos:
            log.append(f"> AI 未找到合适的 (TP) 调整移动位置 (或需为 L 动作保留 TP)。")

    # 执行调整阶段
    if potential_adjust_move_pos and potential_adjust_move_pos != ai_mech.pos:
        log.append(f"> AI 决定执行调整移动！")
        ai_mech.last_pos = ai_mech.pos
        ai_mech.pos = potential_adjust_move_pos
        tp -= 1
        if timing != potential_attack_timing:
            log.append(f"> AI 将时机从 [{timing}] 更改为 [{potential_attack_timing}]！")
            timing = potential_attack_timing
        target_orientation = _get_orientation_to_target(ai_mech.pos, player_pos)
        if ai_mech.orientation != target_orientation:
            log.append(f"> AI 调整移动后立即转向 {target_orientation}。")
            ai_mech.orientation = target_orientation
    else:
        # 如果不移动，则考虑转向
        target_orientation = _get_orientation_to_target(ai_mech.pos, player_pos)
        if ai_mech.orientation != target_orientation and tp >= 1:
            tp_needed_for_shot = False
            if (timing == '射击' or timing == '抛射') and best_shoot_tuple:
                action_obj = best_shoot_tuple[0]
                if action_obj and action_obj.effects.get("static_range_bonus", 0) > 0:
                    base_range = action_obj.range_val
                    dist = _get_distance(ai_mech.pos, player_pos)
                    if dist > base_range:
                        tp_needed_for_shot = True
                        log.append(f"> AI 侦测到 TP 必须用于 [{action_obj.name}] 的【静止】射程加成。")

            if tp_needed_for_shot:
                log.append(f"> AI 决定保留 TP 用于射击，本回合放弃转向。")
            else:
                log.append(f"> AI 消耗1 TP进行转向, 朝向从 {ai_mech.orientation} 变为 {target_orientation}。")
                ai_mech.orientation = target_orientation
                tp -= 1

    # --- 阶段 4: 主要动作 (AP) 循环 ---
    opening_move_taken = False
    while ap > 0:
        # 重新评估当前可用动作
        current_available_actions_tuples = []
        for action, part_slot in all_actions_raw:
            action_id = (part_slot, action.name)
            if action_id not in ai_mech.actions_used_this_turn:
                part_obj = ai_mech.parts.get(part_slot)
                if part_obj and part_obj.status != 'destroyed':
                    if not (action.action_type == '被动' and action.effects.get("interceptor")):
                        current_available_actions_tuples.append((action, part_slot))

        if not current_available_actions_tuples:
            log.append(f"> AI {ai_mech.name} 已无可用动作。")
            break

        current_available_s_count = sum(1 for a, s in current_available_actions_tuples if a.cost == 'S')
        current_orientation = ai_mech.orientation
        is_ai_locked_now = get_ai_lock_status(game_state, ai_mech)[0]

        # 评估当前所有可立即执行的动作
        possible_now_melee = sorted(
            [(a, slot) for (a, slot) in current_available_actions_tuples if
             a.action_type == '近战' and _calculate_ai_attack_range(game_state, ai_mech, a, ai_mech.pos,
                                                                    current_orientation,
                                                                    player_pos, current_tp=tp)],
            key=lambda item: _evaluate_action_strength(item[0], current_available_s_count, is_in_range=True),
            reverse=True
        )
        possible_now_shoot = sorted(
            [(a, slot) for (a, slot) in current_available_actions_tuples if
             (a.action_type == '射击' or a.action_type == '抛射') and
             _calculate_ai_attack_range(game_state, ai_mech, a, ai_mech.pos, current_orientation,
                                        player_pos, current_tp=tp) and (
                     a.action_type == '抛射' or not is_ai_locked_now)],
            key=lambda item: _evaluate_action_strength(item[0], current_available_s_count, is_in_range=True),
            reverse=True
        )
        possible_now_move = sorted(
            [(a, slot) for (a, slot) in current_available_actions_tuples if a.action_type == '移动'],
            key=lambda item: item[0].range_val, reverse=True
        )

        action_to_perform_tuple = None
        action_log_prefix = ""

        if not opening_move_taken:
            action_log_prefix = "起手动作"
            log.append(f"> AI {ai_mech.name} 正在寻找时机为 [{timing}] 的起手动作...")

            potential_openers = []
            if timing == '近战':
                potential_openers.extend(possible_now_melee)
                if best_melee_tuple and best_melee_tuple[0].cost == 'L':
                    potential_openers.append(best_melee_tuple)
            elif timing == '射击' or timing == '抛射':
                potential_openers.extend(possible_now_shoot)
                if best_shoot_tuple and best_shoot_tuple[0].cost == 'L':
                    potential_openers.append(best_shoot_tuple)
            elif timing == '移动':
                potential_openers.extend(possible_now_move)

            affordable_openers = []
            for (action, slot) in potential_openers:
                cost_ap_check, cost_tp_check = _get_action_cost(action)
                if ap >= cost_ap_check and tp >= cost_tp_check:
                    affordable_openers.append((action, slot))

            if affordable_openers:
                if timing == '移动':
                    action_to_perform_tuple = max(
                        affordable_openers,
                        key=lambda item: item[0].range_val
                    )
                else:
                    action_to_perform_tuple = max(
                        affordable_openers,
                        key=lambda item: _evaluate_action_strength(item[0], current_available_s_count, True)
                    )

            if not action_to_perform_tuple:
                log.append(f"> AI {ai_mech.name} 无法找到或负担得起时机为 [{timing}] 的起手动作！回合结束。")
                break

        else:
            action_log_prefix = "额外动作"
            log.append(f"> AI {ai_mech.name} 尚有 {ap}AP {tp}TP，正在寻找额外动作...")

            all_possible_now = possible_now_melee + possible_now_shoot + possible_now_move
            valid_extra_actions = []
            for (action, slot) in all_possible_now:
                cost_ap_check, cost_tp_check = _get_action_cost(action)
                if ap >= cost_ap_check and tp >= cost_tp_check:
                    if action.cost != 'L':  # L 动作不能作为额外动作
                        valid_extra_actions.append((action, slot))

            if not valid_extra_actions:
                log.append("> AI 无成本足够的额外动作。")
                break

            action_to_perform_tuple = max(
                valid_extra_actions,
                key=lambda item: _evaluate_action_strength(item[0], current_available_s_count, True) if item[
                                                                                                            0].action_type in [
                                                                                                            '近战',
                                                                                                            '射击',
                                                                                                            '抛射']
                else (0.5 if item[0].action_type == '移动' else 0),
                default=None
            )

        if not action_to_perform_tuple:
            log.append(f"> AI 找不到可执行的 {action_log_prefix}。")
            break

        (action_obj, action_slot) = action_to_perform_tuple
        cost_ap, cost_tp_action = _get_action_cost(action_obj)

        if ap < cost_ap or tp < cost_tp_action:
            log.append(
                f"> [成本检查失败] AI 试图执行 [{action_obj.name}] (需 {cost_ap}AP {cost_tp_action}TP) 但只有 ( {ap}AP {tp}TP)。")
            ai_mech.actions_used_this_turn.append((action_slot, action_obj.name))
            if not opening_move_taken:
                log.append("> AI 无法执行起手动作，回合结束。")
                break
            else:
                continue

        log.append(
            f"> AI 执行 [{action_log_prefix}] [{action_obj.name}] (来自 {action_slot}, 消耗 {cost_ap}AP, {cost_tp_action}TP)。")

        action_id = (action_slot, action_obj.name)
        ai_mech.actions_used_this_turn.append(action_id)
        ap -= cost_ap
        tp -= cost_tp_action
        opening_move_taken = True

        if action_obj.action_type == '移动':
            log.append(f"> AI 正在为 [{action_obj.name}] 寻找移动目标...")
            move_target_pos = None
            move_distance_val = action_obj.range_val
            current_dist_to_player = _get_distance(ai_mech.pos, player_pos)

            if ai_personality == 'brawler':
                move_target_pos = _find_best_move_position(game_state, move_distance_val, 1, 1, 'closest',
                                                           all_reachable_costs, player_pos)
            else:
                if is_ai_locked_now:
                    log.append("> AI (狙击手) 被锁定，尝试逃离！")
                    move_target_pos = _find_farthest_move_position(game_state, move_distance_val, all_reachable_costs,
                                                                   player_pos)
                elif current_dist_to_player < 5:
                    log.append("> AI (狙击手) 距离过近，尝试拉开距离...")
                    move_target_pos = _find_best_move_position(game_state, move_distance_val, 5, 8, 'farthest_in_range',
                                                               all_reachable_costs, player_pos)
                else:
                    log.append("> AI (狙击手) 尝试寻找理想射击位置...")
                    move_target_pos = _find_best_move_position(game_state, move_distance_val, 5, 8, 'ideal',
                                                               all_reachable_costs, player_pos)

            if not move_target_pos:
                log.append("> AI 未找到理想移动位置，尝试寻找任意可移动位置...")
                move_target_pos = _find_best_move_position(game_state, move_distance_val, 0,
                                                           game_state.board_width + game_state.board_height, 'closest',
                                                           all_reachable_costs, player_pos)

            if move_target_pos and move_target_pos != ai_mech.pos:
                ai_mech.last_pos = ai_mech.pos
                ai_mech.pos = move_target_pos
                log.append(f"> AI 移动到 {ai_mech.pos}。")
                target_orientation = _get_orientation_to_target(ai_mech.pos, player_pos)
                if ai_mech.orientation != target_orientation:
                    ai_mech.orientation = target_orientation
                    log.append(f"> AI 移动后转向 {target_orientation}。")
            else:
                log.append(f"> AI 未找到合适的移动位置，动作 [{action_obj.name}] 被跳过。")


        elif action_obj.action_type in ['近战', '射击', '抛射']:
            if action_obj.action_type == '抛射':
                salvo_count = action_obj.effects.get('salvo', 1)
                ammo_key = (ai_mech.id, action_slot, action_obj.name)
                current_ammo = game_state.ammo_counts.get(ammo_key, 0)
                launch_count = min(salvo_count, current_ammo)

                if launch_count <= 0:
                    log.append(f"> [AI错误] 弹药耗尽，无法发射 [{action_obj.name}]。")
                    ap += cost_ap
                    tp += cost_tp_action
                    ai_mech.actions_used_this_turn.pop()
                    opening_move_taken = False
                    continue

                game_state.ammo_counts[ammo_key] -= launch_count
                log.append(f"> AI 发射 [{action_obj.name}] (齐射 {launch_count}) 到 {player_pos}！")
                log.append(f"> 消耗 {launch_count} 弹药, 剩余 {game_state.ammo_counts[ammo_key]}。")

                for i in range(launch_count):
                    proj_id, proj_obj = game_state.spawn_projectile(
                        launcher_entity=ai_mech,
                        target_pos=player_pos,  # AI 总是以玩家位置为目标
                        projectile_key=action_obj.projectile_to_spawn
                    )
                    if not proj_obj:
                        log.append(f"> [错误] AI 生成抛射物 {action_obj.projectile_to_spawn} 失败。")
                        continue

                    has_immediate_action = proj_obj.get_action_by_timing('立即')[0] is not None

                    # [修复] 移除对 check_interception 的调用
                    # '立即' 抛射物的拦截将在 controller 结算
                    # '延迟' 抛射物的拦截将在 controller 的 run_projectile_phase 结算

                    log.append(f"> [AI] 检查 {proj_obj.name} (ID: {proj_id}) 是否有 '立即' 动作...")

                    proj_log, proj_attacks = run_projectile_logic(proj_obj, game_state, '立即')

                    if proj_attacks:
                        log.extend(proj_log)
                        attacks_to_resolve_list.extend(proj_attacks)
                    else:
                        log.append(f"> [AI] ...{proj_obj.name} 没有 '立即' 动作 (将等待 '延迟' 阶段)。")

            # 常规近战/射击
            else:
                attacks_to_resolve_list.append({
                    'attacker': ai_mech,
                    'defender': player_mech,
                    'action': action_obj
                })

        if ap == 0:
            log.append(f"> AI {ai_mech.name} 已耗尽 AP。")
            break
        elif action_obj.cost == 'S' and current_available_s_count <= 1:
            log.append(f"> AI {ai_mech.name} 已执行唯一的 S 动作。")
            pass  # (这个 pass 不是必需的，但保留它以明确逻辑)

    if not opening_move_taken and not attacks_to_resolve_list:
        log.append(f"> AI {ai_mech.name} 结束回合，未执行任何主要动作。")

    ai_mech.player_ap = ap
    ai_mech.player_tp = tp

    return log, attacks_to_resolve_list