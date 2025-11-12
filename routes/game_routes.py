import os
from flask import Blueprint, render_template, session, redirect, url_for, make_response, jsonify
from game_logic.game_logic import GameState, get_player_lock_status
from game_logic.data_models import Mech, Projectile

# [重构] 导入 *统一的* game_controller
# 我们不再从这个文件导入 combat_system, ai_system, dice_roller 等
# 所有的游戏逻辑都由 game_controller 统一处理
import game_logic.game_controller as controller

# [重构]
# 这个蓝图现在只处理“全页刷新”的路由 (GET /game, POST /end_turn 等)
# 所有的核心逻辑都已移至 game_controller.py

game_bp = Blueprint('game', __name__)

MAX_LOG_ENTRIES = 50


@game_bp.route('/game', methods=['GET'])
def game():
    """
    渲染主游戏界面。
    这个函数现在还负责处理和清除上一回合遗留的视觉事件。
    """
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

    # [重构] 事件处理逻辑:
    # 1. 从 game_state 中获取由控制器生成的事件
    visual_events = game_state_obj.visual_events or []

    # 2. 检查是否需要自动运行抛射物阶段
    # [FIX] 不要 'pop'！如果页面因重投而重载，标志会丢失。
    # 必须 'get'，并让 '/run_projectile_phase' 路由自己来 'pop'。
    run_projectile_phase_flag = session.get('run_projectile_phase', False)

    # 从环境变量读取 Firebase 配置
    firebase_config = os.environ.get('__firebase_config', '{}')
    app_id = os.environ.get('__app_id', 'default-app-id')
    auth_token = os.environ.get('__initial_auth_token', 'undefined')

    # 提取用于分析的数据
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

    # 3. 渲染模板
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
        visual_feedback_events=visual_events,  # 传递事件
        orientationMap=orientation_map,
        run_projectile_phase=run_projectile_phase_flag,
        firebase_config=firebase_config,
        app_id=app_id,
        initial_auth_token=auth_token,
        player_loadout=player_loadout,
        ai_opponent_name=ai_opponent_name
    )

    # 4. 渲染完成后，清除 game_state 中的瞬时状态
    # (例如 last_pos 和 visual_events)，然后保存回 session
    state_modified = False
    if game_state_obj.visual_events:
        # 仅当游戏 *不* 处于中断状态时才清除 visual_events
        if player_mech and not player_mech.pending_effect_data and not player_mech.pending_reroll_data:
            game_state_obj.visual_events = []
            state_modified = True

    for entity in game_state_obj.entities.values():
        if entity.last_pos:
            entity.last_pos = None
            state_modified = True

    if state_modified:
        session['game_state'] = game_state_obj.to_dict()

    # 5. 返回响应，禁止缓存
    response = make_response(html_to_render)
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@game_bp.route('/reset_game', methods=['POST'])
def reset_game():
    """清除会话数据，重置游戏并返回机库。"""
    session.pop('game_state', None)
    session.pop('combat_log', None)
    session.pop('visual_feedback_events', None)
    session.pop('run_projectile_phase', None)
    return redirect(url_for('main.hangar'))


@game_bp.route('/end_turn', methods=['POST'])
def end_turn():
    """
    [重构] 结束玩家回合。
    此函数不再包含任何游戏逻辑。
    它只是调用 game_controller 来处理回合结束。
    """
    game_state_obj = GameState.from_dict(session.get('game_state'))
    log = session.get('combat_log', [])

    # 1. 调用控制器
    updated_state, new_logs, result_data, error = controller.handle_end_turn(game_state_obj)

    # 2. 处理结果
    log.extend(new_logs)
    if error:
        log.append(error)  # 将控制器返回的错误添加到日志中

    # 3. 检查控制器是否要求立即运行抛射物阶段
    if result_data and result_data.get('run_projectile_phase'):
        # 设置一个标志，让 /game 路由在加载时知道要自动触发 JS
        session['run_projectile_phase'] = True

    # 4. 保存所有状态回 session
    session['game_state'] = updated_state.to_dict()
    if len(log) > MAX_LOG_ENTRIES:
        log = log[-MAX_LOG_ENTRIES:]
    session['combat_log'] = log

    # 5. 重定向回游戏界面
    return redirect(url_for('game.game'))


@game_bp.route('/run_projectile_phase', methods=['POST'])
def run_projectile_phase():
    """
    [重构] 运行抛射物阶段。
    这是一个由 game.js 中的 AJAX 调用的路由。
    它调用 game_controller 来处理此阶段。
    [FIX] 此路由现在返回 JSON，而不是重定向，
    以便 game.js 可以控制何时重载。
    """
    game_state_obj = GameState.from_dict(session.get('game_state'))
    log = session.get('combat_log', [])

    # 1. 消耗 'run_projectile_phase' 标志
    session.pop('run_projectile_phase', None)

    if game_state_obj.game_over:
        # 游戏已结束，直接返回成功，让前端重载
        return jsonify({'success': True, 'message': 'Game Over'})

    # 2. 调用控制器
    updated_state, new_logs, result_data, error = controller.handle_run_projectile_phase(game_state_obj)

    # 3. 处理结果
    log.extend(new_logs)
    if error:
        log.append(error)

    # 4. 保存所有状态回 session
    session['game_state'] = updated_state.to_dict()
    if len(log) > MAX_LOG_ENTRIES:
        log = log[-MAX_LOG_ENTRIES:]
    session['combat_log'] = log

    # 5. [FIX] 返回 JSON，让 game.js 来处理重载
    return jsonify({'success': True, 'message': 'Projectile phase processed'})


@game_bp.route('/respawn_ai', methods=['POST'])
def respawn_ai():
    """
    [重构] 在靶场模式下重生 AI。
    调用 game_controller 来处理。
    """
    game_state_obj = GameState.from_dict(session.get('game_state'))
    log = session.get('combat_log', [])

    # 1. 调用控制器
    updated_state, new_logs, result_data, error = controller.handle_respawn_ai(game_state_obj)

    # 2. 处理结果
    log.extend(new_logs)
    if error:
        log.append(error)

    # 3. 保存状态
    session['game_state'] = updated_state.to_dict()
    if len(log) > MAX_LOG_ENTRIES:
        log = log[-MAX_LOG_ENTRIES:]
    session['combat_log'] = log

    # 4. 重定向
    return redirect(url_for('game.game'))