import os
import random
import tempfile  # [新增] 导入 tempfile
from flask import Flask, render_template, jsonify, request, session, redirect, url_for
from flask_session import Session  # [新增] 导入 flask_session
from data_models import Mech, Part, Action
from combat_system import resolve_attack, _resolve_effect_logic  # [修改 v1.13] 导入新的辅助函数
from dice_roller import roll_black_die
from game_logic import (
    GameState, is_back_attack, create_mech_from_selection, get_player_lock_status,
    AI_LOADOUTS,
    _get_distance, is_in_forward_arc
)
from ai_system import run_ai_turn
from parts_database import (
    PLAYER_CORES, PLAYER_LEGS, PLAYER_LEFT_ARMS, PLAYER_RIGHT_ARMS, PLAYER_BACKPACKS
)
import markdown
import bleach

app = Flask(__name__)
app.secret_key = os.urandom(24)

# --- [新增] 服务器端会话配置 ---
# 1. 设置会话类型为 "filesystem"（存储在服务器硬盘上）
app.config["SESSION_TYPE"] = "filesystem"
# 2. 为会话文件创建一个临时目录
app.config["SESSION_FILE_DIR"] = tempfile.mkdtemp()
# 3. 会话在浏览器关闭时失效
app.config["SESSION_PERMANENT"] = False
# 4. 初始化 Session 插件
Session(app)
# --- 会话配置结束 ---

# [新增] 日志条目限制
MAX_LOG_ENTRIES = 50


# [新增] 用于清除一次性视觉效果的辅助函数
def clear_visual_feedback():
    """清除会话中的一次性事件。"""
    session['visual_feedback_events'] = []
    # 重置 last_pos，这样刷新页面时不会重复播放动画
    if 'game_state' in session:
        game = GameState.from_dict(session['game_state'])
        game.last_player_pos = None
        game.last_ai_pos = None
        session['game_state'] = game.to_dict()


# --- 核心路由 ---

@app.route('/')
def index():
    """渲染游戏的主索引/开始页面。"""
    update_notes = [
        "版本 v1.3:",
        "- 增加了新的部件与效果",
        "- 优化了AI逻辑",
        "- [新增] 实现了移动和攻击的视觉反馈！"
    ]
    rules_html = ""
    try:
        with open("Game Introduction.md", "r", encoding="utf-8") as f:
            md_content = f.read()
            html = markdown.markdown(md_content)
            allowed_tags = ['h1', 'h2', 'h3', 'p', 'ul', 'ol', 'li', 'strong', 'em', 'br', 'div']
            rules_html = bleach.clean(html, tags=allowed_tags)
    except FileNotFoundError:
        rules_html = "<p>错误：未找到 Game Introduction.md 文件。</p>"
    except Exception as e:
        rules_html = f"<p>加载规则时出错: {e}</p>"

    return render_template('index.html', update_notes=update_notes, rules_html=rules_html)


@app.route('/hangar')
def hangar():
    """渲染机库页面，用于机甲组装和模式选择。"""
    return render_template(
        'hangar.html',
        cores=PLAYER_CORES,
        legs=PLAYER_LEGS,
        left_arms=PLAYER_LEFT_ARMS,
        right_arms=PLAYER_RIGHT_ARMS,
        backpacks=PLAYER_BACKPACKS,
        ai_loadouts=AI_LOADOUTS
    )


@app.route('/start_game', methods=['POST'])
def start_game():
    """处理来自机库的表单，初始化游戏状态并重定向到游戏界面。"""
    selection = {
        'core': request.form.get('core'),
        'legs': request.form.get('legs'),
        'left_arm': request.form.get('left_arm'),
        'right_arm': request.form.get('right_arm'),
        'backpack': request.form.get('backpack')
    }
    game_mode = request.form.get('game_mode', 'duel')
    ai_opponent_key = request.form.get('ai_opponent')
    player_mech = create_mech_from_selection("玩家机甲", selection)
    game = GameState(
        player_mech=player_mech,
        ai_loadout_key=ai_opponent_key,
        game_mode=game_mode
    )
    session['game_state'] = game.to_dict()
    log = [f"> 玩家机甲组装完毕。"]
    if game_mode == 'horde':
        log.append(f"> [生存模式] 已启动。")
        log.append(f"> 第一波遭遇: {game.ai_mech.name}。")
    else:
        log.append(f"> [决斗模式] 已启动。")
        log.append(f"> 遭遇敌机: {game.ai_mech.name}。")
    log.append("> 战斗开始！")

    # [修改] 日志裁剪
    if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
    session['combat_log'] = log
    session['visual_feedback_events'] = []  # [新增] 初始化视觉事件列表
    return redirect(url_for('game'))


@app.route('/game', methods=['GET'])
def game():
    """渲染主游戏界面，显示棋盘、状态和日志。"""
    if 'game_state' not in session:
        return redirect(url_for('hangar'))
    game_state_obj = GameState.from_dict(session['game_state'])
    if not game_state_obj.player_mech:
        return redirect(url_for('hangar'))
    is_player_locked, locker_pos = get_player_lock_status(game_state_obj)
    log = session.get('combat_log', [])

    # [新增] 获取并传递视觉事件
    visual_events = session.get('visual_feedback_events', [])

    return render_template(
        'game.html',
        game=game_state_obj,
        combat_log=log,
        is_player_locked=is_player_locked,
        player_actions_used=game_state_obj.player_actions_used_this_turn,
        game_mode=game_state_obj.game_mode,
        ai_defeat_count=game_state_obj.ai_defeat_count,
        visual_feedback_events=visual_events  # [新增]
    )


@app.route('/reset_game', methods=['POST'])
def reset_game():
    """清除会话数据，重置游戏并返回机库。"""
    session.pop('game_state', None)
    session.pop('combat_log', None)
    session.pop('visual_feedback_events', None)  # [新增]
    return redirect(url_for('hangar'))


@app.route('/end_turn', methods=['POST'])
def end_turn():
    """玩家结束回合，触发AI回合逻辑，并在AI行动后刷新游戏状态。"""
    clear_visual_feedback()  # [新增] 清除玩家的旧事件
    game_state_obj = GameState.from_dict(session.get('game_state'))
    if game_state_obj.game_over:
        return redirect(url_for('game'))

    log = session.get('combat_log', [])
    if game_state_obj.pending_effect_data:
        log.append("> [错误] 必须先选择效果才能结束回合！")
        # [修改] 日志裁剪
        if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
        session['combat_log'] = log
        return redirect(url_for('game'))

    log.append("-" * 20)
    log.append("> 玩家回合结束。")
    ai_turn_log, attacks_to_resolve_list = run_ai_turn(game_state_obj)
    log.extend(ai_turn_log)
    if not attacks_to_resolve_list:
        log.append("> AI 未执行攻击。")
    for attack_action in attacks_to_resolve_list:
        log.append(f"--- AI 攻击结算 ({attack_action.name}) ---")
        back_attack = is_back_attack(game_state_obj.ai_pos, game_state_obj.player_pos,
                                     game_state_obj.player_mech.orientation)
        target_part_slot = None
        if attack_action.action_type == '近战' and not back_attack:
            parry_parts = [(s, p) for s, p in game_state_obj.player_mech.parts.items() if
                           p.parry > 0 and p.status != 'destroyed']
            if parry_parts:
                target_part_slot, best_parry_part = max(parry_parts, key=lambda item: item[1].parry)
                log.append(f"> 玩家决定用 [{best_parry_part.name}] 进行招架！")
        if not target_part_slot:
            hit_roll_result = roll_black_die()
            log.append(f"> AI 投掷部位骰结果: 【{hit_roll_result}】")
            if hit_roll_result == 'any' or back_attack:
                if back_attack:
                    log.append("> [背击] AI 获得任意选择权！")
                else:
                    log.append("> AI 获得任意选择权！")
                damaged_parts = [s for s, p in game_state_obj.player_mech.parts.items() if p.status == 'damaged']
                if damaged_parts:
                    target_part_slot = random.choice(damaged_parts)
                    log.append(f"> AI 优先攻击已受损部件: [{target_part_slot}]。")
                elif game_state_obj.player_mech.parts['core'].status != 'destroyed':
                    target_part_slot = 'core'
                    log.append("> AI 决定攻击 [核心]。")
                else:
                    valid_parts = [s for s, p in game_state_obj.player_mech.parts.items() if p.status != 'destroyed']
                    target_part_slot = random.choice(valid_parts) if valid_parts else 'core'
            elif game_state_obj.player_mech.parts.get(hit_roll_result) and game_state_obj.player_mech.parts[
                hit_roll_result].status != 'destroyed':
                target_part_slot = hit_roll_result
            else:
                target_part_slot = 'core'
                log.append(f"> 部位 [{hit_roll_result}] 不存在或已摧毁，转而命中 [核心]。")

        # [修改 v1.13] resolve_attack 现在返回 overflow_data
        attack_log, result, overflow_data = resolve_attack(
            attacker_mech=game_state_obj.ai_mech,
            defender_mech=game_state_obj.player_mech,
            action=attack_action,
            target_part_name=target_part_slot,
            is_back_attack=back_attack,
            chosen_effect=None  # AI 会自动选择效果，不需要玩家介入
        )
        log.extend(attack_log)

        # [新增] 为AI攻击添加视觉反馈事件
        session['visual_feedback_events'].append({
            'type': 'attack_result',
            'attacker_pos': game_state_obj.ai_pos,
            'defender_pos': game_state_obj.player_pos,
            'result_text': result  # '击穿' 或 '无效'
        })

        # [修改 v1.13] AI 攻击不需要玩家选择，所以 effect_choice_required 逻辑已移除

        game_is_over = game_state_obj.check_game_over()
        if game_is_over and game_state_obj.game_over == 'ai_win':
            log.append(f"> 玩家机甲已被摧毁！")
            if game_state_obj.game_mode == 'horde':
                log.append(f"> [生存模式] 最终击败数: {game_state_obj.ai_defeat_count}")
            break
    if not game_state_obj.game_over:
        log.append("> AI回合结束。请开始你的回合。")
        log.append("-" * 20)
        game_state_obj.current_turn = 'player'
        game_state_obj.player_ap = 2
        game_state_obj.player_tp = 1
        game_state_obj.turn_phase = 'timing'
        game_state_obj.timing = None
        game_state_obj.opening_move_taken = False
        game_state_obj.player_actions_used_this_turn = []
        game_state_obj.pending_effect_data = None

        # [新增] 重置玩家和AI的上一个位置，为玩家回合做准备
        game_state_obj.last_player_pos = None
        game_state_obj.last_ai_pos = game_state_obj.ai_mech.last_pos  # 从机甲对象同步

        game_state_obj.check_game_over()

    session['game_state'] = game_state_obj.to_dict()
    # [修改] 日志裁剪
    if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
    session['combat_log'] = log
    return redirect(url_for('game'))


# --- 行动阶段与玩家动作路由 ---

@app.route('/select_timing', methods=['POST'])
def select_timing():
    clear_visual_feedback()  # [新增] 清除旧事件
    data = request.get_json()
    timing = data.get('timing')
    game_state_obj = GameState.from_dict(session.get('game_state'))
    if game_state_obj.turn_phase == 'timing' and not game_state_obj.game_over:
        game_state_obj.timing = timing
        session['game_state'] = game_state_obj.to_dict()
        return jsonify({'success': True})
    return jsonify({'success': False})


@app.route('/confirm_timing', methods=['POST'])
def confirm_timing():
    clear_visual_feedback()  # [新增] 清除旧事件
    game_state_obj = GameState.from_dict(session.get('game_state'))
    if game_state_obj.turn_phase == 'timing' and game_state_obj.timing and not game_state_obj.game_over:
        game_state_obj.turn_phase = 'stance'
        session['game_state'] = game_state_obj.to_dict()
        log = session.get('combat_log', [])
        log.append(f"> 时机已确认为 [{game_state_obj.timing}]。进入姿态选择阶段。")
        # [修改] 日志裁剪
        if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
        session['combat_log'] = log
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Please select a timing first.'})


@app.route('/change_stance', methods=['POST'])
def change_stance():
    clear_visual_feedback()  # [新增] 清除旧事件
    data = request.get_json()
    new_stance = data.get('stance')
    game_state_obj = GameState.from_dict(session.get('game_state'))
    if game_state_obj.turn_phase == 'stance' and not game_state_obj.game_over:
        game_state_obj.player_mech.stance = new_stance
        session['game_state'] = game_state_obj.to_dict()
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Not in stance phase.'})


@app.route('/confirm_stance', methods=['POST'])
def confirm_stance():
    clear_visual_feedback()  # [新增] 清除旧事件
    game_state_obj = GameState.from_dict(session.get('game_state'))
    if game_state_obj.turn_phase == 'stance' and not game_state_obj.game_over:
        game_state_obj.turn_phase = 'adjustment'
        session['game_state'] = game_state_obj.to_dict()
        log = session.get('combat_log', [])
        log.append(f"> 姿态已确认为 [{game_state_obj.player_mech.stance}]。进入调整阶段。")
        # [修改] 日志裁剪
        if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
        session['combat_log'] = log
        return jsonify({'success': True})
    return jsonify({'success': False})


@app.route('/execute_adjust_move', methods=['POST'])
def execute_adjust_move():
    clear_visual_feedback()  # [新增] 清除旧事件
    data = request.get_json()
    game_state_obj = GameState.from_dict(session.get('game_state'))
    if game_state_obj.turn_phase == 'adjustment' and game_state_obj.player_tp >= 1 and not game_state_obj.game_over:
        game_state_obj.last_player_pos = game_state_obj.player_pos  # [新增] 记录移动前的位置
        game_state_obj.player_pos = tuple(data.get('target_pos'))
        game_state_obj.player_mech.orientation = data.get('final_orientation')
        game_state_obj.player_tp -= 1
        game_state_obj.turn_phase = 'main'
        session['game_state'] = game_state_obj.to_dict()
        log = session.get('combat_log', [])
        log.append(f"> 玩家调整移动到 {game_state_obj.player_pos}。进入主动作阶段。")
        # [修改] 日志裁剪
        if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
        session['combat_log'] = log
        return jsonify({'success': True})
    return jsonify({'success': False})


@app.route('/change_orientation', methods=['POST'])
def change_orientation():
    clear_visual_feedback()  # [新增] 清除旧事件
    data = request.get_json()
    game_state_obj = GameState.from_dict(session.get('game_state'))
    if game_state_obj.turn_phase == 'adjustment' and game_state_obj.player_tp >= 1 and not game_state_obj.game_over:
        game_state_obj.player_mech.orientation = data.get('final_orientation')
        game_state_obj.player_tp -= 1
        game_state_obj.turn_phase = 'main'
        session['game_state'] = game_state_obj.to_dict()
        log = session.get('combat_log', [])
        log.append(f"> 玩家仅转向。进入主动作阶段。")
        # [修改] 日志裁剪
        if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
        session['combat_log'] = log
        return jsonify({'success': True})
    return jsonify({'success': False})


@app.route('/skip_adjustment', methods=['POST'])
def skip_adjustment():
    clear_visual_feedback()  # [新增] 清除旧事件
    game_state_obj = GameState.from_dict(session.get('game_state'))
    if game_state_obj.turn_phase == 'adjustment' and not game_state_obj.game_over:
        game_state_obj.turn_phase = 'main'
        session['game_state'] = game_state_obj.to_dict()
        log = session.get('combat_log', [])
        log.append(f"> 玩家跳过调整阶段。进入主动作阶段。")
        # [修改] 日志裁剪
        if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
        session['combat_log'] = log
        return jsonify({'success': True})
    return jsonify({'success': False})


def execute_main_action(game, action, action_name, part_slot):
    """ (服务器端) 验证并执行一个主动作。 """
    log = session.get('combat_log', [])
    action_id = (part_slot, action_name)
    if action_id in game.player_actions_used_this_turn:
        log.append(f"> [错误] [{action_name}] (来自: {part_slot}) 本回合已使用过。")
        # [修改] 日志裁剪
        if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
        session['combat_log'] = log
        return False
    ap_cost = action.cost.count('M') * 2 + action.cost.count('S') * 1
    tp_cost = 0
    if action.cost == 'L':
        ap_cost = 2
        tp_cost = 1
    if game.player_ap < ap_cost:
        log.append(f"> [错误] AP不足 (需要 {ap_cost})，无法执行 [{action.name}]。")
        # [修改] 日志裁剪
        if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
        session['combat_log'] = log
        return False
    if game.player_tp < tp_cost:
        log.append(f"> [错误] TP不足 (需要 {tp_cost})，无法执行 [{action.name}]。")
        # [修改] 日志裁剪
        if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
        session['combat_log'] = log
        return False
    if not game.opening_move_taken:
        if action.action_type != game.timing:
            log.append(
                f"> [错误] 起手动作错误！当前时机为 [{game.timing}]，无法执行 [{action.action_type}] 动作。")
            # [修改] 日志裁剪
            if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
            session['combat_log'] = log
            return False
        game.opening_move_taken = True
    game.player_ap -= ap_cost
    game.player_tp -= tp_cost
    game.player_actions_used_this_turn.append(action_id)
    return True


@app.route('/move_player', methods=['POST'])
def move_player():
    """(AJAX) 处理玩家的“移动”类型动作（非调整移动）。"""
    clear_visual_feedback()  # [新增] 清除旧事件
    data = request.get_json()
    game_state_obj = GameState.from_dict(session.get('game_state'))
    if game_state_obj.game_over: return jsonify({'success': False})

    log = session.get('combat_log', [])
    if game_state_obj.pending_effect_data:
        log.append("> [错误] 必须先解决待处理的效果选择！")
        if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
        session['combat_log'] = log
        return jsonify({'success': False, 'message': '必须先选择效果！'})

    action_name = data.get('action_name')
    part_slot = data.get('part_slot')
    action = None
    if part_slot and part_slot in game_state_obj.player_mech.parts:
        part = game_state_obj.player_mech.parts[part_slot]
        if part.status != 'destroyed':
            action = next((a for a in part.actions if a.name == action_name), None)
    if game_state_obj.turn_phase == 'main' and action and execute_main_action(game_state_obj, action, action_name,
                                                                              part_slot):
        game_state_obj.last_player_pos = game_state_obj.player_pos  # [新增] 记录移动前的位置
        game_state_obj.player_pos = tuple(data.get('target_pos'))
        game_state_obj.player_mech.orientation = data.get('final_orientation')
        session['game_state'] = game_state_obj.to_dict()
        log.append(f"> 玩家执行 [{action.name}]。")
        # [修改] 日志裁剪
        if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
        session['combat_log'] = log
        return jsonify({'success': True})
    return jsonify({'success': False})


@app.route('/execute_attack', methods=['POST'])
def execute_attack():
    """ (AJAX) 处理玩家的“攻击”动作（近战或射击）。 """
    clear_visual_feedback()  # [新增] 清除旧事件
    data = request.get_json()
    game_state_obj = GameState.from_dict(session.get('game_state'))
    log = session.get('combat_log', [])
    if game_state_obj.game_over: return jsonify({'success': False})

    if game_state_obj.pending_effect_data:
        log.append("> [错误] 必须先解决待处理的效果选择！")
        if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
        session['combat_log'] = log
        return jsonify({'success': False, 'message': '必须先选择效果！'})

    action_name = data.get('action_name')
    part_slot = data.get('part_slot')
    attack_action = None
    if part_slot and part_slot in game_state_obj.player_mech.parts:
        part = game_state_obj.player_mech.parts[part_slot]
        if part.status != 'destroyed':
            attack_action = next((a for a in part.actions if a.name == action_name), None)

    if game_state_obj.turn_phase == 'main' and attack_action:
        # --- (验证逻辑) ---
        if attack_action.action_type == '射击':
            effective_range = attack_action.range_val
            static_bonus = attack_action.effects.get("static_range_bonus", 0)
            if static_bonus > 0 and game_state_obj.player_tp >= 1:
                effective_range += static_bonus
                log.append(f"> 动作效果【静止】触发！射程 +{static_bonus}。")
            two_handed_bonus = attack_action.effects.get("two_handed_range_bonus", 0)
            if two_handed_bonus > 0:
                other_arm_slot = 'left_arm' if part_slot == 'right_arm' else 'right_arm'
                other_arm_part = game_state_obj.player_mech.parts.get(other_arm_slot)
                if other_arm_part and "【空手】" in other_arm_part.tags:
                    effective_range += two_handed_bonus
                    log.append(f"> 动作效果【【双手】+2射程】触发 (另一只手为【空手】)！射程 +{two_handed_bonus}。")
            target_pos_tuple = tuple(data.get('target_pos'))
            dist = _get_distance(game_state_obj.player_pos, target_pos_tuple)
            if dist > effective_range:
                log.append(f"> [错误] 目标超出有效射程 {effective_range} (距离 {dist})。")
                if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
                session['combat_log'] = log
                return jsonify({'success': False, 'message': 'Target out of range.'})
            if not is_in_forward_arc(game_state_obj.player_pos, game_state_obj.player_mech.orientation,
                                     target_pos_tuple):
                log.append(f"> [错误] 目标不在前方视线内。")
                if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
                session['combat_log'] = log
                return jsonify({'success': False, 'message': 'Target not in forward arc.'})
        if attack_action.action_type == '近战':
            valid_targets = game_state_obj.calculate_attack_range(
                game_state_obj.player_mech, game_state_obj.player_pos, attack_action
            )
            if not any(t['pos'] == tuple(data.get('target_pos')) for t in valid_targets):
                log.append(f"> [错误] 目标不在近战攻击范围内。")
                if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
                session['combat_log'] = log
                return jsonify({'success': False, 'message': 'Target out of melee range.'})
        is_player_locked, _ = get_player_lock_status(game_state_obj)
        if is_player_locked and attack_action.action_type == '射击':
            log.append(f"> [错误] 你被近战锁定，无法执行 [{attack_action.name}]！")
            if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
            session['combat_log'] = log
            return jsonify({'success': False, 'message': '被近战锁定，无法射击！'})
        back_attack = is_back_attack(game_state_obj.player_pos, game_state_obj.ai_pos,
                                     game_state_obj.ai_mech.orientation)
        target_part_slot = data.get('target_part_name')
        has_two_handed_sniper = attack_action.effects.get("two_handed_sniper", False)
        two_handed_sniper_active = False
        if has_two_handed_sniper:
            other_arm_slot = 'left_arm' if part_slot == 'right_arm' else 'right_arm'
            other_arm_part = game_state_obj.player_mech.parts.get(other_arm_slot)
            if other_arm_part and "【空手】" in other_arm_part.tags:
                two_handed_sniper_active = True
                log.append(f"> 动作效果【【双手】获得狙击】触发 (另一只手为【空手】)！")
        if not target_part_slot:
            if back_attack or two_handed_sniper_active:
                if back_attack:
                    log.append("> [背击] 玩家获得任意选择权！请选择目标部位。")
                else:
                    log.append("> [狙击效果] 玩家获得任意选择权！请选择目标部位。")
                if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
                session['combat_log'] = log
                return jsonify({'success': True, 'action_required': 'select_part'})
            if attack_action.action_type == '近战':
                parry_parts = [(s, p) for s, p in game_state_obj.ai_mech.parts.items() if
                               p.parry > 0 and p.status != 'destroyed']
                if parry_parts:
                    target_part_slot, best_parry_part = max(parry_parts, key=lambda item: item[1].parry)
                    log.append(f"> AI 决定用 [{best_parry_part.name}] 进行招架！")
            if not target_part_slot:
                hit_roll_result = roll_black_die()
                log.append(f"> 玩家投掷部位骰结果: 【{hit_roll_result}】")
                if hit_roll_result == 'any':
                    log.append("> 玩家获得任意选择权！请选择目标部位。")
                    if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
                    session['combat_log'] = log
                    return jsonify({'success': True, 'action_required': 'select_part'})
                elif game_state_obj.ai_mech.parts.get(hit_roll_result) and game_state_obj.ai_mech.parts[
                    hit_roll_result].status != 'destroyed':
                    target_part_slot = hit_roll_result
                else:
                    target_part_slot = 'core'
                    log.append(f"> 部位 [{hit_roll_result}] 不存在或已摧毁，转而命中 [核心]。")

        if not execute_main_action(game_state_obj, attack_action, action_name, part_slot):
            # (execute_main_action 已经保存了日志)
            return jsonify({'success': False, 'message': 'Action cost validation failed.'})

        if not target_part_slot:
            log.append("> [严重错误] 未能确定目标部位！攻击中止。")
            if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
            session['combat_log'] = log
            return jsonify({'success': False, 'message': 'Internal error: Target part slot not determined.'})

        attack_log, result, overflow_data = resolve_attack(
            attacker_mech=game_state_obj.player_mech,
            defender_mech=game_state_obj.ai_mech,
            action=attack_action,
            target_part_name=target_part_slot,
            is_back_attack=back_attack,
            chosen_effect=None
        )

        # [新增] 为玩家攻击添加视觉反馈事件
        session['visual_feedback_events'].append({
            'type': 'attack_result',
            'attacker_pos': game_state_obj.player_pos,
            'defender_pos': game_state_obj.ai_pos,
            'result_text': result  # '击穿' 或 '无效'
        })

        if result == "effect_choice_required":
            log.extend(attack_log)
            game_state_obj.pending_effect_data = {
                'action_dict': attack_action.to_dict(),
                'overflow_data': {'hits': overflow_data['hits'], 'crits': overflow_data['crits']},
                'options': overflow_data['options'],
                'target_part_name': target_part_slot,
                'is_back_attack': back_attack
            }
            session['game_state'] = game_state_obj.to_dict()
            if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
            session['combat_log'] = log
            return jsonify({'success': True, 'action_required': 'select_effect', 'options': overflow_data['options']})

        log.extend(attack_log)
        game_state_obj.pending_effect_data = None
        ai_was_defeated = game_state_obj.ai_mech.parts[
                              'core'].status == 'destroyed' or game_state_obj.ai_mech.get_active_parts_count() < 3
        game_is_over = game_state_obj.check_game_over()
        if game_state_obj.game_mode == 'horde' and ai_was_defeated and not game_is_over:
            log.append(f"> [生存模式] 击败了 {game_state_obj.ai_defeat_count} 台敌机！")
            log.append(f"> [警告] 新的敌人出现: {game_state_obj.ai_mech.name}！")

        session['game_state'] = game_state_obj.to_dict()
        if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
        session['combat_log'] = log
        return jsonify({'success': True})

    if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
    session['combat_log'] = log
    return jsonify({'success': False})


@app.route('/resolve_effect_choice', methods=['POST'])
def resolve_effect_choice():
    """ (AJAX) 接收玩家关于【毁伤】/【霰射】/【顺劈】的选择。 """
    # 注意：这里 *不* 清除视觉反馈，因为这是攻击流程的一部分
    data = request.get_json()
    choice = data.get('choice')

    game_state_obj = GameState.from_dict(session.get('game_state'))
    log = session.get('combat_log', [])
    pending_data = game_state_obj.pending_effect_data

    if not pending_data:
        log.append("> [错误] 找不到待处理的效果数据！")
        if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
        session['combat_log'] = log
        return jsonify({'success': False, 'message': 'No pending data.'})

    if choice not in pending_data.get('options', []):
        log.append(f"> [错误] 无效的选择: {choice}")
        if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
        session['combat_log'] = log
        return jsonify({'success': False, 'message': 'Invalid choice.'})

    # [!!! BUG 修复 v1.13 开始 !!!]

    # 1. 获取当前状态的部件（它现在应该是 'damaged' 状态）
    target_part_name = pending_data['target_part_name']
    target_part = game_state_obj.ai_mech.get_part_by_name(target_part_name)

    if not target_part:
        log.append(f"> [错误] 在解析效果时找不到目标部件: {target_part_name}")
        if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
        session['combat_log'] = log
        return jsonify({'success': False, 'message': 'Target part not found.'})

    # 2. 从挂起数据中获取原始的溢出伤害
    overflow_hits = pending_data['overflow_data']['hits']
    overflow_crits = pending_data['overflow_data']['crits']

    log.append(
        f"> 玩家选择了【{'毁伤' if choice == 'devastating' else ('霰射' if choice == 'scattershot' else '顺劈')}】！")

    # 3. 调用新的辅助函数，它只处理溢出逻辑
    #    不再调用 resolve_attack()
    log = _resolve_effect_logic(
        log=log,
        defender_mech=game_state_obj.ai_mech,
        target_part=target_part,  # 传递实际的部件对象
        overflow_hits=overflow_hits,
        overflow_crits=overflow_crits,
        chosen_effect=choice
    )

    # [!!! BUG 修复 v1.13 结束 !!!]

    game_state_obj.pending_effect_data = None  # 清除挂起数据

    # 检查AI是否被效果摧毁
    ai_was_defeated = game_state_obj.ai_mech.parts[
                          'core'].status == 'destroyed' or game_state_obj.ai_mech.get_active_parts_count() < 3
    game_is_over = game_state_obj.check_game_over()
    if game_state_obj.game_mode == 'horde' and ai_was_defeated and not game_is_over:
        log.append(f"> [生存模式] 击败了 {game_state_obj.ai_defeat_count} 台敌机！")
        log.append(f"> [警告] 新的敌人出现: {game_state_obj.ai_mech.name}！")

    session['game_state'] = game_state_obj.to_dict()
    if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
    session['combat_log'] = log
    return jsonify({'success': True})


# --- 数据请求路由 ---
@app.route('/get_move_range', methods=['POST'])
def get_move_range():
    clear_visual_feedback()  # [新增] 清除旧事件
    data = request.get_json()
    game_state_obj = GameState.from_dict(session.get('game_state'))
    if game_state_obj.game_over: return jsonify({'valid_moves': []})
    action_name = data.get('action_name')
    action = None
    is_flight_action = False
    if action_name == '调整移动':
        pass
    else:
        part_slot = data.get('part_slot')
        if part_slot and part_slot in game_state_obj.player_mech.parts:
            part = game_state_obj.player_mech.parts[part_slot]
            if part.status != 'destroyed':
                action = next((a for a in part.actions if a.name == action_name), None)
                if action and action.effects.get("flight_movement"):
                    is_flight_action = True
    move_distance = 0
    if action and action.action_type == '移动':
        move_distance = action.range_val
    elif action_name == '调整移动':
        legs_part = game_state_obj.player_mech.parts.get('legs')
        if legs_part and legs_part.status != 'destroyed':
            move_distance = legs_part.adjust_move
        else:
            move_distance = 0
        if game_state_obj.player_mech.stance == 'agile':
            move_distance *= 2
    if move_distance > 0:
        valid_moves = game_state_obj.calculate_move_range(
            game_state_obj.player_pos,
            move_distance,
            is_flight=is_flight_action
        )
        return jsonify({'valid_moves': valid_moves})
    return jsonify({'valid_moves': []})


@app.route('/get_attack_range', methods=['POST'])
def get_attack_range():
    clear_visual_feedback()  # [新增] 清除旧事件
    data = request.get_json()
    game_state_obj = GameState.from_dict(session.get('game_state'))
    if game_state_obj.game_over: return jsonify({'valid_targets': []})
    action_name = data.get('action_name')
    part_slot = data.get('part_slot')
    action = None
    if part_slot and part_slot in game_state_obj.player_mech.parts:
        part = game_state_obj.player_mech.parts[part_slot]
        if part.status != 'destroyed':
            action = next((a for a in part.actions if a.name == action_name), None)
    if action:
        return jsonify({'valid_targets': game_state_obj.calculate_attack_range(
            game_state_obj.player_mech,
            game_state_obj.player_pos,
            action,
            current_tp=game_state_obj.player_tp
        )})
    return jsonify({'valid_targets': []})


if __name__ == '__main__':
    app.run(debug=True)

