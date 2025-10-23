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
    # [已修正] 使用机甲的 name 属性动态生成日志
    log = [f"> {attacker_mech.name} 使用 [{action.name}] 攻击 {defender_mech.name}。"]

    # 1. 确定目标部件
    target_part = defender_mech.get_part_by_name(target_part_name)
    if is_back_attack:
        log.append("  > 这是一次背击！防御方无法招架。")
        log.append(f"  > [背击] 攻击方指定命中部位为: {target_part.name}。")
    elif action.action_type == '近战' and target_part.parry > 0:
        log.append(f"  > {defender_mech.name} 决定用 [{target_part.name}] 进行招架！")
    else:
        log.append(f"  > 随机命中部位为: {target_part.name} ({target_part_name} 槽位)。")

    # 2. 投掷攻击骰
    attack_dice_counts = parse_dice_string(action.dice)
    attack_roll = roll_dice(**attack_dice_counts)
    if attacker_mech.stance == 'attack':
        if '空心轻击' in attack_roll:
            attack_roll['轻击'] = attack_roll.get('轻击', 0) + attack_roll.pop('空心轻击')
            log.append("  > [攻击姿态] 空心轻击 变为 轻击。")
        if '空心重击' in attack_roll:
            attack_roll['重击'] = attack_roll.get('重击', 0) + attack_roll.pop('空心重击')
            log.append("  > [攻击姿态] 空心重击 变为 重击。")
    log.append(f"  > 攻击方投掷结果: {attack_roll}")

    # 3. 投掷受击骰
    white_dice_count = target_part.structure if target_part.status == 'damaged' else target_part.armor
    blue_dice_count = defender_mech.get_total_evasion() if defender_mech.stance == 'agile' else 0
    if action.action_type == '近战' and target_part.parry > 0 and not is_back_attack:
        white_dice_count += target_part.parry
        log.append(f"  > [招架] 额外增加 {target_part.parry} 个白骰。")
    defense_roll = roll_dice(white_count=white_dice_count, blue_count=blue_dice_count)
    if defender_mech.stance == 'defense' and '空心防御' in defense_roll:
        defense_roll['防御'] = defense_roll.get('防御', 0) + defense_roll.pop('空心防御')
        log.append("  > [防御姿态] 空心防御 变为 防御。")
    log.append(f"  > 防御方投掷 {white_dice_count}白 {blue_dice_count}蓝, 结果: {defense_roll}")

    # 4. 结算伤害
    hits = attack_roll.get('轻击', 0);
    crits = attack_roll.get('重击', 0)
    defenses = defense_roll.get('防御', 0);
    dodges = defense_roll.get('闪避', 0)
    cancelled_hits = min(hits, defenses);
    hits -= cancelled_hits
    log.append(f"  > {cancelled_hits}个[防御]抵消了{cancelled_hits}个[轻击]。")
    cancelled_crits = min(crits, dodges);
    crits -= cancelled_crits;
    dodges -= cancelled_crits
    cancelled_hits_by_dodge = min(hits, dodges);
    hits -= cancelled_hits_by_dodge
    log.append(
        f"  > {dodges + cancelled_crits}个[闪避]抵消了{cancelled_crits}个[重击]和{cancelled_hits_by_dodge}个[轻击]。")

    # 5. 判断结果
    final_damage = hits + crits
    if final_damage > 0:
        log.append(f"  > 最终造成了 [击穿]！")
        if target_part.structure == 0:
            target_part.status = 'destroyed'; log.append(f"  > 部件 [{target_part.name}] 被 [摧毁]！")
        elif target_part.status == 'ok':
            target_part.status = 'damaged'; log.append(f"  > 部件 [{target_part.name}] 状态变为 [破损]。")
        elif target_part.status == 'damaged':
            target_part.status = 'destroyed'; log.append(f"  > 已破损的部件 [{target_part.name}] 被 [摧毁]！")
        return log, "击穿"
    else:
        log.append("  > 所有伤害均被抵消，攻击无效。");
        return log, "无效"

