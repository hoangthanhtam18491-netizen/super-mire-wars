from flask import Blueprint, jsonify, request, session
from game_logic.game_logic import GameState
from game_logic.data_models import Mech
import game_logic.game_controller as controller

# [v_REFACTOR]
# “优化 1 & 2” - 这是一个新的蓝图文件
# 它包含所有的玩家动作 API (AJAX 调用)
# 它的大部分逻辑都委托给 game_controller.py

api_bp = Blueprint('api', __name__, url_prefix='/api')

MAX_LOG_ENTRIES = 50


def _get_game_state_and_player(data):
    """(辅助函数) 从 session 和 data 中安全地获取 game_state 和 player_mech。"""
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
    """(辅助函数) 处理来自 game_controller 的标准响应。"""
    if error:
        return jsonify({'success': False, 'message': error})

    log = session.get('combat_log', [])
    log.extend(log_entries)
    if len(log) > MAX_LOG_ENTRIES:
        log = log[-MAX_LOG_ENTRIES:]

    session['combat_log'] = log
    session['game_state'] = game_state.to_dict()
    session['visual_feedback_events'] = game_state.visual_events

    response = {'success': True}
    if result_data:
        response.update(result_data)

    return jsonify(response)


@api_bp.route('/select_timing', methods=['POST'])
def select_timing():
    data = request.get_json()
    game_state, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    new_state, logs, result, err = controller.handle_select_timing(game_state, player_mech, data.get('timing'))
    return _handle_controller_response(new_state, logs, result, err)


@api_bp.route('/confirm_timing', methods=['POST'])
def confirm_timing():
    data = request.get_json()
    game_state, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    new_state, logs, result, err = controller.handle_confirm_timing(game_state, player_mech)
    return _handle_controller_response(new_state, logs, result, err)


@api_bp.route('/change_stance', methods=['POST'])
def change_stance():
    data = request.get_json()
    game_state, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    new_state, logs, result, err = controller.handle_change_stance(game_state, player_mech, data.get('stance'))
    return _handle_controller_response(new_state, logs, result, err)


@api_bp.route('/confirm_stance', methods=['POST'])
def confirm_stance():
    data = request.get_json()
    game_state, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    new_state, logs, result, err = controller.handle_confirm_stance(game_state, player_mech)
    return _handle_controller_response(new_state, logs, result, err)


@api_bp.route('/execute_adjust_move', methods=['POST'])
def execute_adjust_move():
    data = request.get_json()
    game_state, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    new_state, logs, result, err = controller.handle_adjust_move(
        game_state, player_mech, data.get('target_pos'), data.get('final_orientation')
    )
    return _handle_controller_response(new_state, logs, result, err)


@api_bp.route('/change_orientation', methods=['POST'])
def change_orientation():
    data = request.get_json()
    game_state, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    new_state, logs, result, err = controller.handle_change_orientation(
        game_state, player_mech, data.get('final_orientation')
    )
    return _handle_controller_response(new_state, logs, result, err)


@api_bp.route('/skip_adjustment', methods=['POST'])
def skip_adjustment():
    data = request.get_json()
    game_state, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    new_state, logs, result, err = controller.handle_skip_adjustment(game_state, player_mech)
    return _handle_controller_response(new_state, logs, result, err)


@api_bp.route('/move_player', methods=['POST'])
def move_player():
    data = request.get_json()
    game_state, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    if player_mech.pending_effect_data:
        return jsonify({'success': False, 'message': '必须先选择效果！'})

    new_state, logs, result, err = controller.handle_move_player(
        game_state, player_mech,
        data.get('action_name'), data.get('part_slot'),
        data.get('target_pos'), data.get('final_orientation')
    )
    return _handle_controller_response(new_state, logs, result, err)


@api_bp.route('/execute_attack', methods=['POST'])
def execute_attack():
    data = request.get_json()
    game_state, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    if player_mech.pending_effect_data:
        return jsonify({'success': False, 'message': '必须先选择效果！'})

    # handle_execute_attack 返回 (game_state, log, visual_events, result_data, error_message)
    # [v_REFACTOR_FIX] 修复 ValueError。期望 5 个返回值，而不是 4 个。
    new_state, logs, _, result, err = controller.handle_execute_attack(game_state, player_mech, data)
    return _handle_controller_response(new_state, logs, result, err)


# [NEW] 弃置部件的 API 路由
@api_bp.route('/jettison_part', methods=['POST'])
def jettison_part():
    data = request.get_json()
    game_state, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    new_state, logs, result, err = controller.handle_jettison_part(
        game_state, player_mech, data.get('part_slot')
    )
    return _handle_controller_response(new_state, logs, result, err)


@api_bp.route('/resolve_effect_choice', methods=['POST'])
def resolve_effect_choice():
    data = request.get_json()
    game_state, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    new_state, logs, result, err = controller.handle_resolve_effect_choice(game_state, player_mech, data.get('choice'))
    return _handle_controller_response(new_state, logs, result, err)


@api_bp.route('/get_move_range', methods=['POST'])
def get_move_range():
    data = request.get_json()
    game_state, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    if game_state.game_over: return jsonify({'valid_moves': []})

    action_name = data.get('action_name')
    part_slot = data.get('part_slot')
    move_distance = 0
    is_flight_action = False

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
        return jsonify({'valid_moves': valid_moves})
    return jsonify({'valid_moves': []})


@api_bp.route('/get_attack_range', methods=['POST'])
def get_attack_range():
    data = request.get_json()
    game_state, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    if game_state.game_over:
        return jsonify({'valid_targets': [], 'valid_launch_cells': []})

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