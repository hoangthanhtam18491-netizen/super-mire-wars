import random
import os  # [MODIFIED] 确保 os 被导入
from flask import Blueprint, render_template, session, redirect, url_for, make_response
from game_logic.game_logic import GameState, is_back_attack, get_player_lock_status, check_interception
from game_logic.ai_system import run_ai_turn
from game_logic.combat_system import resolve_attack
from game_logic.dice_roller import roll_black_die
from game_logic.data_models import Mech, Projectile
from game_logic.game_logic import run_projectile_logic, run_drone_logic

# [v_REFACTOR]
# “优化 1” - 这是一个新的蓝图文件
# 它包含核心游戏循环路由 (/game, /end_turn, /reset_game 等)

game_bp = Blueprint('game', __name__)

MAX_LOG_ENTRIES = 50


@game_bp.route('/game', methods=['GET'])
def game():
    """
    [v_REROLL_FIX]
    修复了状态管理逻辑，防止在页面刷新时清除待处理的 visual_events。
    """
    if 'game_state' not in session:
        # [v_REFACTOR] 重定向到 'main.hangar'
        return redirect(url_for('main.hangar'))

    game_state_obj = GameState.from_dict(session['game_state'])

    player_mech = game_state_obj.get_player_mech()
    ai_mech = game_state_obj.get_ai_mech()
    player_pilot = player_mech.pilot if player_mech else None
    ai_pilot = ai_mech.pilot if ai_mech else None

    if not player_mech:
        # [v_REFACTOR] 重定向到 'main.hangar'
        return redirect(url_for('main.hangar'))

    is_player_locked, locker_pos = get_player_lock_status(game_state_obj, player_mech)
    log = session.get('combat_log', [])

    # [v_REROLL_FIX] 修改事件处理逻辑
    # 1. 从 session 弹出旧的事件（如果有）
    visual_events = session.pop('visual_feedback_events', [])

    # [v_REROLL_FIX] 2. 从 game_state 扩展事件
    #    (这是现在的主要来源, 特别是对于 API 驱动的事件)
    state_modified = False
    if hasattr(game_state_obj, 'visual_events') and game_state_obj.visual_events:
        visual_events.extend(game_state_obj.visual_events)

        # [v_REROLL_FIX] 关键修复：
        # 仅当游戏*不*处于中断状态时，才清除 visual_events。
        # 如果有待处理的重投或效果，*必须*保留这些事件，以便页面刷新时能恢复。
        if player_mech and not player_mech.pending_effect_data and not player_mech.pending_reroll_data:
            game_state_obj.visual_events = []
            state_modified = True  # 标记已修改，以便保存

    # [v1.28] 检查是否需要自动运行抛射物阶段
    # [BUG 修复 v_NEXT] 不能 'pop'！如果页面因重投而重载，标志会丢失。
    # 必须 'get'，并让 '/run_projectile_phase' 路由自己来 'pop'。
    run_projectile_phase_flag = session.get('run_projectile_phase', False)

    # [FIX #8] 从 os.environ 读取配置并将其传递给模板
    firebase_config = os.environ.get('__firebase_config', '{}')
    app_id = os.environ.get('__app_id', 'default-app-id')
    auth_token = os.environ.get('__initial_auth_token', 'undefined')

    # [NEW] 提取玩家配置和AI名称以用于分析
    player_loadout = {}
    if player_mech and player_mech.parts:
        player_loadout = {slot: part.name for slot, part in player_mech.parts.items() if part}

    ai_opponent_name = "Unknown AI"  # 默认值
    if ai_mech and ai_mech.name:
        ai_opponent_name = ai_mech.name

    # [v1.23] 为 Jinja 模板定义 orientation_map
    orientation_map = {
        'N': '↑', 'S': '↓', 'E': '→', 'W': '←',
        'NONE': ''
    }

    # [AttributeError 修复]
    player_actions_used_tuples = player_mech.actions_used_this_turn if player_mech else []
    player_actions_used_lists = [list(t) for t in player_actions_used_tuples]

    # 3. 渲染模板。此时 `visual_events` 包含所有需要显示的事件
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
        visual_feedback_events=visual_events,  # [v_REROLL_FIX] 传递合并后的事件列表
        orientationMap=orientation_map,
        run_projectile_phase=run_projectile_phase_flag,
        # [FIX #8] 将配置传递给 Jinja
        firebase_config=firebase_config,
        app_id=app_id,
        initial_auth_token=auth_token,
        player_loadout=player_loadout,
        ai_opponent_name=ai_opponent_name
    )

    # --- [v1.26 修复] ---
    # 4. 渲染完成后，*现在*清除所有实体的 `last_pos`
    for entity in game_state_obj.entities.values():
        if entity.last_pos:
            entity.last_pos = None
            state_modified = True  # 标记状态已被修改

    # 5. [v_REROLL_FIX] 保存已清除 `last_pos` 和 (可能已清除的) `visual_events` 的状态回 session
    if state_modified:
        session['game_state'] = game_state_obj.to_dict()
    # --- 修复结束 ---

    # [v_fix] 创建一个 response 对象并添加“禁止缓存”的头信息
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
    session.pop('run_projectile_phase', None)  # [v1.28] 清除
    # [v_REFACTOR] 重定向到 'main.hangar'
    return redirect(url_for('main.hangar'))


@game_bp.route('/end_turn', methods=['POST'])
def end_turn():
    """
    [v_REROLL_FIX]
    AI 攻击现在会检查 'reroll_choice_required' 并正确中断回合。
    [v_PROJECTILE_FIX]
    修复了“齐射”中断bug。
    """
    game_state_obj = GameState.from_dict(session.get('game_state'))
    player_mech = game_state_obj.get_player_mech()

    if game_state_obj.game_over:
        return redirect(url_for('game.game'))

    log = session.get('combat_log', [])
    if player_mech and (player_mech.pending_effect_data or player_mech.pending_reroll_data):  # [v_REROLL] 增加检查
        log.append("> [错误] 必须先解决重投或效果才能结束回合！")  # [v_REROLL]
        if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
        session['combat_log'] = log
        return redirect(url_for('game.game'))

    # [v_REROLL_FIX] 在回合开始时清除视觉事件
    game_state_obj.visual_events = []

    log.append("-" * 20)
    log.append("> 玩家回合结束。")

    entities_to_process = list(game_state_obj.entities.values())
    game_ended_mid_turn = False

    # --- 阶段 1: AI 机甲阶段 ---
    log.append("--- AI 机甲阶段 ---")
    for entity in entities_to_process:
        # [v_PROJECTILE_FIX] 移除此处的 break。
        # if game_ended_mid_turn: break

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
                        # [v_PROJECTILE_FIX] 检查是否*已经*触发了中断
                        if game_ended_mid_turn:
                            log.append(
                                f"> [结算] 攻击 {attack.get('action').name if attack.get('action') else ''} 被暂停，等待玩家重投。")
                            continue

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

                        # [v_REROLL_FIX] AI 攻击玩家时，也使用 skip_reroll_phase=False
                        attack_log, result, overflow_data, dice_roll_details = resolve_attack(
                            attacker_entity=attacker_entity,
                            defender_entity=defender_entity,
                            action=attack_action,
                            target_part_name=target_part_slot,
                            is_back_attack=back_attack,
                            chosen_effect=None,
                            skip_reroll_phase=False  # [v_REROLL] 允许玩家在被AI攻击时重投
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

                        # [v_REROLL_FIX] 新增：捕获 AI 攻击玩家时的重投中断
                        if result == "reroll_choice_required":
                            player_mech = game_state_obj.get_player_mech()
                            player_mech.pending_reroll_data = overflow_data
                            result_data = {
                                'action_required': 'select_reroll',
                                'dice_details': dice_roll_details,
                                # [v_REROLL_FIX] 将名称信息添加到此
                                'attacker_name': attacker_entity.name,
                                'defender_name': defender_entity.name,
                                'action_name': attack_action.name
                            }
                            game_state_obj.add_visual_event('reroll_required', details=result_data)
                            game_ended_mid_turn = True  # 中断回合
                            break  # 停止结算攻击

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

        # [v_PROJECTILE_FIX] 在 entity 循环中检查中断
        if game_ended_mid_turn:
            break

    # --- [v1.28] 阶段 1 结束 ---
    # [v_REROLL_FIX] 仅在未被重投中断时才添加日志
    if not game_ended_mid_turn:
        log.append("--- AI 机甲阶段结束 ---")

    # [v_REROLL_FIX] 如果回合因重投而中断，则取消抛射物阶段
    # [BUG 修复 v_NEXT] 不！不能取消。客户端JS会处理这个。
    # 无论是否中断，都设置 'run_projectile_phase' = True。
    # 客户端JS会等待 reroll 解决后再触发。
    session['run_projectile_phase'] = True  # [BUG 修复] 总是设置此标志

    session['game_state'] = game_state_obj.to_dict()
    if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
    session['combat_log'] = log
    # [v_REROLL_FIX] 确保 visual_events 被保存到旧 key，以便 /game 路由可以 pop
    session['visual_feedback_events'] = game_state_obj.visual_events

    return redirect(url_for('game.game'))


@game_bp.route('/run_projectile_phase', methods=['POST'])
def run_projectile_phase():
    """
    [v_REROLL_FIX]
    抛射物攻击现在也会检查 'reroll_choice_required' 并正确中断回合。
    [v_PROJECTILE_FIX]
    修复了“齐射”中断bug。
    """
    game_state_obj = GameState.from_dict(session.get('game_state'))
    log = session.get('combat_log', [])

    # [BUG 修复 v_NEXT] 消耗 'run_projectile_phase' 标志，防止重复运行
    session.pop('run_projectile_phase', None)

    if game_state_obj.game_over:
        # [v_REFACTOR] 确保重定向到正确的蓝图
        return redirect(url_for('game.game'))

    # [v_REROLL_FIX] 在阶段开始时清除视觉事件
    game_state_obj.visual_events = []

    game_ended_mid_turn = False

    # --- 阶段 2: 延迟动作阶段 (抛射物) ---
    log.append("--- 延迟动作阶段 (抛射物) ---")

    # 重新获取实体列表, 因为 '立即' 动作可能生成了新的抛射物
    entities_to_process = list(game_state_obj.entities.values())

    for entity in entities_to_process:
        # [v_PROJECTILE_FIX] 移除此处的 break。
        # if game_ended_mid_turn: break

        # 运行所有抛射物 (无论属于谁)
        if entity.entity_type == 'projectile' and entity.status == 'ok':
            # [v_MODIFIED] 运行 '延迟' 逻辑
            entity_log, attacks = run_projectile_logic(entity, game_state_obj, '延迟')
            log.extend(entity_log)  # [v1.29 修复] 确保移动日志被记录

            # [v_MODIFIED] 立即结算此抛射物的攻击
            for attack in attacks:
                # [v_PROJECTILE_FIX] 检查是否*已经*触发了中断
                if game_ended_mid_turn:
                    log.append(
                        f"> [结算] 攻击 {attack.get('action').name if attack.get('action') else ''} 被暂停，等待玩家重投。")
                    continue

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

                # [v_REROLL_FIX] 抛射物攻击也检查重投
                attack_log, result, overflow_data, dice_roll_details = resolve_attack(
                    attacker_entity=attacker_entity,
                    defender_entity=defender_entity,
                    action=attack_action,
                    target_part_name=target_part_slot,
                    is_back_attack=back_attack,
                    chosen_effect=None,
                    skip_reroll_phase=False  # [v_REROLL] 允许玩家在被抛射物攻击时重投
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

                # [v_REROLL_FIX] 新增：捕获抛射物攻击玩家时的重投中断
                if result == "reroll_choice_required":
                    player_mech = game_state_obj.get_player_mech()
                    player_mech.pending_reroll_data = overflow_data
                    result_data = {
                        'action_required': 'select_reroll',
                        'dice_details': dice_roll_details,
                        'attacker_name': attacker_entity.name,
                        'defender_name': defender_entity.name,
                        'action_name': attack_action.name
                    }
                    game_state_obj.add_visual_event('reroll_required', details=result_data)
                    game_ended_mid_turn = True  # 中断回合
                    break  # 停止结算攻击

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

        # [v_PROJECTILE_FIX] 在 entity 循环中检查中断
        if game_ended_mid_turn:
            break

    # --- 阶段 3: 回合结束 ---
    # [v_REROLL_FIX] 仅在未被重投中断时才重置玩家
    if not game_state_obj.game_over and not game_ended_mid_turn:
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
            # [v_REROLL_FIX] 确保在这里也清除 reroll data
            player_mech.pending_reroll_data = None

        game_state_obj.check_game_over()

    session['game_state'] = game_state_obj.to_dict()
    if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
    session['combat_log'] = log
    # [v_REROLL_FIX] 确保 visual_events 被保存到旧 key
    session['visual_feedback_events'] = game_state_obj.visual_events
    return redirect(url_for('game.game'))


@game_bp.route('/respawn_ai', methods=['POST'])
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
    return redirect(url_for('game.game'))