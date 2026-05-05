"""
AI 回合执行、中断解决和抛射物阶段处理器。
从 game_controller.py 拆分，共享辅助函数仍从 game_controller 导入。
"""

import random
from .data_models import Mech, Projectile, Action
from .combat_system import CombatState
from .dice_roller import roll_black_die
from .game_logic import is_back_attack, run_projectile_logic, run_drone_logic
from .ai_system import run_ai_turn
from . import ace_logic
from . import ace_ai_system
from .game_controller import (
    _clear_transient_state, _apply_combat_packet,
    _run_interception_checks
)


def _resolve_queued_attack(game_state, log, attack_data, remaining_attacks_queue):
    """
    (辅助函数) 结算一次 AI 攻击 (或抛射物攻击)。
    返回: (game_state, log, result_data, game_ended_mid_turn)
    """
    result_data = None
    game_ended_mid_turn = False

    if not isinstance(attack_data, dict):
        log.append(f"> [严重错误] 队列攻击数据不是字典: {attack_data}")
        return game_state, log, result_data, game_ended_mid_turn

    attacker_entity = game_state.get_entity_by_id(attack_data.get('attacker_id'))
    defender_entity = game_state.get_entity_by_id(attack_data.get('defender_id'))
    attack_action_dict = attack_data.get('action_dict')

    if not attacker_entity or not defender_entity or not attack_action_dict:
        log.append(f"> [严重错误] 队列攻击数据不完整: {attack_data}")
        return game_state, log, result_data, game_ended_mid_turn

    attack_action = Action.from_dict(attack_action_dict)

    if attacker_entity.status == 'destroyed' or defender_entity.status == 'destroyed':
        return game_state, log, result_data, game_ended_mid_turn

    log.append(f"--- 攻击结算 ({attacker_entity.name} -> {attack_action.name}) ---")

    back_attack = False
    if isinstance(defender_entity, Mech):
        if isinstance(attacker_entity, Mech):
            back_attack = is_back_attack(attacker_entity.pos, defender_entity.pos, defender_entity.orientation)
        elif isinstance(attacker_entity, Projectile):
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
                damaged_parts = [s for s, p in defender_entity.parts.items() if p and p.status == 'damaged']
                if damaged_parts:
                    target_part_slot = random.choice(damaged_parts)
                    log.append(f"> AI 优先攻击已受损部件: [{target_part_slot}]。")
                elif defender_entity.parts.get('core') and defender_entity.parts['core'].status != 'destroyed':
                    target_part_slot = 'core'
                    log.append("> AI 决定攻击 [核心]。")
                else:
                    valid_parts = [s for s, p in defender_entity.parts.items() if p and p.status != 'destroyed']
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

    combat_session = CombatState(
        attacker_entity=attacker_entity,
        defender_entity=defender_entity,
        action=attack_action,
        target_part_name=target_part_slot,
        is_back_attack=back_attack,
        ace_reroll_callback=ace_logic.decide_reroll,
    )
    log, result_packet = combat_session.resolve(log)

    game_state = _apply_combat_packet(game_state, result_packet, log)

    dice_roll_details = result_packet.get('dice_roll_details')
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
        result_text=result_packet['status']
    )

    if combat_session.stage != 'RESOLVED':
        if isinstance(defender_entity, Mech):
            remaining_attacks_serializable = []
            for atk in remaining_attacks_queue:
                if isinstance(atk, dict):
                    remaining_attacks_serializable.append(atk)

            pending_combat_dict = combat_session.to_dict()
            pending_combat_dict['remaining_attacks'] = remaining_attacks_serializable
            defender_entity.pending_combat = pending_combat_dict

            log.append(
                f"> [系统] AI 攻击队列已暂停，剩余 {len(remaining_attacks_serializable)} 个动作待处理。")

        result_data = {
            'action_required': 'select_reroll' if combat_session.stage == 'AWAITING_ATTACK_REROLL' else 'select_effect',
            'dice_details': dice_roll_details,
            'attacker_name': attacker_entity.name,
            'defender_name': defender_entity.name,
            'action_name': attack_action.name
        }
        if combat_session.stage == 'AWAITING_EFFECT_CHOICE':
            result_data['options'] = combat_session.available_effect_options

        game_state.add_visual_event(result_data['action_required'], details=result_data)
        game_ended_mid_turn = True

    game_is_over = game_state.check_game_over()
    if game_is_over and game_state.game_over == 'ai_win':
        log.append(f"> 玩家机甲已被摧毁！")
        if game_state.game_mode == 'horde':
            log.append(f"> [生存模式] 最终击败数: {game_state.ai_defeat_count}")
        game_ended_mid_turn = True

    return game_state, log, result_data, game_ended_mid_turn


# --- 中断处理控制器 ---

def handle_resolve_effect_choice(game_state, player_mech, choice):
    """(玩家) 中断：处理溢出效果选择"""
    log = []
    game_state.visual_events = []

    pending_combat_data = getattr(player_mech, 'pending_combat', None)
    if not pending_combat_data:
        error = "找不到待处理的战斗数据！"
        log.append(f"> [错误] {error}")
        return game_state, log, None, None, error

    try:
        combat_session = CombatState.from_dict(pending_combat_data, game_state,
                                               ace_reroll_callback=ace_logic.decide_reroll)
    except ValueError as e:
        log.append(f"> [严重错误] 恢复战斗状态失败: {e}")
        player_mech.pending_combat = None
        return game_state, log, None, None, f"恢复战斗状态失败: {e}"

    if combat_session.stage != 'AWAITING_EFFECT_CHOICE':
        error = f"战斗状态不匹配 (预期: AWAITING_EFFECT_CHOICE, 得到: {combat_session.stage})"
        log.append(f"> [错误] {error}")
        player_mech.pending_combat = None
        return game_state, log, None, None, error

    log, result_packet = combat_session.submit_effect_choice(log, choice)
    game_state = _apply_combat_packet(game_state, result_packet, log)

    dice_roll_details = result_packet.get('dice_roll_details')
    if dice_roll_details:
        game_state.add_visual_event(
            'dice_roll',
            attacker_name=combat_session.attacker_entity.name,
            defender_name=combat_session.defender_entity.name,
            action_name=combat_session.action.name,
            details=dice_roll_details
        )
    game_state.add_visual_event('attack_result', defender_pos=combat_session.defender_entity.pos,
                                result_text=result_packet['status'])

    if combat_session.stage == 'AWAITING_EFFECT_REROLL':
        player_mech.pending_combat = combat_session.to_dict()
        result_data = {
            'action_required': 'select_reroll',
            'dice_details': dice_roll_details.get('secondary_roll'),
            'attacker_name': combat_session.attacker_entity.name,
            'defender_name': combat_session.defender_entity.name,
            'action_name': choice.capitalize()
        }
        game_state.add_visual_event('reroll_required', details=result_data)
        return game_state, log, None, result_data, None
    else:
        player_mech.pending_combat = None

    game_state.check_game_over()
    return game_state, log, None, None, None


def handle_resolve_reroll(game_state, player_mech, data):
    """(玩家) 中断：处理专注重投"""
    log = []
    game_state.visual_events = []

    pending_combat_data = None
    rerolling_mech = None

    if player_mech and getattr(player_mech, 'pending_combat', None):
        pending_combat_data = player_mech.pending_combat
        rerolling_mech = player_mech
    else:
        for entity in game_state.entities.values():
            if isinstance(entity, Mech) and getattr(entity, 'pending_combat', None):
                pending_combat_data = entity.pending_combat
                rerolling_mech = entity
                break

    if not pending_combat_data:
        return game_state, log, None, None, "找不到待处理的重投数据！"

    try:
        combat_session = CombatState.from_dict(pending_combat_data, game_state,
                                               ace_reroll_callback=ace_logic.decide_reroll)
    except ValueError as e:
        log.append(f"> [严重错误] 恢复战斗状态失败: {e}")
        rerolling_mech.pending_combat = None
        return game_state, log, None, None, f"恢复战斗状态失败: {e}"

    for entity in game_state.entities.values():
        if isinstance(entity, Mech):
            entity.pending_combat = None

    rerolling_player = None
    if rerolling_mech and rerolling_mech.controller == 'player':
        rerolling_player = rerolling_mech
    else:
        rerolling_player = player_mech

    if not isinstance(rerolling_player, Mech):
        log.append("[系统警告] 找不到重投的玩家机甲，将无法消耗链接值。")

    reroll_selections_attacker = data.get('reroll_selections_attacker', [])
    reroll_selections_defender = data.get('reroll_selections_defender', [])

    log, result_packet = combat_session.submit_reroll(
        log, reroll_selections_attacker, reroll_selections_defender, rerolling_player
    )

    game_state = _apply_combat_packet(game_state, result_packet, log)

    result_data = None
    dice_roll_details = result_packet.get('dice_roll_details')

    if combat_session.stage == 'AWAITING_EFFECT_CHOICE':
        attacker_mech = game_state.get_entity_by_id(combat_session.attacker_entity.id)
        if isinstance(attacker_mech, Mech):
            attacker_mech.pending_combat = combat_session.to_dict()

        result_data = {
            'action_required': 'select_effect',
            'options': combat_session.available_effect_options,
            'dice_details': dice_roll_details,
            'attacker_name': combat_session.attacker_entity.name,
            'defender_name': combat_session.defender_entity.name,
            'action_name': combat_session.action.name
        }
        game_state.add_visual_event('effect_choice_required', details=result_data)

    elif combat_session.stage in ('AWAITING_ATTACK_REROLL', 'AWAITING_EFFECT_REROLL'):
        log.append("[系统警告] 重投后再次触发了重投！")
        rerolling_mech.pending_combat = combat_session.to_dict()
        result_data = {
            'action_required': 'select_reroll',
            'dice_details': dice_roll_details,
            'attacker_name': combat_session.attacker_entity.name,
            'defender_name': combat_session.defender_entity.name,
            'action_name': combat_session.action.name
        }
        game_state.add_visual_event('reroll_required', details=result_data)

    if combat_session.stage == 'RESOLVED':
        if dice_roll_details:
            game_state.add_visual_event(
                'dice_roll',
                attacker_name=combat_session.attacker_entity.name,
                defender_name=combat_session.defender_entity.name,
                action_name=combat_session.action.name,
                details=dice_roll_details
            )
        game_state.add_visual_event('attack_result', defender_pos=combat_session.defender_entity.pos,
                                    result_text=result_packet['status'])

    queued_attacks = pending_combat_data.get('remaining_attacks', [])
    game_ended_mid_turn = False

    if queued_attacks and combat_session.stage == 'RESOLVED':
        log.append(f"> [系统] 玩家重投已解决。正在恢复攻击队列... ({len(queued_attacks)} 个动作)")

        for i, attack_data in enumerate(queued_attacks):
            if game_ended_mid_turn:
                log.append(f"> [结算] 攻击被暂停，等待玩家重投。")
                continue

            game_state, log, result_data, game_ended_mid_turn = _resolve_queued_attack(
                game_state, log, attack_data, queued_attacks[i + 1:]
            )

            if game_ended_mid_turn:
                return game_state, log, None, result_data, None

    game_state.check_game_over()
    return game_state, log, None, result_data, None


# --- 回合结束 / AI 回合 ---

def handle_end_turn(game_state):
    """
    (系统) 结束玩家回合，开始 AI 回合，并结算所有 AI 攻击。
    """
    log = []
    player_mech = game_state.get_player_mech()

    if game_state.game_over:
        return game_state, log, None, None, "Game Over"

    if player_mech and getattr(player_mech, 'pending_combat', None):
        error = "> [错误] 必须先解决战斗中断才能结束回合！"
        log.append(error)
        return game_state, log, None, None, error

    game_state.visual_events = []
    log.append("-" * 20)
    log.append("> 玩家回合结束。")

    game_state.projectile_phase_active = True
    for entity in game_state.entities.values():
        if entity.entity_type == 'projectile':
            entity.has_acted = False

    entities_to_process = list(game_state.entities.values())
    game_ended_mid_turn = False
    result_data = {}

    # --- 阶段 1: AI 机甲阶段 ---
    log.append("--- AI 机甲阶段 ---")
    for entity in entities_to_process:
        if game_ended_mid_turn:
            break

        if entity.controller == 'ai' and entity.status == 'ok':

            if entity.entity_type == 'mech':

                if hasattr(entity, 'has_acted_early') and entity.has_acted_early:
                    log.append(f"> [系统] {entity.name} 已经在回合初行动过，跳过本阶段。")
                    entity.has_acted_early = False
                    continue

                if game_state.game_mode == 'range':
                    log.append("> [靶场模式] AI 跳过回合。")
                    entity.last_pos = None
                else:
                    entity.last_pos = entity.pos

                    is_ace = entity.pilot and "Raven" in entity.pilot.name
                    if is_ace:
                        entity_log, attacks = ace_ai_system.run_ace_turn(entity, game_state)
                    else:
                        entity_log, attacks = run_ai_turn(entity, game_state)

                    log.extend(entity_log)

                    attack_queue = []
                    for attack in attacks:
                        attack_queue.append({
                            'attacker_id': attack['attacker'].id,
                            'defender_id': attack['defender'].id,
                            'action_dict': attack['action'].to_dict()
                        })

                    for i, attack_data in enumerate(attack_queue):
                        game_state, log, result_data, game_ended_mid_turn = _resolve_queued_attack(
                            game_state, log, attack_data, attack_queue[i + 1:]
                        )
                        if game_ended_mid_turn:
                            break

            elif entity.entity_type == 'drone':
                entity_log, attacks = run_drone_logic(entity, game_state)
                log.extend(entity_log)

    if not game_ended_mid_turn:
        log.append("--- AI 机甲阶段结束 ---")

    result_data = result_data or {}
    result_data['run_projectile_phase'] = True

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
