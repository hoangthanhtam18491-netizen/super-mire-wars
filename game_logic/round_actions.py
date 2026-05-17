"""
9 阶段回合系统的核心引擎。
包含 _reset_round() 和 handle_advance_round()。
"""

import logging
from .config import PHASE_ORDER, DEFAULT_PLAYER_AP, DEFAULT_PLAYER_TP
from .data_models import Mech
from .ai_system import run_ai_turn
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
            entity.actions_used_this_turn = []

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
            logger.info("[ADVANCE] phase [%s] skip (reserved)", phase)
            game_state.phase_index += 1
            continue

        # === [自动] ===
        elif phase == '自动':
            logger.info("[ADVANCE] phase [%s] processing normal AI", phase)
            log.append(f"--- [{phase}] 阶段 ---")
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

            if not game_ended_mid_turn:
                logger.info("[ADVANCE] [自动] done, processed %d entities", entities_processed)
                log.append(f"--- [{phase}] 阶段结束 ---")
                game_state.phase_index += 1
            continue

        # === [延迟] ===
        elif phase == '延迟':
            logger.info("[ADVANCE] phase [%s] processing projectiles", phase)
            log.append(f"--- [{phase}] 阶段 ---")

            game_state, proj_logs, rd, _ = handle_run_projectile_phase(game_state, reset_round=False)
            log.extend(proj_logs)
            if rd:
                result_data.update(rd)

            if player_mech and getattr(player_mech, 'pending_combat', None):
                logger.info("[ADVANCE] [延迟] player interrupt detected, breaking")
                game_ended_mid_turn = True
                break

            if not game_ended_mid_turn:
                logger.info("[ADVANCE] [延迟] done")
                log.append(f"--- [{phase}] 阶段结束 ---")
                game_state.phase_index += 1
            continue

        # === 战斗阶段 ===
        else:
            logger.info("[ADVANCE] phase [%s] combat phase", phase)
            log.append(f"--- [{phase}] 阶段 ---")

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
                log.append(f"--- [{phase}] 阶段结束 ---")
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
                log.append(f"--- [{phase}] 阶段结束 ---")
                game_state.phase_index += 1
                continue

    # === 所有阶段处理完毕 ===
    if game_state.phase_index >= len(PHASE_ORDER) and not game_ended_mid_turn:
        logger.info("[ADVANCE] all phases done, resetting round")
        _reset_round(game_state)
        log.append("-" * 20)
        log.append("> 请开始你的回合。")
        result_data['round_complete'] = True

    logger.info("[ADVANCE] returning: round_complete=%s, player_turn=%s, action_required=%s, error=%s",
                result_data.get('round_complete'), result_data.get('player_turn'),
                result_data.get('action_required'), None)
    return game_state, log, None, result_data, None
