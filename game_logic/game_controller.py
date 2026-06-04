"""
游戏控制器 — 业务调度中心。
实际的处理器实现已拆分到:
- player_actions.py  (玩家回合阶段 1-4)
- ai_actions.py      (AI 回合 + 中断解决)
- projectile_actions.py (抛射物延迟阶段)

本文件保留共享辅助函数并重新导出所有公共接口，
以保持向后兼容性。
"""

import random
from .data_models import Mech, Projectile, Action
from .combat_system import CombatState
from .dice_roller import roll_black_die
from .game_logic import is_back_attack, run_projectile_logic, GameState
from .config import log_action, log_err, log_warn, log_intercept, log_drone
from . import ace_logic


# === 共享辅助函数 ===

def _clear_transient_state(game_state):
    """清除所有用于单次动画的 'last_pos' 状态。"""
    for entity in game_state.entities.values():
        entity.last_pos = None
    return game_state


def _apply_combat_packet(game_state, packet, log):
    """将 CombatState 结果包应用到 game_state。"""
    if not packet:
        log.append(log_err("_apply_combat_packet 接收到一个空的 packet。"))
        return game_state

    for change in packet.get('part_changes', []):
        target_id = change.get('target_id')
        part_slot_or_name = change.get('part_slot')
        new_status = change.get('new_status')

        entity = game_state.get_entity_by_id(target_id)
        if entity and new_status:
            part = None
            if part_slot_or_name in entity.parts:
                part = entity.parts.get(part_slot_or_name)
            elif hasattr(entity, 'get_part_by_name'):
                part = entity.get_part_by_name(part_slot_or_name)

            if part:
                part.status = new_status
            else:
                log.append(log_err(f"找不到部件: {part_slot_or_name} (在 {target_id} 上)"))

    for change in packet.get('pilot_changes', []):
        target_id = change.get('target_id')
        link_loss = change.get('link_loss', 0)
        entity = game_state.get_entity_by_id(target_id)
        if entity and isinstance(entity, Mech) and entity.pilot and link_loss > 0:
            entity.pilot.link_points = max(0, entity.pilot.link_points - link_loss)

    for change in packet.get('entity_changes', []):
        target_id = change.get('target_id')
        entity = game_state.get_entity_by_id(target_id)
        if entity:
            if 'status' in change:
                entity.status = change['status']
            if 'stance' in change:
                entity.stance = change['stance']

    return game_state


def _execute_main_action(game_state, player_mech, action, action_name, part_slot):
    """验证并消耗一个主动作 (AP/TP/弹药/使用次数)。"""
    log = []
    action_id = (part_slot, action_name)

    if action_id in player_mech.actions_used_this_turn:
        error = f"[{action_name}] (来自: {part_slot}) 本回合已使用过。"
        log.append(log_err(error))
        return game_state, log, False, error

    ammo_key = (player_mech.id, part_slot, action.name)
    if action.ammo > 0:
        current_ammo = game_state.ammo_counts.get(ammo_key, 0)
        if current_ammo <= 0:
            error = f"弹药耗尽，无法执行 [{action.name}]。"
            log.append(log_err(error))
            return game_state, log, False, error

    ap_cost = action.cost.count('M') * 2 + action.cost.count('S') * 1
    tp_cost = 0
    if action.cost == 'L':
        ap_cost = 2
        tp_cost = 1

    if player_mech.player_ap < ap_cost:
        error = f"AP不足 (需要 {ap_cost})，无法执行 [{action.name}]。"
        log.append(log_err(error))
        return game_state, log, False, error

    if player_mech.player_tp < tp_cost:
        error = f"TP不足 (需要 {tp_cost})，无法执行 [{action.name}]。"
        log.append(log_err(error))
        return game_state, log, False, error

    if not player_mech.opening_move_taken:
        if action.action_type != player_mech.timing and action.action_type != '快速':
            error = f"起手动作错误！当前时机为 [{player_mech.timing}]，无法执行 [{action.action_type}] 动作。"
            log.append(log_err(error))
            return game_state, log, False, error
        player_mech.opening_move_taken = True

    player_mech.player_ap -= ap_cost
    player_mech.player_tp -= tp_cost
    player_mech.actions_used_this_turn.append((part_slot, action_name))

    if action.ammo > 0 and action.action_type != '抛射' and not action.effects.get("interceptor"):
        game_state.ammo_counts[ammo_key] -= 1
        log.append(log_action(f"[{action.name}] 消耗 1 弹药，剩余 {game_state.ammo_counts[ammo_key]}。"))

    return game_state, log, True, "Success"


def _run_interception_checks(projectile, game_state, log):
    """检查并执行对一个抛射物的所有拦截。"""
    if not projectile or projectile.status == 'destroyed':
        return game_state, log

    # 跟踪已拦截过的 (entity_id, projectile_id) 配对，防止多次调用时重复开火
    if not hasattr(game_state, '_intercepted_pairs'):
        game_state._intercepted_pairs = set()

    landing_pos = projectile.pos
    intercepting_entities = [
        e for e in game_state.entities.values()
        if e.controller != projectile.controller and e.entity_type in ('mech', 'drone') and e.status != 'destroyed'
    ]

    for entity in intercepting_entities:
        if projectile.status == 'destroyed':
            log.append(log_intercept(f"{projectile.name} 已被摧毁，{entity.name} 取消拦截。"))
            break

        interceptor_actions = entity.get_interceptor_actions()
        if not interceptor_actions:
            continue

        for intercept_action, part_slot in interceptor_actions:
            if projectile.status == 'destroyed':
                break

            intercept_range = intercept_action.range_val
            dist_to_landing = abs(entity.pos[0] - landing_pos[0]) + abs(entity.pos[1] - landing_pos[1])

            if dist_to_landing <= intercept_range:
                pair_key = (entity.id, projectile.id)
                if pair_key in game_state._intercepted_pairs:
                    continue  # 已拦截过此抛射物，跳过
                game_state._intercepted_pairs.add(pair_key)

                ammo_key = (entity.id, part_slot, intercept_action.name)
                current_ammo = game_state.ammo_counts.get(ammo_key, 0)
                has_unlimited_ammo = (intercept_action.ammo == 0)

                if current_ammo > 0 or has_unlimited_ammo:
                    log.append(
                        log_intercept(f"{entity.name} 的 [{intercept_action.name}] 侦测到 {projectile.name}！"))

                    shots_fired = 0
                    max_shots = 1 if has_unlimited_ammo else current_ammo
                    while (has_unlimited_ammo or current_ammo > 0) and projectile.status != 'destroyed' and shots_fired < max_shots:
                        shots_fired += 1
                        if not has_unlimited_ammo:
                            log.append(
                                log_intercept(f"{entity.name} 消耗 1 弹药 (剩余 {current_ammo - 1}) 尝试第 {shots_fired} 次拦截..."))
                            game_state.ammo_counts[ammo_key] -= 1
                            current_ammo -= 1
                        else:
                            log.append(
                                log_intercept(f"{entity.name} 尝试第 {shots_fired} 次拦截..."))

                        combat_session = CombatState(
                            attacker_entity=entity,
                            defender_entity=projectile,
                            action=intercept_action,
                            target_part_name='core',
                            is_back_attack=False,
                            is_interception_attack=True,
                            ace_reroll_callback=ace_logic.decide_reroll,
                            game_state=game_state,
                        )

                        log, result_packet = combat_session.resolve(log)
                        game_state = _apply_combat_packet(game_state, result_packet, log)

                    if shots_fired > 0 and projectile.status == 'destroyed':
                        log.append(log_intercept(f"{entity.name} 成功摧毁 {projectile.name}！"))

    return game_state, log


def _crush_drones_at_pos(game_state, mech, pos, log):
    """机甲移动到 pos 时碾压该格上的无人机：推开或摧毁。"""
    from .config import BOARD_WIDTH, BOARD_HEIGHT
    entities_at_dest = game_state.get_entities_at_pos(pos, exclude_id=mech.id)
    for e in entities_at_dest:
        if e.entity_type == 'drone' and e.status == 'ok':
            pushed = False
            for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
                adj = (e.pos[0] + dx, e.pos[1] + dy)
                if (1 <= adj[0] <= BOARD_WIDTH and 1 <= adj[1] <= BOARD_HEIGHT
                        and adj not in game_state.get_occupied_tiles()):
                    e.last_pos = e.pos
                    e.pos = adj
                    log.append(log_action(f"[碾压] {mech.name} 将 {e.name} 撞至 {adj}！"))
                    pushed = True
                    break
            if not pushed:
                e.status = 'destroyed'
                log.append(log_action(f"[碾压] {mech.name} 碾碎了 {e.name}（无可用相邻格子）！"))


def _execute_drone_auto_move(drone, game_state, closest_enemy, log):
    """指令阶段无人机自动朝最近敌人移动一步。"""
    if not closest_enemy:
        log.append(log_drone(f"[指令] {drone.name} 无可移动目标。"))
        return

    move_range = drone.move_range
    possible = game_state.calculate_move_range(drone, move_range, is_flight=True)
    mech_tiles = game_state.get_mech_occupied_tiles(exclude_id=drone.id)
    possible = [p for p in possible if p not in mech_tiles]
    best_pos = drone.pos
    best_d = abs(drone.pos[0] - closest_enemy.pos[0]) + abs(drone.pos[1] - closest_enemy.pos[1])
    for mp in possible:
        d = abs(mp[0] - closest_enemy.pos[0]) + abs(mp[1] - closest_enemy.pos[1])
        if d < best_d:
            best_d = d
            best_pos = mp
    if best_pos != drone.pos:
        drone.last_pos = drone.pos
        drone.pos = best_pos
        log.append(log_drone(f"[指令] {drone.name} 移动至 {drone.pos}（距敌{best_d}）"))
    else:
        log.append(log_drone(f"[指令] {drone.name} 无法靠近敌人。"))


# === 重新导出所有公共接口 (向后兼容) ===

from .player_actions import (
    handle_select_timing,
    handle_confirm_timing,
    handle_change_stance,
    handle_confirm_stance,
    handle_adjust_move,
    handle_change_orientation,
    handle_skip_adjustment,
    handle_move_player,
    handle_execute_attack,
    handle_jettison_part,
    handle_debug_skill,
    handle_charge_part,
)

from .ai_actions import (
    _resolve_queued_attack,
    handle_resolve_effect_choice,
    handle_resolve_reroll,
    handle_end_turn,
    handle_respawn_ai,
)

from .projectile_actions import (
    handle_run_projectile_phase,
)

from .round_actions import (
    handle_advance_round,
    _reset_round,
)
