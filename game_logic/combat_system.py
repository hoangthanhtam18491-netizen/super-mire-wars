import random
# [v_REFACTOR]
# 文件已移至 game_logic/
# 更新导入以使用相对路径
from .dice_roller import roll_dice, process_rolls
import re
from .data_models import Mech, Projectile, Part, Action


def parse_dice_string(dice_str):
    """
    [v1.15] 使用正则表达式更准确地解析骰子字符串，例如 '1黄3红'。
    """
    counts = {'yellow_count': 0, 'red_count': 0, 'white_count': 0, 'blue_count': 0}
    if not dice_str: return counts
    patterns = {'yellow_count': r'(\d+)\s*黄', 'red_count': r'(\d+)\s*红'}
    for key, pattern in patterns.items():
        match = re.search(pattern, dice_str)
        if match: counts[key] = int(match.group(1))
    return counts


# [v_MODIFIED] 签名更新：添加了 attacker_entity, skip_reroll_phase, rerolled_defense_raw
def _resolve_effect_logic(log, attacker_entity, defender_entity, target_part, overflow_hits, overflow_crits,
                          chosen_effect,
                          skip_reroll_phase=False, rerolled_defense_raw=None):
    """
    [修改 v1.17]
    分离的逻辑，用于在做出选择后解析溢出效果（毁伤、霰射、顺劈）。
    现在接收一个通用的 defender_entity。
    [v_NEXT_REROLL_FIX]
    此函数现在支持专注重投中断。
    它现在返回 (log, dice_roll_details_2, overflow_data)，其中 overflow_data 在重投时为 pending_data。
    """

    # [新增 v1.ISTATET] 效果逻辑目前只对机甲有效
    if not isinstance(defender_entity, Mech):
        log.append(f"  > [效果：{chosen_effect}] 触发，但目标不是机甲，效果跳过。")
        return log, None, None  # [MODIFIED] 返回 3 个值

    dice_roll_details_2 = None
    pending_reroll_data = None  # [NEW]

    # 5.2.A 【毁伤】
    if (chosen_effect == 'devastating'):
        log.append(f"  > [效果：毁伤] 触发！")
        log.append(f"  > 计算对结构值的溢出伤害: {overflow_crits}重, {overflow_hits}轻。")
        white_dice_count_2 = target_part.structure
        blue_dice_count_2 = defender_entity.get_total_evasion() if defender_entity.stance == 'agile' else 0

        dice_roll_details_2 = {
            'type': 'devastating_roll',
            'defense_dice_input': {'white_count': white_dice_count_2, 'blue_count': blue_dice_count_2},
            'attack_dice_input': {},  # [NEW] 确保前端有空占位符
            'attack_dice_result': {}  # [NEW] 确保前端有空占位符
        }

        # [NEW] 检查是否传入了重投
        if rerolled_defense_raw:
            defense_raw_rolls_2 = rerolled_defense_raw
            log.append("  > (使用重投后的毁伤防御骰...)")
        else:
            defense_raw_rolls_2 = roll_dice(white_count=white_dice_count_2, blue_count=blue_dice_count_2)

        # --- [NEW REROLL BLOCK] ---
        if not skip_reroll_phase:
            player_is_defender = (defender_entity.controller == 'player')
            defender_can_reroll = (
                    player_is_defender and
                    isinstance(defender_entity, Mech) and
                    defender_entity.pilot and
                    defender_entity.pilot.link_points > 0
            )
            if defender_can_reroll:
                log.append(f"  > [毁伤结算] 玩家链接值: {defender_entity.pilot.link_points}。等待重投决策...")

                # 预处理骰子以便显示
                processed_rolls, _ = process_rolls(defense_raw_rolls_2, stance=defender_entity.stance)
                dice_roll_details_2['defense_dice_result'] = processed_rolls

                pending_reroll_data = {
                    'type': 'effect_reroll',  # [NEW] 特殊类型
                    'attacker_id': attacker_entity.id,
                    'defender_id': defender_entity.id,
                    'target_part_name': target_part.name,
                    'overflow_hits': overflow_hits,
                    'overflow_crits': overflow_crits,
                    'chosen_effect': chosen_effect,
                    'attack_raw_rolls': {},  # [NEW] 攻击骰为空
                    'defense_raw_rolls': defense_raw_rolls_2,
                    'player_is_attacker': False,
                    'player_is_defender': True,
                }
                # 返回中断信号和数据
                return log, "reroll_choice_required", pending_reroll_data, dice_roll_details_2
        # --- [END NEW REROLL BLOCK] ---

        # [修改] 使用新的 roll_dice 和 process_rolls
        processed_defense_rolls_2, defense_roll_2 = process_rolls(
            defense_raw_rolls_2,
            stance=defender_entity.stance
        )
        dice_roll_details_2['defense_dice_result'] = processed_defense_rolls_2  # [修改] 发送处理后的分组结果

        log_msg_2 = f"  > [毁伤结算] 防御方 (基于结构值) 投掷 {white_dice_count_2}白"
        if blue_dice_count_2 > 0: log_msg_2 += f" {blue_dice_count_2}蓝 (机动姿态)"
        # [修改] defense_roll_2 现在是聚合后的字典
        log_msg_2 += f", 结果: {defense_roll_2 or '无'}"
        log.append(log_msg_2)

        defenses_2 = defense_roll_2.get('防御', 0)
        dodges_2 = defense_roll_2.get('闪避', 0)
        hits_2 = overflow_hits
        crits_2 = overflow_crits

        cancelled_hits_2 = min(hits_2, defenses_2)
        hits_2 -= cancelled_hits_2
        log.append(f"  > [毁伤结算] {cancelled_hits_2}个[防御]抵消了{cancelled_hits_2}个[轻击]。")

        cancelled_crits_2 = min(crits_2, dodges_2)
        crits_2 -= cancelled_crits_2
        dodges_2 -= cancelled_crits_2

        cancelled_hits_by_dodge_2 = min(hits_2, dodges_2)
        hits_2 -= cancelled_hits_by_dodge_2
        log.append(
            f"  > [毁伤结算] {dodges_2 + cancelled_crits_2}个[闪避]抵消了{cancelled_crits_2}个[重击]和{cancelled_hits_by_dodge_2}个[轻击]。")

        final_damage_2 = hits_2 + crits_2
        if final_damage_2 > 0:
            log.append(f"  > [毁伤结算] 结构值被击穿！")
            target_part.status = 'destroyed'
            log.append(f"  > (毁伤) 部件 [{target_part.name}] 被 [摧毁]！")

            # [新规则：宕机检查]
            if defender_entity.pilot and defender_entity.pilot.link_points > 0:
                defender_entity.pilot.link_points -= 1
                log.append(
                    f"  > 驾驶员 [{defender_entity.pilot.name}] 失去 1 点链接值 (剩余: {defender_entity.pilot.link_points})！")

                # [新规则：宕机检查]
                if defender_entity.pilot.link_points <= 0 and defender_entity.stance != 'downed':
                    defender_entity.stance = 'downed'
                    log.append(f"  > 驾驶员链接值归零！机甲 [{defender_entity.name}] 进入 [宕机姿态]！")

            # [BUG FIX] 检查被摧毁的是否为核心
            if target_part.name.endswith("核心"):  # 假设核心部件名称都包含 "核心"
                defender_entity.status = 'destroyed'
                log.append(f"  > [毁伤结算] 实体 [{defender_entity.name}] 的核心被摧毁，实体被移除！")

    # 5.2.B 【霰射】
    elif (chosen_effect == 'scattershot'):
        log.append(f"  > [效果：霰射] 触发！")
        # [修改 v1.17] 确保 defender_entity 是机甲
        other_parts = [p for p in defender_entity.parts.values() if
                       p and p.status != 'destroyed' and p.name != target_part.name]
        if not other_parts:
            log.append(f"  > [霰射] 没有其他有效部件可以作为目标。")
        else:
            secondary_target = random.choice(other_parts)
            secondary_status = secondary_target.status
            log.append(
                f"  > [霰射] 溢出伤害 ({overflow_crits}重, {overflow_hits}轻) 结算至随机部件: [{secondary_target.name}]！")
            white_dice_2 = secondary_target.structure if secondary_status == 'damaged' else secondary_target.armor
            log_dice_source_2 = "结构值" if secondary_status == 'damaged' else "装甲值"
            blue_dice_2 = defender_entity.get_total_evasion() if defender_entity.stance == 'agile' else 0

            dice_roll_details_2 = {
                'type': 'scattershot_roll',
                'defense_dice_input': {'white_count': white_dice_2, 'blue_count': blue_dice_2},
                'attack_dice_input': {},  # [NEW]
                'attack_dice_result': {}  # [NEW]
            }

            # [NEW] 检查是否传入了重投
            if rerolled_defense_raw:
                defense_raw_rolls_2 = rerolled_defense_raw
                log.append("  > (使用重投后的霰射防御骰...)")
            else:
                defense_raw_rolls_2 = roll_dice(white_count=white_dice_2, blue_count=blue_dice_2)

            # --- [NEW REROLL BLOCK] ---
            if not skip_reroll_phase:
                player_is_defender = (defender_entity.controller == 'player')
                defender_can_reroll = (
                        player_is_defender and
                        isinstance(defender_entity, Mech) and
                        defender_entity.pilot and
                        defender_entity.pilot.link_points > 0
                )
                if defender_can_reroll:
                    log.append(f"  > [霰射结算] 玩家链接值: {defender_entity.pilot.link_points}。等待重投决策...")

                    processed_rolls, _ = process_rolls(defense_raw_rolls_2, stance=defender_entity.stance)
                    dice_roll_details_2['defense_dice_result'] = processed_rolls

                    pending_reroll_data = {
                        'type': 'effect_reroll',
                        'attacker_id': attacker_entity.id,
                        'defender_id': defender_entity.id,
                        'target_part_name': secondary_target.name,  # [FIX] 目标是新部件
                        'overflow_hits': overflow_hits,
                        'overflow_crits': overflow_crits,
                        'chosen_effect': chosen_effect,
                        'attack_raw_rolls': {},
                        'defense_raw_rolls': defense_raw_rolls_2,
                        'player_is_attacker': False,
                        'player_is_defender': True,
                    }
                    return log, "reroll_choice_required", pending_reroll_data, dice_roll_details_2
            # --- [END NEW REROLL BLOCK] ---

            # [修改] 使用新的 roll_dice 和 process_rolls
            processed_defense_rolls_2, defense_roll_2 = process_rolls(
                defense_raw_rolls_2,
                stance=defender_entity.stance
            )
            dice_roll_details_2['defense_dice_result'] = processed_defense_rolls_2  # [修改] 发送处理后的分组结果

            log_msg_2 = f"  > [霰射结算] 防御方 (基于{log_dice_source_2}) 投掷 {white_dice_2}白"
            if blue_dice_2 > 0: log_msg_2 += f" {blue_dice_2}蓝 (机动姿态)"
            log_msg_2 += f", 结果: {defense_roll_2 or '无'}"
            log.append(log_msg_2)

            defenses_2 = defense_roll_2.get('防御', 0)
            dodges_2 = defense_roll_2.get('闪避', 0)
            hits_2 = overflow_hits
            crits_2 = overflow_crits

            cancelled_hits_2 = min(hits_2, defenses_2)
            hits_2 -= cancelled_hits_2
            log.append(f"  > [霰射结算] {cancelled_hits_2}个[防御]抵消了{cancelled_hits_2}个[轻击]。")

            cancelled_crits_2 = min(crits_2, dodges_2)
            crits_2 -= cancelled_crits_2
            dodges_2 -= cancelled_crits_2

            cancelled_hits_by_dodge_2 = min(hits_2, dodges_2)
            hits_2 -= cancelled_hits_by_dodge_2
            log.append(
                f"  > [霰射结算] {dodges_2 + cancelled_crits_2}个[闪避]抵消了{cancelled_crits_2}个[重击]和{cancelled_hits_by_dodge_2}个[轻击]。")

            final_damage_2 = hits_2 + crits_2
            if final_damage_2 > 0:
                log.append(f"  > [霰射结算] 击穿了 [{secondary_target.name}]！")
                if secondary_target.structure == 0:
                    secondary_target.status = 'destroyed'
                elif secondary_status == 'ok':
                    secondary_target.status = 'damaged'
                elif secondary_status == 'damaged':
                    secondary_target.status = 'destroyed'

                log.append(f"  > (霰射) 部件 [{secondary_target.name}] 状态变为 [{secondary_target.status}]！")

                # [新规则：宕机检查]
                if secondary_target.status == 'destroyed':
                    if defender_entity.pilot and defender_entity.pilot.link_points > 0:
                        defender_entity.pilot.link_points -= 1
                        log.append(
                            f"  > 驾驶员 [{defender_entity.pilot.name}] 失去 1 点链接值 (剩余: {defender_entity.pilot.link_points})！")

                        # [新规则：宕机检查]
                        if defender_entity.pilot.link_points <= 0 and defender_entity.stance != 'downed':
                            defender_entity.stance = 'downed'
                            log.append(f"  > 驾驶员链接值归零！机甲 [{defender_entity.name}] 进入 [宕机姿态]！")

                # [BUG FIX] 检查被摧毁的是否为核心
                if secondary_target.status == 'destroyed' and secondary_target.name.endswith("核心"):
                    defender_entity.status = 'destroyed'
                    log.append(f"  > [霰射结算] 实体 [{defender_entity.name}] 的核心被摧毁，实体被移除！")
            else:
                log.append(f"  > [霰射结算] 第二个部件抵消了所有溢出伤害。")

    # 5.2.C 【顺劈】
    elif (chosen_effect == 'cleave'):
        log.append(f"  > [效果：顺劈] 触发！")
        # [修改 v1.17] 确保 defender_entity 是机甲
        other_parts = [p for p in defender_entity.parts.values() if
                       p and p.status != 'destroyed' and p.name != target_part.name]
        if not other_parts:
            log.append(f"  > [顺劈] 没有其他有效部件可以作为目标。")
        else:
            secondary_target = random.choice(other_parts)
            secondary_status = secondary_target.status
            log.append(
                f"  > [顺劈] 溢出伤害 ({overflow_crits}重, {overflow_hits}轻) 结算至随机部件: [{secondary_target.name}]！")

            white_dice_2 = secondary_target.structure if secondary_status == 'damaged' else secondary_target.armor
            log_dice_source_2 = "结构值" if secondary_status == 'damaged' else "装甲值"
            blue_dice_2 = defender_entity.get_total_evasion() if defender_entity.stance == 'agile' else 0

            dice_roll_details_2 = {
                'type': 'cleave_roll',
                'defense_dice_input': {'white_count': white_dice_2, 'blue_count': blue_dice_2},
                'attack_dice_input': {},  # [NEW]
                'attack_dice_result': {}  # [NEW]
            }

            # [NEW] 检查是否传入了重投
            if rerolled_defense_raw:
                defense_raw_rolls_2 = rerolled_defense_raw
                log.append("  > (使用重投后的顺劈防御骰...)")
            else:
                defense_raw_rolls_2 = roll_dice(white_count=white_dice_2, blue_count=blue_dice_2)

            # --- [NEW REROLL BLOCK] ---
            if not skip_reroll_phase:
                player_is_defender = (defender_entity.controller == 'player')
                defender_can_reroll = (
                        player_is_defender and
                        isinstance(defender_entity, Mech) and
                        defender_entity.pilot and
                        defender_entity.pilot.link_points > 0
                )
                if defender_can_reroll:
                    log.append(f"  > [顺劈结算] 玩家链接值: {defender_entity.pilot.link_points}。等待重投决策...")

                    processed_rolls, _ = process_rolls(defense_raw_rolls_2, stance=defender_entity.stance)
                    dice_roll_details_2['defense_dice_result'] = processed_rolls

                    pending_reroll_data = {
                        'type': 'effect_reroll',
                        'attacker_id': attacker_entity.id,
                        'defender_id': defender_entity.id,
                        'target_part_name': secondary_target.name,  # [FIX] 目标是新部件
                        'overflow_hits': overflow_hits,
                        'overflow_crits': overflow_crits,
                        'chosen_effect': chosen_effect,
                        'attack_raw_rolls': {},
                        'defense_raw_rolls': defense_raw_rolls_2,
                        'player_is_attacker': False,
                        'player_is_defender': True,
                    }
                    return log, "reroll_choice_required", pending_reroll_data, dice_roll_details_2
            # --- [END NEW REROLL BLOCK] ---

            # [修改] 使用新的 roll_dice 和 process_rolls
            processed_defense_rolls_2, defense_roll_2 = process_rolls(
                defense_raw_rolls_2,
                stance=defender_entity.stance
            )
            dice_roll_details_2['defense_dice_result'] = processed_defense_rolls_2  # [修改] 发送处理后的分组结果

            log_msg_2 = f"  > [顺劈结算] 防御方 (基于{log_dice_source_2}) 投掷 {white_dice_2}白"
            if blue_dice_2 > 0: log_msg_2 += f" {blue_dice_2}蓝 (机动姿态)"
            log_msg_2 += f", 结果: {defense_roll_2 or '无'}"
            log.append(log_msg_2)

            defenses_2 = defense_roll_2.get('防御', 0)
            dodges_2 = defense_roll_2.get('闪避', 0)
            hits_2 = overflow_hits
            crits_2 = overflow_crits

            cancelled_hits_2 = min(hits_2, defenses_2)
            hits_2 -= cancelled_hits_2
            log.append(f"  > [顺劈结算] {cancelled_hits_2}个[防御]抵消了{cancelled_hits_2}个[轻击]。")

            cancelled_crits_2 = min(crits_2, dodges_2)
            crits_2 -= cancelled_crits_2
            dodges_2 -= cancelled_crits_2

            cancelled_hits_by_dodge_2 = min(hits_2, dodges_2)
            hits_2 -= cancelled_hits_by_dodge_2

            log.append(
                f"  > [顺劈结算] {dodges_2 + cancelled_crits_2}个[闪避]抵消了{cancelled_crits_2}个[重击]和{cancelled_hits_by_dodge_2}个[轻击]。")

            final_damage_2 = hits_2 + crits_2
            if final_damage_2 > 0:
                log.append(f"  > [顺劈结算] 击穿了 [{secondary_target.name}]！")

                if secondary_target.structure == 0:
                    secondary_target.status = 'destroyed'
                elif secondary_status == 'ok':
                    secondary_target.status = 'damaged'
                elif secondary_status == 'damaged':
                    secondary_target.status = 'destroyed'

                log.append(f"  > (顺劈) 部件 [{secondary_target.name}] 状态变为 [{secondary_target.status}]！")

                # [新规则：宕机检查]
                if secondary_target.status == 'destroyed':
                    if defender_entity.pilot and defender_entity.pilot.link_points > 0:
                        defender_entity.pilot.link_points -= 1
                        log.append(
                            f"  > 驾驶员 [{defender_entity.pilot.name}] 失去 1 点链接值 (剩余: {defender_entity.pilot.link_points})！")

                        # [新规则：宕机检查]
                        if defender_entity.pilot.link_points <= 0 and defender_entity.stance != 'downed':
                            defender_entity.stance = 'downed'
                            log.append(f"  > 驾驶员链接值归零！机甲 [{defender_entity.name}] 进入 [宕机姿态]！")

                # [BUG FIX] 检查被摧毁的是否为核心
                if secondary_target.status == 'destroyed' and secondary_target.name.endswith("核心"):
                    defender_entity.status = 'destroyed'
                    log.append(f"  > [顺劈结算] 实体 [{defender_entity.name}] 的核心被摧毁，实体被移除！")
            else:
                log.append(f"  > [顺劈结算] 第二个部件抵消了所有溢出伤害。")

    return log, dice_roll_details_2, None  # [MODIFIED] 返回 3 个值


# [v_REROLL] 修改函数签名
def resolve_attack(attacker_entity, defender_entity, action, target_part_name, is_back_attack=False,
                   chosen_effect=None, skip_reroll_phase=False, rerolled_attack_raw=None, rerolled_defense_raw=None):
    """
    [v_MODIFIED v1.29]
    处理一次完整的攻击结算流程。
    现在接收通用的 GameEntity。
    抛射物在攻击后会自毁。
    [BUG 修复] 确保所有代码路径都返回一个 4 元组。
    [v_REROLL] 添加 skip_reroll_phase 和 rerolled_..._raw 参数用于专注重投。
    """
    log = [f"> {attacker_entity.name} 使用 [{action.name}] 攻击 {defender_entity.name}。"]

    dice_roll_details = {
        'type': 'attack_roll',
        'attack_dice_input': {},
        'attack_dice_result': {},  # [修改] 这将存储分组后的结果
        'defense_dice_input': {},
        'defense_dice_result': {},  # [修改] 这将存储分组后的结果
        'secondary_roll': None
    }

    # 1. 确定目标部件
    target_part = None
    is_mech_defender = isinstance(defender_entity, Mech)

    if is_mech_defender:
        # --- 目标是机甲 ---
        target_part = defender_entity.get_part_by_name(target_part_name)
        if not target_part:
            log.append(f"  > [错误] 无法找到机甲部件 '{target_part_name}'。攻击中止。")
            return log, "无效", None, dice_roll_details

        if is_back_attack:
            log.append("  > 这是一次背击！防御方无法招架。")
            log.append(f"  > [背击] 攻击方指定命中部位为: {target_part.name}。")
        elif action.action_type == '近战' and target_part.parry > 0:
            log.append(f"  > {defender_entity.name} 决定用 [{target_part.name}] 进行招架！")
        else:
            log.append(f"  > 命中部位为: {target_part.name} ({target_part_name} 槽位)。")
    else:
        # --- 目标是抛射物/无人机 ---
        # [BUG 修复 v1.31] Projectile/Drone 没有 .get_part_by_name()
        # 应该直接访问 .parts 字典
        target_part = defender_entity.parts.get('core')
        if not target_part:
            log.append(f"  > [错误] 目标 {defender_entity.name} 没有 'core' 部件。攻击中止。")
            return log, "无效", None, dice_roll_details
        log.append(f"  > 命中 {defender_entity.name} 的 [核心]。")

    original_status = target_part.status

    # 2. 投掷攻击骰
    attack_dice_counts = parse_dice_string(action.dice)

    # [修改 v1.17] 检查攻击方是否是机甲
    is_mech_attacker = isinstance(attacker_entity, Mech)
    if is_mech_attacker:
        passive_effects = attacker_entity.get_passive_effects()
        for effect_dict in passive_effects:
            if "passive_dice_boost" in effect_dict:
                boost_rule = effect_dict["passive_dice_boost"]
                if (attacker_entity.stance == boost_rule.get("trigger_stance") and
                        action.action_type == boost_rule.get("trigger_type")):
                    dice_type_to_check = boost_rule.get("dice_type")
                    base_count = attack_dice_counts.get(dice_type_to_check, 0)
                    if base_count > 0:
                        ratio_base = boost_rule.get("ratio_base", 3)
                        ratio_add = boost_rule.get("ratio_add", 1)
                        bonus_dice = (base_count // ratio_base) * ratio_add
                        if bonus_dice > 0:
                            log.append(f"  > [被动效果: {effect_dict.get('display_effects', ['未知效果'])[0]}] 触发！")
                            log.append(f"  > 攻击姿态下的射击动作，黄骰 {base_count} -> {base_count + bonus_dice}。")
                            attack_dice_counts[dice_type_to_check] = base_count + bonus_dice

    dice_roll_details['attack_dice_input'] = attack_dice_counts.copy()

    # [v_REROLL] 检查是否传入了重投的骰子
    if rerolled_attack_raw:
        attack_raw_rolls = rerolled_attack_raw
        log.append("  > (使用重投后的攻击骰...)")
    else:
        attack_raw_rolls = roll_dice(**attack_dice_counts)

    # 检查【频闪武器】
    convert_lightning = action.effects and action.effects.get("convert_lightning_to_crit", False)

    # 检查攻击姿态 (仅当攻击者是机甲时)
    attacker_stance = 'attack' if (is_mech_attacker and attacker_entity.stance == 'attack') else 'defense'

    processed_attack_rolls, attack_roll = process_rolls(
        attack_raw_rolls,
        stance=attacker_stance,
        convert_lightning_to_crit=convert_lightning
    )
    dice_roll_details['attack_dice_result'] = processed_attack_rolls  # [修改] 发送处理后的分组结果

    log.append(f"  > 攻击方投掷结果 (处理后): {attack_roll or '无'}")
    hits = attack_roll.get('轻击', 0)
    crits = attack_roll.get('重击', 0)

    # 3. 投掷受击骰
    white_dice_count = target_part.structure if original_status == 'damaged' else target_part.armor
    log_dice_source = "结构值" if original_status == 'damaged' else "装甲值"

    if action.effects:
        ap_value = action.effects.get("armor_piercing", 0)
        if ap_value > 0 and original_status != 'damaged':
            log.append(f"  > 动作效果【穿甲{ap_value}】触发！")
            original_dice = white_dice_count
            white_dice_count = max(0, white_dice_count - ap_value)
            log.append(f"  > 受击方白骰 (来自{log_dice_source}) 从 {original_dice} 减少为 {white_dice_count}。")
        elif ap_value > 0 and original_status == 'damaged':
            log.append(f"  > 动作效果【穿甲{ap_value}】触发！但目标已破损，穿甲对结构值无效。")

    # [修改 v1.17] 使用 get_total_evasion()
    blue_dice_count = defender_entity.get_total_evasion() if defender_entity.stance == 'agile' else 0

    # [修改 v1.17] 招架只适用于机甲
    # [新规则：宕机检查]
    if is_mech_defender and action.action_type == '近战' and target_part.parry > 0 and not is_back_attack and defender_entity.stance != 'downed':
        white_dice_count += target_part.parry
        log.append(f"  > [招架] 额外增加 {target_part.parry} 个白骰 (总计 {white_dice_count} 白)。")

    dice_roll_details['defense_dice_input'] = {'white_count': white_dice_count, 'blue_count': blue_dice_count}

    # [v_REROLL] 检查是否传入了重投的骰子
    if rerolled_defense_raw:
        defense_raw_rolls = rerolled_defense_raw
        log.append("  > (使用重投后的防御骰...)")
    else:
        defense_raw_rolls = roll_dice(white_count=white_dice_count, blue_count=blue_dice_count)

    processed_defense_rolls, defense_roll = process_rolls(
        defense_raw_rolls,
        stance=defender_entity.stance
    )
    dice_roll_details['defense_dice_result'] = processed_defense_rolls  # [修改] 发送处理后的分组结果

    log.append(
        f"  > 防御方 (基于{log_dice_source}) 投掷 {white_dice_count}白 {blue_dice_count}蓝, 结果 (处理后): {defense_roll or '无'}")

    # 4. [v_REROLL] 专注重投检查
    if not skip_reroll_phase:
        # 检查是否*任何一方*是玩家机甲且有链接值
        player_is_attacker = (attacker_entity.controller == 'player')
        player_is_defender = (defender_entity.controller == 'player')

        attacker_can_reroll = (
                player_is_attacker and
                isinstance(attacker_entity, Mech) and
                attacker_entity.pilot and
                attacker_entity.pilot.link_points > 0
        )
        defender_can_reroll = (
                player_is_defender and
                isinstance(defender_entity, Mech) and
                defender_entity.pilot and
                defender_entity.pilot.link_points > 0
        )

        # 只要玩家 (作为攻击方或防御方) 可以重投，就中断
        if attacker_can_reroll or defender_can_reroll:

            player_link_points = 0
            if player_is_attacker:
                # 确保 attacker_entity 是 Mech 实例 (理论上 attacker_can_reroll 已保证)
                if isinstance(attacker_entity, Mech):
                    player_link_points = attacker_entity.pilot.link_points
            elif player_is_defender:
                # 确保 defender_entity 是 Mech 实例
                if isinstance(defender_entity, Mech):
                    player_link_points = defender_entity.pilot.link_points

            log.append(f"  > 玩家链接值: {player_link_points}。等待重投决策...")

            # 准备用于 *恢复* 战斗的数据
            pending_reroll_data = {
                'type': 'attack_reroll',  # [NEW] 明确这是标准攻击重投
                'attacker_id': attacker_entity.id,
                'defender_id': defender_entity.id,
                'action_dict': action.to_dict(),
                'target_part_name': target_part_name,
                'is_back_attack': is_back_attack,
                'attack_raw_rolls': attack_raw_rolls,  # 存储 *原始* 结果
                'defense_raw_rolls': defense_raw_rolls,  # 存储 *原始* 结果
                'player_is_attacker': player_is_attacker,  # 告诉控制器谁是玩家
                'player_is_defender': player_is_defender
            }

            # 中断并返回！
            return log, "reroll_choice_required", pending_reroll_data, dice_roll_details

    # 5. 结算伤害
    defenses = defense_roll.get('防御', 0)
    dodges = defense_roll.get('闪避', 0)
    cancelled_hits = min(hits, defenses)
    hits -= cancelled_hits
    log.append(f"  > {cancelled_hits}个[防御]抵消了{cancelled_hits}个[轻击]。")
    cancelled_crits = min(crits, dodges)
    crits -= cancelled_crits
    dodges -= cancelled_crits
    cancelled_hits_by_dodge = min(hits, dodges)
    hits -= cancelled_hits_by_dodge
    log.append(
        f"  > {dodges + cancelled_crits}个[闪避]抵消了{cancelled_crits}个[重击]和{cancelled_hits_by_dodge}个[轻击]。")

    # 6. 判断结果
    final_damage = hits + crits
    overflow_hits_for_effects = hits
    overflow_crits_for_effects = crits

    if final_damage > 0:
        log.append(f"  > 最终造成了 [击穿]！")

        # 6.1 更新状态
        # [v1.36 修复] 抛射物被击穿时应立即摧毁，无视 "ok -> damaged" 规则
        if isinstance(defender_entity, Projectile):
            target_part.status = 'destroyed'
            log.append(f"  > [抛射物] 目标 [{target_part.name}] 被 [摧毁]！")

        # [v1.36] 常规机甲部件的损伤逻辑
        elif target_part.structure == 0:
            target_part.status = 'destroyed'
            log.append(f"  > (无结构) 部件 [{target_part.name}] 被 [摧毁]！")
        elif original_status == 'ok':
            target_part.status = 'damaged'
            log.append(f"  > 部件 [{target_part.name}] 状态变为 [破损]。")
        elif original_status == 'damaged':
            target_part.status = 'destroyed'
            log.append(f"  > 已破损的部件 [{target_part.name}] 被 [摧毁]！")

        # [v_NEW_RULE] 部件被破坏时，驾驶员失去链接值
        # [MODIFIED] 仅当目标是机甲且部件真的被摧毁时
        if is_mech_defender and target_part.status == 'destroyed':
            if defender_entity.pilot and defender_entity.pilot.link_points > 0:
                defender_entity.pilot.link_points -= 1
                log.append(
                    f"  > 驾驶员 [{defender_entity.pilot.name}] 失去 1 点链接值 (剩余: {defender_entity.pilot.link_points})！")

                # [新规则：宕机检查]
                if defender_entity.pilot.link_points <= 0 and defender_entity.stance != 'downed':
                    defender_entity.stance = 'downed'
                    log.append(f"  > 驾驶员链接值归零！机甲 [{defender_entity.name}] 进入 [宕机姿态]！")

        # [新增 v1.17] 如果被摧毁的是实体本身的核心，则将实体状态设为 'destroyed'
        if target_part.status == 'destroyed' and target_part_name == 'core':
            defender_entity.status = 'destroyed'
            log.append(f"  > 实体 [{defender_entity.name}] 的核心被摧毁，实体被移除！")

        # 6.2 --- 【毁伤】/【霰射】/【顺劈】互斥选择 ---
        # [修改 v1.17] 这些效果只在攻击机甲时有效
        if not is_mech_defender:
            log.append(f"  > 目标不是机甲，跳过【毁伤】/【霰射】/【顺劈】效果结算。")

            # [新增 v1.29] 抛射物在攻击后自毁
            if isinstance(attacker_entity, Projectile):
                attacker_entity.status = 'destroyed'
                log.append(f"  > [抛射物] {attacker_entity.name} 在攻击后引爆并移除。")

            return log, "击穿", None, dice_roll_details  # <--- [BUG 修复] 确保这里有返回

        # 检查动态效果，如 【双手】获得毁伤
        has_devastating = action.effects.get("devastating", False)
        if is_mech_attacker and not has_devastating and action.effects.get("two_handed_devastating", False):
            action_slot = None
            for slot, part in attacker_entity.parts.items():
                if part and part.status != 'destroyed':
                    for act in part.actions:
                        if act.name == action.name:
                            action_slot = slot
                            break
                if action_slot: break
            if action_slot in ['left_arm', 'right_arm']:
                other_arm_slot = 'right_arm' if action_slot == 'left_arm' else 'left_arm'
                other_arm_part = attacker_entity.parts.get(other_arm_slot)
                if other_arm_part and other_arm_part.status != 'destroyed' and "【空手】" in other_arm_part.tags:
                    log.append(f"  > 动作效果【【双手】获得毁伤】触发 (另一只手为【空手】)！")
                    has_devastating = True

        has_scattershot = action.effects.get("scattershot", False)
        has_cleave = action.effects.get("cleave", False)
        has_overflow = (overflow_hits_for_effects > 0 or overflow_crits_for_effects > 0)

        devastating_conditions_met = (
                has_devastating and
                target_part.structure > 0 and
                original_status == 'ok' and
                target_part.status == 'damaged' and
                has_overflow
        )
        scattershot_conditions_met = (
                has_scattershot and
                has_overflow
        )
        cleave_conditions_met = (
                has_cleave and
                has_overflow
        )

        available_options = []
        if devastating_conditions_met:
            available_options.append('devastating')
        if scattershot_conditions_met:
            available_options.append('scattershot')
        if cleave_conditions_met:
            available_options.append('cleave')

        # --- 优先级决策 ---
        if len(available_options) > 1 and chosen_effect is None:
            # [修改 v1.17] 检查是否是玩家机甲
            if is_mech_attacker and attacker_entity.controller == 'player':
                log.append(f"> [玩家决策] 攻击同时触发 {len(available_options)} 个效果！")
                log.append("> 请选择要发动的效果...")
                overflow_data = {
                    'hits': overflow_hits_for_effects,
                    'crits': overflow_crits_for_effects,
                    'options': available_options
                }
                return log, "effect_choice_required", overflow_data, dice_roll_details
            else:
                # AI 或 抛射物 自动选择
                if 'devastating' in available_options:
                    chosen_effect = 'devastating'
                    log.append("> [AI决策] AI 优先选择【毁伤】。")
                elif 'cleave' in available_options:
                    chosen_effect = 'cleave'
                    log.append("> [AI决策] AI 优先选择【顺劈】。")
                else:
                    chosen_effect = 'scattershot'
                    log.append("> [AI决策] AI 优先选择【霰射】。")

        elif len(available_options) == 1 and chosen_effect is None:
            chosen_effect = available_options[0]

        # --- 效果执行 ---
        secondary_roll_details = None
        if chosen_effect == 'devastating' and devastating_conditions_met:
            # [MODIFIED] 传入 attacker_entity, 并准备接收 3 个返回值
            log_ext, secondary_roll_details, overflow_data = _resolve_effect_logic(
                log, attacker_entity, defender_entity, target_part,
                overflow_hits_for_effects, overflow_crits_for_effects, 'devastating',
                skip_reroll_phase=skip_reroll_phase  # [MODIFIED] 传递 skip 标志
            )
            # [MODIFIED] log_ext 已经是 log 本身
            # [MODIFIED] 检查效果是否触发了重投
            if overflow_data:
                return log, "reroll_choice_required", overflow_data, secondary_roll_details

        elif chosen_effect == 'scattershot' and scattershot_conditions_met:
            # [MODIFIED] 传入 attacker_entity, 并准备接收 3 个返回值
            log_ext, secondary_roll_details, overflow_data = _resolve_effect_logic(
                log, attacker_entity, defender_entity, target_part,
                overflow_hits_for_effects, overflow_crits_for_effects, 'scattershot',
                skip_reroll_phase=skip_reroll_phase
            )
            if overflow_data:
                return log, "reroll_choice_required", overflow_data, secondary_roll_details

        elif chosen_effect == 'cleave' and cleave_conditions_met:
            # [MODIFIED] 传入 attacker_entity, 并准备接收 3 个返回值
            log_ext, secondary_roll_details, overflow_data = _resolve_effect_logic(
                log, attacker_entity, defender_entity, target_part,
                overflow_hits_for_effects, overflow_crits_for_effects, 'cleave',
                skip_reroll_phase=skip_reroll_phase
            )
            if overflow_data:
                return log, "reroll_choice_required", overflow_data, secondary_roll_details

        if secondary_roll_details:
            dice_roll_details['secondary_roll'] = secondary_roll_details

        # [新增 v1.29] 抛射物在攻击后自毁
        if isinstance(attacker_entity, Projectile):
            attacker_entity.status = 'destroyed'
            log.append(f"  > [抛射物] {attacker_entity.name} 在攻击后引爆并移除。")

        return log, "击穿", None, dice_roll_details

    else:
        log.append("  > 所有伤害均被抵消，攻击无效。")

        # [新增 vS.29] 抛射物在攻击后自毁
        if isinstance(attacker_entity, Projectile):
            attacker_entity.status = 'destroyed'
            log.append(f"  > [抛射物] {attacker_entity.name} 在攻击后引爆并移除。")

        return log, "无效", None, dice_roll_details