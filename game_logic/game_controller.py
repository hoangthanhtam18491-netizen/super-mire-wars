from .data_models import Mech, Projectile, Action  # [v_REROLL] 导入 Action
from .combat_system import resolve_attack, _resolve_effect_logic
from .dice_roller import roll_black_die, reroll_specific_dice  # [v_REROLL] 导入 reroll
from .game_logic import is_back_attack, run_projectile_logic, check_interception, GameState
import random


# [v_REFACTOR]
# “优化 2” - 这是一个新的控制器模块
# 它包含了所有 *执行* 玩家动作的纯 Python 逻辑。
# 它不了解 Flask、session 或 request。
# 它接收一个 GameState 对象和数据，然后返回更新后的 GameState、日志、事件和结果。

# --- 辅助函数 ---

def _clear_transient_state(game_state):
    """
    (辅助函数) 清除所有用于单次动画的状态
    [v_REROLL_FIX] 此函数现在只应清除 last_pos。
    visual_events 由控制器在适当的时候（例如处理完中断后）清除。
    """
    for entity in game_state.entities.values():
        entity.last_pos = None
    # game_state.visual_events = [] # [v_REROLL_FIX] 移除此行
    return game_state


def _execute_main_action(game_state, player_mech, action, action_name, part_slot):
    """ (服务器端) 验证并执行一个主动作。 """
    log = []
    action_id = (part_slot, action_name)

    if action_id in player_mech.actions_used_this_turn:
        error = f"[{action_name}] (来自: {part_slot}) 本回合已使用过。"
        log.append(f"> [错误] {error}")
        return game_state, log, False, error

    ammo_key = (player_mech.id, part_slot, action.name)
    if action.ammo > 0:
        current_ammo = game_state.ammo_counts.get(ammo_key, 0)
        if current_ammo <= 0:
            error = f"弹药耗尽，无法执行 [{action.name}]。"
            log.append(f"> [错误] {error}")
            return game_state, log, False, error

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

    if not player_mech.opening_move_taken:
        # [MODIFIED] 允许 '快速' 动作
        if action.action_type != player_mech.timing and action.action_type != '快速':
            error = f"起手动作错误！当前时机为 [{player_mech.timing}]，无法执行 [{action.action_type}] 动作。"
            log.append(f"> [错误] {error}")
            return game_state, log, False, error
        player_mech.opening_move_taken = True

    player_mech.player_ap -= ap_cost
    player_mech.player_tp -= tp_cost
    player_mech.actions_used_this_turn.append((part_slot, action_name))

    # [v_MODIFIED] 弹药消耗逻辑移至 /execute_attack 以处理【齐射】
    # [v1.30] 拦截动作的弹药在 game_logic.py 中消耗
    if action.ammo > 0 and action.action_type != '抛射' and not action.effects.get("interceptor"):
        game_state.ammo_counts[ammo_key] -= 1
        log.append(f"> [{action.name}] 消耗 1 弹药，剩余 {game_state.ammo_counts[ammo_key]}。")

    return game_state, log, True, "Success"


# --- 阶段 1 & 2 控制器 ---

def handle_select_timing(game_state, player_mech, timing):
    log = []
    if player_mech.turn_phase == 'timing' and not game_state.game_over:
        player_mech.timing = timing
        game_state = _clear_transient_state(game_state)
        game_state.visual_events = []  # [v_REROLL_FIX] 确认动作后清除事件
        return game_state, log, None, None
    return game_state, log, None, "Not in timing phase"


def handle_confirm_timing(game_state, player_mech):
    log = []
    if player_mech.turn_phase == 'timing' and player_mech.timing and not game_state.game_over:
        player_mech.turn_phase = 'stance'
        game_state = _clear_transient_state(game_state)
        game_state.visual_events = []  # [v_REROLL_FIX] 确认动作后清除事件
        log.append(f"> 时机已确认为 [{player_mech.timing}]。进入姿态选择阶段。")
        return game_state, log, None, None
    return game_state, log, None, "Please select a timing first."


def handle_change_stance(game_state, player_mech, new_stance):
    log = []
    if player_mech.turn_phase == 'stance' and not game_state.game_over:
        player_mech.stance = new_stance
        game_state = _clear_transient_state(game_state)
        game_state.visual_events = []  # [v_REROLL_FIX] 确认动作后清除事件
        return game_state, log, None, None
    return game_state, log, None, "Not in stance phase."


def handle_confirm_stance(game_state, player_mech):
    log = []
    if player_mech.turn_phase == 'stance' and not game_state.game_over:
        player_mech.turn_phase = 'adjustment'
        game_state = _clear_transient_state(game_state)
        game_state.visual_events = []  # [v_REROLL_FIX] 确认动作后清除事件
        log.append(f"> 姿态已确认为 [{player_mech.stance}]。进入调整阶段。")
        return game_state, log, None, None
    return game_state, log, None, "Not in stance phase."


# --- 阶段 3 控制器 ---

def handle_adjust_move(game_state, player_mech, target_pos, final_orientation):
    log = []
    if player_mech.turn_phase == 'adjustment' and player_mech.player_tp >= 1 and not game_state.game_over:
        player_mech.last_pos = player_mech.pos
        player_mech.pos = tuple(target_pos)
        player_mech.orientation = final_orientation
        player_mech.player_tp -= 1
        player_mech.turn_phase = 'main'
        game_state.visual_events = []  # [v_REROLL_FIX] 确认动作后清除事件
        log.append(f"> 玩家调整移动到 {player_mech.pos}。进入主动作阶段。")
        return game_state, log, None, None
    return game_state, log, None, "Cannot perform adjust move"


def handle_change_orientation(game_state, player_mech, final_orientation):
    log = []
    if player_mech.turn_phase == 'adjustment' and player_mech.player_tp >= 1 and not game_state.game_over:
        player_mech.orientation = final_orientation
        player_mech.player_tp -= 1
        player_mech.turn_phase = 'main'
        game_state = _clear_transient_state(game_state)
        game_state.visual_events = []  # [v_REROLL_FIX] 确认动作后清除事件
        log.append(f"> 玩家仅转向。进入主动作阶段。")
        return game_state, log, None, None
    return game_state, log, None, "Cannot change orientation"


def handle_skip_adjustment(game_state, player_mech):
    log = []
    if player_mech.turn_phase == 'adjustment' and not game_state.game_over:
        player_mech.turn_phase = 'main'
        game_state = _clear_transient_state(game_state)
        game_state.visual_events = []  # [v_REROLL_FIX] 确认动作后清除事件
        log.append(f"> 玩家跳过调整阶段。进入主动作阶段。")
        return game_state, log, None, None
    return game_state, log, None, "Cannot skip adjustment"


# --- 阶段 4 控制器 ---

def handle_move_player(game_state, player_mech, action_name, part_slot, target_pos, final_orientation):
    log = []
    action = player_mech.get_action_by_name_and_slot(action_name, part_slot)

    # [v_REROLL_FIX] 在动作开始时清除视觉事件
    game_state.visual_events = []

    if player_mech.turn_phase == 'main' and action:
        game_state, action_log, success, message = _execute_main_action(game_state, player_mech, action, action_name,
                                                                        part_slot)
        log.extend(action_log)
        if success:
            player_mech.last_pos = player_mech.pos
            player_mech.pos = tuple(target_pos)
            player_mech.orientation = final_orientation
            log.append(f"> 玩家执行 [{action.name}]。")
            return game_state, log, None, None
        else:
            return game_state, log, None, message
    return game_state, log, None, "动作执行失败"


def handle_execute_attack(game_state, player_mech, data):
    log = []
    # [v_REROLL_FIX] 在动作开始时清除视觉事件
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

        game_state, action_log, success, message = _execute_main_action(game_state, player_mech, attack_action,
                                                                        action_name, part_slot)
        log.extend(action_log)
        if not success:
            return game_state, log, None, None, message

        attacks_to_resolve_list = []
        salvo_count = attack_action.effects.get("salvo", 1)
        ammo_key = (player_mech.id, part_slot, attack_action.name)
        current_ammo = game_state.ammo_counts.get(ammo_key, 0)
        projectiles_to_launch = min(salvo_count, current_ammo)

        if projectiles_to_launch <= 0:
            error = "弹药耗尽"
            log.append(f"> [错误] {error}，无法执行 [{attack_action.name}]。")
            return game_state, log, None, None, error

        game_state.ammo_counts[ammo_key] -= projectiles_to_launch
        log.append(f"> 玩家发射 [{attack_action.name}] 到 {target_pos}！")
        if projectiles_to_launch > 1:
            log.append(f"> 【齐射{projectiles_to_launch}】触发！发射 {projectiles_to_launch} 枚抛射物。")
        log.append(f"> 消耗 {projectiles_to_launch} 弹药, 剩余 {game_state.ammo_counts[ammo_key]}。")

        for _ in range(projectiles_to_launch):
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
                # [MODIFIED] 拦截现在立即结算
                check_interception(projectile_obj, game_state, log)
                # [MODIFIED] 移除旧的队列逻辑
                # intercept_log, intercept_attacks = check_interception(projectile_obj, game_state)
                # if intercept_attacks:
                #     log.extend(intercept_log)
                #     attacks_to_resolve_list.extend(intercept_attacks)

            entity_log, attacks = run_projectile_logic(projectile_obj, game_state, '立即')
            log.extend(entity_log)
            attacks_to_resolve_list.extend(attacks)

        # [v_PROJECTILE_FIX] 新增变量
        reroll_triggered = False
        first_reroll_result_data = None

        for attack in attacks_to_resolve_list:
            # [v_PROJECTILE_FIX] 如果已触发重投，跳过后续攻击
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

            # [v_REROLL_FIX] 抛射物攻击也需要检查重投
            attack_log, result, overflow_data, dice_roll_details = resolve_attack(
                attacker_entity=attacker, defender_entity=defender, action=action,
                target_part_name=target_part_slot, is_back_attack=False, chosen_effect=None,
                skip_reroll_phase=False  # 允许玩家在被抛射物攻击时重投
            )
            log.extend(attack_log)
            if dice_roll_details:
                game_state.add_visual_event(
                    'dice_roll', attacker_name=attacker.name, defender_name=defender.name,
                    action_name=action.name, details=dice_roll_details
                )
            game_state.add_visual_event('attack_result', defender_pos=defender.pos, result_text=result)

            # [v_REROLL_FIX] 捕获抛射物攻击时的重投
            if result == "reroll_choice_required":
                # [v_PROJECTILE_FIX] 设置标志，捕获数据，但不返回
                reroll_triggered = True
                # [v_REROLL_FIX] 确保在正确的 mecha (player_mech) 上设置 pending_data
                player_mech.pending_reroll_data = overflow_data
                first_reroll_result_data = {
                    'action_required': 'select_reroll',
                    'dice_details': dice_roll_details,
                    'attacker_name': attacker.name,
                    'defender_name': defender.name,
                    'action_name': action.name
                }
                game_state.add_visual_event('reroll_required', details=first_reroll_result_data)
                # [v_PROJECTILE_FIX] 不要在这里返回，继续循环（但后续循环会跳过）
                # return game_state, log, None, result_data, None

            game_state.check_game_over()
            if game_state.game_over:
                break

        # [v_PROJECTILE_FIX] 在循环结束后，检查是否触发了重投
        if reroll_triggered:
            return game_state, log, None, first_reroll_result_data, None

        return game_state, log, None, None, None

    # 2. '射击' 或 '近战' 动作
    elif attack_action.action_type in ['射击', '近战', '快速']:  # [v_REROLL_FIX] 允许'快速'动作
        if not defender_entity:
            error = "射击/近战动作需要一个实体目标。"
            log.append(f"> [错误] {error}")
            return game_state, log, None, None, error

        target_data = next((t for t in valid_targets_list if t['entity'].id == defender_entity.id), None)
        if not target_data:
            error = f"目标 {defender_entity.name} 不在有效攻击范围内。"
            log.append(f"> [错误] {error}")
            return game_state, log, None, None, error

        from .game_logic import get_player_lock_status  # 避免循环导入
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

        # [新规则：宕机检查]
        defender_is_downed = (defender_entity.stance == 'downed')

        if not target_part_slot:
            # [修改] 增加 defender_is_downed 条件
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
                # [新规则：宕机检查] 宕机状态下无法招架
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

        game_state, action_log, success, message = _execute_main_action(game_state, player_mech, attack_action,
                                                                        action_name, part_slot)
        log.extend(action_log)
        if not success:
            return game_state, log, None, None, message

        if not target_part_slot:
            error = "未能确定目标部件！攻击中止。"
            log.append(f"> [严重错误] {error}")
            return game_state, log, None, None, error

        # [v_REROLL] 新增参数
        attack_log, result, overflow_data, dice_roll_details = resolve_attack(
            attacker_entity=player_mech, defender_entity=defender_entity, action=attack_action,
            target_part_name=target_part_slot, is_back_attack=back_attack, chosen_effect=None,
            skip_reroll_phase=False  # [v_REROLL] 玩家攻击时 *不* 跳过重投阶段
        )
        log.extend(attack_log)

        if dice_roll_details:
            game_state.add_visual_event(
                'dice_roll', attacker_name=player_mech.name, defender_name=defender_entity.name,
                action_name=attack_action.name, details=dice_roll_details
            )
        game_state.add_visual_event('attack_result', defender_pos=defender_entity.pos, result_text=result)

        # [v_REROLL] 捕获重投中断
        if result == "reroll_choice_required":
            player_mech.pending_reroll_data = overflow_data  # 'overflow_data' 包含了 pending_reroll_data
            # [v_REROLL_FIX] 将所有需要的上下文添加到 result_data
            result_data = {
                'action_required': 'select_reroll',
                'dice_details': dice_roll_details,
                'attacker_name': player_mech.name,
                'defender_name': defender_entity.name,
                'action_name': attack_action.name
            }
            # [v_REROLL_FIX] 添加视觉事件
            game_state.add_visual_event('reroll_required', details=result_data)
            return game_state, log, None, result_data, None

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

        ai_was_defeated = (defender_entity.controller == 'ai' and
                           (defender_entity.status == 'destroyed' or
                            (isinstance(defender_entity, Mech) and defender_entity.parts.get('core') and (
                                    defender_entity.parts[
                                        'core'].status == 'destroyed' or defender_entity.get_active_parts_count() < 3))))

        # [v_REROLL_FIX] 修复 visual_events 传递 (现在已弃用)
        game_is_over = game_state.check_game_over()

        ai_mech = game_state.get_ai_mech()
        if game_state.game_mode == 'horde' and ai_was_defeated and not game_is_over and ai_mech:
            log.append(f"> [生存模式] 击败了 {game_state.ai_defeat_count} 台敌机！")
            log.append(f"> [警告] 新的敌人出现: {ai_mech.name}！")

        return game_state, log, None, None, None

    # [v_REROLL_FIX] 修复 visual_events 传递 (现在已弃用)
    return game_state, log, None, None, "无效的动作类型"


# [NEW] 弃置部件的控制器逻辑
def handle_jettison_part(game_state, player_mech, part_slot):
    # [MODIFIED] 将导入移至函数内部，以解决循环导入
    from parts_database import ALL_PARTS
    from .data_models import Part  # [MODIFIED] 在这里（函数内部）导入 Part

    log = []
    # [v_REROLL_FIX] 在动作开始时清除视觉事件
    game_state.visual_events = []

    # 1. 验证部件和动作
    part = player_mech.parts.get(part_slot)
    if not part:
        return game_state, log, None, "未找到部件"

    action_obj = None
    for act in part.actions:
        if act.name == "【弃置】":
            action_obj = act
            break

    if not action_obj:
        return game_state, log, None, "该部件没有【弃置】动作"

    # 2. 消耗AP (调用 _execute_main_action)
    game_state, action_log, success, message = _execute_main_action(
        game_state, player_mech, action_obj, "【弃置】", part_slot
    )
    log.extend(action_log)
    if not success:
        return game_state, log, None, message

    # 3. 执行弃置逻辑
    current_part_name = part.name
    current_status = part.status
    discarded_part_name = f"{current_part_name}（弃置）"

    if discarded_part_name not in ALL_PARTS:
        log.append(f"> [错误] 数据库中未找到对应的（弃置）部件: {discarded_part_name}")
        # AP 已经消耗，这是一个“失败”的动作
        return game_state, log, None, "未找到（弃置）部件"

    # 4. 创建并替换部件
    new_part_data = ALL_PARTS[discarded_part_name]
    new_part = Part.from_dict(new_part_data.to_dict())

    # 继承状态
    new_part.status = current_status
    if current_status == 'damaged':
        log.append(f"> 部件状态 [破损] 已继承。")
    elif current_status == 'destroyed':
        # 这种情况不应该发生，因为已摧毁的部件无法执行动作
        new_part.status = 'destroyed'

    player_mech.parts[part_slot] = new_part
    log.append(f"> 玩家弃置了 [{current_part_name}]，更换为 [{new_part.name}]。")

    # [v1.26] 清除动画状态，因为我们即将刷新
    game_state = _clear_transient_state(game_state)

    return game_state, log, None, None


def handle_resolve_effect_choice(game_state, player_mech, choice):
    log = []
    # [v_REROLL_FIX] 在处理中断时，首先清除所有旧的视觉事件
    game_state.visual_events = []

    pending_data = player_mech.pending_effect_data
    if not pending_data:
        error = "找不到待处理的效果数据！"
        log.append(f"> [错误] {error}")
        return game_state, log, None, error

    if choice not in pending_data.get('options', []):
        error = f"无效的选择: {choice}"
        log.append(f"> [错误] {error}")
        return game_state, log, None, error

    target_entity_id = pending_data['target_entity_id']
    target_entity = game_state.get_entity_by_id(target_entity_id)
    if not target_entity or target_entity.status == 'destroyed':
        error = f"在解析效果时找不到目标实体: {target_entity_id}"
        log.append(f"> [错误] {error}")
        return game_state, log, None, error

    if not isinstance(target_entity, Mech):
        error = f"效果只能对机甲触发: {target_entity_id}"
        log.append(f"> [错误] {error}")
        return game_state, log, None, error

    target_part_name = pending_data['target_part_name']
    target_part = target_entity.get_part_by_name(target_part_name)
    if not target_part:
        error = f"在解析效果时找不到目标部件: {target_part_name}"
        log.append(f"> [错误] {error}")
        return game_state, log, None, error

    overflow_hits = pending_data['overflow_data']['hits']
    overflow_crits = pending_data['overflow_data']['crits']

    log.append(
        f"> 玩家选择了【{'毁伤' if choice == 'devastating' else ('霰射' if choice == 'scattershot' else '顺劈')}】！")

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

    player_mech.pending_effect_data = None

    ai_was_defeated = (target_entity.controller == 'ai' and
                       (target_entity.status == 'destroyed' or
                        (isinstance(target_entity, Mech) and target_entity.parts.get('core') and (target_entity.parts[
                                                                                                      'core'].status == 'destroyed' or target_entity.get_active_parts_count() < 3))))

    game_is_over = game_state.check_game_over()

    ai_mech = game_state.get_ai_mech()
    if game_state.game_mode == 'horde' and ai_was_defeated and not game_is_over and ai_mech:
        log.append(f"> [生存模式] 击败了 {game_state.ai_defeat_count} 台敌机！")
        log.append(f"> [警告] 新的敌人出现: {ai_mech.name}！")

    return game_state, log, None, None


# [v_REROLL] 新增：处理重投的函数
def handle_resolve_reroll(game_state, player_mech, data):
    log = []
    # [v_REROLL_FIX] 在处理中断时，首先清除所有旧的视觉事件
    game_state.visual_events = []

    # [v_REROLL_FIX] player_mech 始终是 player_1。我们需要从 pending_data 中找到 *真正* 的玩家实体
    pending_data = None
    player_entity_to_clear = None  # 将在重投时消耗链接值的实体

    if player_mech.pending_reroll_data:
        pending_data = player_mech.pending_reroll_data
        player_entity_to_clear = player_mech
    else:
        # 检查AI是否被中断（AI攻击玩家，玩家是防御方）
        ai_mech = game_state.get_ai_mech()
        if ai_mech and ai_mech.pending_reroll_data:
            pending_data = ai_mech.pending_reroll_data
            player_entity_to_clear = player_mech  # 玩家是被攻击方

    if not pending_data:
        # [v_REROLL_FIX] 即使找不到数据，也返回4个值
        return game_state, log, None, "找不到待处理的重投数据！"

    # 1. 恢复上下文
    attacker = game_state.get_entity_by_id(pending_data['attacker_id'])
    defender = game_state.get_entity_by_id(pending_data['defender_id'])

    # [MODIFIED] 根据重投类型恢复 action
    action = None
    action_name_for_log = "Attack"
    if pending_data['type'] == 'attack_reroll':
        action = Action.from_dict(pending_data['action_dict'])
        action_name_for_log = action.name
    elif pending_data['type'] == 'effect_reroll':
        # 效果重投（例如毁伤）没有 action_dict，我们从 chosen_effect 恢复
        action_name_for_log = pending_data['chosen_effect'].capitalize()

    if not attacker or not defender:
        return game_state, log, None, "重投时找不到攻击者或防御者。"
    # [MODIFIED] effect_reroll 时 action 为 None
    # if not action:
    #     return game_state, log, None, "重投时找不到动作。"

    # 2. 准备骰子
    new_attack_rolls = pending_data['attack_raw_rolls']
    new_defense_rolls = pending_data['defense_raw_rolls']

    # 3. 获取玩家的重投选择
    reroll_selections_attacker = data.get('reroll_selections_attacker', [])
    reroll_selections_defender = data.get('reroll_selections_defender', [])
    is_skipping = not reroll_selections_attacker and not reroll_selections_defender

    player_did_reroll = False
    link_cost_applied = False  # 确保只消耗 1 点

    # 4. 执行玩家的重投
    if pending_data['player_is_attacker'] and reroll_selections_attacker:
        # 攻击者是玩家 (player_mech)
        if player_mech.pilot and player_mech.pilot.link_points > 0:
            log.append(f"  > 玩家 (攻击方) 消耗 1 链接值重投 {len(reroll_selections_attacker)} 枚骰子！")
            player_mech.pilot.link_points -= 1
            player_did_reroll = True
            link_cost_applied = True
            new_attack_rolls = reroll_specific_dice(new_attack_rolls, reroll_selections_attacker)
        else:
            log.append("  > [警告] 玩家试图重投攻击骰，但链接值不足！")

    if pending_data['player_is_defender'] and reroll_selections_defender:
        # 防御者是玩家 (player_mech)
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
    # [v_REROLL_FIX] 确保清除了正确的 mecha 上的 data
    if pending_data['player_is_attacker']:
        if isinstance(attacker, Mech):
            attacker.pending_reroll_data = None
    if pending_data['player_is_defender']:
        if isinstance(defender, Mech):
            defender.pending_reroll_data = None

    # 6. 恢复战斗 (跳过重投阶段)
    # [MODIFIED] 根据重投类型选择恢复路径
    result_data = None
    dice_roll_details = None

    if pending_data['type'] == 'attack_reroll':
        attack_log, result, overflow_data, dice_roll_details = resolve_attack(
            attacker_entity=attacker,
            defender_entity=defender,
            action=action,
            target_part_name=pending_data['target_part_name'],
            is_back_attack=pending_data['is_back_attack'],
            chosen_effect=None,  # 重投后，效果选择重置
            skip_reroll_phase=True,  # 关键：跳过下一次中断
            rerolled_attack_raw=new_attack_rolls,  # 关键：传入新骰子
            rerolled_defense_raw=new_defense_rolls  # 关键：传入新骰子
        )
        log.extend(attack_log)

        # 7. [重要] 检查战斗恢复后是否需要 *另一次* 中断 (效果选择)
        if result == "effect_choice_required":
            if isinstance(attacker, Mech):
                attacker.pending_effect_data = overflow_data
            result_data = {
                'action_required': 'select_effect',
                'options': overflow_data['options'],
            }
            game_state.add_visual_event('effect_choice_required', details=result_data)
            # [MODIFIED] 效果选择不需要 dice_details，但我们仍然需要添加 *攻击* 的掷骰结果

    elif pending_data['type'] == 'effect_reroll':
        # [MODIFIED] 恢复效果逻辑
        target_part = defender.get_part_by_name(pending_data['target_part_name'])
        if not target_part:
            log.append(f"> [错误] 重投效果时找不到部件 {pending_data['target_part_name']}。")
            return game_state, log, None, "重投效果时找不到部件"

        attack_log_ext, secondary_roll_details, overflow_data_ext = _resolve_effect_logic(
            log=log,
            attacker_entity=attacker,
            defender_entity=defender,
            target_part=target_part,
            overflow_hits=pending_data['overflow_hits'],
            overflow_crits=pending_data['overflow_crits'],
            chosen_effect=pending_data['chosen_effect'],
            skip_reroll_phase=True,  # 关键：跳过
            rerolled_defense_raw=new_defense_rolls  # 关键：传入
        )

        # [MODIFIED] 效果逻辑重投 *不会* 再次触发重投 (overflow_data_ext 应为 None)
        # [MODIFIED] 效果逻辑返回的是 *次要* 掷骰，将其设为 *主要* 掷骰以便显示
        dice_roll_details = secondary_roll_details
        result = "击穿"  # 效果逻辑总是由“击穿”触发
        # (log 已经被 _resolve_effect_logic 更新了)

    # [v_REROLL_FIX] 总是添加最终的掷骰结果事件
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
        # [MODIFIED] 如果触发了效果选择，将 dice_roll_details 添加到 result_data 中
        result_data.update({
            'dice_details': dice_roll_details,
            'attacker_name': attacker.name,
            'defender_name': defender.name,
            'action_name': action_name_for_log
        })
        return game_state, log, result_data, None

    # 8. 如果战斗结束，正常返回
    game_is_over = game_state.check_game_over()

    # [v_REROLL_FIX] 修复“卡在阶段4”的BUG
    # 无论玩家是攻击方还是防御方，只要重投/效果结算完毕，且游戏未结束，
    # 并且现在是AI的回合（即玩家是防御方），我们就必须重置玩家的回合。
    # 玩家攻击时 (player_is_attacker)，我们 *不* 重置，因为玩家可能还有AP。
    if (not game_is_over and not player_mech.pending_effect_data):

        # 检查这是否是 AI 回合的结束
        if pending_data['player_is_defender']:
            log.append(
                "> AI回合结束。请开始你的回合。" if game_state.game_mode != 'range' else "> [靶场模式] 请开始你的回合。")
            log.append("-" * 20)

            # [v_REROLL_FIX] 重置玩家状态
            player_mech.player_ap = 2
            player_mech.player_tp = 1
            player_mech.turn_phase = 'timing'
            player_mech.timing = None
            player_mech.opening_move_taken = False
            player_mech.actions_used_this_turn = []
            player_mech.pending_effect_data = None
            player_mech.pending_reroll_data = None  # 确保清除

    return game_state, log, result_data, None

