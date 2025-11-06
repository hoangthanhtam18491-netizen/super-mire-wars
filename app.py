import os
import random
import tempfile
from flask import Flask, render_template, jsonify, request, session, redirect, url_for, make_response
from flask_session import Session
from data_models import (
    Mech, Part, Action, GameEntity, Projectile, Drone
)
from combat_system import resolve_attack, _resolve_effect_logic
from dice_roller import roll_black_die
from game_logic import (
    GameState, is_back_attack,
    get_player_lock_status, get_ai_lock_status,
    _get_distance, is_in_forward_arc,
    run_projectile_logic, run_drone_logic,
    check_interception  # [v1.33 新增] 导入拦截检查
)
from ai_system import run_ai_turn
from parts_database import (
    PLAYER_CORES, PLAYER_LEGS, PLAYER_LEFT_ARMS, PLAYER_RIGHT_ARMS, PLAYER_BACKPACKS,
    AI_LOADOUTS
)
import markdown
import bleach

app = Flask(__name__)
app.secret_key = os.urandom(24)

# --- 服务器端会话配置 ---
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_FILE_DIR"] = tempfile.mkdtemp()
app.config["SESSION_PERMANENT"] = False
Session(app)

MAX_LOG_ENTRIES = 50

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# --- 核心路由 ---

@app.route('/')
def index():
    """渲染游戏的主索引/开始页面。"""
    update_notes = [
        "版本 v1.34: 拦截逻辑修复",
        "- [修复] 修复了拦截系统会重复触发的问题。",
        "- [修复] 修复了被拦截的抛射物仍然能攻击的问题。",
        "- [修复] 修复了AI拦截弹药未正确初始化的问题。",
    ]
    rules_html = ""

    rules_file_path = os.path.join(BASE_DIR, "Game Introduction.md")

    try:
        with open(rules_file_path, "r", encoding="utf-8") as f:
            md_content = f.read()
            html = markdown.markdown(md_content)
            allowed_tags = ['h1', 'h2', 'h3', 'p', 'ul', 'ol', 'li', 'strong', 'em', 'br', 'div']
            rules_html = bleach.clean(html, tags=allowed_tags)
    except FileNotFoundError:
        rules_html = f"<p>错误：在 {rules_file_path} 未找到 Game Introduction.md 文件。</p>"
    except Exception as e:
        rules_html = f"<p>加载规则时出错: {e}</p>"

    return render_template('index.html', update_notes=update_notes, rules_html=rules_html)


@app.route('/hangar')
def hangar():
    """渲染机库页面，用于机甲组装和模式选择。"""
    player_left_arms = {k: v for k, v in PLAYER_LEFT_ARMS.items()}

    return render_template(
        'hangar.html',
        cores=PLAYER_CORES,
        legs=PLAYER_LEGS,
        left_arms=player_left_arms,
        right_arms=PLAYER_RIGHT_ARMS,
        backpacks=PLAYER_BACKPACKS,
        ai_loadouts=AI_LOADOUTS
    )


@app.route('/start_game', methods=['POST'])
def start_game():
    """
    [v1.17]
    处理来自机库的表单，初始化游戏状态并重定向到游戏界面。
    """
    selection = {
        'core': request.form.get('core'),
        'legs': request.form.get('legs'),
        'left_arm': request.form.get('left_arm'),
        'right_arm': request.form.get('right_arm'),
        'backpack': request.form.get('backpack')
    }
    game_mode = request.form.get('game_mode', 'duel')
    ai_opponent_key = request.form.get('ai_opponent')

    game = GameState(
        player_mech_selection=selection,
        ai_loadout_key=ai_opponent_key,
        game_mode=game_mode
    )

    session['game_state'] = game.to_dict()
    log = [f"> 玩家机甲组装完毕。"]

    ai_mech = game.get_ai_mech()
    ai_name = ai_mech.name if ai_mech else "未知AI"

    if game_mode == 'horde':
        log.append(f"> [生存模式] 已启动。")
        log.append(f"> 第一波遭遇: {ai_name}。")
    elif game_mode == 'range':
        log.append(f"> [靶场模式] 已启动。")
        log.append(f"> 遭遇敌机: {ai_name}。")
    else:
        log.append(f"> [决斗模式] 已启动。")
        log.append(f"> 遭遇敌机: {ai_name}。")
    log.append("> 战斗开始！")

    if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
    session['combat_log'] = log
    session['visual_feedback_events'] = []
    # [v1.28] 清除回合过渡标志
    session.pop('run_projectile_phase', None)
    return redirect(url_for('game'))


@app.route('/game', methods=['GET'])
def game():
    """
    [v1.26 修复]
    渲染主游戏界面，显示棋盘、状态和日志。
    修复了 'last_pos' 的清除逻辑，防止重复动画。
    """
    if 'game_state' not in session:
        return redirect(url_for('hangar'))

    game_state_obj = GameState.from_dict(session['game_state'])

    player_mech = game_state_obj.get_player_mech()
    ai_mech = game_state_obj.get_ai_mech()

    if not player_mech:
        return redirect(url_for('hangar'))

    is_player_locked, locker_pos = get_player_lock_status(game_state_obj, player_mech)
    log = session.get('combat_log', [])

    # 1. 弹出 *之前* 存储的事件 (来自 /end_turn 或 /execute_attack)
    visual_events = session.pop('visual_feedback_events', [])

    # [v1.28] 检查是否需要自动运行抛射物阶段
    run_projectile_phase_flag = session.pop('run_projectile_phase', False)

    # 2. 从 *当前* 游戏状态中获取新生成的事件
    state_modified = False
    if hasattr(game_state_obj, 'visual_events') and game_state_obj.visual_events:
        visual_events.extend(game_state_obj.visual_events)
        game_state_obj.visual_events = []  # <-- [BUG FIX] 立即清空 game_state_obj 内部的事件列表
        state_modified = True  # <-- [BUG FIX] 确保这个清空操作会被保存

    # [v1.23] 为 Jinja 模板定义 orientation_map
    orientation_map = {
        'N': '↑', 'S': '↓', 'E': '→', 'W': '←',
        'NONE': ''
    }

    # [AttributeError 修复]
    # player_mech.actions_used_this_turn 存储的是 (slot, name) 元组。
    # Jinja 模板期望一个 [slot, name] 列表列表。
    player_actions_used_tuples = player_mech.actions_used_this_turn
    player_actions_used_lists = [list(t) for t in player_actions_used_tuples]

    # 3. 渲染模板。此时 `game_state_obj` *仍然包含* `last_pos`
    html_to_render = render_template(
        'game.html',
        game=game_state_obj,
        player_mech=player_mech,
        ai_mech=ai_mech,
        combat_log=log,
        is_player_locked=is_player_locked,
        player_actions_used=player_actions_used_lists,  # [AttributeError 修复] 使用转换后的列表
        game_mode=game_state_obj.game_mode,
        ai_defeat_count=game_state_obj.ai_defeat_count,
        visual_feedback_events=visual_events,
        orientationMap=orientation_map,
        run_projectile_phase=run_projectile_phase_flag  # [v1.28] 传递标志
    )

    # --- [v1.26 修复] ---
    # 4. 渲染完成后，*现在*清除所有实体的 `last_pos`
    for entity in game_state_obj.entities.values():
        if entity.last_pos:
            entity.last_pos = None
            state_modified = True  # 标记状态已被修改

    # 5. 保存已清除 `last_pos` 和 `visual_events` 的状态回 session
    if state_modified:
        session['game_state'] = game_state_obj.to_dict()
    # --- 修复结束 ---

    # [v_fix] 创建一个 response 对象并添加“禁止缓存”的头信息
    response = make_response(html_to_render)
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'  # HTTP 1.1.
    response.headers['Pragma'] = 'no-cache'  # HTTP 1.0.
    response.headers['Expires'] = '0'  # Proxies.
    return response


@app.route('/reset_game', methods=['POST'])
def reset_game():
    """清除会话数据，重置游戏并返回机库。"""
    session.pop('game_state', None)
    session.pop('combat_log', None)
    session.pop('visual_feedback_events', None)
    session.pop('run_projectile_phase', None)  # [v1.28] 清除
    return redirect(url_for('hangar'))


@app.route('/end_turn', methods=['POST'])
def end_turn():
    """
    [v_MODIFIED v1.28]
    玩家结束回合。
    流程:
    1. AI 机甲阶段 (AI 机甲移动并发射 '立即' 抛射物, 立即结算攻击)
    2. (v1.28) 暂停, 将 'run_projectile_phase' 标志设为 True, 重定向回 /game
    """
    game_state_obj = GameState.from_dict(session.get('game_state'))
    player_mech = game_state_obj.get_player_mech()

    if game_state_obj.game_over:
        return redirect(url_for('game'))

    log = session.get('combat_log', [])
    if player_mech and player_mech.pending_effect_data:
        log.append("> [错误] 必须先选择效果才能结束回合！")
        if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
        session['combat_log'] = log
        return redirect(url_for('game'))

    log.append("-" * 20)
    log.append("> 玩家回合结束。")

    entities_to_process = list(game_state_obj.entities.values())
    game_ended_mid_turn = False

    # --- 阶段 1: AI 机甲阶段 ---
    log.append("--- AI 机甲阶段 ---")
    for entity in entities_to_process:
        if game_ended_mid_turn: break
        if entity.controller == 'ai' and entity.status == 'ok':

            # 1. AI 机甲逻辑
            if entity.entity_type == 'mech':
                if game_state_obj.game_mode == 'range':
                    log.append("> [靶场模式] AI 跳过回合。")
                    entity.last_pos = None
                else:
                    entity.last_pos = entity.pos
                    # run_ai_turn 现在返回 (log, attacks_to_resolve_list)
                    entity_log, attacks = run_ai_turn(entity, game_state_obj)
                    log.extend(entity_log)

                    # [v_MODIFIED] 立即结算此 AI 机甲的攻击
                    for attack in attacks:
                        if not isinstance(attack, dict): continue

                        attacker_entity = attack.get('attacker')
                        defender_entity = attack.get('defender')
                        attack_action = attack.get('action')

                        if not attacker_entity or not defender_entity or not attack_action:
                            log.append(f"> [严重错误] AI 攻击字典数据不完整: {attack}")
                            continue

                        # [v1.34 修复] 检查攻击者是否已被摧毁 (例如, 被发射时拦截)
                        if attacker_entity.status == 'destroyed':
                            log.append(f"> [结算] 攻击者 {attacker_entity.name} 已被摧毁，攻击取消！")
                            continue

                        if defender_entity.status == 'destroyed':
                            log.append(f"> [AI] {attacker_entity.name} 的目标 {defender_entity.name} 已被摧毁。")
                            continue

                        log.append(f"--- 攻击结算 ({attacker_entity.name} -> {attack_action.name}) ---")

                        back_attack = False
                        if isinstance(defender_entity, Mech):
                            # [BUG FIX] 只有机甲 (Mech) 才能执行背击。抛射物 (Projectile) 不计算背击。
                            if isinstance(attacker_entity, Mech):
                                back_attack = is_back_attack(attacker_entity.pos, defender_entity.pos,
                                                             defender_entity.orientation)
                            # [v1.31 修复] 拦截攻击 (attacker=Mech, defender=Projectile) 不会触发背击
                            elif isinstance(defender_entity, Projectile):
                                back_attack = False

                        target_part_slot = None

                        if isinstance(defender_entity, Mech):
                            if attack_action.action_type == '近战' and not back_attack:
                                parry_parts = [(s, p) for s, p in defender_entity.parts.items() if
                                               p and p.parry > 0 and p.status != 'destroyed']
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

                                    damaged_parts = [s for s, p in defender_entity.parts.items() if
                                                     p and p.status == 'damaged']
                                    if damaged_parts:
                                        target_part_slot = random.choice(damaged_parts)
                                        log.append(f"> AI 优先攻击已受损部件: [{target_part_slot}]。")
                                    elif defender_entity.parts.get('core') and defender_entity.parts[
                                        'core'].status != 'destroyed':
                                        target_part_slot = 'core'
                                        log.append("> AI 决定攻击 [核心]。")
                                    else:
                                        valid_parts = [s for s, p in defender_entity.parts.items() if
                                                       p and p.status != 'destroyed']
                                        target_part_slot = random.choice(valid_parts) if valid_parts else 'core'

                                elif defender_entity.parts.get(hit_roll_result) and defender_entity.parts[
                                    hit_roll_result].status != 'destroyed':
                                    target_part_slot = hit_roll_result
                                else:
                                    target_part_slot = 'core'
                                    log.append(f"> 部位 [{hit_roll_result}] 不存在或已摧毁，转而命中 [核心]。")

                        else:
                            # [v1.31 修复] 目标是 Projectile 或 Drone
                            target_part_slot = 'core'
                            log.append(f"> 攻击自动瞄准 [{defender_entity.name}] 的核心。")

                        attack_log, result, overflow_data, dice_roll_details = resolve_attack(
                            attacker_entity=attacker_entity,
                            defender_entity=defender_entity,
                            action=attack_action,
                            target_part_name=target_part_slot,
                            is_back_attack=back_attack,
                            chosen_effect=None
                        )
                        log.extend(attack_log)

                        if dice_roll_details:
                            game_state_obj.add_visual_event(
                                'dice_roll',
                                attacker_name=attacker_entity.name,
                                defender_name=defender_entity.name,
                                action_name=attack_action.name,
                                details=dice_roll_details
                            )

                        game_state_obj.add_visual_event(
                            'attack_result',
                            defender_pos=defender_entity.pos,
                            result_text=result
                        )

                        game_is_over = game_state_obj.check_game_over()
                        if game_is_over and game_state_obj.game_over == 'ai_win':
                            log.append(f"> 玩家机甲已被摧毁！")
                            if game_state_obj.game_mode == 'horde':
                                log.append(f"> [生存模式] 最终击败数: {game_state_obj.ai_defeat_count}")
                            game_ended_mid_turn = True
                            break  # 停止结算攻击

            # 2. AI 无人机逻辑 (目前无攻击, 仅记录日志)
            elif entity.entity_type == 'drone':
                entity_log, attacks = run_drone_logic(entity, game_state_obj)
                log.extend(entity_log)
                # (如果无人机未来有攻击, 也应在这里结算)

    # --- [v1.28] 阶段 1 结束 ---
    log.append("--- AI 机甲阶段结束 ---")

    session['game_state'] = game_state_obj.to_dict()
    if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
    session['combat_log'] = log
    session['visual_feedback_events'] = game_state_obj.visual_events

    # [v1.28] 设置标志, 让 /game 在重定向后触发 JS 暂停, 然后再调用 /run_projectile_phase
    if not game_ended_mid_turn:
        session['run_projectile_phase'] = True

    return redirect(url_for('game'))


@app.route('/run_projectile_phase', methods=['POST'])
def run_projectile_phase():
    """
    [v1.28 新增]
    在 AI 机甲阶段之后由 JS 调用的独立路由。
    流程:
    1. 延迟动作阶段 (所有 '延迟' 抛射物 (玩家和AI的) 移动并攻击, 立即结算攻击)
    2. 回合重置
    """
    game_state_obj = GameState.from_dict(session.get('game_state'))
    log = session.get('combat_log', [])

    if game_state_obj.game_over:
        return redirect(url_for('game'))

    game_ended_mid_turn = False

    # --- 阶段 2: 延迟动作阶段 (抛射物) ---
    log.append("--- 延迟动作阶段 (抛射物) ---")

    # 重新获取实体列表, 因为 '立即' 动作可能生成了新的抛射物
    entities_to_process = list(game_state_obj.entities.values())

    for entity in entities_to_process:
        if game_ended_mid_turn: break

        # 运行所有抛射物 (无论属于谁)
        if entity.entity_type == 'projectile' and entity.status == 'ok':
            # [v_MODIFIED] 运行 '延迟' 逻辑
            entity_log, attacks = run_projectile_logic(entity, game_state_obj, '延迟')
            log.extend(entity_log)  # [v1.29 修复] 确保移动日志被记录

            # [v_MODIFIED] 立即结算此抛射物的攻击
            for attack in attacks:
                if not isinstance(attack, dict): continue

                attacker_entity = attack.get('attacker')
                defender_entity = attack.get('defender')
                attack_action = attack.get('action')

                if not attacker_entity or not defender_entity or not attack_action:
                    log.append(f"> [严重错误] 抛射物攻击字典数据不完整: {attack}")
                    continue

                # [v1.31 修复] 检查攻击者是否已被摧毁 (例如, 被拦截)
                if attacker_entity.status == 'destroyed':
                    log.append(f"> [结算] 攻击者 {attacker_entity.name} 已被摧毁，攻击取消！")
                    continue

                if defender_entity.status == 'destroyed':
                    log.append(f"> [结算] {attacker_entity.name} 的目标 {defender_entity.name} 已被摧毁。")
                    continue

                log.append(f"--- 攻击结算 ({attacker_entity.name} -> {attack_action.name}) ---")

                back_attack = False
                if isinstance(defender_entity, Mech):
                    # [BUG FIX] 抛射物不计算背击
                    if isinstance(attacker_entity, Mech):
                        back_attack = is_back_attack(attacker_entity.pos, defender_entity.pos,
                                                     defender_entity.orientation)
                    # [v1.31 修复] 拦截攻击 (attacker=Mech, defender=Projectile) 不会触发背击
                    elif isinstance(defender_entity, Projectile):
                        back_attack = False

                target_part_slot = None

                if isinstance(defender_entity, Mech):
                    if attack_action.action_type == '近战' and not back_attack:
                        # 抛射物不会触发招架, 跳过
                        pass

                    if not target_part_slot:
                        hit_roll_result = roll_black_die()
                        log.append(f"> 投掷部位骰结果: 【{hit_roll_result}】")
                        if hit_roll_result == 'any' or back_attack:
                            # (抛射物没有智能, 随机选择)
                            valid_parts = [s for s, p in defender_entity.parts.items() if
                                           p and p.status != 'destroyed']
                            target_part_slot = random.choice(valid_parts) if valid_parts else 'core'
                            log.append(f"> 抛射物随机命中: [{target_part_slot}]。")

                        elif defender_entity.parts.get(hit_roll_result) and defender_entity.parts[
                            hit_roll_result].status != 'destroyed':
                            target_part_slot = hit_roll_result
                        else:
                            target_part_slot = 'core'
                            log.append(f"> 部位 [{hit_roll_result}] 不存在或已摧毁，转而命中 [核心]。")

                else:
                    # [v1.31 修复] 目标是 Projectile 或 Drone
                    target_part_slot = 'core'
                    log.append(f"> 攻击自动瞄准 [{defender_entity.name}] 的核心。")

                attack_log, result, overflow_data, dice_roll_details = resolve_attack(
                    attacker_entity=attacker_entity,
                    defender_entity=defender_entity,
                    action=attack_action,
                    target_part_name=target_part_slot,
                    is_back_attack=back_attack,
                    chosen_effect=None
                )
                log.extend(attack_log)

                if dice_roll_details:
                    game_state_obj.add_visual_event(
                        'dice_roll',
                        attacker_name=attacker_entity.name,
                        defender_name=defender_entity.name,
                        action_name=attack_action.name,
                        details=dice_roll_details
                    )

                game_state_obj.add_visual_event(
                    'attack_result',
                    defender_pos=defender_entity.pos,
                    result_text=result
                )

                # [v_MODIFIED] 检查游戏是否在抛射物攻击后结束
                game_is_over = game_state_obj.check_game_over()
                if game_is_over:
                    if game_state_obj.game_over == 'ai_win':
                        log.append(f"> 玩家机甲已被摧毁！")
                    elif game_state_obj.game_over == 'player_win':
                        log.append(f"> AI 机甲已被摧毁！")

                    if game_state_obj.game_mode == 'horde' and game_state_obj.game_over == 'ai_win':
                        log.append(f"> [生存模式] 最终击败数: {game_state_obj.ai_defeat_count}")

                    game_ended_mid_turn = True
                    break  # 停止结算攻击

    # --- 阶段 3: 回合结束 ---
    if not game_state_obj.game_over:
        log.append(
            "> AI回合结束。请开始你的回合。" if game_state_obj.game_mode != 'range' else "> [靶场模式] 请开始你的回合。")
        log.append("-" * 20)

        player_mech = game_state_obj.get_player_mech()  # [v1.28] 重新获取
        if player_mech:
            player_mech.player_ap = 2
            player_mech.player_tp = 1
            player_mech.turn_phase = 'timing'
            player_mech.timing = None
            player_mech.opening_move_taken = False
            player_mech.actions_used_this_turn = []
            player_mech.pending_effect_data = None
            # [v_MODIFIED] 不再在这里重置 last_pos

        game_state_obj.check_game_over()

    session['game_state'] = game_state_obj.to_dict()
    if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
    session['combat_log'] = log
    session['visual_feedback_events'] = game_state_obj.visual_events
    return redirect(url_for('game'))


@app.route('/respawn_ai', methods=['POST'])
def respawn_ai():
    """[v1.17] 靶场模式下，重新生成一个AI。"""
    game_state_obj = GameState.from_dict(session.get('game_state'))
    log = session.get('combat_log', [])

    if game_state_obj.game_mode == 'range' and game_state_obj.game_over == 'ai_defeated_in_range':
        game_state_obj._spawn_range_ai()
        ai_mech = game_state_obj.get_ai_mech()
        ai_name = ai_mech.name if ai_mech else "未知AI"

        log.append("-" * 20)
        log.append(f"> [靶场模式] 新的目标出现: {ai_name}！")
        log.append("> 请开始你的回合。")
    else:
        log.append("[错误] 尝试在非靶场模式下重生AI。")

    session['game_state'] = game_state_obj.to_dict()
    if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
    session['combat_log'] = log
    session['visual_feedback_events'] = game_state_obj.visual_events
    return redirect(url_for('game'))


# --- [v1.17] 玩家动作路由 (已重构) ---

def _clear_transient_state(game_state_obj):
    """(辅助函数) 清除所有用于单次动画的状态"""
    for entity in game_state_obj.entities.values():
        entity.last_pos = None
    game_state_obj.visual_events = []
    return game_state_obj


def _get_game_state_and_player(data):
    """(辅助函数) 从 session 和 data 中安全地获取 game_state 和 player_mech。"""
    game_state_obj = GameState.from_dict(session.get('game_state'))
    if not game_state_obj:
        return None, None, jsonify({'success': False, 'message': '游戏状态丢失，请刷新。'})

    player_id = data.get('player_id', 'player_1')
    player_mech = game_state_obj.get_entity_by_id(player_id)

    if not player_mech or player_mech.entity_type != 'mech':
        return game_state_obj, None, jsonify({'success': False, 'message': '找不到玩家机甲实体。'})

    return game_state_obj, player_mech, None


@app.route('/select_timing', methods=['POST'])
def select_timing():
    data = request.get_json()
    game_state_obj, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    timing = data.get('timing')

    if player_mech.turn_phase == 'timing' and not game_state_obj.game_over:
        player_mech.timing = timing

        game_state_obj = _clear_transient_state(game_state_obj)
        session['game_state'] = game_state_obj.to_dict()
        return jsonify({'success': True})
    return jsonify({'success': False})


@app.route('/confirm_timing', methods=['POST'])
def confirm_timing():
    data = request.get_json()
    game_state_obj, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    if player_mech.turn_phase == 'timing' and player_mech.timing and not game_state_obj.game_over:
        player_mech.turn_phase = 'stance'

        game_state_obj = _clear_transient_state(game_state_obj)
        session['game_state'] = game_state_obj.to_dict()
        log = session.get('combat_log', [])
        log.append(f"> 时机已确认为 [{player_mech.timing}]。进入姿态选择阶段。")
        if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
        session['combat_log'] = log
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Please select a timing first.'})


@app.route('/change_stance', methods=['POST'])
def change_stance():
    data = request.get_json()
    game_state_obj, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    new_stance = data.get('stance')
    if player_mech.turn_phase == 'stance' and not game_state_obj.game_over:
        player_mech.stance = new_stance

        game_state_obj = _clear_transient_state(game_state_obj)
        session['game_state'] = game_state_obj.to_dict()
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Not in stance phase.'})


@app.route('/confirm_stance', methods=['POST'])
def confirm_stance():
    data = request.get_json()
    game_state_obj, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    if player_mech.turn_phase == 'stance' and not game_state_obj.game_over:
        player_mech.turn_phase = 'adjustment'

        game_state_obj = _clear_transient_state(game_state_obj)
        session['game_state'] = game_state_obj.to_dict()
        log = session.get('combat_log', [])
        log.append(f"> 姿态已确认为 [{player_mech.stance}]。进入调整阶段。")
        if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
        session['combat_log'] = log
        return jsonify({'success': True})
    return jsonify({'success': False})


@app.route('/execute_adjust_move', methods=['POST'])
def execute_adjust_move():
    data = request.get_json()
    game_state_obj, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    if player_mech.turn_phase == 'adjustment' and player_mech.player_tp >= 1 and not game_state_obj.game_over:
        player_mech.last_pos = player_mech.pos
        player_mech.pos = tuple(data.get('target_pos'))
        player_mech.orientation = data.get('final_orientation')
        player_mech.player_tp -= 1
        player_mech.turn_phase = 'main'

        session['game_state'] = game_state_obj.to_dict()
        log = session.get('combat_log', [])
        log.append(f"> 玩家调整移动到 {player_mech.pos}。进入主动作阶段。")
        if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
        session['combat_log'] = log
        return jsonify({'success': True})
    return jsonify({'success': False})


@app.route('/change_orientation', methods=['POST'])
def change_orientation():
    data = request.get_json()
    game_state_obj, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    if player_mech.turn_phase == 'adjustment' and player_mech.player_tp >= 1 and not game_state_obj.game_over:
        player_mech.orientation = data.get('final_orientation')
        player_mech.player_tp -= 1
        player_mech.turn_phase = 'main'

        game_state_obj = _clear_transient_state(game_state_obj)
        session['game_state'] = game_state_obj.to_dict()
        log = session.get('combat_log', [])
        log.append(f"> 玩家仅转向。进入主动作阶段。")
        if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
        session['combat_log'] = log
        return jsonify({'success': True})
    return jsonify({'success': False})


@app.route('/skip_adjustment', methods=['POST'])
def skip_adjustment():
    data = request.get_json()
    game_state_obj, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    if player_mech.turn_phase == 'adjustment' and not game_state_obj.game_over:
        player_mech.turn_phase = 'main'

        game_state_obj = _clear_transient_state(game_state_obj)
        session['game_state'] = game_state_obj.to_dict()
        log = session.get('combat_log', [])
        log.append(f"> 玩家跳过调整阶段。进入主动作阶段。")
        if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
        session['combat_log'] = log
        return jsonify({'success': True})
    return jsonify({'success': False})


def execute_main_action(game_state, player_mech, action, action_name, part_slot):
    """ (服务器端) 验证并执行一个主动作。 """
    log = session.get('combat_log', [])
    action_id = (part_slot, action_name)

    if action_id in player_mech.actions_used_this_turn:
        log.append(f"> [错误] [{action_name}] (来自: {part_slot}) 本回合已使用过。")
        if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
        session['combat_log'] = log
        return False, "本回合已使用"

    ammo_key = (player_mech.id, part_slot, action.name)
    if action.ammo > 0:
        current_ammo = game_state.ammo_counts.get(ammo_key, 0)
        if current_ammo <= 0:
            log.append(f"> [错误] 弹药耗尽，无法执行 [{action.name}]。")
            if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
            session['combat_log'] = log
            return False, "弹药耗尽"

    ap_cost = action.cost.count('M') * 2 + action.cost.count('S') * 1
    tp_cost = 0
    if action.cost == 'L':
        ap_cost = 2
        tp_cost = 1

    if player_mech.player_ap < ap_cost:
        log.append(f"> [错误] AP不足 (需要 {ap_cost})，无法执行 [{action.name}]。")
        if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
        session['combat_log'] = log
        return False, "AP不足"

    if player_mech.player_tp < tp_cost:
        log.append(f"> [错误] TP不足 (需要 {tp_cost})，无法执行 [{action.name}]。")
        if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
        session['combat_log'] = log
        return False, "TP不足"

    if not player_mech.opening_move_taken:
        if action.action_type != player_mech.timing:
            log.append(f"> [错误] 起手动作错误！当前时机为 [{player_mech.timing}]，无法执行 [{action.action_type}] 动作。")
            if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
            session['combat_log'] = log
            return False, "起手动作时机错误"
        player_mech.opening_move_taken = True

    player_mech.player_ap -= ap_cost
    player_mech.player_tp -= tp_cost
    player_mech.actions_used_this_turn.append((part_slot, action_name))

    # [v_MODIFIED] 弹药消耗逻辑移至 /execute_attack 以处理【齐射】
    # [v1.30] 拦截动作的弹药在 game_logic.py 中消耗
    if action.ammo > 0 and action.action_type != '抛射' and not action.effects.get("interceptor"):
        game_state.ammo_counts[ammo_key] -= 1
        log.append(f"> [{action.name}] 消耗 1 弹药，剩余 {game_state.ammo_counts[ammo_key]}。")

    return True, "Success"


@app.route('/move_player', methods=['POST'])
def move_player():
    """(AJAX) 处理玩家的“移动”类型动作（非调整移动）。"""
    data = request.get_json()
    game_state_obj, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    if game_state_obj.game_over: return jsonify({'success': False})

    log = session.get('combat_log', [])
    if player_mech.pending_effect_data:
        log.append("> [错误] 必须先解决待处理的效果选择！")
        if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
        session['combat_log'] = log
        session['visual_feedback_events'] = game_state_obj.visual_events
        return jsonify({'success': False, 'message': '必须先选择效果！'})

    action_name = data.get('action_name')
    part_slot = data.get('part_slot')
    action = player_mech.get_action_by_name_and_slot(action_name, part_slot)

    if player_mech.turn_phase == 'main' and action:
        success, message = execute_main_action(game_state_obj, player_mech, action, action_name, part_slot)
        if success:
            player_mech.last_pos = player_mech.pos
            player_mech.pos = tuple(data.get('target_pos'))
            player_mech.orientation = data.get('final_orientation')

            session['game_state'] = game_state_obj.to_dict()
            log.append(f"> 玩家执行 [{action.name}]。")
            if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
            session['combat_log'] = log
            return jsonify({'success': True})

    return jsonify({'success': False, 'message': message if 'message' in locals() else '动作执行失败'})


@app.route('/execute_attack', methods=['POST'])
def execute_attack():
    """
    [v_MODIFIED v1.34]
    (AJAX) 处理玩家的“攻击”动作（近战、射击、抛射）。
    - 增加了【齐射】 (Salvo) 逻辑。
    - 增加了【立即】 (Immediate) 抛射物结算逻辑。
    - 修复了拦截逻辑
    """
    data = request.get_json()
    game_state_obj, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    log = session.get('combat_log', [])
    if game_state_obj.game_over: return jsonify({'success': False})

    if player_mech.pending_effect_data:
        log.append("> [错误] 必须先解决待处理的效果选择！")
        if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
        session['combat_log'] = log
        session['visual_feedback_events'] = game_state_obj.visual_events
        return jsonify({'success': False, 'message': '必须先选择效果！'})

    action_name = data.get('action_name')
    part_slot = data.get('part_slot')
    attack_action = player_mech.get_action_by_name_and_slot(action_name, part_slot)

    if player_mech.turn_phase == 'main' and attack_action:

        target_entity_id = data.get('target_entity_id')
        defender_entity = None

        if target_entity_id:
            defender_entity = game_state_obj.get_entity_by_id(target_entity_id)
            if not defender_entity:
                log.append(f"> [错误] 找不到目标实体 ID: {target_entity_id}。")
                if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
                session['combat_log'] = log
                return jsonify({'success': False, 'message': 'Target entity not found.'})

        valid_targets_list, valid_launch_cells_list = game_state_obj.calculate_attack_range(
            player_mech, attack_action
        )

        # 1. 检查是否是 '抛射' 动作
        if attack_action.action_type == '抛射':
            target_pos_tuple = tuple(data.get('target_pos')) if data.get('target_pos') else None

            target_pos = None
            if defender_entity:
                target_pos = defender_entity.pos
            elif target_pos_tuple:
                target_pos = target_pos_tuple

            target_is_valid = False
            if target_pos in valid_launch_cells_list:
                target_is_valid = True
            if not target_is_valid and defender_entity:
                if any(t['entity'].id == defender_entity.id for t in valid_targets_list):
                    target_is_valid = True
                    target_pos = defender_entity.pos  # 覆盖地块目标为实体目标

            if not target_is_valid or not target_pos:
                log.append(f"> [错误] 目标位置 {target_pos} 不在有效发射范围内。")
                if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
                session['combat_log'] = log
                return jsonify({'success': False, 'message': 'Target position out of launch range.'})

            # [v_MODIFIED] 先验证动作,但不消耗弹药
            success, message = execute_main_action(game_state_obj, player_mech, attack_action, action_name, part_slot)
            if not success:
                return jsonify({'success': False, 'message': message})

            # [v1.33 修复] 在这里初始化列表
            attacks_to_resolve_list = []

            # [v_MODIFIED] 处理【齐射】和弹药
            salvo_count = attack_action.effects.get("salvo", 1)
            ammo_key = (player_mech.id, part_slot, attack_action.name)
            current_ammo = game_state_obj.ammo_counts.get(ammo_key, 0)

            projectiles_to_launch = min(salvo_count, current_ammo)

            if projectiles_to_launch <= 0:
                log.append(f"> [错误] 弹药耗尽，无法执行 [{attack_action.name}]。")
                if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
                session['combat_log'] = log
                return jsonify({'success': False, 'message': '弹药耗尽'})

            # 消耗弹药
            game_state_obj.ammo_counts[ammo_key] -= projectiles_to_launch

            log.append(f"> 玩家发射 [{attack_action.name}] 到 {target_pos}！")
            if projectiles_to_launch > 1:
                log.append(f"> 【齐射{projectiles_to_launch}】触发！发射 {projectiles_to_launch} 枚抛射物。")
            log.append(f"> 消耗 {projectiles_to_launch} 弹药, 剩余 {game_state_obj.ammo_counts[ammo_key]}。")

            # [v_MODIFIED] 循环生成抛射物
            for _ in range(projectiles_to_launch):
                projectile_id, projectile_obj = game_state_obj.spawn_projectile(
                    launcher_entity=player_mech,
                    target_pos=target_pos,
                    projectile_key=attack_action.projectile_to_spawn
                )

                if not projectile_obj:
                    log.append(f"> [错误] 生成抛射物 {attack_action.projectile_to_spawn} 失败！")
                    continue

                # [v1.34 修复] 检查抛射物是否有'立即'动作
                has_immediate_action = projectile_obj.get_action_by_timing('立即')[0] is not None

                # [v1.34 修复] 只有 '延迟' 抛射物 (如导弹) 才在发射时检查拦截
                if not has_immediate_action:
                    intercept_log, intercept_attacks = check_interception(projectile_obj, game_state_obj)
                    if intercept_attacks:
                        log.extend(intercept_log)
                        attacks_to_resolve_list.extend(intercept_attacks)

                # [v_MODIFIED] 立即检查 '立即' 动作 (例如火箭弹)
                entity_log, attacks = run_projectile_logic(projectile_obj, game_state_obj, '立即')
                log.extend(entity_log)
                # [v1.33 修复] 将 '立即' 攻击添加到同一个列表
                attacks_to_resolve_list.extend(attacks)

            # [v_MODIFIED] 立即结算 '立即' 动作的攻击
            # [v1.33 修复] 循环遍历 *所有* 待处理的攻击 (拦截 + 立即)
            for attack in attacks_to_resolve_list:
                if not isinstance(attack, dict): continue
                attacker = attack.get('attacker')
                defender = attack.get('defender')
                action = attack.get('action')
                if not attacker or not defender or not action: continue

                # [v1.34 修复] 检查攻击者是否已被摧毁
                if attacker.status == 'destroyed':
                    log.append(f"> [结算] 攻击者 {attacker.name} 已被摧毁，攻击取消！")
                    continue
                # [v1.34 修复] 检查防御者是否已被摧毁 (例如被同一个齐射中的前一枚火箭弹)
                if defender.status == 'destroyed':
                    log.append(f"> [结算] 目标 {defender.name} 已被摧毁，攻击跳过。")
                    continue

                log.append(f"--- [立即引爆] 结算 ({attacker.name} -> {action.name}) ---")

                back_attack = False  # 抛射物不计算背击
                target_part_slot = None

                if isinstance(defender, Mech):
                    hit_roll_result = roll_black_die()
                    log.append(f"> 投掷部位骰结果: 【{hit_roll_result}】")
                    if hit_roll_result == 'any':
                        valid_parts = [s for s, p in defender.parts.items() if p and p.status != 'destroyed']
                        target_part_slot = random.choice(valid_parts) if valid_parts else 'core'
                        log.append(f"> 抛射物随机命中: [{target_part_slot}]。")
                    elif defender.parts.get(hit_roll_result) and defender.parts[
                        hit_roll_result].status != 'destroyed':
                        target_part_slot = hit_roll_result
                    else:
                        target_part_slot = 'core'
                        log.append(f"> 部位 [{hit_roll_result}] 不存在或已摧毁，转而命中 [核心]。")
                else:
                    target_part_slot = 'core'
                    log.append(f"> 攻击自动瞄准 [{defender.name}] 的核心。")

                attack_log, result, overflow_data, dice_roll_details = resolve_attack(
                    attacker_entity=attacker,
                    defender_entity=defender,
                    action=action,
                    target_part_name=target_part_slot,
                    is_back_attack=False,  # 抛射物不计算背击
                    chosen_effect=None
                )
                log.extend(attack_log)

                if dice_roll_details:
                    game_state_obj.add_visual_event(
                        'dice_roll',
                        attacker_name=attacker.name,
                        defender_name=defender.name,
                        action_name=action.name,
                        details=dice_roll_details
                    )
                game_state_obj.add_visual_event(
                    'attack_result',
                    defender_pos=defender.pos,
                    result_text=result
                )
                game_state_obj.check_game_over()
                if game_state_obj.game_over:
                    break  # 如果游戏结束, 停止结算

            session['game_state'] = game_state_obj.to_dict()
            if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
            session['combat_log'] = log
            session['visual_feedback_events'] = game_state_obj.visual_events
            return jsonify({'success': True})

        # 2. 检查是否是 '射击' 或 '近战' 动作
        elif attack_action.action_type in ['射击', '近战']:
            if not defender_entity:
                log.append(f"> [错误] 射击/近战动作需要一个实体目标。")
                if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
                session['combat_log'] = log
                return jsonify({'success': False, 'message': 'Shooting/Melee requires an entity target.'})

            target_data = next((t for t in valid_targets_list if t['entity'].id == defender_entity.id), None)
            if not target_data:
                log.append(f"> [错误] 目标 {defender_entity.name} 不在有效攻击范围内。")
                if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
                session['combat_log'] = log
                return jsonify({'success': False, 'message': 'Target out of range.'})

            is_player_locked, _ = get_player_lock_status(game_state_obj, player_mech)
            if is_player_locked and attack_action.action_type == '射击':
                log.append(f"> [错误] 你被近战锁定，无法执行 [{attack_action.name}]！")
                if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
                session['combat_log'] = log
                return jsonify({'success': False, 'message': '被近战锁定，无法射击！'})

            back_attack = target_data['is_back_attack']
            target_part_slot = data.get('target_part_name')

            has_two_handed_sniper = attack_action.effects.get("two_handed_sniper", False)
            two_handed_sniper_active = False
            if has_two_handed_sniper:
                other_arm_slot = 'left_arm' if part_slot == 'right_arm' else 'right_arm'
                other_arm_part = player_mech.parts.get(other_arm_slot)
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

                if isinstance(defender_entity, Mech):
                    if attack_action.action_type == '近战':
                        parry_parts = [(s, p) for s, p in defender_entity.parts.items() if
                                       p and p.parry > 0 and p.status != 'destroyed']
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

                    if isinstance(defender_entity, Mech) and defender_entity.parts.get(hit_roll_result) and \
                            defender_entity.parts[hit_roll_result].status != 'destroyed':
                        target_part_slot = hit_roll_result
                    else:
                        target_part_slot = 'core'
                        if isinstance(defender_entity, Mech):
                            log.append(f"> 部位 [{hit_roll_result}] 不存在或已摧毁，转而命中 [核心]。")
                        else:
                            log.append(f"> 目标为非机甲单位，自动命中 [核心]。")

            success, message = execute_main_action(game_state_obj, player_mech, attack_action, action_name, part_slot)
            if not success:
                return jsonify({'success': False, 'message': message})

            if not target_part_slot:
                log.append("> [严重错误] 未能确定目标部件！攻击中止。")
                if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
                session['combat_log'] = log
                return jsonify({'success': False, 'message': 'Internal error: Target part slot not determined.'})

            attack_log, result, overflow_data, dice_roll_details = resolve_attack(
                attacker_entity=player_mech,
                defender_entity=defender_entity,
                action=attack_action,
                target_part_name=target_part_slot,
                is_back_attack=back_attack,
                chosen_effect=None
            )

            if dice_roll_details:
                game_state_obj.add_visual_event(
                    'dice_roll',
                    attacker_name=player_mech.name,
                    defender_name=defender_entity.name,
                    action_name=attack_action.name,
                    details=dice_roll_details
                )

            game_state_obj.add_visual_event(
                'attack_result',
                defender_pos=defender_entity.pos,
                result_text=result
            )

            if result == "effect_choice_required":
                log.extend(attack_log)

                player_mech.pending_effect_data = {
                    'action_dict': attack_action.to_dict(),
                    'overflow_data': {'hits': overflow_data['hits'], 'crits': overflow_data['crits']},
                    'options': overflow_data['options'],
                    'target_entity_id': defender_entity.id,
                    'target_part_name': target_part_slot,
                    'is_back_attack': back_attack,
                    'choice': None
                }
                session['game_state'] = game_state_obj.to_dict()
                if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
                session['combat_log'] = log
                session['visual_feedback_events'] = game_state_obj.visual_events
                return jsonify(
                    {'success': True, 'action_required': 'select_effect', 'options': overflow_data['options']})

            log.extend(attack_log)
            player_mech.pending_effect_data = None

            ai_was_defeated = (defender_entity.controller == 'ai' and
                               (defender_entity.status == 'destroyed' or
                                (isinstance(defender_entity, Mech) and defender_entity.parts.get('core') and (
                                        defender_entity.parts[
                                            'core'].status == 'destroyed' or defender_entity.get_active_parts_count() < 3))))

            game_is_over = game_state_obj.check_game_over()

            ai_mech = game_state_obj.get_ai_mech()
            if game_state_obj.game_mode == 'horde' and ai_was_defeated and not game_is_over and ai_mech:
                log.append(f"> [生存模式] 击败了 {game_state_obj.ai_defeat_count} 台敌机！")
                log.append(f"> [警告] 新的敌人出现: {ai_mech.name}！")

            session['game_state'] = game_state_obj.to_dict()
            if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
            session['combat_log'] = log
            session['visual_feedback_events'] = game_state_obj.visual_events
            return jsonify({'success': True})

    if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
    session['combat_log'] = log
    return jsonify({'success': False, 'message': '动作未在 main 阶段执行或动作未找到。'})


@app.route('/resolve_effect_choice', methods=['POST'])
def resolve_effect_choice():
    """
    [v1.17]
    (AJAX) 接收玩家关于【毁伤】/【霰射】/【顺劈】的选择。
    """
    data = request.get_json()
    choice = data.get('choice')

    game_state_obj, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    log = session.get('combat_log', [])
    pending_data = player_mech.pending_effect_data

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

    target_entity_id = pending_data['target_entity_id']
    target_entity = game_state_obj.get_entity_by_id(target_entity_id)
    if not target_entity or target_entity.status == 'destroyed':
        log.append(f"> [错误] 在解析效果时找不到目标实体: {target_entity_id}")
        if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
        session['combat_log'] = log
        return jsonify({'success': False, 'message': 'Target entity not found.'})

    if not isinstance(target_entity, Mech):
        log.append(f"> [错误] 效果只能对机甲触发: {target_entity_id}")
        if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
        session['combat_log'] = log
        return jsonify({'success': False, 'message': 'Target is not a Mech.'})

    target_part_name = pending_data['target_part_name']
    target_part = target_entity.get_part_by_name(target_part_name)

    if not target_part:
        log.append(f"> [错误] 在解析效果时找不到目标部件: {target_part_name}")
        if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
        session['combat_log'] = log
        return jsonify({'success': False, 'message': 'Target part not found.'})

    overflow_hits = pending_data['overflow_data']['hits']
    overflow_crits = pending_data['overflow_data']['crits']

    log.append(
        f"> 玩家选择了【{'毁伤' if choice == 'devastating' else ('霰射' if choice == 'scattershot' else '顺劈')}】！")

    from combat_system import _resolve_effect_logic

    log_ext_list, secondary_roll_details = _resolve_effect_logic(
        log=log,
        defender_entity=target_entity,
        target_part=target_part,
        overflow_hits=overflow_hits,
        overflow_crits=overflow_crits,
        chosen_effect=choice
    )

    if secondary_roll_details:
        game_state_obj.add_visual_event(
            'dice_roll',
            attacker_name=player_mech.name,
            defender_name=target_entity.name,
            action_name=choice.capitalize(),
            details=secondary_roll_details
        )

    game_state_obj.add_visual_event(
        'attack_result',
        defender_pos=target_entity.pos,
        result_text='击穿'
    )

    player_mech.pending_effect_data = None

    ai_was_defeated = (target_entity.controller == 'ai' and
                       (target_entity.status == 'destroyed' or
                        (isinstance(target_entity, Mech) and target_entity.parts.get('core') and (target_entity.parts[
                                                                                                      'core'].status == 'destroyed' or target_entity.get_active_parts_count() < 3))))

    game_is_over = game_state_obj.check_game_over()

    ai_mech = game_state_obj.get_ai_mech()
    if game_state_obj.game_mode == 'horde' and ai_was_defeated and not game_is_over and ai_mech:
        log.append(f"> [生存模式] 击败了 {game_state_obj.ai_defeat_count} 台敌机！")
        log.append(f"> [警告] 新的敌人出现: {ai_mech.name}！")

    session['game_state'] = game_state_obj.to_dict()
    if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
    session['combat_log'] = log
    session['visual_feedback_events'] = game_state_obj.visual_events
    return jsonify({'success': True})


# --- [v1.22] 数据请求路由 (已重构) ---
@app.route('/get_move_range', methods=['POST'])
def get_move_range():
    data = request.get_json()
    game_state_obj, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    if game_state_obj.game_over: return jsonify({'valid_moves': []})

    action_name = data.get('action_name')
    part_slot = data.get('part_slot')
    action = None
    is_flight_action = False
    move_distance = 0

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
        valid_moves = game_state_obj.calculate_move_range(
            player_mech,
            move_distance,
            is_flight=is_flight_action
        )
        return jsonify({'valid_moves': valid_moves})

    return jsonify({'valid_moves': []})


@app.route('/get_attack_range', methods=['POST'])
def get_attack_range():
    data = request.get_json()
    game_state_obj, player_mech, error_response = _get_game_state_and_player(data)
    if error_response: return error_response

    if game_state_obj.game_over:
        return jsonify({'valid_targets': [], 'valid_launch_cells': []})

    action_name = data.get('action_name')
    part_slot = data.get('part_slot')
    action = player_mech.get_action_by_name_and_slot(action_name, part_slot)

    if action:
        valid_targets_list, valid_launch_cells_list = game_state_obj.calculate_attack_range(
            player_mech,
            action
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


if __name__ == '__main__':
    app.run(debug=True)