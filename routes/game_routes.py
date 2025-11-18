import os
from flask import Blueprint, render_template, session, redirect, url_for, make_response, jsonify
from game_logic.game_logic import GameState, get_player_lock_status
from game_logic.data_models import Mech, Projectile
import game_logic.game_controller as controller

#
# 这个蓝图 (Blueprint) 负责处理所有与主游戏界面相关的、
# 通常会导致“全页刷新”的路由。
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

MAX_LOG_ENTRIES = 50


@game_bp.route('/game', methods=['GET'])
def game():
    """
    渲染主游戏界面 (game.html)。
    这是游戏的核心路由，负责从 session 加载完整的游戏状态，
    并将其传递给 Jinja2 模板进行渲染。
    """
    # 如果 session 中没有游戏状态 (例如服务器重启或 session 过期)，
    # 将玩家重定向回机库页面。
    if 'game_state' not in session:
        return redirect(url_for('main.hangar'))

    # 从 session 加载字典，并将其反序列化为 GameState 对象
    game_state_obj = GameState.from_dict(session['game_state'])

    # 为模板准备核心实体
    player_mech = game_state_obj.get_player_mech()
    ai_mech = game_state_obj.get_ai_mech()
    player_pilot = player_mech.pilot if player_mech else None
    ai_pilot = ai_mech.pilot if ai_mech else None

    if not player_mech:
        # 如果玩家机甲不存在 (数据损坏)，也重定向回机库
        return redirect(url_for('main.hangar'))

    # 检查玩家是否被AI锁定，并获取日志
    is_player_locked, locker_pos = get_player_lock_status(game_state_obj, player_mech)
    log = session.get('combat_log', [])

    # 1. 从 game_state 中获取由控制器(controller)生成的、需要前端显示的视觉事件
    visual_events = game_state_obj.visual_events or []

    # [BUG 2 修复] 检查 session 中是否有 'pending_interrupt_data'
    # 这是由 handle_end_turn 存储的、在重定向上丢失的中断数据
    pending_interrupt = session.pop('pending_interrupt_data', None)
    if pending_interrupt:
        # 找到一个待处理的中断！将其注入到 visual_events 中，
        # 这样 game.js 就能在页面加载时立即捕获它。
        action_required = pending_interrupt.get('action_required')
        if action_required:
            visual_events.append({
                'type': action_required,  # 'select_reroll' 或 'select_effect'
                'details': pending_interrupt
            })
            # [健壮性] 确保 game_state 也有这个事件，以防万一
            game_state_obj.add_visual_event(action_required, details=pending_interrupt)

    # 2. 检查 session 中是否有 'run_projectile_phase' 标志
    #    (由 /end_turn 路由设置)
    #    这会告诉 game.js 在页面加载后立即触发 AJAX 调用
    run_projectile_phase_flag = session.get('run_projectile_phase', False)

    # [FIX] 使用 projectile_phase_active 来判断是否需要继续运行抛射物阶段
    # 这比仅仅检查队列更健壮，因为它覆盖了队列被清空但阶段未结束的情况
    if game_state_obj.projectile_phase_active:
        run_projectile_phase_flag = True

    # 从环境变量读取 Firebase 配置 (用于分析)
    firebase_config = os.environ.get('__firebase_config', '{}')
    app_id = os.environ.get('__app_id', 'default-app-id')
    auth_token = os.environ.get('__initial_auth_token', 'undefined')

    # 提取用于游戏结束分析的数据
    player_loadout = {}
    if player_mech and player_mech.parts:
        player_loadout = {slot: part.name for slot, part in player_mech.parts.items() if part}

    ai_opponent_name = "Unknown AI"
    if ai_mech and ai_mech.name:
        ai_opponent_name = ai_mech.name

    # 用于在棋盘上显示方向的映射
    orientation_map = {
        'N': '↑', 'S': '↓', 'E': '→', 'W': '←',
        'NONE': ''
    }

    # 转换 actions_used_this_turn 为 JSON 兼容的列表
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
    #    (例如 last_pos 和 visual_events)，然后保存回 session
    state_modified = False
    if game_state_obj.visual_events:
        # [核心修复] 检查 'pending_combat'
        # 只有在玩家 *没有* 待处理的中断 (如重投) 时，才清除视觉事件。
        # 这可以防止刷新页面时丢失重投弹窗。
        if player_mech and not player_mech.pending_combat:
            game_state_obj.visual_events = []
            state_modified = True

    # 清除所有实体的 'last_pos' (用于动画)
    for entity in game_state_obj.entities.values():
        if entity.last_pos:
            entity.last_pos = None
            state_modified = True

    if state_modified:
        session['game_state'] = game_state_obj.to_dict()

    # 5. 返回响应，并设置HTTP头，禁止浏览器缓存游戏页面
    response = make_response(html_to_render)
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@game_bp.route('/reset_game', methods=['POST'])
def reset_game():
    """
    (POST) 清除会话数据，重置游戏并返回机库。
    """
    session.pop('game_state', None)
    session.pop('combat_log', None)
    session.pop('visual_feedback_events', None)
    session.pop('run_projectile_phase', None)
    session.pop('pending_interrupt_data', None)  # [BUG 2 修复] 清理
    return redirect(url_for('main.hangar'))


@game_bp.route('/end_turn', methods=['POST'])
def end_turn():
    """
    (POST) 结束玩家回合。
    此路由将所有逻辑委托给 game_controller.handle_end_turn。
    """
    game_state_obj = GameState.from_dict(session.get('game_state'))
    log = session.get('combat_log', [])

    # 1. 调用控制器处理回合结束逻辑 (包括AI回合)
    updated_state, new_logs, result_data, error = controller.handle_end_turn(game_state_obj)

    # 2. 处理日志和错误
    log.extend(new_logs)
    if error:
        log.append(error)

    # 3. 检查控制器是否要求立即运行抛射物阶段
    if result_data and result_data.get('run_projectile_phase'):
        # 设置一个标志，让 /game 路由在加载时知道要自动触发 JS
        session['run_projectile_phase'] = True

    # [BUG 2 修复] 检查是否发生了中断 (e.g., AI回合的攻击触发了玩家重投)
    if result_data and result_data.get('action_required'):
        # 不要丢失这个中断数据！将其存入 session。
        # GET /game 路由将会读取它并注入到 visual_events 中。
        session['pending_interrupt_data'] = result_data
        # 同时，确保我们不运行抛射物阶段，因为中断优先
        session.pop('run_projectile_phase', None)

    # 4. 保存所有状态回 session
    session['game_state'] = updated_state.to_dict()
    if len(log) > MAX_LOG_ENTRIES:
        log = log[-MAX_LOG_ENTRIES:]
    session['combat_log'] = log

    # 5. 重定向回游戏界面 (将触发 /game 的GET请求)
    return redirect(url_for('game.game'))


@game_bp.route('/run_projectile_phase', methods=['POST'])
def run_projectile_phase():
    """
    (AJAX POST) 运行抛射物阶段。
    这是一个由 game.js 自动调用的 AJAX 路由。
    它调用 game_controller 来处理抛射物移动和攻击。
    它返回 JSON 而不是重定向。
    """
    # [FIX] 防御性编程：检查 session 是否有效
    raw_state = session.get('game_state')
    if not raw_state:
        return jsonify({'success': False, 'message': 'Session expired', 'redirect': url_for('main.hangar')}), 401

    try:
        game_state_obj = GameState.from_dict(raw_state)
    except Exception as e:
        return jsonify({'success': False, 'message': f'State corrupted: {e}', 'redirect': url_for('main.hangar')}), 500

    log = session.get('combat_log', [])

    # 1. 消耗 'run_projectile_phase' 标志，防止重复运行
    session.pop('run_projectile_phase', None)

    if game_state_obj.game_over:
        return jsonify({'success': True, 'message': 'Game Over'})

    # 2. 调用控制器
    updated_state, new_logs, result_data, error = controller.handle_run_projectile_phase(game_state_obj)

    # 3. 处理日志和错误
    log.extend(new_logs)
    if error:
        log.append(error)

    # 4. 保存所有状态回 session
    session['game_state'] = updated_state.to_dict()
    if len(log) > MAX_LOG_ENTRIES:
        log = log[-MAX_LOG_ENTRIES:]
    session['combat_log'] = log

    # 5. [BUG 2 修复] 返回 JSON，通知 game.js 操作已完成
    #    **并且** 将 result_data (中断数据) 一起返回！
    response_data = {'success': True, 'message': 'Projectile phase processed'}
    if result_data:
        response_data.update(result_data)  # 合并中断数据

    return jsonify(response_data)


@game_bp.route('/respawn_ai', methods=['POST'])
def respawn_ai():
    """
    (POST) 在靶场模式下重生 AI。
    调用 game_controller 来处理。
    """
    game_state_obj = GameState.from_dict(session.get('game_state'))
    log = session.get('combat_log', [])

    # 1. 调用控制器
    updated_state, new_logs, result_data, error = controller.handle_respawn_ai(game_state_obj)

    # 2. 处理日志和错误
    log.extend(new_logs)
    if error:
        log.append(error)

    # 3. 保存状态
    session['game_state'] = updated_state.to_dict()
    if len(log) > MAX_LOG_ENTRIES:
        log = log[-MAX_LOG_ENTRIES:]
    session['combat_log'] = log

    # 4. 重定向回游戏界面
    return redirect(url_for('game.game'))