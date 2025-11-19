import random
# 基础数据模型
from .data_models import Mech, Projectile, Action
# [阶段2重构] 导入新的 CombatState 状态机
from .combat_system import CombatState
from .dice_roller import roll_black_die
# 核心游戏规则
from .game_logic import is_back_attack, run_projectile_logic, GameState, run_drone_logic
# AI 逻辑
from .ai_system import run_ai_turn
# [NEW] 导入 Ace 逻辑
from . import ace_logic
# [NEW] 导入新的 Ace AI 系统
from . import ace_ai_system


# --- 辅助函数 ---

def _clear_transient_state(game_state):
    """(辅助函数) 清除所有用于单次动画的 'last_pos' 状态。"""
    for entity in game_state.entities.values():
        entity.last_pos = None
    return game_state


def _apply_combat_packet(game_state, packet, log):
    """
    将 "结果包" (Result Packet) 应用到 game_state。
    这是修改游戏状态的唯一途径之一。
    """
    if not packet:
        log.append("[系统错误] _apply_combat_packet 接收到一个空的 packet。")
        return game_state

    # 1. 应用部件变更
    for change in packet.get('part_changes', []):
        target_id = change.get('target_id')
        part_slot_or_name = change.get('part_slot')
        new_status = change.get('new_status')

        entity = game_state.get_entity_by_id(target_id)
        if entity and new_status:
            part = None
            if part_slot_or_name in entity.parts:
                part = entity.parts.get(part_slot_or_name)
            else:
                # [健壮性] 确保 get_part_by_name 存在
                if hasattr(entity, 'get_part_by_name'):
                    part = entity.get_part_by_name(part_slot_or_name)

            if part:
                part.status = new_status
            else:
                log.append(f"[系统错误] 找不到部件: {part_slot_or_name} (在 {target_id} 上)")

    # 2. 应用驾驶员变更 (例如：震撼导致的链接值损失)
    for change in packet.get('pilot_changes', []):
        target_id = change.get('target_id')
        link_loss = change.get('link_loss', 0)

        entity = game_state.get_entity_by_id(target_id)
        if entity and isinstance(entity, Mech) and entity.pilot and link_loss > 0:
            # [重要] 这里的 -= 1 是幂等的，CombatState 已经计算过
            # 我们只应用 CombatState 告诉我们的变更
            entity.pilot.link_points = max(0, entity.pilot.link_points - link_loss)

    # 3. 应用实体变更 (例如：宕机或摧毁)
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


# --- [新] 拦截辅助函数 ---

def _run_interception_checks(projectile, game_state, log):
    """
    [阶段2重构]
    检查并执行对一个抛射物的所有拦截。
    此函数现在位于 game_controller 中，并使用 CombatState。
    它会直接修改 game_state。
    返回: (game_state, log)
    """
    if not projectile or projectile.status == 'destroyed':
        return game_state, log

    landing_pos = projectile.pos
    intercepting_entities = [
        e for e in game_state.entities.values()
        if e.controller != projectile.controller and e.entity_type == 'mech' and e.status != 'destroyed'
    ]

    for entity in intercepting_entities:
        if projectile.status == 'destroyed':
            log.append(f"> [拦截] {projectile.name} 已被摧毁，{entity.name} 取消拦截。")
            break

        interceptor_actions = entity.get_interceptor_actions()
        if not interceptor_actions:
            continue

        for intercept_action, part_slot in interceptor_actions:
            if projectile.status == 'destroyed':
                break  # 已被此机甲的其他武器摧毁

            intercept_range = intercept_action.range_val
            dist_to_landing = abs(entity.pos[0] - landing_pos[0]) + abs(entity.pos[1] - landing_pos[1])

            if dist_to_landing <= intercept_range:
                ammo_key = (entity.id, part_slot, intercept_action.name)
                current_ammo = game_state.ammo_counts.get(ammo_key, 0)

                if current_ammo > 0:
                    log.append(
                        f"> [拦截] {entity.name} 的 [{intercept_action.name}] 侦测到 {projectile.name}！")

                    shots_fired = 0
                    while current_ammo > 0 and projectile.status != 'destroyed':
                        shots_fired += 1
                        log.append(
                            f"> [拦截] {entity.name} 消耗 1 弹药 (剩余 {current_ammo - 1}) 尝试第 {shots_fired} 次拦截...")

                        game_state.ammo_counts[ammo_key] -= 1
                        current_ammo -= 1

                        # [阶段2重构] 使用 CombatState 结算拦截
                        combat_session = CombatState(
                            attacker_entity=entity,
                            defender_entity=projectile,
                            action=intercept_action,
                            target_part_name='core',  # 抛射物只有一个 'core'
                            is_back_attack=False,
                            is_interception_attack=True  # 标记为拦截，跳过重投
                        )

                        log, result_packet = combat_session.resolve(log)
                        game_state = _apply_combat_packet(game_state, result_packet, log)

                        # 拦截不需要视觉事件，因为它们是即时的

                    if shots_fired > 0 and projectile.status == 'destroyed':
                        log.append(f"> [拦截] {entity.name} 成功摧毁 {projectile.name}！")

    return game_state, log


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
    """(玩家) 阶段 1：确认时机
    [NEW] Ace AI 抢先手逻辑已移动至此。
    """
    log = []
    result_data = {}

    if player_mech.turn_phase == 'timing' and player_mech.timing and not game_state.game_over:

        # [Ace Logic] 检查是否触发抢先手
        ai_mech = game_state.get_ai_mech()
        # 模糊匹配以兼容 "【Raven】"
        if ai_mech and ai_mech.pilot and "Raven" in ai_mech.pilot.name:
            log.append("--- [⚠️ WARNING] 遭遇王牌机师！ ---")

            # 1. Ace 决定时机
            ai_timing = ace_logic.decide_ace_timing(ai_mech, player_mech, game_state)

            # 2. 拼点
            winner, reason = ace_logic.check_initiative(player_mech.timing, ai_timing, player_mech.pilot, ai_mech.pilot)
            log.append(f"> [拼刀] 玩家选择 [{player_mech.timing}] vs AI选择 [{ai_timing}]")
            log.append(f"> [结果] {reason}")

            clash_event_data = {
                'player_timing': player_mech.timing,
                'ai_timing': ai_timing,
                'winner': winner,
                'reason': reason
            }

            # 告知前端发生了拼点 (用于触发 reload)
            result_data['clash_occurred'] = True

            if winner == 'ai':
                log.append("> [严重警告] 你的先手时机被 Ace 夺取！AI 将立即行动！")

                # 3. 执行 AI 回合 (作为中断)
                # 标记为已行动，这样 End Turn 时会跳过
                ai_mech.has_acted_early = True

                # [NEW] 调用 Ace AI 系统
                ai_mech.last_pos = ai_mech.pos
                entity_log, attacks = ace_ai_system.run_ace_turn(ai_mech, game_state)
                log.extend(entity_log)

                # 立即结算所有攻击
                attack_queue = []
                for attack in attacks:
                    attack_queue.append({
                        'attacker_id': attack['attacker'].id,
                        'defender_id': attack['defender'].id,
                        'action_dict': attack['action'].to_dict()
                    })

                # 循环结算
                game_ended_mid_turn = False
                for i, attack_data in enumerate(attack_queue):
                    game_state, log, rd, game_ended_mid_turn = _resolve_queued_attack(
                        game_state, log, attack_data, attack_queue[i + 1:]
                    )
                    if rd:  # 如果有重投中断
                        result_data.update(rd)  # 传递给前端
                    if game_ended_mid_turn:
                        break

                # 添加特殊的视觉事件
                game_state.add_visual_event('clash_result', details=clash_event_data)

            else:
                log.append("> [系统] 你赢得了先手！继续回合。")
                game_state.add_visual_event('clash_result', details=clash_event_data)

        # 正常推进阶段
        player_mech.turn_phase = 'stance'
        game_state = _clear_transient_state(game_state)

        # 注意：如果 AI 抢先手并杀死了玩家，check_game_over 会在 _resolve_queued_attack 中处理

        log.append(f"> 时机已确认为 [{player_mech.timing}]。进入姿态选择阶段。")

        # [FIX] 返回值位置修正：result_data 必须在第4个位置
        # 签名: game_state, log, unused, result_data, error
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

        # 抛射物队列
        projectile_queue = []
        for _ in range(projectiles_to_launch):
            projectile_queue.append(target_pos)

        while projectile_queue:
            # 如果战斗被中断，立即停止处理队列
            # [健壮性修复] 使用 getattr
            if getattr(player_mech, 'pending_combat', None):
                log.append(f"> [结算] 战斗被暂停，剩余 {len(projectile_queue)} 枚抛射物在队列中。")
                # [健壮性] 将剩余队列存入 pending_combat
                player_mech.pending_combat['projectile_queue'] = projectile_queue
                log.append(f"> [系统] 剩余齐射已保存。")
                break

            current_target_pos = projectile_queue.pop(0)

            projectile_id, projectile_obj = game_state.spawn_projectile(
                launcher_entity=player_mech,
                target_pos=current_target_pos,
                projectile_key=attack_action.projectile_to_spawn
            )
            if not projectile_obj:
                log.append(f"> [错误] 生成抛射物 {attack_action.projectile_to_spawn} 失败！")
                continue

            has_immediate_action = projectile_obj.get_action_by_timing('立即')[0] is not None
            if not has_immediate_action:
                # [重构] 调用新的拦截函数
                game_state, log = _run_interception_checks(projectile_obj, game_state, log)

            entity_log, attacks = run_projectile_logic(projectile_obj, game_state, '立即')
            log.extend(entity_log)

            # 结算所有 '立即' 攻击
            for attack in attacks:
                # [健壮性修复] 使用 getattr
                if getattr(player_mech, 'pending_combat', None):  # 再次检查
                    log.append(f"> [结算] 战斗被暂停，跳过 {attack.get('action').name} 结算。")
                    continue

                if not isinstance(attack, dict): continue
                attacker = attack.get('attacker')
                defender = attack.get('defender')
                action = attack.get('action')
                if not attacker or not defender or not action: continue
                if attacker.status == 'destroyed' or defender.status == 'destroyed':
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

                # [阶段2重构] 使用 CombatState
                combat_session = CombatState(
                    attacker_entity=attacker,
                    defender_entity=defender,
                    action=action,
                    target_part_name=target_part_slot,
                    is_back_attack=False
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
                    # 中断发生！
                    player_mech.pending_combat = combat_session.to_dict()
                    result_data = {
                        'action_required': 'select_reroll' if combat_session.stage == 'AWAITING_ATTACK_REROLL' else 'select_effect',
                        'dice_details': dice_roll_details,
                        'attacker_name': attacker.name,
                        'defender_name': defender.name,
                        'action_name': action.name
                    }
                    if combat_session.stage == 'AWAITING_EFFECT_CHOICE':
                        result_data['options'] = combat_session.available_effect_options

                    game_state.add_visual_event(result_data['action_required'], details=result_data)
                    return game_state, log, None, result_data, None  # 立即返回

        return game_state, log, None, None, None  # 齐射正常完成

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

        # 2. [阶段2重构] 结算攻击
        combat_session = CombatState(
            attacker_entity=player_mech,
            defender_entity=defender_entity,
            action=attack_action,
            target_part_name=target_part_slot,
            is_back_attack=back_attack
        )
        log, result_packet = combat_session.resolve(log)

        # 3. 应用攻击
        game_state = _apply_combat_packet(game_state, result_packet, log)

        # 4. 添加视觉事件
        dice_roll_details = result_packet.get('dice_roll_details')
        if dice_roll_details:
            game_state.add_visual_event(
                'dice_roll', attacker_name=player_mech.name, defender_name=defender_entity.name,
                action_name=attack_action.name, details=dice_roll_details
            )
        game_state.add_visual_event('attack_result', defender_pos=defender_entity.pos,
                                    result_text=result_packet['status'])

        # 5. [阶段2重构] 处理中断
        if combat_session.stage != 'RESOLVED':
            player_mech.pending_combat = combat_session.to_dict()
            result_data = {
                'action_required': 'select_reroll' if combat_session.stage == 'AWAITING_ATTACK_REROLL' else 'select_effect',
                'dice_details': dice_roll_details,
                'attacker_name': player_mech.name,
                'defender_name': defender_entity.name,
                'action_name': attack_action.name
            }
            if combat_session.stage == 'AWAITING_EFFECT_CHOICE':
                result_data['options'] = combat_session.available_effect_options

            game_state.add_visual_event(result_data['action_required'], details=result_data)
            return game_state, log, None, result_data, None

        # 6. 检查游戏是否结束 (在应用包之后)
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

    return game_state, log, None, None, "无效的动作类型"


def handle_jettison_part(game_state, player_mech, part_slot):
    """(玩家) 阶段 4：执行[弃置]动作"""
    from game_logic.database import ALL_PARTS
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

    # [健壮性修复] 使用 getattr
    pending_combat_data = getattr(player_mech, 'pending_combat', None)
    if not pending_combat_data:
        error = "找不到待处理的战斗数据！"
        log.append(f"> [错误] {error}")
        return game_state, log, None, None, error

    # [阶段2重构] 恢复战斗状态
    try:
        combat_session = CombatState.from_dict(pending_combat_data, game_state)
    except ValueError as e:
        log.append(f"> [严重错误] 恢复战斗状态失败: {e}")
        player_mech.pending_combat = None  # 清除损坏的数据
        return game_state, log, None, None, f"恢复战斗状态失败: {e}"

    if combat_session.stage != 'AWAITING_EFFECT_CHOICE':
        error = f"战斗状态不匹配 (预期: AWAITING_EFFECT_CHOICE, 得到: {combat_session.stage})"
        log.append(f"> [错误] {error}")
        player_mech.pending_combat = None  # 清除
        return game_state, log, None, None, error

    # 提交选择并推进状态机
    log, result_packet = combat_session.submit_effect_choice(log, choice)

    # 应用结果
    game_state = _apply_combat_packet(game_state, result_packet, log)

    # 添加视觉事件
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

    # 检查是否又触发了重投 (效果的重投)
    if combat_session.stage == 'AWAITING_EFFECT_REROLL':
        player_mech.pending_combat = combat_session.to_dict()
        result_data = {
            'action_required': 'select_reroll',
            'dice_details': dice_roll_details.get('secondary_roll'),  # 只显示次要掷骰
            'attacker_name': combat_session.attacker_entity.name,
            'defender_name': combat_session.defender_entity.name,
            'action_name': choice.capitalize()
        }
        game_state.add_visual_event('reroll_required', details=result_data)
        return game_state, log, None, result_data, None
    else:
        # 战斗已解决
        player_mech.pending_combat = None

    # 检查游戏是否结束
    game_state.check_game_over()
    # (注意：horde 模式的 AI 重生逻辑在 check_game_over 内部)

    return game_state, log, None, None, None


def handle_resolve_reroll(game_state, player_mech, data):
    """(玩家) 中断：处理专注重投"""
    log = []
    game_state.visual_events = []

    # 1. 查找待处理数据 (可能在玩家身上，也可能在AI身上)
    pending_combat_data = None
    rerolling_mech = None  # 哪台机甲存储了状态

    # [健壮性修复] 使用 getattr
    if player_mech and getattr(player_mech, 'pending_combat', None):
        pending_combat_data = player_mech.pending_combat
        rerolling_mech = player_mech
    else:
        # 检查所有实体
        for entity in game_state.entities.values():
            # [健壮性修复] 使用 getattr
            if isinstance(entity, Mech) and getattr(entity, 'pending_combat', None):
                pending_combat_data = entity.pending_combat
                rerolling_mech = entity
                break

    if not pending_combat_data:
        return game_state, log, None, None, "找不到待处理的重投数据！"

    # 2. [阶段2重构] 恢复战斗状态
    try:
        combat_session = CombatState.from_dict(pending_combat_data, game_state)
    except ValueError as e:
        log.append(f"> [严重错误] 恢复战斗状态失败: {e}")
        rerolling_mech.pending_combat = None  # 清除损坏的数据
        return game_state, log, None, None, f"恢复战斗状态失败: {e}"

    # 3. [关键] 清除所有实体上的中断标志
    for entity in game_state.entities.values():
        if isinstance(entity, Mech):
            entity.pending_combat = None

    # 4. 确定谁在执行重投
    rerolling_player = None
    if rerolling_mech and rerolling_mech.controller == 'player':
        rerolling_player = rerolling_mech
    else:
        # AI 攻击了玩家，玩家 (player_mech) 在重投
        rerolling_player = player_mech

    if not isinstance(rerolling_player, Mech):
        log.append("[系统警告] 找不到重投的玩家机甲，将无法消耗链接值。")

    # 5. 提交重投
    reroll_selections_attacker = data.get('reroll_selections_attacker', [])
    reroll_selections_defender = data.get('reroll_selections_defender', [])

    log, result_packet = combat_session.submit_reroll(
        log, reroll_selections_attacker, reroll_selections_defender, rerolling_player
    )

    # 6. 应用结果
    game_state = _apply_combat_packet(game_state, result_packet, log)

    result_data = None
    dice_roll_details = result_packet.get('dice_roll_details')

    # 7. 检查是否又触发了中断 (例如：重投 -> 效果选择)
    if combat_session.stage == 'AWAITING_EFFECT_CHOICE':
        # 效果选择总是由攻击方触发
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

    elif combat_session.stage == 'AWAITING_ATTACK_REROLL' or combat_session.stage == 'AWAITING_EFFECT_REROLL':
        # 这不应该发生（重投又触发了重投），但作为安全措施
        log.append("[系统警告] 重投后再次触发了重投！")
        rerolling_mech.pending_combat = combat_session.to_dict()
        # 准备数据以便前端可以再次显示重投
        result_data = {
            'action_required': 'select_reroll',
            'dice_details': dice_roll_details,
            'attacker_name': combat_session.attacker_entity.name,
            'defender_name': combat_session.defender_entity.name,
            'action_name': combat_session.action.name
        }
        game_state.add_visual_event('reroll_required', details=result_data)

    # 8. 添加最终的视觉事件 (仅当战斗已解决时)
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

    # 9. [健壮性] 检查是否有待处理的攻击队列 (例如 AI 齐射被玩家重投中断)
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
                # 中断 (重投或游戏结束) 发生
                return game_state, log, None, result_data, None

    # 10. 检查游戏是否结束
    game_state.check_game_over()

    return game_state, log, None, result_data, None


# --- AI 攻击结算辅助函数 ---
def _resolve_queued_attack(game_state, log, attack_data, remaining_attacks_queue):
    """
    (辅助函数) 结算一次 AI 攻击 (或抛射物攻击)。
    这是 handle_end_turn 和 handle_resolve_reroll 共享的逻辑。
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
        return game_state, log, result_data, game_ended_mid_turn  # 攻击跳过

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

    # [阶段2重构] 结算攻击
    combat_session = CombatState(
        attacker_entity=attacker_entity,
        defender_entity=defender_entity,
        action=attack_action,
        target_part_name=target_part_slot,
        is_back_attack=back_attack
    )
    log, result_packet = combat_session.resolve(log)

    # 应用攻击
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

    # [阶段2重构] 处理中断：重投
    if combat_session.stage != 'RESOLVED':
        if isinstance(defender_entity, Mech):  # 玩家机甲
            # 序列化剩余的攻击
            remaining_attacks_serializable = []
            for atk in remaining_attacks_queue:
                # [健壮性] 确保 atk 是字典
                if isinstance(atk, dict):
                    remaining_attacks_serializable.append(atk)
                # (如果它不是字典，我们跳过它，防止崩溃)

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

    # 检查游戏是否结束
    game_is_over = game_state.check_game_over()
    if game_is_over and game_state.game_over == 'ai_win':
        log.append(f"> 玩家机甲已被摧毁！")
        if game_state.game_mode == 'horde':
            log.append(f"> [生存模式] 最终击败数: {game_state.ai_defeat_count}")
        game_ended_mid_turn = True

    return game_state, log, result_data, game_ended_mid_turn


# --- 回合结束控制器 ---

def handle_end_turn(game_state):
    """
    (系统) 结束玩家回合，开始 AI 回合，并结算所有 AI 攻击。
    返回: (game_state, log, result_data, error)
    """
    log = []
    player_mech = game_state.get_player_mech()

    if game_state.game_over:
        return game_state, log, None, None, "Game Over"

    # [健壮性修复] 使用 getattr
    if player_mech and getattr(player_mech, 'pending_combat', None):
        error = "> [错误] 必须先解决战斗中断才能结束回合！"
        log.append(error)
        return game_state, log, None, None, error

    game_state.visual_events = []
    log.append("-" * 20)
    log.append("> 玩家回合结束。")

    # [NEW] 在回合结束时，激活抛射物阶段标志
    game_state.projectile_phase_active = True
    # [NEW] 重置所有抛射物的行动状态
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

            # 1. AI 机甲逻辑
            if entity.entity_type == 'mech':

                # [Ace Logic] 如果 Ace 已经抢先行动，跳过此阶段
                if hasattr(entity, 'has_acted_early') and entity.has_acted_early:
                    log.append(f"> [系统] {entity.name} 已经在回合初行动过，跳过本阶段。")
                    entity.has_acted_early = False  # 重置状态
                    continue

                if game_state.game_mode == 'range':
                    log.append("> [靶场模式] AI 跳过回合。")
                    entity.last_pos = None
                else:
                    entity.last_pos = entity.pos

                    # [NEW] 智能切换：如果是 Ace，调用 Ace 系统
                    is_ace = entity.pilot and "Raven" in entity.pilot.name
                    if is_ace:
                        entity_log, attacks = ace_ai_system.run_ace_turn(entity, game_state)
                    else:
                        entity_log, attacks = run_ai_turn(entity, game_state)

                    log.extend(entity_log)

                    # 序列化攻击队列
                    attack_queue = []
                    for attack in attacks:
                        attack_queue.append({
                            'attacker_id': attack['attacker'].id,
                            'defender_id': attack['defender'].id,
                            'action_dict': attack['action'].to_dict()
                        })

                    # 循环结算 AI 攻击
                    for i, attack_data in enumerate(attack_queue):
                        game_state, log, result_data, game_ended_mid_turn = _resolve_queued_attack(
                            game_state, log, attack_data, attack_queue[i + 1:]
                        )
                        if game_ended_mid_turn:
                            break

            # 2. AI 无人机逻辑
            elif entity.entity_type == 'drone':
                entity_log, attacks = run_drone_logic(entity, game_state)
                log.extend(entity_log)
                # (如果无人机有攻击，也应在此处结算)

    if not game_ended_mid_turn:
        log.append("--- AI 机甲阶段结束 ---")

    result_data = result_data or {}  # 确保 result_data 是字典
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

    # [MODIFIED] 取消召唤失调逻辑，使用持久化队列断点续传

    # 1. 初始化队列 (如果为空，且是本回合第一次进入此逻辑)
    if not game_state.pending_projectile_queue:
        projectiles_to_act = []
        entities = list(game_state.entities.values())
        for entity in entities:
            if entity.entity_type == 'projectile' and entity.status == 'ok':
                # [FIX] 使用 getattr 安全获取 is_active，防止旧存档报错
                # 如果 entity 没有 is_active 属性，默认为 False，然后立即激活
                if not getattr(entity, 'is_active', False):
                    entity.is_active = True

                    # 只有未行动过的才能加入队列
                # [FIX] 使用 getattr 安全获取 has_acted
                if not getattr(entity, 'has_acted', False):
                    projectiles_to_act.append(entity)

        # 排序：玩家优先
        def sort_key(proj):
            if proj.controller == 'player':
                return 0
            elif proj.controller == 'ai':
                return 1
            else:
                return 2

        projectiles_to_act.sort(key=sort_key)

        # 存入队列 (存 ID)
        game_state.pending_projectile_queue = [p.id for p in projectiles_to_act]

        if projectiles_to_act:
            log.append(f"> [系统] {len(projectiles_to_act)} 个抛射物准备行动。")

    # 2. 处理队列
    while game_state.pending_projectile_queue:
        if game_ended_mid_turn:
            break

        proj_id = game_state.pending_projectile_queue[0]
        entity = game_state.get_entity_by_id(proj_id)

        # 如果实体不存在、已摧毁、或已行动，直接移除并继续
        # [FIX] 使用 getattr 安全检查 has_acted
        if not entity or entity.status != 'ok' or getattr(entity, 'has_acted', False):
            game_state.pending_projectile_queue.pop(0)
            continue

        # -------------------------------------------------
        # 核心逻辑开始
        # -------------------------------------------------

        # [拦截 1] 移动前
        game_state, log = _run_interception_checks(entity, game_state, log)
        if entity.status == 'destroyed':
            log.append(f"> [拦截] {entity.name} 在移动前被摧毁。")
            game_state.pending_projectile_queue.pop(0)
            continue

        # 移动
        entity_log, attacks = run_projectile_logic(entity, game_state, '延迟')
        log.extend(entity_log)

        # [拦截 2] 移动后
        game_state, log = _run_interception_checks(entity, game_state, log)
        if entity.status == 'destroyed':
            log.append(f"> [拦截] {entity.name} 在移动后被摧毁。")
            game_state.pending_projectile_queue.pop(0)
            continue

        # [NEW] 标记为已行动，防止重复
        entity.has_acted = True

        # 序列化攻击
        attack_queue = []
        for attack in attacks:
            attack_queue.append({
                'attacker_id': attack['attacker'].id,
                'defender_id': attack['defender'].id,
                'action_dict': attack['action'].to_dict()
            })

        # [关键步骤] 从队列中移除
        game_state.pending_projectile_queue.pop(0)

        # 结算攻击
        for i, attack_data in enumerate(attack_queue):
            game_state, log, result_data, game_ended_mid_turn = _resolve_queued_attack(
                game_state, log, attack_data, attack_queue[i + 1:]
            )
            if game_ended_mid_turn:
                # 中断发生！
                break

    # --- 阶段 3: 回合结束，重置玩家状态 ---
    if not game_state.pending_projectile_queue and not game_ended_mid_turn:

        # [NEW] 抛射物阶段结束
        game_state.projectile_phase_active = False

        player_mech = game_state.get_player_mech()
        if not game_state.game_over and not (player_mech and player_mech.pending_combat):
            log.append(
                "> AI回合结束。请开始你的回合。" if game_state.game_mode != 'range' else "> [靶场模式] 请开始你的回合。")
            log.append("-" * 20)

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
                player_mech.pending_combat = None

            game_state.check_game_over()
        elif player_mech and player_mech.pending_combat:
            log.append("> [系统] 玩家有待处理的中断，跳过回合重置。")

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