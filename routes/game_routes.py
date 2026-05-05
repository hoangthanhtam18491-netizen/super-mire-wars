import traceback
from flask import Blueprint, render_template, session, redirect, url_for, make_response, jsonify
from game_logic.game_logic import GameState, get_player_lock_status
from game_logic.data_models import Mech, Projectile
from game_logic.config import MAX_LOG_ENTRIES, load_firebase_config, get_firebase_app_id, get_firebase_auth_token
import game_logic.game_controller as controller

#
# 这个蓝图 (Blueprint) 负责处理所有与主游戏界面相关的、
# 通常会导致"全页刷新"的路由。
#
# - GET /game: 渲染主游戏界面 (game.html)
# - POST /end_turn: 结束玩家回合，触发AI回合，然后刷新页面
# - POST /reset_game: 重置游戏并返回机库
# - POST /run_projectile_phase: (AJAX调用) 处理抛射物阶段，返回JSON
# - POST /respawn_ai: (靶场模式) 重生AI并刷新页面
#
# 所有的 AJAX API (如移动、攻击) 都在 api_routes.py 中处理。
#

game_bp = Blueprint('game', __name__)


def _truncate_and_save_log(log):
    """辅助函数：截断日志并保存到 session。"""
    if len(log) > MAX_LOG_ENTRIES:
        log = log[-MAX_LOG_ENTRIES:]
    session['combat_log'] = log


@game_bp.route('/game', methods=['GET'])
def game():
    """
    渲染主游戏界面 (game.html)。
    这是游戏的核心路由，负责从 session 加载完整的游戏状态，
    并将其传递给 Jinja2 模板进行渲染。
    """
    try:
        if 'game_state' not in session:
            return redirect(url_for('main.hangar'))

        game_state_obj = GameState.from_dict(session['game_state'])

        player_mech = game_state_obj.get_player_mech()
        ai_mech = game_state_obj.get_ai_mech()
        player_pilot = player_mech.pilot if player_mech else None
        ai_pilot = ai_mech.pilot if ai_mech else None

        if not player_mech:
            return redirect(url_for('main.hangar'))

        is_player_locked, locker_pos = get_player_lock_status(game_state_obj, player_mech)
        log = session.get('combat_log', [])

        visual_events = game_state_obj.visual_events or []

        pending_interrupt = session.pop('pending_interrupt_data', None)
        if pending_interrupt:
            action_required = pending_interrupt.get('action_required')
            if action_required:
                visual_events.append({
                    'type': action_required,
                    'details': pending_interrupt
                })
                game_state_obj.add_visual_event(action_required, details=pending_interrupt)

        run_projectile_phase_flag = session.get('run_projectile_phase', False)

        if game_state_obj.projectile_phase_active:
            run_projectile_phase_flag = True

        show_raven_intro = session.pop('show_raven_intro', False)

        firebase_config = load_firebase_config()
        app_id = get_firebase_app_id()
        auth_token = get_firebase_auth_token()

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

        html_to_render = render_template(
            'game.html',
            game=game_state_obj,
            player_mech=player_mech,
            ai_mech=ai_mech,
            player_pilot=player_pilot,
            ai_pilot=ai_pilot,
            combat_log=log,
            is_player_locked=is_player_locked,
            player_actions_used=player_actions_used_lists,
            game_mode=game_state_obj.game_mode,
            ai_defeat_count=game_state_obj.ai_defeat_count,
            visual_feedback_events=visual_events,
            orientationMap=orientation_map,
            run_projectile_phase=run_projectile_phase_flag,
            firebase_config=firebase_config,
            app_id=app_id,
            initial_auth_token=auth_token,
            player_loadout=player_loadout,
            ai_opponent_name=ai_opponent_name,
            show_raven_intro=show_raven_intro
        )

        state_modified = False
        if game_state_obj.visual_events:
            if player_mech and not player_mech.pending_combat:
                game_state_obj.visual_events = []
                state_modified = True

        for entity in game_state_obj.entities.values():
            if entity.last_pos:
                entity.last_pos = None
                state_modified = True

        if state_modified:
            session['game_state'] = game_state_obj.to_dict()

        response = make_response(html_to_render)
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response

    except Exception as e:
        traceback.print_exc()
        session.pop('game_state', None)
        session.pop('combat_log', None)
        return redirect(url_for('main.hangar'))


@game_bp.route('/reset_game', methods=['POST'])
def reset_game():
    """
    (POST) 清除会话数据，重置游戏并返回机库。
    """
    session.pop('game_state', None)
    session.pop('combat_log', None)
    session.pop('visual_feedback_events', None)
    session.pop('run_projectile_phase', None)
    session.pop('pending_interrupt_data', None)
    return redirect(url_for('main.hangar'))


@game_bp.route('/end_turn', methods=['POST'])
def end_turn():
    """
    (POST) 结束玩家回合。
    此路由将所有逻辑委托给 game_controller.handle_end_turn。
    """
    try:
        game_state_obj = GameState.from_dict(session.get('game_state'))
        log = session.get('combat_log', [])

        updated_state, new_logs, result_data, error = controller.handle_end_turn(game_state_obj)

        log.extend(new_logs)
        if error:
            log.append(error)

        if result_data and result_data.get('run_projectile_phase'):
            session['run_projectile_phase'] = True

        if result_data and result_data.get('action_required'):
            session['pending_interrupt_data'] = result_data
            session.pop('run_projectile_phase', None)

        session['game_state'] = updated_state.to_dict()
        _truncate_and_save_log(log)

        return redirect(url_for('game.game'))

    except Exception as e:
        traceback.print_exc()
        session['combat_log'] = session.get('combat_log', []) + [f'[系统错误] 回合结束失败: {str(e)}']
        return redirect(url_for('game.game'))


@game_bp.route('/run_projectile_phase', methods=['POST'])
def run_projectile_phase():
    """
    (AJAX POST) 运行抛射物阶段。
    这是一个由 game.js 自动调用的 AJAX 路由。
    """
    raw_state = session.get('game_state')
    if not raw_state:
        return jsonify({'success': False, 'message': 'Session expired', 'redirect': url_for('main.hangar')}), 401

    try:
        game_state_obj = GameState.from_dict(raw_state)
    except Exception as e:
        return jsonify({'success': False, 'message': f'State corrupted: {e}', 'redirect': url_for('main.hangar')}), 500

    log = session.get('combat_log', [])

    session.pop('run_projectile_phase', None)

    if game_state_obj.game_over:
        return jsonify({'success': True, 'message': 'Game Over'})

    try:
        updated_state, new_logs, result_data, error = controller.handle_run_projectile_phase(game_state_obj)

        log.extend(new_logs)
        if error:
            log.append(error)

        session['game_state'] = updated_state.to_dict()
        _truncate_and_save_log(log)

        response_data = {'success': True, 'message': 'Projectile phase processed'}
        if result_data:
            response_data.update(result_data)

        return jsonify(response_data)

    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'抛射物阶段错误: {str(e)}'}), 500


@game_bp.route('/respawn_ai', methods=['POST'])
def respawn_ai():
    """
    (POST) 在靶场模式下重生 AI。
    """
    try:
        game_state_obj = GameState.from_dict(session.get('game_state'))
        log = session.get('combat_log', [])

        updated_state, new_logs, result_data, error = controller.handle_respawn_ai(game_state_obj)

        log.extend(new_logs)
        if error:
            log.append(error)

        session['game_state'] = updated_state.to_dict()
        _truncate_and_save_log(log)

        return redirect(url_for('game.game'))

    except Exception as e:
        traceback.print_exc()
        return redirect(url_for('game.game'))
