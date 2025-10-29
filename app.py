import os
import random
from flask import Flask, render_template, jsonify, request, session, redirect, url_for
from data_models import Mech, Part, Action
from combat_system import resolve_attack
from dice_roller import roll_black_die
from game_logic import (
    GameState, is_back_attack, create_mech_from_selection, get_player_lock_status,
    AI_LOADOUTS,
    _get_distance, is_in_forward_arc  # [新增] 导入距离和视线函数
)
from ai_system import run_ai_turn
from parts_database import (
    PLAYER_CORES, PLAYER_LEGS, PLAYER_LEFT_ARMS, PLAYER_RIGHT_ARMS, PLAYER_BACKPACKS
)
# [新增] 导入 markdown 和 bleach 用于规则显示
import markdown
import bleach

app = Flask(__name__)
app.secret_key = os.urandom(24)  # 用于 session 加密


# --- 核心路由 ---

@app.route('/')
def index():
    """渲染游戏的主索引/开始页面。"""
    # [新增] 在这里编写更新介绍
    update_notes = [
        "版本 v1.2 更新:",
        "- 增加了几个新的部件",
        "- 增加了目前可用部件的效果词条",
        "- 修正了近战锁定"
    ]

    # [新增] 读取并转换规则 Markdown 文件
    rules_html = ""
    try:
        with open("Game Introduction.md", "r", encoding="utf-8") as f:
            md_content = f.read()
            # 转换 Markdown 为 HTML
            html = markdown.markdown(md_content)
            # 清理 HTML，只允许安全的标签
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
    """渲染主游戏界面，显示棋盘、状态和日志。"""
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
    """清除会话数据，重置游戏并返回机库。"""
    session.pop('game_state', None)
    session.pop('combat_log', None)
    return redirect(url_for('hangar'))


@app.route('/end_turn', methods=['POST'])
def end_turn():
    """玩家结束回合，触发AI回合逻辑，并在AI行动后刷新游戏状态。"""
    game_state_obj = GameState.from_dict(session.get('game_state'))
    if game_state_obj.game_over:
        return redirect(url_for('game'))

    log = session.get('combat_log', [])
    log.append("-" * 20)
    log.append("> 玩家回合结束。")

    # --- AI 回合开始 ---
    # [修改 v1.4] run_ai_turn 现在返回一个列表
    ai_turn_log, attacks_to_resolve_list = run_ai_turn(game_state_obj)
    log.extend(ai_turn_log)

    if not attacks_to_resolve_list:
        log.append("> AI 未执行攻击。")

    # [修改 v1.4] 循环处理所有 AI 攻击
    for attack_action in attacks_to_resolve_list:
        log.append(f"--- AI 攻击结算 ({attack_action.name}) ---")

        back_attack = is_back_attack(game_state_obj.ai_pos, game_state_obj.player_pos,
                                     game_state_obj.player_mech.orientation)

        target_part_slot = None

        # 1. 检查招架 (如果不被背击)
        if attack_action.action_type == '近战' and not back_attack:
            parry_parts = [(s, p) for s, p in game_state_obj.player_mech.parts.items() if
                           p.parry > 0 and p.status != 'destroyed']
            if parry_parts:
                target_part_slot, best_parry_part = max(parry_parts, key=lambda item: item[1].parry)
                log.append(f"> 玩家决定用 [{best_parry_part.name}] 进行招架！")

        # 2. 如果不招架，则投掷黑骰子
        if not target_part_slot:
            hit_roll_result = roll_black_die()
            log.append(f"> AI 投掷部位骰结果: 【{hit_roll_result}】")

            if hit_roll_result == 'any' or back_attack:
                if back_attack:
                    log.append("> [背击] AI 获得任意选择权！")
                else:
                    log.append("> AI 获得任意选择权！")

                # AI 优先攻击受损部件，其次是核心
                damaged_parts = [s for s, p in game_state_obj.player_mech.parts.items() if p.status == 'damaged']
                if damaged_parts:
                    target_part_slot = random.choice(damaged_parts)
                    log.append(f"> AI 优先攻击已受损部件: [{target_part_slot}]。")
                elif game_state_obj.player_mech.parts['core'].status != 'destroyed':
                    target_part_slot = 'core'
                    log.append("> AI 决定攻击 [核心]。")
                else:
                    # 如果核心已毁，随便选一个
                    valid_parts = [s for s, p in game_state_obj.player_mech.parts.items() if p.status != 'destroyed']
                    target_part_slot = random.choice(valid_parts) if valid_parts else 'core'

            elif game_state_obj.player_mech.parts.get(hit_roll_result) and game_state_obj.player_mech.parts[
                hit_roll_result].status != 'destroyed':
                target_part_slot = hit_roll_result
            else:
                target_part_slot = 'core'
                log.append(f"> 部位 [{hit_roll_result}] 不存在或已摧毁，转而命中 [核心]。")

        # 3. 解析攻击
        attack_log, result = resolve_attack(
            attacker_mech=game_state_obj.ai_mech,
            defender_mech=game_state_obj.player_mech,
            action=attack_action,  # [修改 v1.4] 使用循环中的动作
            target_part_name=target_part_slot,
            is_back_attack=back_attack
        )
        log.extend(attack_log)

        # [修改 v1.4] 在每次攻击后检查玩家是否死亡
        game_is_over = game_state_obj.check_game_over()
        if game_is_over and game_state_obj.game_over == 'ai_win':
            log.append(f"> 玩家机甲已被摧毁！")
            if game_state_obj.game_mode == 'horde':
                log.append(f"> [生存模式] 最终击败数: {game_state_obj.ai_defeat_count}")
            break  # [修改 v1.4] 停止处理攻击

    # [修改 v1.4] 如果玩家在攻击循环中存活，才继续
    if not game_state_obj.game_over:
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

        # 再次检查 (主要用于 Horde 模式 AI 自爆等情况，虽然目前没有)
        game_state_obj.check_game_over()

    session['game_state'] = game_state_obj.to_dict()
    session['combat_log'] = log
    return redirect(url_for('game'))


# --- 行动阶段与玩家动作路由 ---

@app.route('/select_timing', methods=['POST'])
def select_timing():
    """(AJAX) 接收玩家选择的“时机”并更新会话。"""
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
    """(AJAX) 确认玩家的“时机”选择，并将游戏阶段推进到“姿态”。"""
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
    """(AJAX) 接收玩家选择的“姿态”并更新会话。"""
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
    """(AJAX) 确认玩家的“姿态”选择，并将游戏阶段推进到“调整”。"""
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
    """(AJAX) 处理玩家的“调整移动”动作，消耗TP并推进到“主动作”。"""
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
    """(AJAX) 处理玩家仅“调整转向”的动作，消耗TP并推进到“主动作”。"""
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
    """(AJAX) 处理玩家跳过“调整阶段”的请求，推进到“主动作”。"""
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
    检查AP/TP消耗、起手动作规则和动作是否已使用。
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
    """(AJAX) 处理玩家的“移动”类型动作（非调整移动）。"""
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
    """
    (AJAX) 处理玩家的“攻击”动作（近战或射击）。
    这是核心的战斗路由，负责处理目标选择、射程验证、近战锁定检查，
    并在必要时（如背击或掷出'any'）请求前端选择部位。
    """
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

    # [修改] 将 execute_main_action 移到所有检查之后
    if game_state_obj.turn_phase == 'main' and attack_action:

        # [新增] 服务器端射程验证（包含【静止】效果）
        if attack_action.action_type == '射击':
            effective_range = attack_action.range_val

            # 1. 检查【静止】效果
            static_bonus = attack_action.effects.get("static_range_bonus", 0)
            if static_bonus > 0 and game_state_obj.player_tp >= 1:
                effective_range += static_bonus
                log.append(f"> 动作效果【静止】触发！射程 +{static_bonus}。")

            # 2. [新增] 检查【双手】效果
            two_handed_bonus = attack_action.effects.get("two_handed_range_bonus", 0)
            if two_handed_bonus > 0:
                # 'part_slot' (例如 'right_arm') 在这个函数中是可用的
                other_arm_slot = 'left_arm' if part_slot == 'right_arm' else 'right_arm'
                other_arm_part = game_state_obj.player_mech.parts.get(other_arm_slot)

                if other_arm_part and "【空手】" in other_arm_part.tags:
                    effective_range += two_handed_bonus
                    log.append(f"> 动作效果【【双手】+2射程】触发 (另一只手为【空手】)！射程 +{two_handed_bonus}。")

            target_pos_tuple = tuple(data.get('target_pos'))
            dist = _get_distance(game_state_obj.player_pos, target_pos_tuple)

            if dist > effective_range:
                log.append(f"> [错误] 目标超出有效射程 {effective_range} (距离 {dist})。")
                session['combat_log'] = log
                return jsonify({'success': False, 'message': 'Target out of range.'})

            if not is_in_forward_arc(game_state_obj.player_pos, game_state_obj.player_mech.orientation,
                                     target_pos_tuple):
                log.append(f"> [错误] 目标不在前方视线内。")
                session['combat_log'] = log
                return jsonify({'success': False, 'message': 'Target not in forward arc.'})

        # [新增] 验证近战射程
        if attack_action.action_type == '近战':
            # 使用 calculate_attack_range 验证目标是否合法
            valid_targets = game_state_obj.calculate_attack_range(
                game_state_obj.player_mech,
                game_state_obj.player_pos,
                attack_action
            )
            if not any(t['pos'] == tuple(data.get('target_pos')) for t in valid_targets):
                log.append(f"> [错误] 目标不在近战攻击范围内。")
                session['combat_log'] = log
                return jsonify({'success': False, 'message': 'Target out of melee range.'})

        # --- 检查锁定 ---
        is_player_locked, _ = get_player_lock_status(game_state_obj)
        if is_player_locked and attack_action.action_type == '射击':
            log.append(f"> [错误] 你被近战锁定，无法执行 [{attack_action.name}]！")
            session['combat_log'] = log
            return jsonify({'success': False, 'message': '被近战锁定，无法射击！'})

        # --- 检查目标选择 ---
        back_attack = is_back_attack(game_state_obj.player_pos, game_state_obj.ai_pos,
                                     game_state_obj.ai_mech.orientation)

        target_part_slot = data.get('target_part_name')

        # [新增] 检查【双手】狙击效果
        has_two_handed_sniper = attack_action.effects.get("two_handed_sniper", False)
        two_handed_sniper_active = False
        if has_two_handed_sniper:
            other_arm_slot = 'left_arm' if part_slot == 'right_arm' else 'right_arm'
            other_arm_part = game_state_obj.player_mech.parts.get(other_arm_slot)
            if other_arm_part and "【空手】" in other_arm_part.tags:
                two_handed_sniper_active = True
                log.append(f"> 动作效果【【双手】获得狙击】触发 (另一只手为【空手】)！")


        if not target_part_slot:
            # 1. 检查背击 或 [新增] 检查激活的【双手】狙击效果
            if back_attack or two_handed_sniper_active:
                if back_attack:
                    log.append("> [背击] 玩家获得任意选择权！请选择目标部位。")
                else: # two_handed_sniper_active
                    log.append("> [狙击效果] 玩家获得任意选择权！请选择目标部位。")
                session['combat_log'] = log
                return jsonify({'success': True, 'action_required': 'select_part'})

            # 2. 检查AI招架 (仅近战且非背击/非狙击时)
            if attack_action.action_type == '近战': # 狙击必定是射击，所以不会触发这里
                parry_parts = [(s, p) for s, p in game_state_obj.ai_mech.parts.items() if
                               p.parry > 0 and p.status != 'destroyed']
                if parry_parts:
                    target_part_slot, best_parry_part = max(parry_parts, key=lambda item: item[1].parry)
                    log.append(f"> AI 决定用 [{best_parry_part.name}] 进行招架！")

            # 3. [修正逻辑] 投掷黑骰子 (仅在没有招架发生时)
            if not target_part_slot: # 只有在上面招架没发生时，才进入这里
                hit_roll_result = roll_black_die()
                log.append(f"> 玩家投掷部位骰结果: 【{hit_roll_result}】")

                if hit_roll_result == 'any':
                    log.append("> 玩家获得任意选择权！请选择目标部位。")
                    session['combat_log'] = log
                    # 这里之前错误地 return 了 jsonify，现在修正
                    return jsonify({'success': True, 'action_required': 'select_part'}) # 让前端弹窗

                elif game_state_obj.ai_mech.parts.get(hit_roll_result) and game_state_obj.ai_mech.parts[
                    hit_roll_result].status != 'destroyed':
                    target_part_slot = hit_roll_result
                else:
                    target_part_slot = 'core' # 后备：命中核心
                    log.append(f"> 部位 [{hit_roll_result}] 不存在或已摧毁，转而命中 [核心]。")
            # --- 黑骰子逻辑结束 ---

        # --- 所有检查通过，现在执行动作（消耗AP/TP） ---
        if not execute_main_action(game_state_obj, attack_action, action_name, part_slot):
            # ... (如果AP/TP不足或起手动作错误，execute_main_action 会返回 False)
            session['combat_log'] = log  # 确保日志被保存
            return jsonify({'success': False, 'message': 'Action cost validation failed.'})

        # --- 动作执行成功，开始结算 ---
        # 此时 target_part_slot 必须有值 (来自玩家选择、AI招架或黑骰子)
        if not target_part_slot:
             log.append("> [严重错误] 未能确定目标部位！攻击中止。")
             session['combat_log'] = log
             # 撤销动作消耗 (可选，取决于你想如何处理这种错误)
             # game_state_obj.player_ap += ...
             # game_state_obj.player_tp += ...
             # game_state_obj.player_actions_used_this_turn.remove(...)
             return jsonify({'success': False, 'message': 'Internal error: Target part slot not determined.'})


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
    """(AJAX) 根据请求的移动动作，计算并返回所有有效的移动格子坐标。"""
    data = request.get_json()
    game_state_obj = GameState.from_dict(session.get('game_state'))
    if game_state_obj.game_over: return jsonify({'valid_moves': []})

    action_name = data.get('action_name')
    action = None
    is_flight_action = False # [新增] 标记是否为飞行

    if action_name == '调整移动':
        pass # 调整移动不是飞行
    else:
        part_slot = data.get('part_slot')
        if part_slot and part_slot in game_state_obj.player_mech.parts:
            part = game_state_obj.player_mech.parts[part_slot]
            if part.status != 'destroyed':
                action = next((a for a in part.actions if a.name == action_name), None)
                # [新增] 检查动作是否有飞行效果
                if action and action.effects.get("flight_movement"):
                    is_flight_action = True

    move_distance = 0
    if action and action.action_type == '移动':
        move_distance = action.range_val
    elif action_name == '调整移动': # 注意调整移动不能飞行
        legs_part = game_state_obj.player_mech.parts.get('legs')
        if legs_part and legs_part.status != 'destroyed':
            move_distance = legs_part.adjust_move
        else:
            move_distance = 0
        if game_state_obj.player_mech.stance == 'agile':
            move_distance *= 2

    if move_distance > 0:
        # [修改] 调用 calculate_move_range 时传入 is_flight 参数
        valid_moves = game_state_obj.calculate_move_range(
            game_state_obj.player_pos,
            move_distance,
            is_flight=is_flight_action # 传入飞行标记
        )
        return jsonify({'valid_moves': valid_moves})
    return jsonify({'valid_moves': []})


@app.route('/get_attack_range', methods=['POST'])
def get_attack_range():
    """(AJAX) 根据请求的攻击动作，计算并返回所有有效的攻击目标。"""
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
        # [修改] 传入玩家当前的TP，以便计算【静止】效果
        return jsonify({'valid_targets': game_state_obj.calculate_attack_range(
            game_state_obj.player_mech,
            game_state_obj.player_pos,
            action,
            current_tp=game_state_obj.player_tp  # [新增]
        )})
    return jsonify({'valid_targets': []})


if __name__ == '__main__':
    app.run(debug=True)


