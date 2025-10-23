import os
import random
from flask import Flask, render_template, jsonify, request, session, redirect, url_for
from data_models import Mech, Part, Action
from combat_system import resolve_attack
from game_logic import (
    GameState, is_back_attack, create_mech_from_selection, get_player_lock_status,
    AI_LOADOUTS
)
from ai_system import run_ai_turn
from parts_database import (
    PLAYER_CORES, PLAYER_LEGS, PLAYER_LEFT_ARMS, PLAYER_RIGHT_ARMS, PLAYER_BACKPACKS
)

app = Flask(__name__)
app.secret_key = os.urandom(24)  # 用于 session 加密


# --- 核心路由 ---

@app.route('/')
def index():
    """显示开始页面。"""
    # [新增] 在这里编写更新介绍
    update_notes = [
        "版本 v1.0 更新:",
        "- 增加部件选择功能",
        "- 增加了一个新的AI对手",
        "- 新增 [决斗模式] 和 [生存模式]。",
        "- 生存模式实装AI刷新和计分。",
        "- 调整了机库UI以适配新模式选择。",
        "- 强化了AI的智力。"
    ]
    return render_template('index.html', update_notes=update_notes)


@app.route('/hangar')
def hangar():
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
    """[修改] 从机库接收机甲配置和游戏模式，并开始游戏。"""
    selection = {
        'core': request.form.get('core'),
        'legs': request.form.get('legs'),
        'left_arm': request.form.get('left_arm'),
        'right_arm': request.form.get('right_arm'),
        'backpack': request.form.get('backpack')
    }

    # [新增] 从表单获取游戏模式
    game_mode = request.form.get('game_mode', 'duel')  # 默认为 'duel'
    ai_opponent_key = request.form.get('ai_opponent')

    player_mech = create_mech_from_selection("玩家机甲", selection)

    # [修改] 创建游戏状态，传入玩家机甲、AI key 和 游戏模式
    game = GameState(
        player_mech=player_mech,
        ai_loadout_key=ai_opponent_key,
        game_mode=game_mode
    )

    # 存入 session
    session['game_state'] = game.to_dict()

    # [修改] 根据游戏模式添加不同的初始日志
    log = [f"> 玩家机甲组装完毕。"]
    if game_mode == 'horde':
        log.append(f"> [生存模式] 已启动。")
        log.append(f"> 第一波遭遇: {game.ai_mech.name}。")
    else:  # duel
        log.append(f"> [决斗模式] 已启动。")
        log.append(f"> 遭遇敌机: {game.ai_mech.name}。")
    log.append("> 战斗开始！")

    session['combat_log'] = log
    return redirect(url_for('game'))


@app.route('/game', methods=['GET'])
def game():
    """显示主游戏界面。"""
    if 'game_state' not in session:
        return redirect(url_for('hangar'))

    game_state_obj = GameState.from_dict(session['game_state'])

    if not game_state_obj.player_mech:
        return redirect(url_for('hangar'))

    is_player_locked, locker_pos = get_player_lock_status(game_state_obj)
    log = session.get('combat_log', [])

    return render_template(
        'game.html',
        game=game_state_obj,
        combat_log=log,
        is_player_locked=is_player_locked,
        player_actions_used=game_state_obj.player_actions_used_this_turn,
        # [新增] 传递模式和击败数到前端
        game_mode=game_state_obj.game_mode,
        ai_defeat_count=game_state_obj.ai_defeat_count
    )


@app.route('/reset_game', methods=['POST'])
def reset_game():
    """重置游戏会话并返回机库。"""
    session.pop('game_state', None)
    session.pop('combat_log', None)
    return redirect(url_for('hangar'))


@app.route('/end_turn', methods=['POST'])
def end_turn():
    """玩家结束回合，触发 AI 回合。"""
    game_state_obj = GameState.from_dict(session.get('game_state'))
    if game_state_obj.game_over:
        return redirect(url_for('game'))

    log = session.get('combat_log', [])
    log.append("-" * 20)
    log.append("> 玩家回合结束。")

    # --- AI 回合开始 ---
    ai_turn_log, attack_action_to_resolve = run_ai_turn(game_state_obj)
    log.extend(ai_turn_log)

    if attack_action_to_resolve:
        back_attack = is_back_attack(game_state_obj.ai_pos, game_state_obj.player_pos,
                                     game_state_obj.player_mech.orientation)

        target_part_slot = None
        if attack_action_to_resolve.action_type == '近战' and not back_attack:
            parry_parts = [(s, p) for s, p in game_state_obj.player_mech.parts.items() if
                           p.parry > 0 and p.status != 'destroyed']
            if parry_parts:
                target_part_slot, best_parry_part = max(parry_parts, key=lambda item: item[1].parry)
                log.append(f"> 玩家决定用 [{best_parry_part.name}] 进行招架！")

        if not target_part_slot:
            valid_parts = [s for s, p in game_state_obj.player_mech.parts.items() if p.status != 'destroyed']
            target_part_slot = random.choice(valid_parts) if valid_parts else 'core'

        attack_log, result = resolve_attack(
            attacker_mech=game_state_obj.ai_mech,
            defender_mech=game_state_obj.player_mech,
            action=attack_action_to_resolve,
            target_part_name=target_part_slot,
            is_back_attack=back_attack
        )
        log.extend(attack_log)

    log.append("> AI回合结束。请开始你的回合。")
    log.append("-" * 20)

    # 为玩家的下一回合重置状态
    game_state_obj.current_turn = 'player'
    game_state_obj.player_ap = 2
    game_state_obj.player_tp = 1
    game_state_obj.turn_phase = 'timing'
    game_state_obj.timing = None
    game_state_obj.opening_move_taken = False
    game_state_obj.player_actions_used_this_turn = []

    # [修改] check_game_over 现在会处理玩家被击败的情况
    game_is_over = game_state_obj.check_game_over()
    if game_is_over and game_state_obj.game_over == 'ai_win':
        log.append(f"> 玩家机甲已被摧毁！")
        if game_state_obj.game_mode == 'horde':
            log.append(f"> [生存模式] 最终击败数: {game_state_obj.ai_defeat_count}")

    session['game_state'] = game_state_obj.to_dict()
    session['combat_log'] = log
    return redirect(url_for('game'))


# --- 行动阶段与玩家动作路由 ---

@app.route('/select_timing', methods=['POST'])
def select_timing():
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
    game_state_obj = GameState.from_dict(session.get('game_state'))
    if game_state_obj.turn_phase == 'timing' and game_state_obj.timing and not game_state_obj.game_over:
        game_state_obj.turn_phase = 'stance'
        session['game_state'] = game_state_obj.to_dict()
        log = session.get('combat_log', [])
        log.append(f"> 时机已确认为 [{game_state_obj.timing}]。进入姿态选择阶段。")
        session['combat_log'] = log
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Please select a timing first.'})


@app.route('/change_stance', methods=['POST'])
def change_stance():
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
    game_state_obj = GameState.from_dict(session.get('game_state'))
    if game_state_obj.turn_phase == 'stance' and not game_state_obj.game_over:
        game_state_obj.turn_phase = 'adjustment'
        session['game_state'] = game_state_obj.to_dict()
        log = session.get('combat_log', [])
        log.append(f"> 姿态已确认为 [{game_state_obj.player_mech.stance}]。进入调整阶段。")
        session['combat_log'] = log
        return jsonify({'success': True})
    return jsonify({'success': False})


@app.route('/execute_adjust_move', methods=['POST'])
def execute_adjust_move():
    data = request.get_json()
    game_state_obj = GameState.from_dict(session.get('game_state'))
    if game_state_obj.turn_phase == 'adjustment' and game_state_obj.player_tp >= 1 and not game_state_obj.game_over:
        game_state_obj.player_pos = tuple(data.get('target_pos'))
        game_state_obj.player_mech.orientation = data.get('final_orientation')
        game_state_obj.player_tp -= 1
        game_state_obj.turn_phase = 'main'
        session['game_state'] = game_state_obj.to_dict()
        log = session.get('combat_log', [])
        log.append(f"> 玩家调整移动到 {game_state_obj.player_pos}。进入主动作阶段。")
        session['combat_log'] = log
        return jsonify({'success': True})
    return jsonify({'success': False})


@app.route('/change_orientation', methods=['POST'])
def change_orientation():
    data = request.get_json()
    game_state_obj = GameState.from_dict(session.get('game_state'))
    if game_state_obj.turn_phase == 'adjustment' and game_state_obj.player_tp >= 1 and not game_state_obj.game_over:
        game_state_obj.player_mech.orientation = data.get('final_orientation')
        game_state_obj.player_tp -= 1
        game_state_obj.turn_phase = 'main'
        session['game_state'] = game_state_obj.to_dict()
        log = session.get('combat_log', [])
        log.append(f"> 玩家仅转向。进入主动作阶段。")
        session['combat_log'] = log
        return jsonify({'success': True})
    return jsonify({'success': False})


@app.route('/skip_adjustment', methods=['POST'])
def skip_adjustment():
    game_state_obj = GameState.from_dict(session.get('game_state'))
    if game_state_obj.turn_phase == 'adjustment' and not game_state_obj.game_over:
        game_state_obj.turn_phase = 'main'
        session['game_state'] = game_state_obj.to_dict()
        log = session.get('combat_log', [])
        log.append(f"> 玩家跳过调整阶段。进入主动作阶段。")
        session['combat_log'] = log
        return jsonify({'success': True})
    return jsonify({'success': False})


def execute_main_action(game, action, action_name, part_slot):
    """
    (服务器端) 验证并执行一个主动作。
    """
    log = session.get('combat_log', [])
    action_id = (part_slot, action_name)

    if action_id in game.player_actions_used_this_turn:
        log.append(f"> [错误] [{action_name}] (来自: {part_slot}) 本回合已使用过。")
        session['combat_log'] = log
        return False

    ap_cost = action.cost.count('M') * 2 + action.cost.count('S') * 1
    tp_cost = 0
    if action.cost == 'L':
        ap_cost = 2
        tp_cost = 1

    if game.player_ap < ap_cost:
        log.append(f"> [错误] AP不足 (需要 {ap_cost})，无法执行 [{action.name}]。")
        session['combat_log'] = log
        return False
    if game.player_tp < tp_cost:
        log.append(f"> [错误] TP不足 (需要 {tp_cost})，无法执行 [{action.name}]。")
        session['combat_log'] = log
        return False

    if not game.opening_move_taken:
        if action.action_type != game.timing:
            log.append(
                f"> [错误] 起手动作错误！当前时机为 [{game.timing}]，无法执行 [{action.action_type}] 动作。")
            session['combat_log'] = log
            return False
        game.opening_move_taken = True

    game.player_ap -= ap_cost
    game.player_tp -= tp_cost
    game.player_actions_used_this_turn.append(action_id)
    return True


@app.route('/move_player', methods=['POST'])
def move_player():
    data = request.get_json()
    game_state_obj = GameState.from_dict(session.get('game_state'))
    if game_state_obj.game_over: return jsonify({'success': False})

    action_name = data.get('action_name')
    part_slot = data.get('part_slot')

    action = None
    if part_slot and part_slot in game_state_obj.player_mech.parts:
        part = game_state_obj.player_mech.parts[part_slot]
        if part.status != 'destroyed':
            action = next((a for a in part.actions if a.name == action_name), None)

    if game_state_obj.turn_phase == 'main' and action and execute_main_action(game_state_obj, action, action_name,
                                                                              part_slot):
        game_state_obj.player_pos = tuple(data.get('target_pos'))
        game_state_obj.player_mech.orientation = data.get('final_orientation')
        session['game_state'] = game_state_obj.to_dict()
        log = session.get('combat_log', [])
        log.append(f"> 玩家执行 [{action.name}]。")
        session['combat_log'] = log
        return jsonify({'success': True})
    return jsonify({'success': False})


@app.route('/execute_attack', methods=['POST'])
def execute_attack():
    data = request.get_json()
    game_state_obj = GameState.from_dict(session.get('game_state'))
    log = session.get('combat_log', [])  # [修改] 提早获取日志
    if game_state_obj.game_over: return jsonify({'success': False})

    action_name = data.get('action_name')
    part_slot = data.get('part_slot')

    attack_action = None
    if part_slot and part_slot in game_state_obj.player_mech.parts:
        part = game_state_obj.player_mech.parts[part_slot]
        if part.status != 'destroyed':
            attack_action = next((a for a in part.actions if a.name == action_name), None)

    if game_state_obj.turn_phase == 'main' and attack_action and execute_main_action(game_state_obj, attack_action,
                                                                                     action_name,
                                                                                     part_slot):

        is_player_locked, _ = get_player_lock_status(game_state_obj)
        if is_player_locked and attack_action.action_type == '射击':
            log.append(f"> [错误] 你被近战锁定，无法执行 [{attack_action.name}]！")
            session['combat_log'] = log
            return jsonify({'success': False, 'message': '被近战锁定，无法射击！'})

        back_attack = is_back_attack(game_state_obj.player_pos, game_state_obj.ai_pos,
                                     game_state_obj.ai_mech.orientation)

        target_part_slot = data.get('target_part_name')
        if not target_part_slot:
            if attack_action.action_type == '近战' and not back_attack:
                parry_parts = [(s, p) for s, p in game_state_obj.ai_mech.parts.items() if
                               p.parry > 0 and p.status != 'destroyed']
                if parry_parts:
                    target_part_slot, _ = max(parry_parts, key=lambda item: item[1].parry)
            if not target_part_slot:
                valid_parts = [s for s, p in game_state_obj.ai_mech.parts.items() if p.status != 'destroyed']
                target_part_slot = random.choice(valid_parts) if valid_parts else 'core'

        # 解析攻击
        attack_log, result = resolve_attack(
            attacker_mech=game_state_obj.player_mech,
            defender_mech=game_state_obj.ai_mech,
            action=attack_action,
            target_part_name=target_part_slot,
            is_back_attack=back_attack
        )
        log.extend(attack_log)

        # [修改] 检查AI是否在这次攻击中被击败
        ai_was_defeated = game_state_obj.ai_mech.parts[
                              'core'].status == 'destroyed' or game_state_obj.ai_mech.get_active_parts_count() < 3

        # [修改] check_game_over 现在会处理重生逻辑
        game_is_over = game_state_obj.check_game_over()

        # [新增] 检查是否是Horde模式且AI被击败（现在 game_over is None 且 ai_mech 是全新的）
        if game_state_obj.game_mode == 'horde' and ai_was_defeated and not game_is_over:
            log.append(f"> [生存模式] 击败了 {game_state_obj.ai_defeat_count} 台敌机！")
            log.append(f"> [警告] 新的敌人出现: {game_state_obj.ai_mech.name}！")

        session['game_state'] = game_state_obj.to_dict()
        session['combat_log'] = log
        return jsonify({'success': True})

    session['combat_log'] = log  # 确保即使攻击失败，日志也会被保存
    return jsonify({'success': False})


# --- 数据请求路由 ---

@app.route('/get_move_range', methods=['POST'])
def get_move_range():
    data = request.get_json()
    game_state_obj = GameState.from_dict(session.get('game_state'))
    if game_state_obj.game_over: return jsonify({'valid_moves': []})

    action_name = data.get('action_name')
    action = None
    if action_name == '调整移动':
        pass
    else:
        part_slot = data.get('part_slot')
        if part_slot and part_slot in game_state_obj.player_mech.parts:
            part = game_state_obj.player_mech.parts[part_slot]
            if part.status != 'destroyed':
                action = next((a for a in part.actions if a.name == action_name), None)

    move_distance = 0
    if action and action.action_type == '移动':
        move_distance = action.range_val
    elif data.get('action_name') == '调整移动':
        legs_part = game_state_obj.player_mech.parts.get('legs')
        if legs_part and legs_part.status != 'destroyed':
            move_distance = legs_part.adjust_move
        else:
            move_distance = 0
        if game_state_obj.player_mech.stance == 'agile':
            move_distance *= 2

    if move_distance > 0:
        return jsonify({'valid_moves': game_state_obj.calculate_move_range(game_state_obj.player_pos, move_distance)})
    return jsonify({'valid_moves': []})


@app.route('/get_attack_range', methods=['POST'])
def get_attack_range():
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
        return jsonify({'valid_targets': game_state_obj.calculate_attack_range(game_state_obj.player_mech,
                                                                               game_state_obj.player_pos, action)})
    return jsonify({'valid_targets': []})


if __name__ == '__main__':
    app.run(debug=True)

