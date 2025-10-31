import random
from dice_roller import roll_dice


def parse_dice_string(dice_str):
    # ... (此函数无变化) ...
    import re
    counts = {'yellow_count': 0, 'red_count': 0, 'white_count': 0, 'blue_count': 0}
    if not dice_str: return counts
    patterns = {'yellow_count': r'(\d+)\s*黄', 'red_count': r'(\d+)\s*红'}
    for key, pattern in patterns.items():
        match = re.search(pattern, dice_str)
        if match: counts[key] = int(match.group(1))
    return counts


def _resolve_effect_logic(log, defender_mech, target_part, overflow_hits, overflow_crits, chosen_effect):
    """
    [NEW HELPER v1.13]
    分离的逻辑，用于在做出选择后解析溢出效果（毁伤、霰射、顺劈）。
    假定 chosen_effect 是有效的并且条件已经满足。
    """

    # 5.2.A 【毁伤】
    if (chosen_effect == 'devastating'):
        # ... (此效果逻辑无变化) ...
        log.append(f"  > [效果：毁伤] 触发！")
        log.append(f"  > 计算对结构值的溢出伤害: {overflow_crits}重, {overflow_hits}轻。")
        white_dice_count_2 = target_part.structure
        blue_dice_count_2 = defender_mech.get_total_evasion() if defender_mech.stance == 'agile' else 0
        defense_roll_2 = roll_dice(white_count=white_dice_count_2, blue_count=blue_dice_count_2)
        log_msg_2 = f"  > [毁伤结算] 防御方 (基于结构值) 投掷 {white_dice_count_2}白"
        if blue_dice_count_2 > 0: log_msg_2 += f" {blue_dice_count_2}蓝 (机动姿态)"
        log_msg_2 += f", 结果: {defense_roll_2}"
        log.append(log_msg_2)
        if defender_mech.stance == 'defense' and '空心防御' in defense_roll_2:
            defense_roll_2['防御'] = defense_roll_2.get('防御', 0) + defense_roll_2.pop('空心防御')
            log.append("  > [毁伤结算][防御姿态] 空心防御 变为 防御。")
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
        else:
            log.append(f"  > [毁伤结算] 结构值抵消了所有溢出伤害。")

    # 5.2.B 【霰射】
    elif (chosen_effect == 'scattershot'):
        # ... (此效果逻辑无变化) ...
        log.append(f"  > [效果：霰射] 触发！")
        other_parts = [p for p in defender_mech.parts.values() if
                       p.status != 'destroyed' and p.name != target_part.name]
        if not other_parts:
            log.append(f"  > [霰射] 没有其他有效部件可以作为目标。")
        else:
            secondary_target = random.choice(other_parts)
            secondary_status = secondary_target.status
            log.append(
                f"  > [霰射] 溢出伤害 ({overflow_crits}重, {overflow_hits}轻) 结算至随机部件: [{secondary_target.name}]！")
            white_dice_2 = secondary_target.structure if secondary_status == 'damaged' else secondary_target.armor
            log_dice_source_2 = "结构值" if secondary_status == 'damaged' else "装甲值"
            blue_dice_2 = defender_mech.get_total_evasion() if defender_mech.stance == 'agile' else 0
            defense_roll_2 = roll_dice(white_count=white_dice_2, blue_count=blue_dice_2)
            log_msg_2 = f"  > [霰射结算] 防御方 (基于{log_dice_source_2}) 投掷 {white_dice_2}白"
            if blue_dice_2 > 0: log_msg_2 += f" {blue_dice_2}蓝 (机动姿态)"
            log_msg_2 += f", 结果: {defense_roll_2}"
            log.append(log_msg_2)
            if defender_mech.stance == 'defense' and '空心防御' in defense_roll_2:
                defense_roll_2['防御'] = defense_roll_2.get('防御', 0) + defense_roll_2.pop('空心防御')
                log.append("  > [霰射结算][防御姿态] 空心防御 变为 防御。")
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
            else:
                log.append(f"  > [霰射结算] 第二个部件抵消了所有溢出伤害。")

    # 5.2.C 【顺劈】
    elif (chosen_effect == 'cleave'):
        # ... (此效果逻辑无变化) ...
        log.append(f"  > [效果：顺劈] 触发！")
        other_parts = [p for p in defender_mech.parts.values() if
                       p.status != 'destroyed' and p.name != target_part.name]
        if not other_parts:
            log.append(f"  > [顺劈] 没有其他有效部件可以作为目标。")
        else:
            secondary_target = random.choice(other_parts)
            secondary_status = secondary_target.status
            log.append(
                f"  > [顺劈] 溢出伤害 ({overflow_crits}重, {overflow_hits}轻) 结算至随机部件: [{secondary_target.name}]！")

            white_dice_2 = secondary_target.structure if secondary_status == 'damaged' else secondary_target.armor
            log_dice_source_2 = "结构值" if secondary_status == 'damaged' else "装甲值"
            blue_dice_2 = defender_mech.get_total_evasion() if defender_mech.stance == 'agile' else 0

            defense_roll_2 = roll_dice(white_count=white_dice_2, blue_count=blue_dice_2)

            log_msg_2 = f"  > [顺劈结算] 防御方 (基于{log_dice_source_2}) 投掷 {white_dice_2}白"
            if blue_dice_2 > 0: log_msg_2 += f" {blue_dice_2}蓝 (机动姿态)"
            log_msg_2 += f", 结果: {defense_roll_2}"
            log.append(log_msg_2)

            if defender_mech.stance == 'defense' and '空心防御' in defense_roll_2:
                defense_roll_2['防御'] = defense_roll_2.get('防御', 0) + defense_roll_2.pop('空心防御')
                log.append("  > [顺劈结算][防御姿态] 空心防御 变为 防御。")

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
            else:
                log.append(f"  > [顺劈结算] 第二个部件抵消了所有溢出伤害。")

    return log


def resolve_attack(attacker_mech, defender_mech, action, target_part_name, is_back_attack=False, chosen_effect=None):
    """
    处理一次完整的攻击结算流程。
    [修改 v1.10] 动态检查【【双手】获得毁伤】。
    [修复 v1.12] 修正【顺劈】逻辑，确保其攻击 secondary_target 而不是 target_part。
    [修改 v1.13] 将效果选择逻辑分离到 _resolve_effect_logic
    """
    log = [f"> {attacker_mech.name} 使用 [{action.name}] 攻击 {defender_mech.name}。"]

    # 1. 确定目标部件
    # ... (此节无变化) ...
    target_part = defender_mech.get_part_by_name(target_part_name)
    if not target_part:
        log.append(f"  > [错误] 无法找到目标部件 '{target_part_name}'。攻击中止。")
        return log, "无效", None
    original_status = target_part.status
    if is_back_attack:
        log.append("  > 这是一次背击！防御方无法招架。")
        log.append(f"  > [背击] 攻击方指定命中部位为: {target_part.name}。")
    elif action.action_type == '近战' and target_part.parry > 0:
        log.append(f"  > {defender_mech.name} 决定用 [{target_part.name}] 进行招架！")
    else:
        log.append(f"  > 命中部位为: {target_part.name} ({target_part_name} 槽位)。")

    # 2. 投掷攻击骰
    # ... (此节无变化) ...
    attack_dice_counts = parse_dice_string(action.dice)
    passive_effects = attacker_mech.get_passive_effects()
    for effect_dict in passive_effects:
        if "passive_dice_boost" in effect_dict:
            boost_rule = effect_dict["passive_dice_boost"]
            if (attacker_mech.stance == boost_rule.get("trigger_stance") and
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
    attack_roll = roll_dice(**attack_dice_counts)
    if action.effects:
        if action.effects.get("convert_lightning_to_crit") and '闪电' in attack_roll:
            lightning_count = attack_roll.pop('闪电')
            attack_roll['重击'] = attack_roll.get('重击', 0) + lightning_count
            log.append(f"  > 动作效果【频闪武器】触发！ {lightning_count}个[闪电] 变为 {lightning_count}个[重击]。")
    if attacker_mech.stance == 'attack':
        if '空心轻击' in attack_roll:
            attack_roll['轻击'] = attack_roll.get('轻击', 0) + attack_roll.pop('空心轻击')
            log.append("  > [攻击姿态] 空心轻击 变为 轻击。")
        if '空心重击' in attack_roll:
            attack_roll['重击'] = attack_roll.get('重击', 0) + attack_roll.pop('空心重击')
            log.append("  > [攻击姿态] 空心重击 变为 重击。")
    log.append(f"  > 攻击方投掷结果: {attack_roll}")
    hits = attack_roll.get('轻击', 0)
    crits = attack_roll.get('重击', 0)

    # 3. 投掷受击骰
    # ... (此节无变化) ...
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
    blue_dice_count = defender_mech.get_total_evasion() if defender_mech.stance == 'agile' else 0
    if action.action_type == '近战' and target_part.parry > 0 and not is_back_attack:
        white_dice_count += target_part.parry
        log.append(f"  > [招架] 额外增加 {target_part.parry} 个白骰 (总计 {white_dice_count} 白)。")
    defense_roll = roll_dice(white_count=white_dice_count, blue_count=blue_dice_count)
    if defender_mech.stance == 'defense' and '空心防御' in defense_roll:
        defense_roll['防御'] = defense_roll.get('防御', 0) + defense_roll.pop('空心防御')
        log.append("  > [防御姿态] 空心防御 变为 防御。")
    log.append(
        f"  > 防御方 (基于{log_dice_source}) 投掷 {white_dice_count}白 {blue_dice_count}蓝, 结果: {defense_roll}")

    # 4. 结算伤害
    # ... (此节无变化) ...
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

    # 5. 判断结果 (第一次)
    final_damage = hits + crits
    overflow_hits_for_effects = hits
    overflow_crits_for_effects = crits

    if final_damage > 0:
        log.append(f"  > 最终造成了 [击穿]！")

        # 5.1 更新状态
        if target_part.structure == 0:
            target_part.status = 'destroyed'
            log.append(f"  > (无结构) 部件 [{target_part.name}] 被 [摧毁]！")
        elif original_status == 'ok':
            target_part.status = 'damaged'
            log.append(f"  > 部件 [{target_part.name}] 状态变为 [破损]。")
        elif original_status == 'damaged':
            target_part.status = 'destroyed'
            log.append(f"  > 已破损的部件 [{target_part.name}] 被 [摧毁]！")

        # 5.2 --- [修改] 【毁伤】/【霰射】/【顺劈】互斥选择 ---

        # [新增 v1.10] 检查动态效果，如 【双手】获得毁伤
        has_devastating = action.effects.get("devastating", False)
        if not has_devastating and action.effects.get("two_handed_devastating", False):
            # 检查【双手】条件
            action_slot = None
            # (通过遍历找到动作来自哪个槽位)
            for slot, part in attacker_mech.parts.items():
                if part.status != 'destroyed':
                    for act in part.actions:
                        if act.name == action.name:
                            action_slot = slot
                            break
                if action_slot: break

            if action_slot in ['left_arm', 'right_arm']:
                other_arm_slot = 'right_arm' if action_slot == 'left_arm' else 'left_arm'
                other_arm_part = attacker_mech.parts.get(other_arm_slot)
                # 检查另一只手是否未被摧毁且有【空手】标签
                if other_arm_part and other_arm_part.status != 'destroyed' and "【空手】" in other_arm_part.tags:
                    log.append(f"  > 动作效果【【双手】获得毁伤】触发 (另一只手为【空手】)！")
                    has_devastating = True  # 动态激活【毁伤】

        has_scattershot = action.effects.get("scattershot", False)
        has_cleave = action.effects.get("cleave", False)
        has_overflow = (overflow_hits_for_effects > 0 or overflow_crits_for_effects > 0)

        # 检查各自的特定触发条件
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
            if attacker_mech.name == "玩家机甲":
                log.append(f"> [玩家决策] 攻击同时触发 {len(available_options)} 个效果！")
                log.append("> 请选择要发动的效果...")
                overflow_data = {
                    'hits': overflow_hits_for_effects,
                    'crits': overflow_crits_for_effects,
                    'options': available_options
                }
                return log, "effect_choice_required", overflow_data
            else:
                # AI 自动选择
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

        # --- [MODIFICATION v1.13] ---
        # 效果执行 (调用新的辅助函数)

        # 检查 *已选择的* 效果的条件是否满足
        # (这是关键！`chosen_effect` 可能是 'cleave'，但 `cleave_conditions_met` 必须为 true)
        if chosen_effect == 'devastating' and devastating_conditions_met:
            log = _resolve_effect_logic(log, defender_mech, target_part, overflow_hits_for_effects,
                                        overflow_crits_for_effects, 'devastating')
        elif chosen_effect == 'scattershot' and scattershot_conditions_met:
            log = _resolve_effect_logic(log, defender_mech, target_part, overflow_hits_for_effects,
                                        overflow_crits_for_effects, 'scattershot')
        elif chosen_effect == 'cleave' and cleave_conditions_met:
            log = _resolve_effect_logic(log, defender_mech, target_part, overflow_hits_for_effects,
                                        overflow_crits_for_effects, 'cleave')

        return log, "击穿", None  # 正常击穿，没有待办事项

    else:
        log.append("  > 所有伤害均被抵消，攻击无效。")
        return log, "无效", None

