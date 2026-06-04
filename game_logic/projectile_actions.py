"""
抛射物延迟阶段处理器。
从 game_controller.py 拆分，依赖 ai_actions 中的 _resolve_queued_attack。
"""

from .config import log_action, log_phase, log_system, log_intercept
from .data_models import Mech, Projectile
from .game_logic import run_projectile_logic
from .game_controller import _run_interception_checks
from .ai_actions import _resolve_queued_attack


def handle_run_projectile_phase(game_state, reset_round=True):
    """
    (系统) 运行所有抛射物的'延迟'逻辑并结算攻击。
    reset_round=False 时跳过回合复位（由 handle_advance_round 统一处理）。
    """
    log = []
    if game_state.game_over:
        return game_state, log, None, None, "Game Over"

    game_state.visual_events = []
    game_ended_mid_turn = False
    result_data = {}

    log.append(log_phase("延迟动作阶段 (抛射物)"))

    # 1. 初始化队列
    if not game_state.pending_projectile_queue:
        projectiles_to_act = []
        entities = list(game_state.entities.values())
        for entity in entities:
            if entity.entity_type == 'projectile' and entity.status == 'ok':
                if not getattr(entity, 'is_active', False):
                    entity.is_active = True

                if not getattr(entity, 'has_acted', False):
                    projectiles_to_act.append(entity)

        def sort_key(proj):
            if proj.controller == 'player':
                return 0
            elif proj.controller == 'ai':
                return 1
            else:
                return 2

        projectiles_to_act.sort(key=sort_key)
        game_state.pending_projectile_queue = [p.id for p in projectiles_to_act]

        if projectiles_to_act:
            log.append(log_system(f"{len(projectiles_to_act)} 个抛射物准备行动。"))

    # 2. 处理队列
    while game_state.pending_projectile_queue:
        if game_ended_mid_turn:
            break

        proj_id = game_state.pending_projectile_queue[0]
        entity = game_state.get_entity_by_id(proj_id)

        if not entity or entity.status != 'ok' or getattr(entity, 'has_acted', False):
            game_state.pending_projectile_queue.pop(0)
            continue

        # 移动前拦截
        game_state, log = _run_interception_checks(entity, game_state, log)
        if entity.status == 'destroyed':
            log.append(log_intercept(f"{entity.name} 在移动前被摧毁。"))
            game_state.pending_projectile_queue.pop(0)
            continue

        # 移动
        entity_log, attacks = run_projectile_logic(entity, game_state, '延迟')
        log.extend(entity_log)

        # 移动后拦截
        game_state, log = _run_interception_checks(entity, game_state, log)
        if entity.status == 'destroyed':
            log.append(log_intercept(f"{entity.name} 在移动后被摧毁。"))
            game_state.pending_projectile_queue.pop(0)
            continue

        entity.has_acted = True

        # 序列化攻击
        attack_queue = []
        for attack in attacks:
            attack_queue.append({
                'attacker_id': attack['attacker'].id,
                'defender_id': attack['defender'].id,
                'action_dict': attack['action'].to_dict()
            })

        game_state.pending_projectile_queue.pop(0)

        # 结算攻击
        for i, attack_data in enumerate(attack_queue):
            game_state, log, result_data, game_ended_mid_turn = _resolve_queued_attack(
                game_state, log, attack_data, attack_queue[i + 1:]
            )
            if game_ended_mid_turn:
                break

    # --- 回合结束，重置玩家状态（仅在独立调用时） ---
    if not game_state.pending_projectile_queue and not game_ended_mid_turn:
        game_state.projectile_phase_active = False

        if reset_round:
            player_mech = game_state.get_player_mech()
            if not game_state.game_over and not (player_mech and player_mech.pending_combat):
                log.append(
                    "> AI回合结束。请开始你的回合。" if game_state.game_mode != 'range' else "> [靶场模式] 请开始你的回合。")
                log.append(log_phase("-" * 20))

                if player_mech:
                    if player_mech.stance == 'downed':
                        log.append(log_system("驾驶员链接恢复。机甲 [宕机姿态] 解除。"))
                        log.append(log_warn("系统冲击！本回合 AP-1, TP-1！"))
                        player_mech.player_ap = 1
                        player_mech.player_tp = 0
                        player_mech.stance = 'defense'
                    else:
                        player_mech.player_ap = 2
                        player_mech.player_tp = 1

                    player_mech.turn_phase = 'timing'
                    player_mech.timing = None
                    player_mech.opening_move_taken = False
                    player_mech.actions_used_this_turn = []
                    player_mech.pending_combat = None

                game_state.check_game_over()
            elif player_mech and player_mech.pending_combat:
                log.append(log_system("玩家有待处理的中断，跳过回合重置。"))

    return game_state, log, result_data, None
