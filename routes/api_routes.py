import functools
import traceback
from flask import Blueprint, jsonify, request, session, url_for
from game_logic.game_logic import GameState
from game_logic.data_models import Mech
from game_logic.config import MAX_LOG_ENTRIES, BOARD_WIDTH, BOARD_HEIGHT, log_drone, log_err
import game_logic.game_controller as controller

#
# 这个蓝图包含了所有的玩家动作 API (由 game.js 中的 AJAX/fetch 调用)
# 它的大部分逻辑都委托给 game_controller.py 来处理
#

api_bp = Blueprint('api', __name__, url_prefix='/api')


# === 装饰器 ===

def handle_errors(f):
    """装饰器：包裹所有 API 路由，捕获未处理的异常并返回 JSON 错误。"""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            traceback.print_exc()
            return jsonify({'success': False, 'message': f'服务器内部错误: {str(e)}'}), 500
    return wrapper


# === 辅助函数 ===

def _check_no_combat(player_mech):
    """检查玩家是否有待处理的中断。如果有，返回错误 JSON；否则返回 None。"""
    if player_mech.pending_combat:
        return jsonify({'success': False, 'message': '必须先解决重投或效果！'})
    return None


def _check_no_combat_silent(player_mech):
    """检查玩家是否有待处理的中断。如果有，返回空数据 JSON；否则返回 None。
    用于范围获取端点（移动/攻击高亮），这些端点在有中断时不应报错，只返回空数据。"""
    if player_mech.pending_combat:
        return jsonify({})
    return None


def _check_not_downed(player_mech):
    """检查玩家是否处于宕机姿态。如果是，返回错误 JSON；否则返回 None。"""
    if player_mech.stance == 'downed':
        return jsonify({'success': False, 'message': '机甲宕机中，无法行动。请等待回合结束。'})
    return None


def _get_game_state_and_player(data):
    """
    (辅助函数) 安全地从 session 中获取当前的 game_state 和 player_mech 实例。
    这是所有 API 路由的第一步。
    """
    game_state_dict = session.get('game_state')
    if not game_state_dict:
        return None, None, jsonify({'success': False, 'message': '游戏状态丢失，请刷新。'})
    game_state_obj = GameState.from_dict(game_state_dict)

    player_id = data.get('player_id', 'player_1')
    player_mech = game_state_obj.get_entity_by_id(player_id)

    if not player_mech or not isinstance(player_mech, Mech):
        return game_state_obj, None, jsonify({'success': False, 'message': '找不到玩家机甲实体。'})

    return game_state_obj, player_mech, None


def _handle_controller_response(game_state, log_entries, result_data, error):
    """
    (辅助函数) 处理来自 game_controller 的标准响应。
    这是 game_state 持久化(保存)到 session 的唯一途径。
    """
    if error:
        return jsonify({'success': False, 'message': error})

    # 1. 更新日志
    log = session.get('combat_log', [])
    log.extend(log_entries)
    if len(log) > MAX_LOG_ENTRIES:
        log = log[-MAX_LOG_ENTRIES:]
    session['combat_log'] = log

    # 2. [关键] 保存控制器返回的、已经更新过的游戏状态
    session['game_state'] = game_state.to_dict()

    # 3. 清理已解决的中断（如果没有新的中断产生）
    if result_data and not result_data.get('action_required'):
        session.pop('pending_interrupt_data', None)
    elif not result_data:
        session.pop('pending_interrupt_data', None)

    # 4. 准备 JSON 响应
    response = {'success': True}
    if result_data:
        response.update(result_data)

    return jsonify(response)


# === 阶段 1 API (时机) ===

@api_bp.route('/select_timing', methods=['POST'])
@handle_errors
def select_timing():
    """API: 玩家选择时机"""
    data = request.get_json()
    game_state, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    error = _check_no_combat(player_mech)
    if error: return error

    error = _check_not_downed(player_mech)
    if error: return error

    new_state, logs, _, result, err = controller.handle_select_timing(game_state, player_mech, data.get('timing'))
    return _handle_controller_response(new_state, logs, result, err)


@api_bp.route('/confirm_timing', methods=['POST'])
@handle_errors
def confirm_timing():
    """API: 玩家确认时机"""
    data = request.get_json()
    game_state, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    error = _check_no_combat(player_mech)
    if error: return error

    error = _check_not_downed(player_mech)
    if error: return error

    new_state, logs, _, result, err = controller.handle_confirm_timing(game_state, player_mech)
    # 仅在没有中断时级联推进阶段
    if result and result.get('advance_round') and not result.get('action_required'):
        new_state, logs2, _, result2, err2 = controller.handle_advance_round(new_state)
        logs.extend(logs2)
        if result2:
            result.update(result2)
        if err2:
            err = err2
    return _handle_controller_response(new_state, logs, result, err)


# === 阶段 2 API (姿态) ===

@api_bp.route('/change_stance', methods=['POST'])
@handle_errors
def change_stance():
    """API: 玩家改变姿态"""
    data = request.get_json()
    game_state, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    error = _check_no_combat(player_mech)
    if error: return error

    error = _check_not_downed(player_mech)
    if error: return error

    new_state, logs, _, result, err = controller.handle_change_stance(game_state, player_mech, data.get('stance'))
    return _handle_controller_response(new_state, logs, result, err)


@api_bp.route('/confirm_stance', methods=['POST'])
@handle_errors
def confirm_stance():
    """API: 玩家确认姿态"""
    data = request.get_json()
    game_state, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    error = _check_no_combat(player_mech)
    if error: return error

    error = _check_not_downed(player_mech)
    if error: return error

    new_state, logs, _, result, err = controller.handle_confirm_stance(game_state, player_mech)
    return _handle_controller_response(new_state, logs, result, err)


# === 阶段 3 API (调整) ===

@api_bp.route('/execute_adjust_move', methods=['POST'])
@handle_errors
def execute_adjust_move():
    """API: 执行调整阶段的 [调整移动]"""
    data = request.get_json()
    game_state, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    error = _check_no_combat(player_mech)
    if error: return error

    error = _check_not_downed(player_mech)
    if error: return error

    new_state, logs, _, result, err = controller.handle_adjust_move(
        game_state, player_mech, data.get('target_pos'), data.get('final_orientation')
    )
    return _handle_controller_response(new_state, logs, result, err)


@api_bp.route('/change_orientation', methods=['POST'])
@handle_errors
def change_orientation():
    """API: 执行调整阶段的 [仅转向]"""
    data = request.get_json()
    game_state, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    error = _check_no_combat(player_mech)
    if error: return error

    error = _check_not_downed(player_mech)
    if error: return error

    new_state, logs, _, result, err = controller.handle_change_orientation(
        game_state, player_mech, data.get('final_orientation')
    )
    return _handle_controller_response(new_state, logs, result, err)


@api_bp.route('/skip_adjustment', methods=['POST'])
@handle_errors
def skip_adjustment():
    """API: 玩家 [跳过调整] 阶段"""
    data = request.get_json()
    game_state, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    error = _check_no_combat(player_mech)
    if error: return error

    error = _check_not_downed(player_mech)
    if error: return error

    new_state, logs, _, result, err = controller.handle_skip_adjustment(game_state, player_mech)
    return _handle_controller_response(new_state, logs, result, err)


# === 阶段 4 API (主动作) ===

@api_bp.route('/move_player', methods=['POST'])
@handle_errors
def move_player():
    """API: 执行主阶段的 [移动] 动作"""
    data = request.get_json()
    game_state, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    error = _check_no_combat(player_mech)
    if error: return error

    error = _check_not_downed(player_mech)
    if error: return error

    new_state, logs, _, result, err = controller.handle_move_player(
        game_state, player_mech,
        data.get('action_name'), data.get('part_slot'),
        data.get('target_pos'), data.get('final_orientation')
    )
    return _handle_controller_response(new_state, logs, result, err)


@api_bp.route('/execute_attack', methods=['POST'])
@handle_errors
def execute_attack():
    """API: 执行主阶段的 [攻击] 动作 (近战, 射击, 抛射)"""
    data = request.get_json()
    game_state, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    error = _check_no_combat(player_mech)
    if error: return error

    error = _check_not_downed(player_mech)
    if error: return error

    new_state, logs, _, result, err = controller.handle_execute_attack(game_state, player_mech, data)
    return _handle_controller_response(new_state, logs, result, err)


@api_bp.route('/jettison_part', methods=['POST'])
@handle_errors
def jettison_part():
    """API: 执行 [弃置] 动作"""
    data = request.get_json()
    game_state, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    error = _check_no_combat(player_mech)
    if error: return error

    error = _check_not_downed(player_mech)
    if error: return error

    new_state, logs, _, result, err = controller.handle_jettison_part(
        game_state, player_mech, data.get('part_slot')
    )
    return _handle_controller_response(new_state, logs, result, err)


@api_bp.route('/charge_part', methods=['POST'])
@handle_errors
def charge_part():
    """API: 执行 [充能] 动作"""
    data = request.get_json()
    game_state, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    error = _check_no_combat(player_mech)
    if error: return error

    error = _check_not_downed(player_mech)
    if error: return error

    new_state, logs, _, result, err = controller.handle_charge_part(
        game_state, player_mech,
        data.get('action_name'),
        data.get('part_slot'),
        data.get('target_part_slot')
    )
    return _handle_controller_response(new_state, logs, result, err)


@api_bp.route('/debug_skill', methods=['POST'])
@handle_errors
def debug_skill():
    """API: 激活技能【除虫】— 消耗1链接值获得1AP"""
    data = request.get_json()
    game_state, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    error = _check_no_combat(player_mech)
    if error: return error

    error = _check_not_downed(player_mech)
    if error: return error

    new_state, logs, _, result, err = controller.handle_debug_skill(game_state, player_mech)
    return _handle_controller_response(new_state, logs, result, err)


# === 无人机指令 API ===

@api_bp.route('/get_drone_move_range', methods=['POST'])
@handle_errors
def get_drone_move_range():
    """API: 获取无人机的可移动范围"""
    data = request.get_json()
    game_state, player_mech, error_response = _get_game_state_and_player(data)
    if error_response:
        return error_response

    drone_id = data.get('drone_id')
    drone = game_state.get_entity_by_id(drone_id)
    if not drone or drone.entity_type != 'drone' or drone.controller != 'player':
        return jsonify({'success': False, 'message': '无效的无人机ID。'})

    move_range = drone.move_range
    if move_range <= 0:
        return jsonify({'valid_moves': []})

    possible = game_state.calculate_move_range(drone, move_range, is_flight=True)
    mech_tiles = game_state.get_mech_occupied_tiles(exclude_id=drone.id)
    valid_moves = [list(p) for p in possible if p not in mech_tiles]
    return jsonify({'success': True, 'valid_moves': valid_moves})


# === 无人机指令 API ===

@api_bp.route('/assign_drone_command', methods=['POST'])
@handle_errors
def assign_drone_command():
    """API: 玩家分配指令标记给无人机并执行指令动作"""
    data = request.get_json()
    game_state, player_mech, error_response = _get_game_state_and_player(data)
    if error_response:
        return error_response

    # 跳过指令（消耗剩余标记但不执行动作）
    if data.get('skip'):
        game_state.command_markers_available = 0
        session['game_state'] = game_state.to_dict()
        return jsonify({'success': True, 'advance_round': True})

    drone_id = data.get('drone_id')
    drone = game_state.get_entity_by_id(drone_id)
    if not drone or drone.entity_type != 'drone' or drone.controller != 'player':
        return jsonify({'success': False, 'message': '无效的无人机ID。'})

    if drone.command_marker_received:
        return jsonify({'success': False, 'message': '该无人机本回合已获得指令标记。'})

    if game_state.command_markers_available <= 0:
        return jsonify({'success': False, 'message': '没有可用的指令标记。'})

    log = []
    game_state.visual_events = []

    drone.command_marker_received = True
    game_state.command_markers_assigned[drone.id] = True
    game_state.command_markers_available -= 1
    log.append(log_drone(f"玩家指定 [{drone.name}] 获得指令标记。"))

    # 查找最近敌人
    closest_enemy = None
    min_dist = 999
    for entity in game_state.entities.values():
        if entity.controller != drone.controller and entity.status != 'destroyed':
            dist = abs(drone.pos[0] - entity.pos[0]) + abs(drone.pos[1] - entity.pos[1])
            if dist < min_dist:
                min_dist = dist
                closest_enemy = entity

    # 玩家选择的动作（优先），否则回退到第一个指令动作
    action_name = data.get('action_name')
    if action_name:
        cmd_action = drone.get_action_by_name_and_slot(action_name, 'core')
    else:
        cmd_action, _ = drone.get_action_by_timing('指令')

    result_data = {}

    if cmd_action and cmd_action.action_type == '指令' and cmd_action.dice and closest_enemy:
        # 指令攻击动作
        log.append(log_drone(f"{drone.name} 执行 [{cmd_action.name}]，目标 {closest_enemy.name}"))
        from game_logic.ai_actions import _resolve_queued_attack
        atk_q = [{'attacker_id': drone.id, 'defender_id': closest_enemy.id,
                   'action_dict': cmd_action.to_dict()}]
        game_state, log, rd, _ = _resolve_queued_attack(game_state, log, atk_q[0], atk_q[1:])
        if rd:
            result_data.update(rd)
    else:
        # 指令移动（玩家选的动作或无攻击动作时默认）
        action_label = cmd_action.name if cmd_action else '指令移动'
        target_pos = data.get('target_pos')

        if target_pos:
            tx, ty = target_pos[0], target_pos[1]
            if (1 <= tx <= BOARD_WIDTH and 1 <= ty <= BOARD_HEIGHT):
                drone.last_pos = drone.pos
                drone.pos = (tx, ty)
                log.append(log_drone(f"{drone.name} 执行 [{action_label}] 移动至 {drone.pos}"))
            else:
                log.append(log_err(f"无效移动目标 {target_pos}"))
        else:
            controller._execute_drone_auto_move(drone, game_state, closest_enemy, log)
        result_data = {}

    # 检查是否还有可分配的标记和无人机
    remaining_drones = [e for e in game_state.entities.values()
                        if e.controller == 'player' and e.entity_type == 'drone' and e.status == 'ok'
                        and not e.command_marker_received]
    if game_state.command_markers_available <= 0 or not remaining_drones:
        # 所有标记已用完或无剩余无人机，推进阶段
        result_data['advance_round'] = True
    else:
        result_data['drone_command_phase'] = True
        result_data['command_markers_available'] = game_state.command_markers_available
        result_data['available_drones'] = [
            {'id': d.id, 'name': d.name, 'pos': d.pos, 'move_range': d.move_range,
             'actions': [{'name': a.name, 'type': a.action_type, 'range': a.range_val}
                         for a, s in d.get_all_actions() if a.action_type == '指令']}
            for d in remaining_drones
        ]

    # 传递视觉事件给前端（骰子动画等）
    if game_state.visual_events:
        result_data['visual_events'] = game_state.visual_events
        game_state.visual_events = []

    # 保存 game_state
    session['game_state'] = game_state.to_dict()
    combat_log = session.get('combat_log', [])
    combat_log.extend(log)
    if len(combat_log) > MAX_LOG_ENTRIES:
        combat_log = combat_log[-MAX_LOG_ENTRIES:]
    session['combat_log'] = combat_log

    response = {'success': True}
    response.update(result_data)
    return jsonify(response)


# === 中断处理 API ===

@api_bp.route('/resolve_effect_choice', methods=['POST'])
@handle_errors
def resolve_effect_choice():
    """API: 响应 [选择效果] 的中断"""
    data = request.get_json()
    game_state, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    # resolve_effect_choice 的检查更精细：只在 AWAITING_ATTACK_REROLL 阶段阻止
    if player_mech.pending_combat and player_mech.pending_combat.get('stage') == 'AWAITING_ATTACK_REROLL':
        return jsonify({'success': False, 'message': '必须先解决重投！'})

    new_state, logs, _, result, err = controller.handle_resolve_effect_choice(game_state, player_mech,
                                                                              data.get('choice'))

    return _handle_controller_response(new_state, logs, result, err)


@api_bp.route('/resolve_reroll', methods=['POST'])
@handle_errors
def resolve_reroll():
    """API: 响应 [专注重投] 的中断"""
    data = request.get_json()
    game_state, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    # 重投请求是最高优先级的，不需要检查其他中断
    new_state, logs, _, result_data, err = controller.handle_resolve_reroll(game_state, player_mech, data)

    return _handle_controller_response(new_state, logs, result_data, err)


# === 阶段推进 API ===

@api_bp.route('/advance_round', methods=['POST'])
@handle_errors
def advance_round():
    """API: 推进回合阶段"""
    data = request.get_json()
    game_state, player_mech, error_response = _get_game_state_and_player(data)
    if error_response:
        return error_response

    error = _check_no_combat(player_mech)
    if error:
        return error

    new_state, logs, _, result, err = controller.handle_advance_round(game_state)
    return _handle_controller_response(new_state, logs, result, err)


# === 范围获取 API (高亮) ===

@api_bp.route('/get_move_range', methods=['POST'])
@handle_errors
def get_move_range():
    """API: 获取 [移动] 动作的有效范围 (用于前端高亮)"""
    data = request.get_json()
    game_state, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    if game_state.game_over: return jsonify({'valid_moves': []})

    error = _check_no_combat_silent(player_mech)
    if error: return error

    action_name = data.get('action_name')
    part_slot = data.get('part_slot')
    move_distance = 0
    is_flight_action = False
    action = None

    if action_name == '调整移动':
        legs_part = player_mech.parts.get('legs')
        if legs_part and legs_part.status != 'destroyed':
            move_distance = legs_part.adjust_move
        for eff in player_mech.get_passive_effects():
            move_distance += eff.get('adjust_move_bonus', 0)
        if player_mech.stance == 'agile':
            move_distance *= 2
    else:
        action = player_mech.get_action_by_name_and_slot(action_name, part_slot)
        if action and action.action_type == '移动':
            move_distance = action.range_val
            if action.effects.get("flight_movement"):
                is_flight_action = True

    if move_distance > 0:
        valid_moves = game_state.calculate_move_range(
            player_mech, move_distance, is_flight=is_flight_action
        )

        if action and action.effects.get("straight_line_bonus"):
            bonus_distance = action.effects.get("straight_line_bonus", 0)
            total_straight_distance = move_distance + bonus_distance
            start_pos = player_mech.pos
            occupied_tiles = game_state.get_occupied_tiles(exclude_id=player_mech.id)

            for dx, dy in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
                for i in range(1, total_straight_distance + 1):
                    next_x = start_pos[0] + dx * i
                    next_y = start_pos[1] + dy * i
                    next_pos = (next_x, next_y)
                    if not (1 <= next_x <= game_state.board_width and 1 <= next_y <= game_state.board_height):
                        break
                    if next_pos in occupied_tiles:
                        break
                    valid_moves.append(next_pos)

        return jsonify({'valid_moves': list(set(valid_moves))})

    return jsonify({'valid_moves': []})


@api_bp.route('/get_attack_range', methods=['POST'])
@handle_errors
def get_attack_range():
    """API: 获取 [攻击] 动作的有效范围 (用于前端高亮)"""
    data = request.get_json()
    game_state, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    if game_state.game_over:
        return jsonify({'valid_targets': [], 'valid_launch_cells': []})

    error = _check_no_combat_silent(player_mech)
    if error: return error

    action_name = data.get('action_name')
    part_slot = data.get('part_slot')
    action = player_mech.get_action_by_name_and_slot(action_name, part_slot)

    if action:
        valid_targets_list, valid_launch_cells_list = game_state.calculate_attack_range(
            player_mech, action
        )

        serializable_targets = [
            {
                'entity_id': t['entity'].id,
                'pos': t['pos'],
                'is_back_attack': t['is_back_attack']
            } for t in valid_targets_list
        ]

        return jsonify({
            'valid_targets': serializable_targets,
            'valid_launch_cells': valid_launch_cells_list
        })

    return jsonify({'valid_targets': [], 'valid_launch_cells': []})


# === AJAX 局部刷新 ===

@api_bp.route('/game_state', methods=['GET'])
@handle_errors
def get_game_state():
    """返回完整游戏状态 JSON + 渲染后的侧边栏 HTML 片段，供 AJAX 局部刷新使用。"""
    from flask import render_template, url_for
    from game_logic.game_logic import get_player_lock_status

    if 'game_state' not in session:
        return jsonify({'success': False, 'message': 'Session expired', 'redirect': url_for('main.hangar')}), 401

    game_state_obj = GameState.from_dict(session['game_state'])

    player_mech = game_state_obj.get_player_mech()
    ai_mech = game_state_obj.get_ai_mech()
    player_pilot = player_mech.pilot if player_mech else None
    ai_pilot = ai_mech.pilot if ai_mech else None

    if not player_mech:
        return jsonify({'success': False, 'message': 'No player mech', 'redirect': url_for('main.hangar')}), 400

    is_player_locked, _ = get_player_lock_status(game_state_obj, player_mech)
    log = session.get('combat_log', [])

    player_loadout = {}
    if player_mech and player_mech.parts:
        player_loadout = {slot: part.name for slot, part in player_mech.parts.items() if part}

    ai_opponent_name = "Unknown AI"
    if ai_mech and ai_mech.name:
        ai_opponent_name = ai_mech.name

    orientation_map = {
        'N': '↑', 'S': '↓', 'E': '→', 'W': '←',
        'NONE': ''
    }

    player_actions_used_tuples = player_mech.actions_used_this_turn if player_mech else []
    player_actions_used_lists = [list(t) for t in player_actions_used_tuples]

    sidebar_left_html = render_template(
        '_sidebar_left.html',
        game_mode=game_state_obj.game_mode,
        ai_defeat_count=game_state_obj.ai_defeat_count,
        player_mech=player_mech,
        player_pilot=player_pilot,
        player_actions_used=player_actions_used_lists,
        game=game_state_obj
    )

    sidebar_right_html = render_template(
        '_sidebar_right.html',
        ai_mech=ai_mech,
        ai_pilot=ai_pilot,
        combat_log=log
    )

    board_entities_html = render_template(
        '_board_entities.html',
        game=game_state_obj,
        orientationMap=orientation_map
    )

    game_data = {
        'allEntities': game_state_obj.get_all_entities_as_dict(),
        'playerID': player_mech.id if player_mech else '',
        'playerEntity': player_mech.to_dict() if player_mech else None,
        'aiEntity': ai_mech.to_dict() if ai_mech else None,
        'isPlayerLocked': is_player_locked,
        'gameOver': game_state_obj.game_over or '',
        'visualEvents': game_state_obj.visual_events or [],
        'runProjectilePhase': session.get('run_projectile_phase', False),
        'gameMode': game_state_obj.game_mode,
        'defeatCount': game_state_obj.ai_defeat_count,
        'orientationMap': orientation_map,
        'playerLoadout': player_loadout,
        'aiOpponentName': ai_opponent_name,
        'roundPhase': game_state_obj.round_phase,
        'phaseIndex': game_state_obj.phase_index,
        'roundNumber': game_state_obj.round_number,
        'apiUrls': {
            'gameState': url_for('api.get_game_state'),
            'runProjectilePhase': url_for('game.run_projectile_phase'),
            'resetGame': url_for('game.reset_game'),
            'respawnAi': url_for('game.respawn_ai'),
            'endTurn': url_for('game.end_turn'),
            'endTurnAjax': url_for('api.end_turn_ajax'),
            'selectTiming': url_for('api.select_timing'),
            'confirmTiming': url_for('api.confirm_timing'),
            'changeStance': url_for('api.change_stance'),
            'confirmStance': url_for('api.confirm_stance'),
            'skipAdjustment': url_for('api.skip_adjustment'),
            'jettisonPart': url_for('api.jettison_part'),
            'chargePart': url_for('api.charge_part'),
            'resolveEffectChoice': url_for('api.resolve_effect_choice'),
            'resolveReroll': url_for('api.resolve_reroll'),
            'getMoveRange': url_for('api.get_move_range'),
            'getAttackRange': url_for('api.get_attack_range'),
            'executeAttack': url_for('api.execute_attack'),
            'debugSkill': url_for('api.debug_skill'),
            'movePlayer': url_for('api.move_player'),
            'executeAdjustMove': url_for('api.execute_adjust_move'),
            'changeOrientation': url_for('api.change_orientation'),
            'advanceRound': url_for('api.advance_round'),
            'assignDroneCommand': url_for('api.assign_drone_command'),
            'getDroneMoveRange': url_for('api.get_drone_move_range')
        }
    }

    # 清除已消费的视觉事件（与 /game 路由保持一致）
    if game_state_obj.visual_events:
        if player_mech and not player_mech.pending_combat:
            game_state_obj.visual_events = []
            session['game_state'] = game_state_obj.to_dict()

    return jsonify({
        'success': True,
        'game_data': game_data,
        'sidebar_left_html': sidebar_left_html,
        'sidebar_right_html': sidebar_right_html,
        'board_entities_html': board_entities_html
    })


# === AJAX 结束回合 ===

@api_bp.route('/end_turn', methods=['POST'])
@handle_errors
def end_turn_ajax():
    """AJAX 版本结束回合：处理 AI 回合，返回 JSON 而非 redirect。"""
    raw_state = session.get('game_state')
    if not raw_state:
        return jsonify({'success': False, 'message': 'Session expired', 'redirect': url_for('main.hangar')}), 401

    game_state_obj = GameState.from_dict(raw_state)
    log = session.get('combat_log', [])

    updated_state, new_logs, _, result_data, error = controller.handle_advance_round(game_state_obj)

    log.extend(new_logs)
    if error:
        log.append(log_err(error))

    if result_data and result_data.get('action_required'):
        session['pending_interrupt_data'] = result_data
    else:
        session.pop('pending_interrupt_data', None)

    session['game_state'] = updated_state.to_dict()

    if len(log) > MAX_LOG_ENTRIES:
        log = log[-MAX_LOG_ENTRIES:]
    session['combat_log'] = log

    response_data = {'success': True}
    if result_data:
        response_data.update(result_data)

    return jsonify(response_data)
