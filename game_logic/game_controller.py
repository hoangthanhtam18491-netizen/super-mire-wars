import random
# 基础数据模型
from .data_models import Mech, Projectile, Action
# 核心战斗与掷骰逻辑
from .combat_system import resolve_attack, _resolve_effect_logic
from .dice_roller import roll_black_die, reroll_specific_dice
# 核心游戏规则
from .game_logic import is_back_attack, run_projectile_logic, check_interception, GameState, run_drone_logic
# AI 逻辑
from .ai_system import run_ai_turn


# [重构]
# 这个文件现在是修改游戏状态的 *唯一* 途径。
# 所有的路由 (api_routes, game_routes) 都必须调用这个文件中的函数来改变世界。
# 它不了解 Flask、session 或 request。它只接收 game_state 和数据，
# 然后返回 (updated_game_state, log_entries, result_data, error)。

# --- 辅助函数 ---

def _clear_transient_state(game_state):
    """
    (辅助函数) 清除所有用于单次动画的 'last_pos' 状态。
    """
    for entity in game_state.entities.values():
        entity.last_pos = None
    return game_state


def _execute_main_action(game_state, player_mech, action, action_name, part_slot):
    """
    (服务器端) 验证并“消耗”一个主动作 (AP/TP/弹药/使用次数)。
    这是执行移动或攻击前的第一步检查。
    """
    log = []
    action_id = (part_slot, action_name)

    # 检查是否已使用
    if action_id in player_mech.actions_used_this_turn:
        error = f"[{action_name}] (来自: {part_slot}) 本回合已使用过。"
        log.append(f"> [错误] {error}")
        return game_state, log, False, error

    # 检查弹药
    ammo_key = (player_mech.id, part_slot, action.name)
    if action.ammo > 0:
        current_ammo = game_state.ammo_counts.get(ammo_key, 0)
        if current_ammo <= 0:
            error = f"弹药耗尽，无法执行 [{action.name}]。"
            log.append(f"> [错误] {error}")
            return game_state, log, False, error

    # 检查 AP/TP 成本
    ap_cost = action.cost.count('M') * 2 + action.cost.count('S') * 1
    tp_cost = 0
    if action.cost == 'L':
        ap_cost = 2
        tp_cost = 1

    if player_mech.player_ap < ap_cost:
        error = f"AP不足 (需要 {ap_cost})，无法执行 [{action.name}]。"
        log.append(f"> [错误] {error}")
        return game_state, log, False, error

    if player_mech.player_tp < tp_cost:
        error = f"TP不足 (需要 {tp_cost})，无法执行 [{action.name}]。"
        log.append(f"> [错误] {error}")
        return game_state, log, False, error

    # 检查时机（起手动作）
    if not player_mech.opening_move_taken:
        if action.action_type != player_mech.timing and action.action_type != '快速':
            error = f"起手动作错误！当前时机为 [{player_mech.timing}]，无法执行 [{action.action_type}] 动作。"
            log.append(f"> [错误] {error}")
            return game_state, log, False, error
        player_mech.opening_move_taken = True

    # 消耗资源
    player_mech.player_ap -= ap_cost
    player_mech.player_tp -= tp_cost
    player_mech.actions_used_this_turn.append((part_slot, action_name))

    # 消耗弹药 (抛射和拦截动作在其他地方处理)
    if action.ammo > 0 and action.action_type != '抛射' and not action.effects.get("interceptor"):
        game_state.ammo_counts[ammo_key] -= 1
        log.append(f"> [{action.name}] 消耗 1 弹药，剩余 {game_state.ammo_counts[ammo_key]}。")

    return game_state, log, True, "Success"


# --- 阶段 1 & 2 控制器 (玩家回合) ---

def handle_select_timing(game_state, player_mech, timing):
    """(玩家) 阶段 1：选择时机"""
    log = []
    if player_mech.turn_phase == 'timing' and not game_state.game_over:
        player_mech.timing = timing
        game_state = _clear_transient_state(game_state)
        game_state.visual_events = []
        return game_state, log, None, None, None
    return game_state, log, None, None, "Not in timing phase"


def handle_confirm_timing(game_state, player_mech):
    """(玩家) 阶段 1：确认时机"""
    log = []
    if player_mech.turn_phase == 'timing' and player_mech.timing and not game_state.game_over:
        player_mech.turn_phase = 'stance'
        game_state = _clear_transient_state(game_state)
        game_state.visual_events = []
        log.append(f"> 时机已确认为 [{player_mech.timing}]。进入姿态选择阶段。")
        return game_state, log, None, None, None
    return game_state, log, None, None, "Please select a timing first."


def handle_change_stance(game_state, player_mech, new_stance):
    """(玩家) 阶段 2：选择姿态"""
    log = []
    if player_mech.turn_phase == 'stance' and not game_state.game_over:
        player_mech.stance = new_stance
        game_state = _clear_transient_state(game_state)
        game_state.visual_events = []
        return game_state, log, None, None, None
    return game_state, log, None, None, "Not in stance phase."


def handle_confirm_stance(game_state, player_mech):
    """(玩家) 阶段 2：确认姿态"""
    log = []
    if player_mech.turn_phase == 'stance' and not game_state.game_over:
        player_mech.turn_phase = 'adjustment'
        game_state = _clear_transient_state(game_state)
        game_state.visual_events = []
        log.append(f"> 姿态已确认为 [{player_mech.stance}]。进入调整阶段。")
        return game_state, log, None, None, None
    return game_state, log, None, None, "Not in stance phase."


# --- 阶段 3 控制器 (玩家回合) ---

def handle_adjust_move(game_state, player_mech, target_pos, final_orientation):
    """(玩家) 阶段 3：执行调整移动"""
    log = []
    if player_mech.turn_phase == 'adjustment' and player_mech.player_tp >= 1 and not game_state.game_over:
        player_mech.last_pos = player_mech.pos
        player_mech.pos = tuple(target_pos)
        player_mech.orientation = final_orientation
        player_mech.player_tp -= 1
        player_mech.turn_phase = 'main'
        game_state.visual_events = []
        log.append(f"> 玩家调整移动到 {player_mech.pos}。进入主动作阶段。")
        return game_state, log, None, None, None
    return game_state, log, None, None, "Cannot perform adjust move"


def handle_change_orientation(game_state, player_mech, final_orientation):
    """(玩家) 阶段 3：执行仅转向"""
    log = []
    if player_mech.turn_phase == 'adjustment' and player_mech.player_tp >= 1 and not game_state.game_over:
        player_mech.orientation = final_orientation
        player_mech.player_tp -= 1
        player_mech.turn_phase = 'main'
        game_state = _clear_transient_state(game_state)
        game_state.visual_events = []
        log.append(f"> 玩家仅转向。进入主动作阶段。")
        return game_state, log, None, None, None
    return game_state, log, None, None, "Cannot change orientation"


def handle_skip_adjustment(game_state, player_mech):
    """(玩家) 阶段 3：跳过调整"""
    log = []
    if player_mech.turn_phase == 'adjustment' and not game_state.game_over:
        player_mech.turn_phase = 'main'
        game_state = _clear_transient_state(game_state)
        game_state.visual_events = []
        log.append(f"> 玩家跳过调整阶段。进入主动作阶段。")
        return game_state, log, None, None, None
    return game_state, log, None, None, "Cannot skip adjustment"


# --- 阶段 4 控制器 (玩家回合) ---

def handle_move_player(game_state, player_mech, action_name, part_slot, target_pos, final_orientation):
    """(玩家) 阶段 4：执行[移动]动作"""
    log = []
    action = player_mech.get_action_by_name_and_slot(action_name, part_slot)

    game_state.visual_events = []

    if player_mech.turn_phase == 'main' and action:
        # 1. 验证并消耗 AP/TP/使用次数
        game_state, action_log, success, message = _execute_main_action(game_state, player_mech, action, action_name,
                                                                        part_slot)
        log.extend(action_log)
        if success:
            # 2. 执行移动
            player_mech.last_pos = player_mech.pos
            player_mech.pos = tuple(target_pos)
            player_mech.orientation = final_orientation
            log.append(f"> 玩家执行 [{action.name}]。")
            return game_state, log, None, None, None
        else:
            return game_state, log, None, None, message
    return game_state, log, None, None, "动作执行失败"


def handle_execute_attack(game_state, player_mech, data):
    """(玩家) 阶段 4：执行[近战]、[射击]或[抛射]动作"""
    log = []
    game_state.visual_events = []

    action_name = data.get('action_name')
    part_slot = data.get('part_slot')
    attack_action = player_mech.get_action_by_name_and_slot(action_name, part_slot)

    if not (player_mech.turn_phase == 'main' and attack_action):
        return game_state, log, None, None, '动作未在 main 阶段执行或动作未找到。'

    target_entity_id = data.get('target_entity_id')
    defender_entity = None
    if target_entity_id:
        defender_entity = game_state.get_entity_by_id(target_entity_id)
        if not defender_entity:
            error = f"找不到目标实体 ID: {target_entity_id}。"
            log.append(f"> [错误] {error}")
            return game_state, log, None, None, error

    # 验证射程
    valid_targets_list, valid_launch_cells_list = game_state.calculate_attack_range(
        player_mech, attack_action
    )

    # 1. '抛射' 动作
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
                target_pos = defender_entity.pos

        if not target_is_valid or not target_pos:
            error = f"目标位置 {target_pos} 不在有效发射范围内。"
            log.append(f"> [错误] {error}")
            return game_state, log, None, None, error

        # 消耗 AP/TP
        game_state, action_log, success, message = _execute_main_action(game_state, player_mech, attack_action,
                                                                        action_name, part_slot)
        log.extend(action_log)
        if not success:
            return game_state, log, None, None, message

        # 处理齐射和弹药
        attacks_to_resolve_list = []
        salvo_count = attack_action.effects.get("salvo", 1)
        ammo_key = (player_mech.id, part_slot, attack_action.name)
        current_ammo = game_state.ammo_counts.get(ammo_key, 0)
        projectiles_to_launch = min(salvo_count, current_ammo)

        if projectiles_to_launch <= 0:
            error = "弹药耗尽"
            log.append(f"> [错误] {error}，无法执行 [{attack_action.name}]。")
            return game_state, log, None, None, error

        # 消耗弹药
        game_state.ammo_counts[ammo_key] -= projectiles_to_launch
        log.append(f"> 玩家发射 [{attack_action.name}] 到 {target_pos}！")
        if projectiles_to_launch > 1:
            log.append(f"> 【齐射{projectiles_to_launch}】触发！发射 {projectiles_to_launch} 枚抛射物。")
        log.append(f"> 消耗 {projectiles_to_launch} 弹药, 剩余 {game_state.ammo_counts[ammo_key]}。")

        reroll_triggered = False
        first_reroll_result_data = None

        # 生成并结算每一个抛射物
        for _ in range(projectiles_to_launch):
            if reroll_triggered:
                log.append(f"> [结算] 攻击被暂停，等待玩家重投。")
                continue

            projectile_id, projectile_obj = game_state.spawn_projectile(
                launcher_entity=player_mech,
                target_pos=target_pos,
                projectile_key=attack_action.projectile_to_spawn
            )
            if not projectile_obj:
                log.append(f"> [错误] 生成抛射物 {attack_action.projectile_to_spawn} 失败！")
                continue

            has_immediate_action = projectile_obj.get_action_by_timing('立即')[0] is not None
            if not has_immediate_action:
                check_interception(projectile_obj, game_state, log)

            entity_log, attacks = run_projectile_logic(projectile_obj, game_state, '立即')
            log.extend(entity_log)
            attacks_to_resolve_list.extend(attacks)

        # 结算所有 '立即' 攻击
        for attack in attacks_to_resolve_list:
            if reroll_triggered:
                log.append(
                    f"> [结算] 攻击 {attack.get('action').name if attack.get('action') else ''} 被暂停，等待玩家重投。")
                continue

            if not isinstance(attack, dict): continue
            attacker = attack.get('attacker')
            defender = attack.get('defender')
            action = attack.get('action')
            if not attacker or not defender or not action: continue

            if attacker.status == 'destroyed':
                log.append(f"> [结算] 攻击者 {attacker.name} 已被摧毁，攻击取消！")
                continue
            if defender.status == 'destroyed':
                log.append(f"> [结算] 目标 {defender.name} 已被摧毁，攻击跳过。")
                continue

            log.append(f"--- [立即引爆] 结算 ({attacker.name} -> {action.name}) ---")

            target_part_slot = 'core'
            if isinstance(defender, Mech):
                hit_roll_result = roll_black_die()
                log.append(f"> 投掷部位骰结果: 【{hit_roll_result}】")
                if hit_roll_result == 'any':
                    valid_parts = [s for s, p in defender.parts.items() if p and p.status != 'destroyed']
                    target_part_slot = random.choice(valid_parts) if valid_parts else 'core'
                    log.append(f"> 抛射物随机命中: [{target_part_slot}]。")
                elif defender.parts.get(hit_roll_result) and defender.parts[hit_roll_result].status != 'destroyed':
                    target_part_slot = hit_roll_result
                else:
                    log.append(f"> 部位 [{hit_roll_result}] 不存在或已摧毁，转而命中 [核心]。")
            else:
                log.append(f"> 攻击自动瞄准 [{defender.name}] 的核心。")

            attack_log, result, overflow_data, dice_roll_details = resolve_attack(
                attacker_entity=attacker, defender_entity=defender, action=action,
                target_part_name=target_part_slot, is_back_attack=False, chosen_effect=None,
                skip_reroll_phase=False
            )
            log.extend(attack_log)
            if dice_roll_details:
                game_state.add_visual_event(
                    'dice_roll', attacker_name=attacker.name, defender_name=defender.name,
                    action_name=action.name, details=dice_roll_details
                )
            game_state.add_visual_event('attack_result', defender_pos=defender.pos, result_text=result)

            if result == "reroll_choice_required":
                reroll_triggered = True
                player_mech.pending_reroll_data = overflow_data
                first_reroll_result_data = {
                    'action_required': 'select_reroll',
                    'dice_details': dice_roll_details,
                    'attacker_name': attacker.name,
                    'defender_name': defender.name,
                    'action_name': action.name
                }
                game_state.add_visual_event('reroll_required', details=first_reroll_result_data)

        if reroll_triggered:
            return game_state, log, None, first_reroll_result_data, None

        return game_state, log, None, None, None

    # 2. '射击' 或 '近战' 或 '快速' 动作
    elif attack_action.action_type in ['射击', '近战', '快速']:
        if not defender_entity:
            error = "射击/近战动作需要一个实体目标。"
            log.append(f"> [错误] {error}")
            return game_state, log, None, None, error

        target_data = next((t for t in valid_targets_list if t['entity'].id == defender_entity.id), None)
        if not target_data:
            error = f"目标 {defender_entity.name} 不在有效攻击范围内。"
            log.append(f"> [错误] {error}")
            return game_state, log, None, None, error

        from .game_logic import get_player_lock_status
        is_player_locked, _ = get_player_lock_status(game_state, player_mech)
        if is_player_locked and attack_action.action_type == '射击':
            error = f"你被近战锁定，无法执行 [{attack_action.name}]！"
            log.append(f"> [错误] {error}")
            return game_state, log, None, None, error

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

        defender_is_downed = (defender_entity.stance == 'downed')

        if not target_part_slot:
            if back_attack or two_handed_sniper_active or defender_is_downed:
                log_msg = ""
                if back_attack:
                    log_msg = "> [背击] 玩家获得任意选择权！请选择目标部位。"
                elif two_handed_sniper_active:
                    log_msg = "> [狙击效果] 玩家获得任意选择权！请选择目标部位。"
                elif defender_is_downed:
                    log_msg = "> [目标宕机] 玩家获得任意选择权！请选择目标部位。"
                log.append(log_msg)
                return game_state, log, None, {'action_required': 'select_part'}, None

            if isinstance(defender_entity, Mech):
                if attack_action.action_type == '近战' and defender_entity.stance != 'downed':
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
                    return game_state, log, None, {'action_required': 'select_part'}, None

                if isinstance(defender_entity, Mech) and defender_entity.parts.get(hit_roll_result) and \
                        defender_entity.parts[hit_roll_result].status != 'destroyed':
                    target_part_slot = hit_roll_result
                else:
                    target_part_slot = 'core'
                    if isinstance(defender_entity, Mech):
                        log.append(f"> 部位 [{hit_roll_result}] 不存在或已摧毁，转而命中 [核心]。")
                    else:
                        log.append(f"> 目标为非机甲单位，自动命中 [核心]。")

        # --- [BUG 修复] 移除错误的抛射物逻辑 ---
        # 1. 消耗 AP/TP
        game_state, action_log, success, message = _execute_main_action(game_state, player_mech, attack_action,
                                                                        action_name, part_slot)
        log.extend(action_log)
        if not success:
            return game_state, log, None, None, message

        if not target_part_slot:
            error = "未能确定目标部件！攻击中止。"
            log.append(f"> [严重错误] {error}")
            return game_state, log, None, None, error

        # 2. 结算攻击
        attack_log, result, overflow_data, dice_roll_details = resolve_attack(
            attacker_entity=player_mech, defender_entity=defender_entity, action=attack_action,
            target_part_name=target_part_slot, is_back_attack=back_attack, chosen_effect=None,
            skip_reroll_phase=False
        )
        log.extend(attack_log)

        # 3. 添加视觉事件
        if dice_roll_details:
            game_state.add_visual_event(
                'dice_roll', attacker_name=player_mech.name, defender_name=defender_entity.name,
                action_name=attack_action.name, details=dice_roll_details
            )
        game_state.add_visual_event('attack_result', defender_pos=defender_entity.pos, result_text=result)

        # 4. 处理中断：重投
        if result == "reroll_choice_required":
            player_mech.pending_reroll_data = overflow_data
            result_data = {
                'action_required': 'select_reroll',
                'dice_details': dice_roll_details,
                'attacker_name': player_mech.name,
                'defender_name': defender_entity.name,
                'action_name': attack_action.name
            }
            game_state.add_visual_event('reroll_required', details=result_data)
            return game_state, log, None, result_data, None

        # 5. 处理中断：效果选择
        if result == "effect_choice_required":
            player_mech.pending_effect_data = {
                'action_dict': attack_action.to_dict(),
                'overflow_data': {'hits': overflow_data['hits'], 'crits': overflow_data['crits']},
                'options': overflow_data['options'],
                'target_entity_id': defender_entity.id,
                'target_part_name': target_part_slot,
                'is_back_attack': back_attack,
                'choice': None
            }
            result_data = {'action_required': 'select_effect', 'options': overflow_data['options']}
            return game_state, log, None, result_data, None

        player_mech.pending_effect_data = None

        # 6. 检查游戏是否结束
        ai_was_defeated = (defender_entity.controller == 'ai' and
                           (defender_entity.status == 'destroyed' or
                            (isinstance(defender_entity, Mech) and defender_entity.parts.get('core') and (
                                    defender_entity.parts[
                                        'core'].status == 'destroyed' or defender_entity.get_active_parts_count() < 3))))
        game_is_over = game_state.check_game_over()

        ai_mech = game_state.get_ai_mech()
        if game_state.game_mode == 'horde' and ai_was_defeated and not game_is_over and ai_mech:
            log.append(f"> [生存模式] 击败了 {game_state.ai_defeat_count} 台敌机！")
            log.append(f"> [警告] 新的敌人出现: {ai_mech.name}！")

        return game_state, log, None, None, None

    # --- [BUG 修复] 结束 ---

    return game_state, log, None, None, "无效的动作类型"


def handle_jettison_part(game_state, player_mech, part_slot):
    """(玩家) 阶段 4：执行[弃置]动作"""
    from parts_database import ALL_PARTS
    from .data_models import Part

    log = []
    game_state.visual_events = []

    part = player_mech.parts.get(part_slot)
    if not part:
        return game_state, log, None, None, "未找到部件"

    action_obj = None
    for act in part.actions:
        if act.name == "【弃置】":
            action_obj = act
            break

    if not action_obj:
        return game_state, log, None, None, "该部件没有【弃置】动作"

    # 消耗 AP
    game_state, action_log, success, message = _execute_main_action(
        game_state, player_mech, action_obj, "【弃置】", part_slot
    )
    log.extend(action_log)
    if not success:
        return game_state, log, None, None, message

    # 执行弃置
    current_part_name = part.name
    current_status = part.status
    discarded_part_name = f"{current_part_name}（弃置）"

    if discarded_part_name not in ALL_PARTS:
        log.append(f"> [错误] 数据库中未找到对应的（弃置）部件: {discarded_part_name}")
        return game_state, log, None, None, "未找到（弃置）部件"

    # 创建并替换部件
    new_part_data = ALL_PARTS[discarded_part_name]
    new_part = Part.from_dict(new_part_data.to_dict())

    # 继承状态
    new_part.status = current_status
    if current_status == 'damaged':
        log.append(f"> 部件状态 [破损] 已继承。")

    player_mech.parts[part_slot] = new_part
    log.append(f"> 玩家弃置了 [{current_part_name}]，更换为 [{new_part.name}]。")

    game_state = _clear_transient_state(game_state)
    return game_state, log, None, None, None


# --- 中断处理控制器 ---

def handle_resolve_effect_choice(game_state, player_mech, choice):
    """(玩家) 中断：处理溢出效果选择 (毁伤/霰射/顺劈)"""
    log = []
    game_state.visual_events = []

    pending_data = player_mech.pending_effect_data
    if not pending_data:
        error = "找不到待处理的效果数据！"
        log.append(f"> [错误] {error}")
        return game_state, log, None, None, error

    if choice not in pending_data.get('options', []):
        error = f"无效的选择: {choice}"
        log.append(f"> [错误] {error}")
        return game_state, log, None, None, error

    target_entity_id = pending_data['target_entity_id']
    target_entity = game_state.get_entity_by_id(target_entity_id)
    if not target_entity or target_entity.status == 'destroyed':
        error = f"在解析效果时找不到目标实体: {target_entity_id}"
        log.append(f"> [错误] {error}")
        return game_state, log, None, None, error

    if not isinstance(target_entity, Mech):
        error = f"效果只能对机甲触发: {target_entity_id}"
        log.append(f"> [错误] {error}")
        return game_state, log, None, None, error

    target_part_name = pending_data['target_part_name']
    target_part = target_entity.get_part_by_name(target_part_name)
    if not target_part:
        error = f"在解析效果时找不到目标部件: {target_part_name}"
        log.append(f"> [错误] {error}")
        return game_state, log, None, None, error

    overflow_hits = pending_data['overflow_data']['hits']
    overflow_crits = pending_data['overflow_data']['crits']

    log.append(
        f"> 玩家选择了【{'毁伤' if choice == 'devastating' else ('霰射' if choice == 'scattershot' else '顺劈')}】！")

    # 调用效果结算逻辑
    log_ext_list, secondary_roll_details, overflow_data = _resolve_effect_logic(
        log=log, attacker_entity=player_mech, defender_entity=target_entity, target_part=target_part,
        overflow_hits=overflow_hits, overflow_crits=overflow_crits, chosen_effect=choice
    )

    if secondary_roll_details:
        game_state.add_visual_event(
            'dice_roll', attacker_name=player_mech.name, defender_name=target_entity.name,
            action_name=choice.capitalize(), details=secondary_roll_details
        )
    game_state.add_visual_event('attack_result', defender_pos=target_entity.pos, result_text='击穿')

    # 清除中断状态
    player_mech.pending_effect_data = None

    # 检查游戏是否结束
    ai_was_defeated = (target_entity.controller == 'ai' and
                       (target_entity.status == 'destroyed' or
                        (isinstance(target_entity, Mech) and target_entity.parts.get('core') and (target_entity.parts[
                                                                                                      'core'].status == 'destroyed' or target_entity.get_active_parts_count() < 3))))
    game_is_over = game_state.check_game_over()

    ai_mech = game_state.get_ai_mech()
    if game_state.game_mode == 'horde' and ai_was_defeated and not game_is_over and ai_mech:
        log.append(f"> [生存模式] 击败了 {game_state.ai_defeat_count} 台敌机！")
        log.append(f"> [警告] 新的敌人出现: {ai_mech.name}！")

    return game_state, log, None, None, None


def handle_resolve_reroll(game_state, player_mech, data):
    """(玩家) 中断：处理专注重投"""
    log = []
    game_state.visual_events = []

    pending_data = None
    if player_mech.pending_reroll_data:
        pending_data = player_mech.pending_reroll_data
    else:
        ai_mech = game_state.get_ai_mech()
        if ai_mech and ai_mech.pending_reroll_data:
            pending_data = ai_mech.pending_reroll_data

    if not pending_data:
        return game_state, log, None, None, "找不到待处理的重投数据！"

    # 1. 恢复上下文
    attacker = game_state.get_entity_by_id(pending_data['attacker_id'])
    defender = game_state.get_entity_by_id(pending_data['defender_id'])

    action = None
    action_name_for_log = "Attack"
    if pending_data['type'] == 'attack_reroll':
        action = Action.from_dict(pending_data['action_dict'])
        action_name_for_log = action.name
    elif pending_data['type'] == 'effect_reroll':
        action_name_for_log = pending_data['chosen_effect'].capitalize()

    if not attacker or not defender:
        return game_state, log, None, None, "重投时找不到攻击者或防御者。"

    # 2. 准备骰子
    new_attack_rolls = pending_data['attack_raw_rolls']
    new_defense_rolls = pending_data['defense_raw_rolls']

    # 3. 获取玩家的重投选择
    reroll_selections_attacker = data.get('reroll_selections_attacker', [])
    reroll_selections_defender = data.get('reroll_selections_defender', [])
    is_skipping = not reroll_selections_attacker and not reroll_selections_defender

    player_did_reroll = False
    link_cost_applied = False

    # 4. 执行玩家的重投
    if pending_data['player_is_attacker'] and reroll_selections_attacker:
        if player_mech.pilot and player_mech.pilot.link_points > 0:
            log.append(f"  > 玩家 (攻击方) 消耗 1 链接值重投 {len(reroll_selections_attacker)} 枚骰子！")
            player_mech.pilot.link_points -= 1
            player_did_reroll = True
            link_cost_applied = True
            new_attack_rolls = reroll_specific_dice(new_attack_rolls, reroll_selections_attacker)
        else:
            log.append("  > [警告] 玩家试图重投攻击骰，但链接值不足！")

    if pending_data['player_is_defender'] and reroll_selections_defender:
        if player_mech.pilot and player_mech.pilot.link_points > 0:
            log.append(f"  > 玩家 (防御方) 消耗 1 链接值重投 {len(reroll_selections_defender)} 枚骰子！")
            if not link_cost_applied:
                player_mech.pilot.link_points -= 1
            player_did_reroll = True
            new_defense_rolls = reroll_specific_dice(new_defense_rolls, reroll_selections_defender)
        else:
            log.append("  > [警告] 玩家试图重投防御骰，但链接值不足！")

    if not player_did_reroll and not is_skipping:
        log.append("  > 玩家选择不重投。")
    elif is_skipping:
        log.append("  > 玩家跳过重投。")

    # 5. 清除中断状态
    if pending_data['player_is_attacker']:
        if isinstance(attacker, Mech):
            attacker.pending_reroll_data = None
    if pending_data['player_is_defender']:
        if isinstance(defender, Mech):
            defender.pending_reroll_data = None

    # 6. 恢复战斗 (跳过重投阶段)
    result_data = None
    dice_roll_details = None
    result = "无效"

    if pending_data['type'] == 'attack_reroll':
        attack_log, result, overflow_data, dice_roll_details = resolve_attack(
            attacker_entity=attacker,
            defender_entity=defender,
            action=action,
            target_part_name=pending_data['target_part_name'],
            is_back_attack=pending_data['is_back_attack'],
            chosen_effect=None,
            skip_reroll_phase=True,
            rerolled_attack_raw=new_attack_rolls,
            rerolled_defense_raw=new_defense_rolls
        )
        log.extend(attack_log)

        # 检查是否需要 *另一次* 中断 (效果选择)
        if result == "effect_choice_required":
            if isinstance(attacker, Mech):
                attacker.pending_effect_data = overflow_data
            result_data = {
                'action_required': 'select_effect',
                'options': overflow_data['options'],
            }
            game_state.add_visual_event('effect_choice_required', details=result_data)

    elif pending_data['type'] == 'effect_reroll':
        target_part = defender.get_part_by_name(pending_data['target_part_name'])
        if not target_part:
            log.append(f"> [错误] 重投效果时找不到部件 {pending_data['target_part_name']}。")
            return game_state, log, None, None, "重投效果时找不到部件"

        attack_log_ext, secondary_roll_details, overflow_data_ext = _resolve_effect_logic(
            log=log,
            attacker_entity=attacker,
            defender_entity=defender,
            target_part=target_part,
            overflow_hits=pending_data['overflow_hits'],
            overflow_crits=pending_data['overflow_crits'],
            chosen_effect=pending_data['chosen_effect'],
            skip_reroll_phase=True,
            rerolled_defense_raw=new_defense_rolls
        )
        dice_roll_details = secondary_roll_details
        result = "击穿"

    # 7. 添加最终的视觉事件
    if dice_roll_details:
        game_state.add_visual_event(
            'dice_roll',
            attacker_name=attacker.name,
            defender_name=defender.name,
            action_name=action_name_for_log,
            details=dice_roll_details
        )
    game_state.add_visual_event('attack_result', defender_pos=defender.pos, result_text=result)

    if result_data:
        # 如果触发了效果选择，将 dice_roll_details 添加到 result_data 中
        result_data.update({
            'dice_details': dice_roll_details,
            'attacker_name': attacker.name,
            'defender_name': defender.name,
            'action_name': action_name_for_log
        })
        return game_state, log, None, result_data, None

    # 8. [MODIFIED] 检查是否有待处理的 AI 攻击队列
    queued_attacks = pending_data.get('remaining_attacks')
    game_ended_mid_turn = False  # 重置标志，用于队列处理

    if queued_attacks and not result_data:  # 仅当没有触发效果选择时才继续
        log.append(f"> [系统] 玩家重投已解决。正在恢复 AI 的攻击队列... ({len(queued_attacks)} 个动作)")

        # [MODIFIED] 这是一个简化的攻击循环，来自 handle_end_turn
        # 它必须能够处理 *另一次* 重投中断
        for i, attack_data in enumerate(queued_attacks):  # Renamed 'attack' to 'attack_data'
            if game_ended_mid_turn:
                log.append(
                    f"> [结算] 攻击 {attack_data.get('action_dict', {}).get('name', '未知')} 被暂停，等待玩家重投。")
                continue

            if not isinstance(attack_data, dict): continue

            # [MODIFIED] Re-fetch entities and action from serialized data
            attacker_entity = game_state.get_entity_by_id(attack_data.get('attacker_id'))
            defender_entity = game_state.get_entity_by_id(attack_data.get('defender_id'))
            attack_action_dict = attack_data.get('action_dict')

            if not attacker_entity or not defender_entity or not attack_action_dict:
                log.append(f"> [严重错误] AI 队列攻击数据不完整: {attack_data}")
                continue

            attack_action = Action.from_dict(attack_action_dict)

            if attacker_entity.status == 'destroyed':
                log.append(f"> [结算] 攻击者 {attacker_entity.name} 已被摧毁，攻击取消！")
                continue

            if defender_entity.status == 'destroyed':
                log.append(f"> [AI] {attacker_entity.name} 的目标 {defender_entity.name} 已被摧毁。")
                continue

            log.append(f"--- 攻击结算 ({attacker_entity.name} -> {attack_action.name}) ---")

            # AI 攻击的部位判定 (Copied from handle_end_turn)
            back_attack = False
            if isinstance(defender_entity, Mech):
                if isinstance(attacker_entity, Mech):
                    back_attack = is_back_attack(attacker_entity.pos, defender_entity.pos,
                                                 defender_entity.orientation)
                elif isinstance(defender_entity, Projectile):
                    back_attack = False

            target_part_slot = None
            if isinstance(defender_entity, Mech):
                if attack_action.action_type == '近战' and not back_attack and defender_entity.stance != 'downed':
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
                target_part_slot = 'core'
                log.append(f"> 攻击自动瞄准 [{defender_entity.name}] 的核心。")

            # 结算攻击
            attack_log, result, overflow_data, dice_roll_details = resolve_attack(
                attacker_entity=attacker_entity,
                defender_entity=defender_entity,
                action=attack_action,
                target_part_name=target_part_slot,
                is_back_attack=back_attack,
                chosen_effect=None,
                skip_reroll_phase=False  # 允许玩家被AI攻击时重投
            )
            log.extend(attack_log)

            if dice_roll_details:
                game_state.add_visual_event(
                    'dice_roll',
                    attacker_name=attacker_entity.name,
                    defender_name=defender_entity.name,
                    action_name=attack_action.name,
                    details=dice_roll_details
                )

            game_state.add_visual_event(
                'attack_result',
                defender_pos=defender_entity.pos,
                result_text=result
            )

            # 处理中断：重投
            if result == "reroll_choice_required":
                if isinstance(defender_entity, Mech):  # 玩家机甲
                    # [MODIFIED] Store remaining attacks inside the reroll data
                    overflow_data['remaining_attacks'] = queued_attacks[
                        i + 1:]  # Store remaining *serializable* attacks
                    defender_entity.pending_reroll_data = overflow_data
                    log.append(
                        f"> [系统] AI 攻击队列已暂停，剩余 {len(overflow_data['remaining_attacks'])} 个动作待处理。")

                result_data = {
                    'action_required': 'select_reroll',
                    'dice_details': dice_roll_details,
                    'attacker_name': attacker_entity.name,
                    'defender_name': defender_entity.name,
                    'action_name': attack_action.name
                }
                game_state.add_visual_event('reroll_required', details=result_data)
                game_ended_mid_turn = True
                break  # Stop processing the *queued* attacks

            game_is_over = game_state.check_game_over()
            if game_is_over and game_state.game_over == 'ai_win':
                log.append(f"> 玩家机甲已被摧毁！")
                if game_state.game_mode == 'horde':
                    log.append(f"> [生存模式] 最终击败数: {game_state.ai_defeat_count}")
                game_ended_mid_turn = True
                break  # Stop processing the *queued* attacks

        if game_ended_mid_turn:
            # A reroll was triggered *inside* the reroll handler.
            # We must return the new result_data.
            return game_state, log, None, result_data, None

    # 9. 检查游戏是否结束 (original step 8)
    game_is_over = game_state.check_game_over()

    return game_state, log, None, result_data, None


# --- [新] 回合结束控制器 (从 game_routes.py 迁移) ---

def handle_end_turn(game_state):
    """
    (系统) 结束玩家回合，开始 AI 回合，并结算所有 AI 攻击。
    返回: (game_state, log, result_data, error)
    result_data 可能会包含 {'run_projectile_phase': True} 或中断数据。
    """
    log = []
    player_mech = game_state.get_player_mech()

    if game_state.game_over:
        return game_state, log, None, None, "Game Over"

    if player_mech and (player_mech.pending_effect_data or player_mech.pending_reroll_data):
        error = "> [错误] 必须先解决重投或效果才能结束回合！"
        log.append(error)
        return game_state, log, None, None, error

    game_state.visual_events = []
    log.append("-" * 20)
    log.append("> 玩家回合结束。")

    entities_to_process = list(game_state.entities.values())
    game_ended_mid_turn = False
    result_data = {}

    # --- 阶段 1: AI 机甲阶段 ---
    log.append("--- AI 机甲阶段 ---")
    for entity in entities_to_process:
        if game_ended_mid_turn:
            break

        if entity.controller == 'ai' and entity.status == 'ok':

            # 1. AI 机甲逻辑
            if entity.entity_type == 'mech':
                if game_state.game_mode == 'range':
                    log.append("> [靶场模式] AI 跳过回合。")
                    entity.last_pos = None
                else:
                    entity.last_pos = entity.pos
                    entity_log, attacks = run_ai_turn(entity, game_state)
                    log.extend(entity_log)

                    # 结算此 AI 机甲的攻击
                    for i, attack in enumerate(attacks):  # [MODIFIED] Add enumerate
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

                        if attacker_entity.status == 'destroyed':
                            log.append(f"> [结算] 攻击者 {attacker_entity.name} 已被摧毁，攻击取消！")
                            continue

                        if defender_entity.status == 'destroyed':
                            log.append(f"> [AI] {attacker_entity.name} 的目标 {defender_entity.name} 已被摧毁。")
                            continue

                        log.append(f"--- 攻击结算 ({attacker_entity.name} -> {attack_action.name}) ---")

                        # AI 攻击的部位判定
                        back_attack = False
                        if isinstance(defender_entity, Mech):
                            if isinstance(attacker_entity, Mech):
                                back_attack = is_back_attack(attacker_entity.pos, defender_entity.pos,
                                                             defender_entity.orientation)
                            elif isinstance(defender_entity, Projectile):
                                back_attack = False

                        target_part_slot = None
                        if isinstance(defender_entity, Mech):
                            # AI 自动招架
                            if attack_action.action_type == '近战' and not back_attack and defender_entity.stance != 'downed':
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
                            target_part_slot = 'core'
                            log.append(f"> 攻击自动瞄准 [{defender_entity.name}] 的核心。")

                        # 结算攻击
                        attack_log, result, overflow_data, dice_roll_details = resolve_attack(
                            attacker_entity=attacker_entity,
                            defender_entity=defender_entity,
                            action=attack_action,
                            target_part_name=target_part_slot,
                            is_back_attack=back_attack,
                            chosen_effect=None,
                            skip_reroll_phase=False  # 允许玩家被AI攻击时重投
                        )
                        log.extend(attack_log)

                        if dice_roll_details:
                            game_state.add_visual_event(
                                'dice_roll',
                                attacker_name=attacker_entity.name,
                                defender_name=defender_entity.name,
                                action_name=attack_action.name,
                                details=dice_roll_details
                            )

                        game_state.add_visual_event(
                            'attack_result',
                            defender_pos=defender_entity.pos,
                            result_text=result
                        )

                        # 处理中断：重投
                        if result == "reroll_choice_required":
                            if isinstance(defender_entity, Mech):  # 玩家机甲
                                # [MODIFIED] Store remaining attacks inside the reroll data

                                # [NEW - FIX] Serialize the remaining attacks to prevent recursion
                                remaining_attacks_serializable = []
                                for atk in attacks[i + 1:]:
                                    remaining_attacks_serializable.append({
                                        'attacker_id': atk['attacker'].id,
                                        'defender_id': atk['defender'].id,
                                        'action_dict': atk['action'].to_dict()
                                    })

                                overflow_data[
                                    'remaining_attacks'] = remaining_attacks_serializable  # Store serializable list
                                defender_entity.pending_reroll_data = overflow_data
                                log.append(
                                    f"> [系统] AI 攻击队列已暂停，剩余 {len(overflow_data['remaining_attacks'])} 个动作待处理。")

                            result_data = {
                                'action_required': 'select_reroll',
                                'dice_details': dice_roll_details,
                                'attacker_name': attacker_entity.name,
                                'defender_name': defender_entity.name,
                                'action_name': attack_action.name
                            }
                            game_state.add_visual_event('reroll_required', details=result_data)
                            game_ended_mid_turn = True
                            break  # [MODIFIED] Re-add the break, it's correct now

                        game_is_over = game_state.check_game_over()
                        if game_is_over and game_state.game_over == 'ai_win':
                            log.append(f"> 玩家机甲已被摧毁！")
                            if game_state.game_mode == 'horde':
                                log.append(f"> [生存模式] 最终击败数: {game_state.ai_defeat_count}")
                            game_ended_mid_turn = True
                            break

            # 2. AI 无人机逻辑
            elif entity.entity_type == 'drone':
                entity_log, attacks = run_drone_logic(entity, game_state)
                log.extend(entity_log)
                # (如果无人机有攻击，也应在此处结算)

    # [FIX]
    # 无论回合是否被中断 (game_ended_mid_turn)，
    # 我们 *总是* 应该设置 'run_projectile_phase' 标志。
    if not game_ended_mid_turn:
        log.append("--- AI 机甲阶段结束 ---")

    result_data['run_projectile_phase'] = True

    return game_state, log, result_data, None


def handle_run_projectile_phase(game_state):
    """
    (系统) 运行所有抛射物的'延迟'逻辑并结算攻击。
    返回: (game_state, log, result_data, error)
    """
    log = []
    if game_state.game_over:
        return game_state, log, None, None, "Game Over"

    game_state.visual_events = []
    game_ended_mid_turn = False
    result_data = {}

    log.append("--- 延迟动作阶段 (抛射物) ---")
    entities_to_process = list(game_state.entities.values())

    for entity in entities_to_process:
        if game_ended_mid_turn:
            break

        if entity.entity_type == 'projectile' and entity.status == 'ok':
            entity_log, attacks = run_projectile_logic(entity, game_state, '延迟')
            log.extend(entity_log)

            # 结算此抛射物的攻击
            for i, attack in enumerate(attacks):  # [MODIFIED] Add enumerate
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

                if attacker_entity.status == 'destroyed':
                    log.append(f"> [结算] 攻击者 {attacker_entity.name} 已被摧毁，攻击取消！")
                    continue
                if defender_entity.status == 'destroyed':
                    log.append(f"> [结算] {attacker_entity.name} 的目标 {defender_entity.name} 已被摧毁。")
                    continue

                log.append(f"--- 攻击结算 ({attacker_entity.name} -> {attack_action.name}) ---")

                # 部位判定
                back_attack = False
                if isinstance(defender_entity, Mech):
                    if isinstance(attacker_entity, Mech):
                        back_attack = is_back_attack(attacker_entity.pos, defender_entity.pos,
                                                     defender_entity.orientation)
                    elif isinstance(defender_entity, Projectile):
                        back_attack = False

                target_part_slot = None
                if isinstance(defender_entity, Mech):
                    hit_roll_result = roll_black_die()
                    log.append(f"> 投掷部位骰结果: 【{hit_roll_result}】")
                    if hit_roll_result == 'any' or back_attack:
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
                    target_part_slot = 'core'
                    log.append(f"> 攻击自动瞄准 [{defender_entity.name}] 的核心。")

                # 结算攻击
                attack_log, result, overflow_data, dice_roll_details = resolve_attack(
                    attacker_entity=attacker_entity,
                    defender_entity=defender_entity,
                    action=attack_action,
                    target_part_name=target_part_slot,
                    is_back_attack=back_attack,
                    chosen_effect=None,
                    skip_reroll_phase=False  # 允许玩家被抛射物攻击时重投
                )
                log.extend(attack_log)

                if dice_roll_details:
                    game_state.add_visual_event(
                        'dice_roll',
                        attacker_name=attacker_entity.name,
                        defender_name=defender_entity.name,
                        action_name=attack_action.name,
                        details=dice_roll_details
                    )
                game_state.add_visual_event(
                    'attack_result',
                    defender_pos=defender_entity.pos,
                    result_text=result
                )

                # 处理中断：重投
                if result == "reroll_choice_required":
                    player_mech = game_state.get_player_mech()
                    if player_mech:
                        # [MODIFIED] Store remaining attacks inside the reroll data

                        # [NEW - FIX] Serialize the remaining attacks
                        remaining_attacks_serializable = []
                        for atk in attacks[i + 1:]:
                            remaining_attacks_serializable.append({
                                'attacker_id': atk['attacker'].id,
                                'defender_id': atk['defender'].id,
                                'action_dict': atk['action'].to_dict()
                            })

                        overflow_data['remaining_attacks'] = remaining_attacks_serializable  # Store serializable list
                        player_mech.pending_reroll_data = overflow_data
                        log.append(
                            f"> [系统] 抛射物攻击队列已暂停，剩余 {len(overflow_data['remaining_attacks'])} 个动作待处理。")

                    result_data = {
                        'action_required': 'select_reroll',
                        'dice_details': dice_roll_details,
                        'attacker_name': attacker_entity.name,
                        'defender_name': defender_entity.name,
                        'action_name': attack_action.name
                    }
                    game_state.add_visual_event('reroll_required', details=result_data)
                    game_ended_mid_turn = True
                    break

                # 检查游戏是否结束
                game_is_over = game_state.check_game_over()
                if game_is_over:
                    if game_state.game_over == 'ai_win':
                        log.append(f"> 玩家机甲已被摧毁！")
                    elif game_state.game_over == 'player_win':
                        log.append(f"> AI 机甲已被摧毁！")
                    if game_state.game_mode == 'horde' and game_state.game_over == 'ai_win':
                        log.append(f"> [生存模式] 最终击败数: {game_state.ai_defeat_count}")
                    game_ended_mid_turn = True
                    break

    # --- 阶段 3: 回合结束，重置玩家状态 ---
    if not game_state.game_over and not game_ended_mid_turn:
        log.append(
            "> AI回合结束。请开始你的回合。" if game_state.game_mode != 'range' else "> [靶场模式] 请开始你的回合。")
        log.append("-" * 20)

        player_mech = game_state.get_player_mech()
        if player_mech:
            # 宕机恢复检查
            if player_mech.stance == 'downed':
                log.append("> [系统] 驾驶员链接恢复。机甲 [宕机姿态] 解除。")
                log.append("> [警告] 系统冲击！本回合 AP-1, TP-1！")
                player_mech.player_ap = 1
                player_mech.player_tp = 0
                player_mech.stance = 'defense'
            else:
                # 正常回合
                player_mech.player_ap = 2
                player_mech.player_tp = 1

            # 状态重置
            player_mech.turn_phase = 'timing'
            player_mech.timing = None
            player_mech.opening_move_taken = False
            player_mech.actions_used_this_turn = []
            player_mech.pending_effect_data = None
            player_mech.pending_reroll_data = None

        game_state.check_game_over()

    return game_state, log, result_data, None


def handle_respawn_ai(game_state):
    """(系统) 在靶场模式下重生 AI。"""
    log = []
    if game_state.game_mode == 'range' and game_state.game_over == 'ai_defeated_in_range':
        game_state._spawn_range_ai()
        ai_mech = game_state.get_ai_mech()
        ai_name = ai_mech.name if ai_mech else "未知AI"

        log.append("-" * 20)
        log.append(f"> [靶场模式] 新的目标出现: {ai_name}！")
        log.append("> 请开始你的回合。")
    else:
        log.append("[错误] 尝试在非靶场模式下重生AI。")
        return game_state, log, None, "Not in range mode"

    return game_state, log, None, None