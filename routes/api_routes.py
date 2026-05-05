import functools
import traceback
from flask import Blueprint, jsonify, request, session
from game_logic.game_logic import GameState
from game_logic.data_models import Mech
from game_logic.config import MAX_LOG_ENTRIES
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

    # 3. 准备 JSON 响应
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

    new_state, logs, _, result, err = controller.handle_confirm_timing(game_state, player_mech)
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

    new_state, logs, _, result, err = controller.handle_jettison_part(
        game_state, player_mech, data.get('part_slot')
    )
    return _handle_controller_response(new_state, logs, result, err)


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
