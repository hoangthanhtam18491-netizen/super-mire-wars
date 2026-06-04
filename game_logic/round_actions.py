"""
9 阶段回合系统的核心引擎。
包含 _reset_round() 和 handle_advance_round()。
"""

import logging
from .config import PHASE_ORDER, DEFAULT_PLAYER_AP, DEFAULT_PLAYER_TP, log_action, log_phase, log_combat, log_system, log_err, log_drone
from .data_models import Mech
from .ai_system import run_ai_turn
from .game_logic import run_drone_logic
from .game_controller import _execute_drone_auto_move
from . import ace_ai_system

logger = logging.getLogger(__name__)


def _reset_round(game_state):
    """重置所有回合级状态，为新回合做准备。"""
    game_state.round_number += 1
    game_state.phase_index = 0
    game_state.round_phase = None
    game_state.projectile_phase_active = False

    player_mech = game_state.get_player_mech()
    if player_mech:
        if player_mech.stance == 'downed':
            player_mech.player_ap = 1
            player_mech.player_tp = 0
            player_mech.stance = 'defense'
        else:
            player_mech.player_ap = DEFAULT_PLAYER_AP
            player_mech.player_tp = DEFAULT_PLAYER_TP
        player_mech.turn_phase = 'timing'
        player_mech.timing = None
        player_mech.opening_move_taken = False
        player_mech.actions_used_this_turn = []
        player_mech.pending_combat = None
        player_mech.has_acted_this_round = False
        player_mech.has_acted_early = False

    for entity in game_state.entities.values():
        if entity.controller == 'ai' and entity.entity_type == 'mech':
            entity.timing = None
            entity.has_acted_this_round = False
            entity.has_acted_early = False
            entity.won_clash = False
            entity.actions_used_this_turn = []

    # 重置拦截跟踪
    if hasattr(game_state, '_intercepted_pairs'):
        game_state._intercepted_pairs = set()

    # 重置无人机状态
    for entity in game_state.entities.values():
        if entity.entity_type == 'drone':
            entity.has_acted = False
            entity.command_marker_received = False

    # 重置指令标记（每回合重新计算）
    player_mech = game_state.get_player_mech()
    game_state.command_markers_available = 1 if player_mech and player_mech.status != 'destroyed' else 0
    ai_mechs = [e for e in game_state.entities.values()
                if e.controller == 'ai' and e.entity_type == 'mech' and e.status != 'destroyed']
    game_state.command_markers_assigned = {}

    game_state.check_game_over()
    logger.info("[ROUND] _reset_round: round=%d, phase_index=%d, player_turn_phase=%s",
                game_state.round_number, game_state.phase_index,
                player_mech.turn_phase if player_mech else 'N/A')


def handle_advance_round(game_state):
    """核心阶段推进引擎。"""
    # 延迟导入以避免循环依赖
    from .ai_actions import _resolve_queued_attack  # noqa: F811
    from .projectile_actions import handle_run_projectile_phase  # noqa: F811

    log = []
    result_data = {}
    game_ended_mid_turn = False

    player_mech = game_state.get_player_mech()
    logger.info("[ADVANCE] start: round=%d, phase_index=%d, phase=%s, player_timing=%s, player_has_acted=%s",
                game_state.round_number, game_state.phase_index, game_state.round_phase,
                player_mech.timing if player_mech else 'N/A',
                player_mech.has_acted_this_round if player_mech else 'N/A')

    if game_state.game_over:
        logger.info("[ADVANCE] game_over=%s, aborting", game_state.game_over)
        return game_state, log, None, result_data, "Game Over"

    if player_mech and getattr(player_mech, 'pending_combat', None):
        logger.info("[ADVANCE] player has pending_combat, aborting")
        return game_state, log, None, result_data, "必须先解决战斗中断！"

    game_state.visual_events = []
    game_state.projectile_phase_active = True

    while game_state.phase_index < len(PHASE_ORDER):
        if game_ended_mid_turn:
            logger.info("[ADVANCE] mid-turn break at phase_index=%d", game_state.phase_index)
            break

        phase = PHASE_ORDER[game_state.phase_index]
        game_state.round_phase = phase

        # === [指令] ===
        if phase == '指令':
            logger.info("[ADVANCE] phase [指令] processing drone commands")
            log.append(log_phase(f"[指令] 阶段"))

            # 指令标记在 _reset_round 中已初始化，此处不重置
            ai_mechs = [e for e in game_state.entities.values()
                        if e.controller == 'ai' and e.entity_type == 'mech' and e.status != 'destroyed']
            ai_command_markers = len(ai_mechs)

            # AI 自动分配指令标记给其无人机
            if ai_command_markers > 0:
                ai_drones = [e for e in game_state.entities.values()
                             if e.controller == 'ai' and e.entity_type == 'drone' and e.status == 'ok'
                             and not e.command_marker_received]
                for i, drone in enumerate(ai_drones[:ai_command_markers]):
                    drone.command_marker_received = True
                    game_state.command_markers_assigned[drone.id] = True
                    cmd_action, cmd_slot = drone.get_action_by_timing('指令')
                    if cmd_action:
                        closest_enemy = None
                        min_dist = 999
                        for entity in game_state.entities.values():
                            if entity.controller != drone.controller and entity.status != 'destroyed':
                                dist = abs(drone.pos[0] - entity.pos[0]) + abs(drone.pos[1] - entity.pos[1])
                                if dist < min_dist:
                                    min_dist = dist
                                    closest_enemy = entity
                        if cmd_action.dice and closest_enemy and min_dist <= cmd_action.range_val:
                            # 指令攻击动作
                            log.append(log_drone(f"{drone.name} 执行 [{cmd_action.name}]，最近敌 {closest_enemy.name}"))
                            atk_q = [{'attacker_id': drone.id, 'defender_id': closest_enemy.id,
                                      'action_dict': cmd_action.to_dict()}]
                            game_state, log, rd, game_ended_mid_turn = _resolve_queued_attack(
                                game_state, log, atk_q[0], atk_q[1:])
                            if rd:
                                result_data.update(rd)
                            if game_ended_mid_turn:
                                break
                        else:
                            # 指令移动——朝最近敌移动
                            _execute_drone_auto_move(drone, game_state, closest_enemy, log)
                    else:
                        log.append(log_drone(f"{drone.name} 获得标记但无指令动作。"))

            # 玩家无人机：暂停阶段等待玩家选择
            if game_state.command_markers_available > 0 and not game_ended_mid_turn:
                player_drones = [e for e in game_state.entities.values()
                                 if e.controller == 'player' and e.entity_type == 'drone' and e.status == 'ok'
                                 and not e.command_marker_received]
                if player_drones:
                    result_data['drone_command_phase'] = True
                    result_data['command_markers_available'] = game_state.command_markers_available
                    result_data['available_drones'] = [
                        {'id': d.id, 'name': d.name, 'pos': d.pos, 'move_range': d.move_range,
                         'actions': [{'name': a.name, 'type': a.action_type, 'range': a.range_val}
                                     for a, s in d.get_all_actions() if a.action_type == '指令']}
                        for d in player_drones
                    ]
                    game_state.projectile_phase_active = False
                    game_ended_mid_turn = True
                    break

            if not game_ended_mid_turn:
                log.append(log_phase(f"[指令] 阶段结束"))
                game_state.phase_index += 1
            continue

        # === [自动] ===
        elif phase == '自动':
            logger.info("[ADVANCE] phase [%s] processing normal AI", phase)
            log.append(log_phase(f"[{phase}] 阶段"))
            entities_processed = 0
            for entity in list(game_state.entities.values()):
                if game_ended_mid_turn:
                    break
                if entity.controller != 'ai' or entity.entity_type != 'mech' or entity.status != 'ok':
                    continue
                if entity.pilot and "Raven" in entity.pilot.name:
                    continue
                if entity.has_acted_this_round:
                    continue
                if game_state.game_mode == 'range':
                    entity.last_pos = None
                    continue

                logger.info("[ADVANCE] [自动] AI entity %s acting, has_acted=%s, stance=%s",
                            entity.id, entity.has_acted_this_round, entity.stance)
                entity.has_acted_this_round = True
                entity.last_pos = entity.pos
                entity_log, attacks = run_ai_turn(entity, game_state)
                log.extend(entity_log)
                entities_processed += 1

                attack_queue = [{
                    'attacker_id': a['attacker'].id,
                    'defender_id': a['defender'].id,
                    'action_dict': a['action'].to_dict()
                } for a in attacks]

                logger.info("[ADVANCE] [自动] AI %s generated %d attacks", entity.id, len(attack_queue))
                for i, atk in enumerate(attack_queue):
                    game_state, log, rd, game_ended_mid_turn = _resolve_queued_attack(
                        game_state, log, atk, attack_queue[i + 1:])
                    if rd:
                        result_data.update(rd)
                    if game_ended_mid_turn:
                        logger.info("[ADVANCE] [自动] attack %d triggered interrupt, breaking", i)
                        break

            # --- 无人机自动阶段（所有阵营） ---
            if not game_ended_mid_turn:
                drone_acted = False
                for entity in list(game_state.entities.values()):
                    if game_ended_mid_turn:
                        break
                    if entity.entity_type != 'drone' or entity.status != 'ok':
                        continue
                    if entity.has_acted:
                        continue

                    entity.last_pos = entity.pos
                    entity_log, attacks = run_drone_logic(entity, game_state)
                    log.extend(entity_log)
                    drone_acted = True

                    attack_queue = [{
                        'attacker_id': a['attacker'].id,
                        'defender_id': a['defender'].id,
                        'action_dict': a['action'].to_dict()
                    } for a in attacks]

                    for i, atk in enumerate(attack_queue):
                        game_state, log, rd, game_ended_mid_turn = _resolve_queued_attack(
                            game_state, log, atk, attack_queue[i + 1:])
                        if rd:
                            result_data.update(rd)
                        if game_ended_mid_turn:
                            logger.info("[ADVANCE] [自动] drone attack triggered interrupt, breaking")
                            break

                if drone_acted and not game_ended_mid_turn:
                    log.append(log_action("[无人机] 自动阶段完成。"))

            if not game_ended_mid_turn:
                logger.info("[ADVANCE] [自动] done, processed %d entities", entities_processed)
                log.append(log_phase(f"[{phase}] 阶段结束"))
                game_state.phase_index += 1
            continue

        # === [延迟] ===
        elif phase == '延迟':
            logger.info("[ADVANCE] phase [%s] processing projectiles", phase)
            log.append(log_phase(f"[{phase}] 阶段"))

            # 保存自动阶段产生的视觉事件（handle_run_projectile_phase 会清空）
            saved_visual_events = list(game_state.visual_events) if game_state.visual_events else []
            game_state, proj_logs, rd, _ = handle_run_projectile_phase(game_state, reset_round=False)
            # 恢复之前保存的视觉事件
            if saved_visual_events:
                game_state.visual_events = saved_visual_events + game_state.visual_events
            log.extend(proj_logs)
            if rd:
                result_data.update(rd)

            if player_mech and getattr(player_mech, 'pending_combat', None):
                logger.info("[ADVANCE] [延迟] player interrupt detected, breaking")
                game_ended_mid_turn = True
                break

            if not game_ended_mid_turn:
                logger.info("[ADVANCE] [延迟] done")
                log.append(log_phase(f"[{phase}] 阶段结束"))
                game_state.phase_index += 1
            continue

        # === 战斗阶段 ===
        else:
            logger.info("[ADVANCE] phase [%s] combat phase", phase)
            log.append(log_phase(f"[{phase}] 阶段"))

            ace_mech = game_state.get_ai_mech()
            is_ace = ace_mech and ace_mech.pilot and "Raven" in ace_mech.pilot.name

            player_chose = (
                player_mech
                and player_mech.timing == phase
                and not player_mech.has_acted_this_round
            )
            ace_chose = (
                is_ace
                and ace_mech.timing == phase
                and not ace_mech.has_acted_this_round
            )

            logger.info("[ADVANCE] [%s] player_chose=%s (timing=%s, has_acted=%s), ace_chose=%s",
                        phase, player_chose,
                        player_mech.timing if player_mech else 'N/A',
                        player_mech.has_acted_this_round if player_mech else 'N/A',
                        ace_chose)

            # --- 相同时机拼刀：Ace 获胜则 Ace 先行动 ---
            if ace_chose and player_chose and getattr(ace_mech, 'won_clash', False):
                logger.info("[ADVANCE] [%s] Ace won clash, acting before player", phase)
                ace_mech.has_acted_this_round = True
                ace_mech.won_clash = False  # 清除标记
                ace_mech.last_pos = ace_mech.pos

                entity_log, attacks = ace_ai_system.run_ace_turn(ace_mech, game_state)
                log.extend(entity_log)

                attack_queue = [{
                    'attacker_id': a['attacker'].id,
                    'defender_id': a['defender'].id,
                    'action_dict': a['action'].to_dict()
                } for a in attacks]

                for i, atk in enumerate(attack_queue):
                    game_state, log, rd, game_ended_mid_turn = _resolve_queued_attack(
                        game_state, log, atk, attack_queue[i + 1:])
                    if rd:
                        result_data.update(rd)
                    if game_ended_mid_turn:
                        break

                if game_ended_mid_turn:
                    break
                # 不推进阶段——玩家将在重入时进入同一阶段
                continue

            # --- Ace 单独入场 ---
            if ace_chose and not player_chose:
                logger.info("[ADVANCE] [%s] Ace acting alone", phase)
                ace_mech.has_acted_this_round = True
                ace_mech.last_pos = ace_mech.pos

                entity_log, attacks = ace_ai_system.run_ace_turn(ace_mech, game_state)
                log.extend(entity_log)

                attack_queue = [{
                    'attacker_id': a['attacker'].id,
                    'defender_id': a['defender'].id,
                    'action_dict': a['action'].to_dict()
                } for a in attacks]

                for i, atk in enumerate(attack_queue):
                    game_state, log, rd, game_ended_mid_turn = _resolve_queued_attack(
                        game_state, log, atk, attack_queue[i + 1:])
                    if rd:
                        result_data.update(rd)
                    if game_ended_mid_turn:
                        break

                if game_ended_mid_turn:
                    break
                log.append(log_phase(f"[{phase}] 阶段结束"))
                game_state.phase_index += 1
                continue

            # --- 玩家入场 ---
            elif player_chose:
                logger.info("[ADVANCE] [%s] Player entering, setting turn_phase=stance", phase)
                player_mech.has_acted_this_round = True
                player_mech.turn_phase = 'stance'
                result_data['player_turn'] = True
                result_data['enter_phase'] = phase
                game_state.projectile_phase_active = False
                break

            # --- 都不在此阶段 ---
            else:
                logger.info("[ADVANCE] [%s] no one enters, skipping", phase)
                log.append(log_phase(f"[{phase}] 阶段结束"))
                game_state.phase_index += 1
                continue

    # === 所有阶段处理完毕 ===
    if game_state.phase_index >= len(PHASE_ORDER) and not game_ended_mid_turn:
        logger.info("[ADVANCE] all phases done, resetting round")
        # 保存视觉事件并清空（避免 refreshGameUI 时重复展示）
        if game_state.visual_events:
            result_data['visual_events'] = list(game_state.visual_events)
            game_state.visual_events = []
        _reset_round(game_state)
        log.append(log_phase("-" * 20))
        log.append(log_action("请开始你的回合。"))
        result_data['round_complete'] = True

    logger.info("[ADVANCE] returning: round_complete=%s, player_turn=%s, action_required=%s, error=%s",
                result_data.get('round_complete'), result_data.get('player_turn'),
                result_data.get('action_required'), None)
    return game_state, log, None, result_data, None
