"""
玩家回合阶段处理器 (Phase 1-4).
从 game_controller.py 拆分，共享辅助函数仍从 game_controller 导入。
"""

import random
from .data_models import Mech, Part, Action
from .combat_system import CombatState
from .dice_roller import roll_black_die
from .game_logic import is_back_attack, run_projectile_logic, get_player_lock_status
from . import ace_logic
from .config import log_action, log_phase, log_combat, log_system, log_err, log_warn, log_detail
from .game_controller import (
    _clear_transient_state, _apply_combat_packet,
    _execute_main_action, _run_interception_checks,
    _crush_drones_at_pos
)


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
    result_data = {}

    if player_mech.turn_phase == 'timing' and player_mech.timing and not game_state.game_over:

        # [Ace Logic] 检查是否触发抢先手
        ai_mech = game_state.get_ai_mech()
        if ai_mech and ai_mech.pilot and "Raven" in ai_mech.pilot.name:
            log.append(log_phase("[⚠️ WARNING] 遭遇王牌机师！"))

            # 守卫：Ace 已在本回合抢先行动过，跳过重复拼刀
            if ai_mech.has_acted_early:
                log.append(log_system("Ace 已抢先行动过，跳过拼刀。"))
            else:
                ai_timing = ace_logic.decide_ace_timing(ai_mech, player_mech, game_state)
                ai_mech.timing = ai_timing  # 存储 Ace 选择的时机

                # 拼刀仅在双方选择同一时机时触发
                if player_mech.timing == ai_timing:
                    winner, reason = ace_logic.check_initiative(player_mech.timing, ai_timing, player_mech.pilot, ai_mech.pilot)
                    log.append(log_action(f"[拼刀] 玩家选择 [{player_mech.timing}] vs AI选择 [{ai_timing}]（相同时机！）"))
                    log.append(log_action(f"{reason}"))

                    clash_event_data = {
                        'player_timing': player_mech.timing,
                        'ai_timing': ai_timing,
                        'winner': winner,
                        'reason': reason
                    }
                    result_data['clash_occurred'] = True

                    if winner == 'ai':
                        log.append(log_warn(f"你的先手时机被 Ace 夺取！AI 将在 [{ai_timing}] 阶段抢先行动！"))
                        ai_mech.has_acted_early = True
                        ai_mech.won_clash = True
                        # Ace 的回合将在 handle_advance_round 的战斗阶段中执行

                        game_state.add_visual_event('clash_result', details=clash_event_data)
                    else:
                        log.append(log_system("你赢得了先手！继续回合。"))
                        game_state.add_visual_event('clash_result', details=clash_event_data)
                else:
                    log.append(log_action(f"[Ace] AI 选择了 [{ai_timing}]，与玩家 [{player_mech.timing}] 不同，无拼刀。各自在对应阶段行动。"))

        game_state = _clear_transient_state(game_state)
        log.append(log_action(f"时机已确认为 [{player_mech.timing}]。推进阶段..."))
        result_data['advance_round'] = True
        return game_state, log, None, result_data, None

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
        log.append(log_action(f"姿态已确认为 [{player_mech.stance}]。进入调整阶段。"))
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

        _crush_drones_at_pos(game_state, player_mech, player_mech.pos, log)
        game_state.visual_events = []
        log.append(log_action(f"玩家调整移动到 {player_mech.pos}。进入主动作阶段。"))
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
        log.append(log_action(f"玩家仅转向。进入主动作阶段。"))
        return game_state, log, None, None, None
    return game_state, log, None, None, "Cannot change orientation"


def handle_skip_adjustment(game_state, player_mech):
    """(玩家) 阶段 3：跳过调整"""
    log = []
    if player_mech.turn_phase == 'adjustment' and not game_state.game_over:
        player_mech.turn_phase = 'main'
        game_state = _clear_transient_state(game_state)
        game_state.visual_events = []
        log.append(log_action(f"玩家跳过调整阶段。进入主动作阶段。"))
        return game_state, log, None, None, None
    return game_state, log, None, None, "Cannot skip adjustment"


# --- 阶段 4 控制器 (玩家回合) ---

def handle_move_player(game_state, player_mech, action_name, part_slot, target_pos, final_orientation):
    """(玩家) 阶段 4：执行[移动]动作"""
    log = []
    action = player_mech.get_action_by_name_and_slot(action_name, part_slot)
    game_state.visual_events = []

    if player_mech.turn_phase == 'main' and action:
        game_state, action_log, success, message = _execute_main_action(game_state, player_mech, action, action_name,
                                                                        part_slot)
        log.extend(action_log)
        if success:
            player_mech.last_pos = player_mech.pos
            player_mech.pos = tuple(target_pos)
            player_mech.orientation = final_orientation

            _crush_drones_at_pos(game_state, player_mech, player_mech.pos, log)

            log.append(log_action(f"玩家执行 [{action.name}]。"))
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
            log.append(log_err(error))
            return game_state, log, None, None, error

    valid_targets_list, valid_launch_cells_list = game_state.calculate_attack_range(
        player_mech, attack_action
    )

    if attack_action.action_type == '抛射':
        return _execute_player_projectile(game_state, player_mech, attack_action,
                                          action_name, part_slot, defender_entity,
                                          valid_targets_list, valid_launch_cells_list, data)
    elif attack_action.action_type in ['射击', '近战', '快速']:
        return _execute_player_direct_attack(game_state, player_mech, attack_action,
                                             action_name, part_slot, defender_entity,
                                             valid_targets_list, data)
    return game_state, log, None, None, "无效的动作类型"


def _execute_player_projectile(game_state, player_mech, attack_action,
                                action_name, part_slot, defender_entity,
                                valid_targets_list, valid_launch_cells_list, data):
    """执行玩家[抛射]动作"""
    log = []

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
        log.append(log_err(error))
        return game_state, log, None, None, error

    game_state, action_log, success, message = _execute_main_action(
        game_state, player_mech, attack_action, action_name, part_slot)
    log.extend(action_log)
    if not success:
        return game_state, log, None, None, message

    salvo_count = attack_action.effects.get("salvo", 1)
    ammo_key = (player_mech.id, part_slot, attack_action.name)
    current_ammo = game_state.ammo_counts.get(ammo_key, 0)
    projectiles_to_launch = min(salvo_count, current_ammo)

    if projectiles_to_launch <= 0:
        error = "弹药耗尽"
        log.append(log_err(f"{error}，无法执行 [{attack_action.name}]。"))
        return game_state, log, None, None, error

    game_state.ammo_counts[ammo_key] -= projectiles_to_launch
    log.append(log_action(f"玩家发射 [{attack_action.name}] 到 {target_pos}！"))
    if projectiles_to_launch > 1:
        log.append(log_action(f"【齐射{projectiles_to_launch}】触发！发射 {projectiles_to_launch} 枚抛射物。"))
    log.append(log_action(f"消耗 {projectiles_to_launch} 弹药, 剩余 {game_state.ammo_counts[ammo_key]}。"))

    projectile_queue = [target_pos] * projectiles_to_launch
    while projectile_queue:
        if getattr(player_mech, 'pending_combat', None):
            log.append(log_action(f"[结算] 战斗被暂停，剩余 {len(projectile_queue)} 枚抛射物在队列中。"))
            player_mech.pending_combat['projectile_queue'] = projectile_queue
            log.append(log_system(f"剩余齐射已保存。"))
            break

        current_target_pos = projectile_queue.pop(0)
        projectile_id, projectile_obj = game_state.spawn_projectile(
            launcher_entity=player_mech,
            target_pos=current_target_pos,
            projectile_key=attack_action.projectile_to_spawn
        )
        if not projectile_obj:
            log.append(log_err(f"生成抛射物 {attack_action.projectile_to_spawn} 失败！"))
            continue

        has_immediate_action = projectile_obj.get_action_by_timing('立即')[0] is not None
        if not has_immediate_action:
            game_state, log = _run_interception_checks(projectile_obj, game_state, log)

        entity_log, attacks = run_projectile_logic(projectile_obj, game_state, '立即')
        log.extend(entity_log)

        for attack in attacks:
            if getattr(player_mech, 'pending_combat', None):
                log.append(log_action(f"[结算] 战斗被暂停，跳过 {attack.get('action').name} 结算。"))
                continue

            if not isinstance(attack, dict): continue
            attacker = attack.get('attacker')
            defender = attack.get('defender')
            action = attack.get('action')
            if not attacker or not defender or not action: continue
            if attacker.status == 'destroyed' or defender.status == 'destroyed':
                continue

            log.append(log_phase(f"[立即引爆] 结算 ({attacker.name} -> {action.name})"))

            target_part_slot = 'core'
            if isinstance(defender, Mech):
                hit_roll_result = roll_black_die()
                log.append(log_action(f"投掷部位骰结果: 【{hit_roll_result}】"))
                if hit_roll_result == 'any':
                    valid_parts = [s for s, p in defender.parts.items() if p and p.status != 'destroyed']
                    target_part_slot = random.choice(valid_parts) if valid_parts else 'core'
                    log.append(log_action(f"抛射物随机命中: [{target_part_slot}]。"))
                elif defender.parts.get(hit_roll_result) and defender.parts[hit_roll_result].status != 'destroyed':
                    target_part_slot = hit_roll_result
                else:
                    log.append(log_action(f"部位 [{hit_roll_result}] 不存在或已摧毁，转而命中 [核心]。"))
            else:
                log.append(log_action(f"攻击自动瞄准 [{defender.name}] 的核心。"))

            combat_session = CombatState(
                attacker_entity=attacker, defender_entity=defender,
                action=action, target_part_name=target_part_slot, is_back_attack=False,
                ace_reroll_callback=ace_logic.decide_reroll,
            )
            log, result_packet = combat_session.resolve(log)
            game_state = _apply_combat_packet(game_state, result_packet, log)

            dice_roll_details = result_packet.get('dice_roll_details')
            if dice_roll_details:
                game_state.add_visual_event(
                    'dice_roll', attacker_name=attacker.name, defender_name=defender.name,
                    action_name=action.name, details=dice_roll_details
                )
            game_state.add_visual_event('attack_result', defender_pos=defender.pos,
                                        result_text=result_packet['status'])

            if combat_session.stage != 'RESOLVED':
                player_mech.pending_combat = combat_session.to_dict()
                result_data = {
                    'action_required': 'select_reroll' if combat_session.stage in ('AWAITING_ATTACK_REROLL', 'AWAITING_EFFECT_REROLL') else 'select_effect',
                    'dice_details': dice_roll_details,
                    'attacker_name': attacker.name,
                    'defender_name': defender.name,
                    'action_name': action.name
                }
                if combat_session.stage == 'AWAITING_EFFECT_CHOICE':
                    result_data['options'] = combat_session.available_effect_options
                game_state.add_visual_event(result_data['action_required'], details=result_data)
                return game_state, log, None, result_data, None

    return game_state, log, None, None, None


def _execute_player_direct_attack(game_state, player_mech, attack_action,
                                   action_name, part_slot, defender_entity,
                                   valid_targets_list, data):
    """执行玩家[射击]/[近战]/[快速]动作"""
    log = []

    if not defender_entity:
        error = "射击/近战动作需要一个实体目标。"
        log.append(log_err(error))
        return game_state, log, None, None, error

    target_data = next((t for t in valid_targets_list if t['entity'].id == defender_entity.id), None)
    if not target_data:
        error = f"目标 {defender_entity.name} 不在有效攻击范围内。"
        log.append(log_err(error))
        return game_state, log, None, None, error

    is_player_locked, _ = get_player_lock_status(game_state, player_mech)
    if is_player_locked and attack_action.action_type == '射击' and not attack_action.effects.get('melee_shooting'):
        error = f"你被近战锁定，无法执行 [{attack_action.name}]！"
        log.append(log_err(error))
        return game_state, log, None, None, error

    back_attack = target_data['is_back_attack']
    target_part_slot = data.get('target_part_name')

    two_handed_sniper_active = False
    if attack_action.effects.get("two_handed_sniper", False):
        other_arm_slot = 'left_arm' if part_slot == 'right_arm' else 'right_arm'
        other_arm_part = player_mech.parts.get(other_arm_slot)
        if other_arm_part and "【空手】" in other_arm_part.tags:
            two_handed_sniper_active = True
            log.append(log_action(f"动作效果【【双手】获得狙击】触发 (另一只手为【空手】)！"))

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
                    log.append(log_action(f"AI 决定用 [{best_parry_part.name}] 进行招架！"))

        if not target_part_slot:
            hit_roll_result = roll_black_die()
            log.append(log_action(f"玩家投掷部位骰结果: 【{hit_roll_result}】"))
            if hit_roll_result == 'any':
                log.append(log_action("玩家获得任意选择权！请选择目标部位。"))
                return game_state, log, None, {'action_required': 'select_part'}, None

            if isinstance(defender_entity, Mech) and defender_entity.parts.get(hit_roll_result) and \
                    defender_entity.parts[hit_roll_result].status != 'destroyed':
                target_part_slot = hit_roll_result
            else:
                target_part_slot = 'core'
                if isinstance(defender_entity, Mech):
                    log.append(log_action(f"部位 [{hit_roll_result}] 不存在或已摧毁，转而命中 [核心]。"))
                else:
                    log.append(log_action(f"目标为非机甲单位，自动命中 [核心]。"))

    game_state, action_log, success, message = _execute_main_action(
        game_state, player_mech, attack_action, action_name, part_slot)
    log.extend(action_log)
    if not success:
        return game_state, log, None, None, message

    if not target_part_slot:
        error = "未能确定目标部件！攻击中止。"
        log.append(log_action(f"[严重错误] {error}"))
        return game_state, log, None, None, error

    combat_session = CombatState(
        attacker_entity=player_mech, defender_entity=defender_entity,
        action=attack_action, target_part_name=target_part_slot, is_back_attack=back_attack,
        ace_reroll_callback=ace_logic.decide_reroll,
    )
    log, result_packet = combat_session.resolve(log)
    game_state = _apply_combat_packet(game_state, result_packet, log)

    dice_roll_details = result_packet.get('dice_roll_details')
    if dice_roll_details:
        game_state.add_visual_event(
            'dice_roll', attacker_name=player_mech.name, defender_name=defender_entity.name,
            action_name=attack_action.name, details=dice_roll_details
        )
    game_state.add_visual_event('attack_result', defender_pos=defender_entity.pos,
                                result_text=result_packet['status'])

    if combat_session.stage != 'RESOLVED':
        player_mech.pending_combat = combat_session.to_dict()
        result_data = {
            'action_required': 'select_reroll' if combat_session.stage in ('AWAITING_ATTACK_REROLL', 'AWAITING_EFFECT_REROLL') else 'select_effect',
            'dice_details': dice_roll_details,
            'attacker_name': player_mech.name,
            'defender_name': defender_entity.name,
            'action_name': attack_action.name
        }
        if combat_session.stage == 'AWAITING_EFFECT_CHOICE':
            result_data['options'] = combat_session.available_effect_options
        game_state.add_visual_event(result_data['action_required'], details=result_data)
        return game_state, log, None, result_data, None

    ai_was_defeated = (defender_entity.controller == 'ai' and
                       (defender_entity.status == 'destroyed' or
                        (isinstance(defender_entity, Mech) and defender_entity.parts.get('core') and (
                                defender_entity.parts['core'].status == 'destroyed' or
                                defender_entity.get_active_parts_count() < 3))))
    game_is_over = game_state.check_game_over()
    ai_mech = game_state.get_ai_mech()
    if game_state.game_mode == 'horde' and ai_was_defeated and not game_is_over and ai_mech:
        log.append(log_system(f"击败了 {game_state.ai_defeat_count} 台敌机！"))
        log.append(log_warn(f"新的敌人出现: {ai_mech.name}！"))

    return game_state, log, None, None, None


def handle_jettison_part(game_state, player_mech, part_slot):
    """(玩家) 阶段 4：执行[弃置]动作"""
    from .database import ALL_PARTS

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

    game_state, action_log, success, message = _execute_main_action(
        game_state, player_mech, action_obj, "【弃置】", part_slot
    )
    log.extend(action_log)
    if not success:
        return game_state, log, None, None, message

    current_part_name = part.name
    current_status = part.status
    discarded_part_name = f"{current_part_name}（弃置）"

    if discarded_part_name not in ALL_PARTS:
        log.append(log_err(f"数据库中未找到对应的（弃置）部件: {discarded_part_name}"))
        return game_state, log, None, None, "未找到（弃置）部件"

    new_part_data = ALL_PARTS[discarded_part_name]
    new_part = Part.from_dict(new_part_data.to_dict())

    new_part.status = current_status
    if current_status == 'damaged':
        log.append(log_action(f"部件状态 [破损] 已继承。"))

    player_mech.parts[part_slot] = new_part
    log.append(log_action(f"玩家弃置了 [{current_part_name}]，更换为 [{new_part.name}]。"))

    game_state = _clear_transient_state(game_state)
    return game_state, log, None, None, None


def handle_debug_skill(game_state, player_mech):
    """(玩家) 阶段 4：技能【除虫】— 攻击姿态下消耗1链接值获得1AP"""
    log = []
    game_state.visual_events = []

    if player_mech.turn_phase != 'main':
        return game_state, log, None, None, "只能在主阶段使用【除虫】。"

    if player_mech.stance != 'attack':
        return game_state, log, None, None, "【除虫】只能在攻击姿态下使用。"

    if ('skill', '【除虫】') in player_mech.actions_used_this_turn:
        return game_state, log, None, None, "【除虫】本回合已使用过。"

    if player_mech.pilot.link_points <= 0:
        return game_state, log, None, None, "链接值不足，无法使用【除虫】。"

    player_mech.pilot.link_points -= 1
    player_mech.player_ap += 1
    player_mech.actions_used_this_turn.append(('skill', '【除虫】'))
    log.append(log_action(f"【除虫】消耗 1 点链接值，获得 1 点行动时点 (AP)。剩余链接值: {player_mech.pilot.link_points}"))

    game_state = _clear_transient_state(game_state)
    return game_state, log, None, None, None
