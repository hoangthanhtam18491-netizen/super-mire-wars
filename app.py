import os
import random
import re  # [新增] 导入 re 用于简单的 Markdown 转换
from flask import Flask, render_template, jsonify, request, session, redirect, url_for
from data_models import Mech, Part, Action
from combat_system import resolve_attack
from game_logic import (
    GameState, is_back_attack, create_mech_from_selection, get_player_lock_status,
    AI_LOADOUTS
)
from ai_system import run_ai_turn
from dice_roller import roll_dice, roll_black_die  # 导入 roll_black_die
from parts_database import (
    PLAYER_CORES, PLAYER_LEGS, PLAYER_LEFT_ARMS, PLAYER_RIGHT_ARMS, PLAYER_BACKPACKS
)

app = Flask(__name__)
app.secret_key = os.urandom(24)  # 用于 session 加密


# --- [新增] Markdown 转换辅助函数 ---
def convert_md_to_html(md_text):
    """一个简单的 Markdown 到 HTML 的转换器，用于规则显示。"""
    html_lines = []
    in_list = False

    for line in md_text.split('\n'):
        line_stripped = line.strip()

        if not line_stripped:
            if in_list:
                html_lines.append('</ul>')
                in_list = False
            html_lines.append('<br>')
            continue

        if line_stripped.startswith('## '):
            if in_list:
                html_lines.append('</ul>')
                in_list = False
            html_lines.append(f'<h3 class="text-2xl font-bold mt-4 mb-2 text-blue-300">{line_stripped[3:]}</h3>')
        elif line_stripped.startswith('# '):
            if in_list:
                html_lines.append('</ul>')
                in_list = False
            html_lines.append(f'<h2 class="text-3xl font-bold mb-4 text-blue-400">{line_stripped[2:]}</h2>')
        elif line_stripped.startswith('* '):
            if not in_list:
                html_lines.append('<ul class="list-disc list-inside text-left space-y-2">')
                in_list = True
            html_lines.append(f'<li>{line_stripped[2:]}</li>')
        else:
            if in_list:
                html_lines.append('</ul>')
                in_list = False
            # 将 [文本] 替换为高亮
            line_with_markup = re.sub(r'\[(.*?)\]', r'<span class="text-yellow-400">[\1]</span>', line_stripped)
            # 将 `text` 替换为高亮
            line_with_markup = re.sub(r'`(.*?)`',
                                      r'<code class="bg-gray-900 text-green-300 px-2 py-1 rounded">\1</code>',
                                      line_with_markup)
            html_lines.append(f'<p class="text-left">{line_with_markup}</p>')

    if in_list:
        html_lines.append('</ul>')

    return '\n'.join(html_lines)


# --- 辅助函数结束 ---


# --- 核心路由 ---

@app.route('/')
def index():
    """[修改] 显示开始页面，并加载规则。"""
    update_notes = [
        "版本 v1.1 更新:",
        "- 增加了几个新的部件",
        "- 强化了AI的智力。",
        "- 增加了两个新的AI对手",
        "- 增加了规则介绍",
        "- 补充了黑骰子的判定"
    ]

    rules_html = "<h3>规则文件 (游戏规则介绍.md) 未找到。</h3>"
    try:
        # 假设规则文件位于 Flask 应用的根目录
        with open('游戏规则介绍.md', 'r', encoding='utf-8') as f:
            md_content = f.read()
            rules_html = convert_md_to_html(md_content)
    except FileNotFoundError:
        print("警告：未在根目录找到 '游戏规则介绍.md'。")
    except Exception as e:
        print(f"读取规则文件时出错: {e}")

    return render_template('index.html', update_notes=update_notes, rules_html=rules_html)


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
    """ [修改 v1.1] 玩家结束回合，触发 AI 回合 (支持多次攻击)。"""
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

        # 1. 检查背击 (AI选择)
        if back_attack:
            log.append("> [背击] AI 随机选择目标部位...")
            # [优化] AI 优先攻击已受损的部件
            damaged_parts = [s for s, p in game_state_obj.player_mech.parts.items() if p.status == 'damaged']
            if damaged_parts:
                target_part_slot = random.choice(damaged_parts)
            else:
                valid_parts = [s for s, p in game_state_obj.player_mech.parts.items() if p.status != 'destroyed']
                target_part_slot = random.choice(valid_parts) if valid_parts else 'core'

        # 2. 检查近战招架 (玩家自动招架)
        elif attack_action.action_type == '近战':
            parry_parts = [(s, p) for s, p in game_state_obj.player_mech.parts.items() if
                           p.parry > 0 and p.status != 'destroyed']
            if parry_parts:
                target_part_slot, best_parry_part = max(parry_parts, key=lambda item: item[1].parry)
                log.append(f"> 玩家决定用 [{best_parry_part.name}] 进行招架！")

        # 3. [修改] 投掷黑骰子
        if not target_part_slot:
            roll_result = roll_black_die()
            log.append(f"> [部位骰] AI 投掷黑骰子，结果为: [{roll_result}]。")

            if roll_result == 'any':
                # AI获得“任意选择”权，逻辑同背击
                log.append("> AI 获得任意选择权...")
                damaged_parts = [s for s, p in game_state_obj.player_mech.parts.items() if p.status == 'damaged']
                if damaged_parts:
                    target_part_slot = random.choice(damaged_parts)
                else:
                    valid_parts = [s for s, p in game_state_obj.player_mech.parts.items() if p.status != 'destroyed']
                    target_part_slot = random.choice(valid_parts) if valid_parts else 'core'
            else:
                target_part_slot = roll_result

            # 检查骰子结果对应的部件是否已摧毁
            target_part_obj = game_state_obj.player_mech.parts.get(target_part_slot)
            if not target_part_obj or target_part_obj.status == 'destroyed':
                log.append(f"> 部位 [{target_part_slot}] 已摧毁，自动命中 [core]。")
                target_part_slot = 'core'

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

    # [修改] 移动动作也使用新的逻辑流程
    # 1. 验证 AP/TP 消耗
    if not (game_state_obj.turn_phase == 'main' and action and execute_main_action(game_state_obj, action, action_name,
                                                                                   part_slot)):
        # execute_main_action 已经记录了错误日志
        return jsonify({'success': False})

    # 2. 执行移动
    game_state_obj.player_pos = tuple(data.get('target_pos'))
    game_state_obj.player_mech.orientation = data.get('final_orientation')
    session['game_state'] = game_state_obj.to_dict()
    log = session.get('combat_log', [])
    log.append(f"> 玩家执行 [{action.name}]。")
    session['combat_log'] = log
    return jsonify({'success': True})


@app.route('/execute_attack', methods=['POST'])
def execute_attack():
    data = request.get_json()
    game_state_obj = GameState.from_dict(session.get('game_state'))
    log = session.get('combat_log', [])
    if game_state_obj.game_over: return jsonify({'success': False})

    action_name = data.get('action_name')
    part_slot = data.get('part_slot')

    attack_action = None
    if part_slot and part_slot in game_state_obj.player_mech.parts:
        part = game_state_obj.player_mech.parts[part_slot]
        if part.status != 'destroyed':
            attack_action = next((a for a in part.actions if a.name == action_name), None)

    if not attack_action:
        log.append(f"> [错误] 无法找到动作: {action_name}。")
        session['combat_log'] = log
        return jsonify({'success': False, 'message': '动作未找到。'})

    if game_state_obj.turn_phase != 'main':
        log.append(f"> [错误] 非主要动作阶段。")
        session['combat_log'] = log
        return jsonify({'success': False, 'message': '非主要动作阶段。'})

    # --- [BUG修复] 新的逻辑流程 ---

    # 1. 确定目标 (背击, 招架, 黑骰子)
    target_part_slot = data.get('target_part_name')
    is_target_determined = (target_part_slot is not None)

    back_attack = is_back_attack(game_state_obj.player_pos, game_state_obj.ai_pos,
                                 game_state_obj.ai_mech.orientation)

    if not is_target_determined:
        if back_attack:
            log.append("> [背击] 请选择目标部位。")
            session['combat_log'] = log
            return jsonify({'success': True, 'action_required': 'select_part'})

        if attack_action.action_type == '近战':
            parry_parts = [(s, p) for s, p in game_state_obj.ai_mech.parts.items() if
                           p.parry > 0 and p.status != 'destroyed']
            if parry_parts:
                target_part_slot, parry_part_obj = max(parry_parts, key=lambda item: item[1].parry)
                log.append(f"> AI 决定用 [{parry_part_obj.name}] 进行招架！")
                is_target_determined = True

        if not is_target_determined:
            roll_result = roll_black_die()
            log.append(f"> [部位骰] 玩家投掷黑骰子，结果为: [{roll_result}]。")

            if roll_result == 'any':
                log.append("> 玩家获得任意选择权！请选择目标部位。")
                session['combat_log'] = log
                return jsonify({'success': True, 'action_required': 'select_part'})

            target_part_slot = roll_result
            is_target_determined = True

            # 检查骰子结果对应的部件是否已摧毁
            target_part_obj = game_state_obj.ai_mech.parts.get(target_part_slot)
            if not target_part_obj or target_part_obj.status == 'destroyed':
                log.append(f"> 部位 [{target_part_slot}] 已摧毁，自动命中 [core]。")
                target_part_slot = 'core'

    # 2. 如果目标已确定 (无论是第一次还是第二次请求)，则消耗AP并执行
    if is_target_determined:

        # 2a. [BUG修复] 在这里消耗 AP/TP
        if not execute_main_action(game_state_obj, attack_action, action_name, part_slot):
            # AP/TP 不足, 或动作已使用
            # execute_main_action 已经记录了日志
            return jsonify({'success': False, 'message': '动作执行失败。'})

        # 2b. 检查近战锁定
        is_player_locked, _ = get_player_lock_status(game_state_obj)
        if is_player_locked and attack_action.action_type == '射击':
            log.append(f"> [错误] 你被近战锁定，无法执行 [{attack_action.name}]！")
            session['combat_log'] = log
            # 注意：AP/TP 已经被消耗了，因为这是规则（尝试射击但失败）
            return jsonify({'success': True})  # 返回True以重载并显示日志

        # 2c. 解析攻击
        attack_log, result = resolve_attack(
            attacker_mech=game_state_obj.player_mech,
            defender_mech=game_state_obj.ai_mech,
            action=attack_action,
            target_part_name=target_part_slot,
            is_back_attack=back_attack
        )
        log.extend(attack_log)

        # 2d. 检查游戏结束
        ai_was_defeated = game_state_obj.ai_mech.parts[
                              'core'].status == 'destroyed' or game_state_obj.ai_mech.get_active_parts_count() < 3

        game_is_over = game_state_obj.check_game_over()

        if game_state_obj.game_mode == 'horde' and ai_was_defeated and not game_is_over:
            log.append(f"> [生存模式] 击败了 {game_state_obj.ai_defeat_count} 台敌机！")
            log.append(f"> [警告] 新的敌人出现: {game_state_obj.ai_mech.name}！")

        session['game_state'] = game_state_obj.to_dict()
        session['combat_log'] = log
        return jsonify({'success': True})

    # 理论上不应该到达这里
    log.append("[严重错误] 攻击逻辑未处理。")
    session['combat_log'] = log
    return jsonify({'success': False, 'message': '攻击逻辑未处理。'})


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


