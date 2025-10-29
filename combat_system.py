import random
from dice_roller import roll_dice


def parse_dice_string(dice_str):
    """使用正则表达式更准确地解析骰子字符串，例如 '1黄3红'。"""
    import re
    counts = {'yellow_count': 0, 'red_count': 0, 'white_count': 0, 'blue_count': 0}
    if not dice_str: return counts
    patterns = {'yellow_count': r'(\d+)\s*黄', 'red_count': r'(\d+)\s*红'}
    for key, pattern in patterns.items():
        match = re.search(pattern, dice_str)
        if match: counts[key] = int(match.group(1))
    return counts


def resolve_attack(attacker_mech, defender_mech, action, target_part_name, is_back_attack=False):
    """
    处理一次完整的攻击结算流程。
    包括：确定目标 -> 投掷攻击骰 -> 投掷防御骰 -> 结算（抵消） -> 应用伤害和状态变化。
    [修改] 新增处理【毁伤】效果的逻辑。
    返回一个战斗日志列表和最终结果（'击穿'或'无效'）。
    """
    # [已修正] 使用机甲的 name 属性动态生成日志
    log = [f"> {attacker_mech.name} 使用 [{action.name}] 攻击 {defender_mech.name}。"]

    # --- 1. 确定目标部件 ---
    target_part = defender_mech.get_part_by_name(target_part_name)
    if not target_part:
        log.append(f"  > [错误] 找不到目标部件: {target_part_name}")
        return log, "错误"

    if is_back_attack:
        log.append("  > 这是一次背击！防御方无法招架。")
        log.append(f"  > [背击] 攻击方指定命中部位为: {target_part.name}。")
    elif action.action_type == '近战' and target_part.parry > 0:
        log.append(f"  > {defender_mech.name} 决定用 [{target_part.name}] 进行招架！")
    else:
        log.append(f"  > 命中部位为: {target_part.name} ({target_part_name} 槽位)。")

    # --- 2. 投掷攻击骰 ---
    attack_dice_counts = parse_dice_string(action.dice)

    # 检查攻击方的被动效果 (例如：增强冷却)
    passive_effects = attacker_mech.get_passive_effects()
    for effect_dict in passive_effects:
        if "passive_dice_boost" in effect_dict:
            boost_rule = effect_dict["passive_dice_boost"]
            if (attacker_mech.stance == boost_rule.get("trigger_stance") and
                    action.action_type == boost_rule.get("trigger_type")):
                dice_type_to_check = boost_rule.get("dice_type", "yellow_count")
                base_count = attack_dice_counts.get(dice_type_to_check, 0)
                if base_count > 0:
                    ratio_base = boost_rule.get("ratio_base", 3)
                    ratio_add = boost_rule.get("ratio_add", 1)
                    bonus_dice = (base_count // ratio_base) * ratio_add
                    if bonus_dice > 0:
                        log.append(f"  > [被动效果: 增强冷却] 触发！")
                        log.append(f"  > 攻击姿态下的射击动作，黄骰 {base_count} -> {base_count + bonus_dice}。")
                        attack_dice_counts[dice_type_to_check] = base_count + bonus_dice

    attack_roll_initial = roll_dice(**attack_dice_counts)
    attack_roll = attack_roll_initial.copy() # 复制一份用于计算，保留原始结果用于【毁伤】

    # 检查动作的主动效果 (例如：频闪武器)
    if action.effects:
        if action.effects.get("convert_lightning_to_crit") and '闪电' in attack_roll:
            lightning_count = attack_roll.pop('闪电')
            attack_roll['重击'] = attack_roll.get('重击', 0) + lightning_count
            log.append(f"  > 动作效果【频闪武器】触发！")
            log.append(f"  > {lightning_count}个[闪电] 变为 {lightning_count}个[重击]。")

    # 处理攻击姿态
    if attacker_mech.stance == 'attack':
        if '空心轻击' in attack_roll:
            attack_roll['轻击'] = attack_roll.get('轻击', 0) + attack_roll.pop('空心轻击')
            log.append("  > [攻击姿态] 空心轻击 变为 轻击。")
        if '空心重击' in attack_roll:
            attack_roll['重击'] = attack_roll.get('重击', 0) + attack_roll.pop('空心重击')
            log.append("  > [攻击姿态] 空心重击 变为 重击。")
    log.append(f"  > 攻击方投掷结果: {attack_roll}") # 显示处理后的结果

    # --- 3. 投掷受击骰 (第一次 - 对抗装甲) ---
    white_dice_count = target_part.armor # 第一次总是对抗装甲
    if target_part.status == 'damaged':
        log.append(f"  > 部件 [{target_part.name}] 已破损，但第一次防御仍使用装甲值 ({target_part.armor})。")
        # 注意：文档规则说破损后用结构值计算白骰，但这里为了实现【毁伤】的逻辑，
        # 第一次总是先打穿装甲，溢出伤害再打结构。如果规则是破损后直接用结构防御，需要调整这里。

    # 检查动作的【穿甲】效果
    if action.effects:
        ap_value = action.effects.get("armor_piercing", 0)
        if ap_value > 0:
            log.append(f"  > 动作效果【穿甲{ap_value}】触发！")
            original_dice = white_dice_count
            white_dice_count = max(0, white_dice_count - ap_value)
            log.append(f"  > 受击方白骰从 {original_dice} 减少为 {white_dice_count}。")

    blue_dice_count = defender_mech.get_total_evasion() if defender_mech.stance == 'agile' else 0

    # 处理招架
    if action.action_type == '近战' and target_part.parry > 0 and not is_back_attack:
        white_dice_count += target_part.parry
        log.append(f"  > [招架] 额外增加 {target_part.parry} 个白骰。")

    defense_roll = roll_dice(white_count=white_dice_count, blue_count=blue_dice_count)

    # 处理防御姿态
    if defender_mech.stance == 'defense' and '空心防御' in defense_roll:
        defense_roll['防御'] = defense_roll.get('防御', 0) + defense_roll.pop('空心防御')
        log.append("  > [防御姿态] 空心防御 变为 防御。")
    log.append(f"  > 防御方投掷 {white_dice_count}白 {blue_dice_count}蓝 (对抗装甲), 结果: {defense_roll}")

    # --- 4. 结算伤害 (第一次) ---
    hits = attack_roll.get('轻击', 0)
    crits = attack_roll.get('重击', 0)
    defenses = defense_roll.get('防御', 0)
    dodges = defense_roll.get('闪避', 0)

    # 防御抵消轻击
    cancelled_hits_by_defense = min(hits, defenses)
    hits -= cancelled_hits_by_defense
    defenses -= cancelled_hits_by_defense # 剩余防御没用
    log.append(f"  > {cancelled_hits_by_defense}个[防御]抵消了{cancelled_hits_by_defense}个[轻击]。")

    # 闪避优先抵消重击
    cancelled_crits_by_dodge = min(crits, dodges)
    crits -= cancelled_crits_by_dodge
    dodges -= cancelled_crits_by_dodge
    log.append(f"  > {cancelled_crits_by_dodge}个[闪避]抵消了{cancelled_crits_by_dodge}个[重击]。")

    # 剩余闪避抵消轻击
    cancelled_hits_by_dodge = min(hits, dodges)
    hits -= cancelled_hits_by_dodge
    dodges -= cancelled_hits_by_dodge # 剩余闪避没用
    log.append(f"  > {cancelled_hits_by_dodge}个[闪避]抵消了{cancelled_hits_by_dodge}个[轻击]。")

    # --- 5. 判断第一次击穿结果 & 处理【毁伤】 ---
    final_damage_armor = hits + crits # 这是穿透装甲的伤害
    has_devastating = action.effects.get("devastating", False)
    penetrated_armor = final_damage_armor > 0

    if penetrated_armor:
        log.append(f"  > 最终造成了 [击穿]！(穿透装甲)")

        # 部件状态变化
        initial_status = target_part.status
        if target_part.structure == 0:
            target_part.status = 'destroyed'
            log.append(f"  > 无结构部件 [{target_part.name}] 被 [摧毁]！")
        elif target_part.status == 'ok':
            target_part.status = 'damaged'
            log.append(f"  > 部件 [{target_part.name}] 状态变为 [破损]。")
        elif target_part.status == 'damaged':
            # 即使有毁伤，如果部件已经是 damaged，这次击穿也会直接摧毁它
            target_part.status = 'destroyed'
            log.append(f"  > 已破损的部件 [{target_part.name}] 被 [摧毁]！")

        # --- 【毁伤】逻辑开始 ---
        # 条件：动作有毁伤 & 部件有结构 & 第一次击穿导致 ok -> damaged
        if (has_devastating and
                target_part.structure > 0 and
                initial_status == 'ok' and
                target_part.status == 'damaged'):

            overflow_hits = hits # 使用第一次结算后剩余的 hits
            overflow_crits = crits # 使用第一次结算后剩余的 crits
            log.append(f"> 攻击具有【毁伤】，计算溢出伤害 {overflow_crits}个[重击]和{overflow_hits}个[轻击]")

            # 第二次防御掷骰 - 对抗结构
            white_dice_structure = target_part.structure
            # 注意：穿甲效果不应用于结构值
            # 注意：招架效果不应用于结构值
            # 注意：机动姿态的蓝骰在第一次防御时已消耗，这里不再投掷

            defense_roll_structure = roll_dice(white_count=white_dice_structure, blue_count=0) # 只投白骰

            # 处理防御姿态 (如果防御方是这个姿态)
            if defender_mech.stance == 'defense' and '空心防御' in defense_roll_structure:
                defense_roll_structure['防御'] = defense_roll_structure.get('防御', 0) + defense_roll_structure.pop('空心防御')
                # 不需要重复记录姿态日志

            log.append(f"> 结算至结构值，防御方投掷 {white_dice_structure}白 0蓝, 结果: {defense_roll_structure}")

            # 第二次伤害结算
            struct_defenses = defense_roll_structure.get('防御', 0)
            struct_dodges = defense_roll_structure.get('闪避', 0) # 结构防御一般不应出闪避，但以防万一

            # 防御抵消轻击
            cancelled_struct_hits_def = min(overflow_hits, struct_defenses)
            overflow_hits -= cancelled_struct_hits_def
            log.append(f"  > {cancelled_struct_hits_def}个[防御]抵消了{cancelled_struct_hits_def}个[轻击]。")

            # 闪避抵消重击 (理论上 struct_dodges 为 0)
            cancelled_struct_crits_dodge = min(overflow_crits, struct_dodges)
            overflow_crits -= cancelled_struct_crits_dodge
            struct_dodges -= cancelled_struct_crits_dodge
            log.append(f"  > {cancelled_struct_crits_dodge}个[闪避]抵消了{cancelled_struct_crits_dodge}个[重击]。")

             # 剩余闪避抵消轻击 (理论上 struct_dodges 为 0)
            cancelled_struct_hits_dodge = min(overflow_hits, struct_dodges)
            overflow_hits -= cancelled_struct_hits_dodge
            log.append(f"  > {cancelled_struct_hits_dodge}个[闪避]抵消了{cancelled_struct_hits_dodge}个[轻击]。")

            final_damage_structure = overflow_hits + overflow_crits

            if final_damage_structure > 0:
                log.append(f"  > 【毁伤】最终造成了 [击穿]！(穿透结构)")
                # 因为是从 ok -> damaged 触发的毁伤，这次结构击穿必定导致 destroyed
                target_part.status = 'destroyed'
                log.append(f"  > 已破损的部件 [{target_part.name}] 被 [摧毁]！")
            else:
                log.append(f"  > 【毁伤】所有溢出伤害均被抵消。")
        # --- 【毁伤】逻辑结束 ---

        return log, "击穿" # 只要第一次击穿了，结果就是击穿

    else: # 没有穿透装甲
        log.append("  > 所有伤害均被抵消，攻击无效。")
        return log, "无效"
