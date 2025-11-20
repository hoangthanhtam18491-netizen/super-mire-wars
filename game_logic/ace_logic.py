"""
【Ace Logic】
负责处理 Ace (王牌) AI 的特殊行为，包括：
1. 抢先手 (Initiative Clash) 判定逻辑
2. 王牌 AI 在玩家回合开始时的战术决策 (Pre-computation)
3. 指令重投决策 (Reroll Decision) - [v2.5 优化] 防御计算与概率学

依赖于:
- game_logic (基础计算函数)
- ace_ai_system (引入规划器，确保言行一致)
"""

import random
# 引入规划器 (延迟导入或仅在函数内导入以防循环)

# === 1. 优先级定义 (Priority Constants) ===
TIMING_PRIORITY = {
    '快速': 1,
    '近战': 2,
    '抛射': 3,
    '射击': 4,
    '移动': 5,
    '战术': 6
}


def get_timing_priority(timing_str):
    """获取时机的优先级数值，未知时机默认为最低优先级"""
    return TIMING_PRIORITY.get(timing_str, 99)


# === 2. 王牌决策 (Ace Decision Making) ===

def decide_ace_timing(ai_mech, player_mech, game_state):
    """
    Ace AI 在玩家回合开始阶段 (Phase 1) 就要决定它的战术时机。
    """
    # 延迟导入以避免循环依赖
    from .ace_ai_system import AceTacticalPlanner

    if not player_mech or player_mech.status == 'destroyed':
        return '移动'

    # 1. 模拟回合开始时的资源状态
    sim_ap = 2
    sim_tp = 1
    if ai_mech.stance == 'downed':
        sim_ap = 1
        sim_tp = 0

    # 技能：乘胜追击模拟 (Phase 1 预判)
    # 如果有乘胜追击且敌人受损，AI 应该意识到自己会有 3 AP，从而规划更贪婪的动作
    if ai_mech.pilot and "pursuit" in ai_mech.pilot.skills:
        has_compromised = False
        for part in player_mech.parts.values():
            if part and part.status in ['damaged', 'destroyed']:
                has_compromised = True
                break
        if has_compromised:
            sim_ap += 1

    # 2. 临时应用模拟资源
    original_ap = ai_mech.player_ap
    original_tp = ai_mech.player_tp

    ai_mech.player_ap = sim_ap
    ai_mech.player_tp = sim_tp

    best_plan = None
    try:
        # 3. 运行规划器生成真实方案
        planner = AceTacticalPlanner(ai_mech, game_state)
        best_plan = planner.generate_best_plan()
    except Exception as e:
        print(f"[AceLogic Error] 规划器出错: {e}")
        # 回退安全值
        ai_mech.player_ap = original_ap
        ai_mech.player_tp = original_tp
        return '移动'

    # 4. 恢复原始资源状态
    ai_mech.player_ap = original_ap
    ai_mech.player_tp = original_tp

    # 5. 缓存计划
    if best_plan:
        ai_mech.cached_ace_plan = best_plan
        # [Log] 可以在这里记录 AI 的心理活动
        # print(f"> [Ace预判] 生成计划: {best_plan.description} (时机: {best_plan.timing})")
        return best_plan.timing

    return '移动'


# === 3. 拼点裁判 (Clash Resolution) ===

def check_initiative(player_timing, ai_timing, player_pilot, ai_pilot):
    """
    判定谁赢得先手。
    """
    p_priority = get_timing_priority(player_timing)
    a_priority = get_timing_priority(ai_timing)

    # 1. 比较类型优先级 (数值小者胜)
    if p_priority < a_priority:
        return 'player', f"玩家 [{player_timing}] 优先级 ({p_priority}) 高于 AI [{ai_timing}] ({a_priority})。"
    elif a_priority < p_priority:
        return 'ai', f"AI [{ai_timing}] 优先级 ({a_priority}) 高于 玩家 [{player_timing}] ({p_priority})。"

    # 2. 优先级相同，比较驾驶员速度属性
    if not player_pilot:
        return 'ai', f"时机相同 [{player_timing}]，但玩家无驾驶员数据，AI 胜出。"

    p_speed = player_pilot.speed_stats.get(player_timing, 5)  # 默认 5
    a_speed = ai_pilot.speed_stats.get(ai_timing, 5)

    if p_speed < a_speed:
        return 'player', f"同为 [{player_timing}]，玩家反应速度 ({p_speed}) 快于 AI ({a_speed})。"
    elif a_speed < p_speed:
        return 'ai', f"同为 [{ai_timing}]，AI 反应速度 ({a_speed}) 快于 玩家 ({p_speed})。"

    # 3. 完全平局 -> 玩家胜 (主角光环)
    return 'player', f"时机与速度完全一致，玩家险胜。"


# === 4. 重投决策逻辑 (Reroll Decision) ===
# [v2.5 优化] 增强版重投逻辑

def decide_reroll(ace_entity, enemy_entity, action, attack_roll_summary, defense_roll_summary, attack_raw_rolls, defense_raw_rolls, is_attacker):
    """
    决定 Ace 是否应该消耗链接值进行重投。
    基于：
    1. 资源 (Link Points)
    2. 局势 (Threat Level)
    3. 技能 (Pilot Skills)
    4. 期望收益 (Expected Value)
    """
    if not ace_entity.pilot or ace_entity.pilot.link_points <= 0:
        return []

    selections = []
    current_links = ace_entity.pilot.link_points
    has_pursuit = "pursuit" in ace_entity.pilot.skills

    # 解析当前净伤害
    hits = attack_roll_summary.get('轻击', 0)
    crits = attack_roll_summary.get('重击', 0)
    defenses = defense_roll_summary.get('防御', 0)
    dodges = defense_roll_summary.get('闪避', 0)
    attack_lightning = attack_roll_summary.get('闪电', 0)

    # 模拟伤害结算
    cancelled_hits = min(hits, defenses)
    hits_remaining = hits - cancelled_hits

    cancelled_crits = min(crits, dodges)
    crits_remaining = crits - cancelled_crits
    dodges_remaining = dodges - cancelled_crits

    cancelled_hits_by_dodge = min(hits_remaining, dodges_remaining)
    hits_remaining -= cancelled_hits_by_dodge

    net_damage = hits_remaining + crits_remaining

    # --- 场景 A: Ace 是攻击方 (Attack Mode) ---
    if is_attacker:
        target_part = None
        # 尝试猜测目标部件 (此处简化，假设打核心或已受损部件)
        # 在真实的 CombatState 中我们知道 target_part_name，但此函数签名未传入
        # 我们假设 Ace 总是想最大化输出

        # 1. [斩杀判定] Kill Confirm
        # 如果伤害为0，或者伤害不足以致命，但重投有望致命
        enemy_hp_estimate = 3 # 假设平均结构
        enemy_is_compromised = False
        enemy_core = enemy_entity.parts.get('core')

        if enemy_core and enemy_core.status == 'damaged':
            enemy_hp_estimate = enemy_core.structure
            enemy_is_compromised = True

        # 技能协同: 乘胜追击 (Pursuit)
        # 如果有此技能，且敌人处于受损状态，Ace 极度渴望击杀以刷新 AP/TP
        pursuit_bonus_weight = 2 if (has_pursuit and enemy_is_compromised) else 0

        # 策略 A-1: 确保击杀/击穿 (Secure Penetration)
        # 如果当前未击穿 (net_damage == 0)，但只要多 1-2 点伤害就能击穿
        if net_damage == 0:
            # 只有当手里有烂骰子时才重投
            bad_dice = _collect_bad_dice(attack_raw_rolls, ace_entity.stance)
            if bad_dice:
                # 如果是 L 动作 (高投入)，必定重投
                if action.cost == 'L':
                    selections.extend(bad_dice)
                # 如果有乘胜追击且值得一搏 (剩余防御不高)
                elif has_pursuit and dodges_remaining <= 1 and defenses <= 1:
                     selections.extend(bad_dice)
                # 链接值充裕时
                elif current_links >= 3:
                     selections.extend(bad_dice)

        # 策略 A-2: 追求爆发 (Burst Damage)
        # 如果已经击穿，但可以用 Link 换取更多暴击 (红骰)
        elif net_damage > 0:
             # 检查是否有“空心重击”或者“空白”的红骰
             red_duds = _collect_dice_by_face(attack_raw_rolls, ['blank', 'hollow_heavy_hit', 'hollow_light_hit', 'eye'], color_filter=['red'])
             if red_duds and current_links >= 2:
                 selections.extend(red_duds)

    # --- 场景 B: Ace 是防御方 (Defense Mode) ---
    else:
        ace_core = ace_entity.parts.get('core')
        ace_hp = ace_core.structure if ace_core.status == 'damaged' else ace_core.armor

        # 判定危险程度
        is_dangerous = net_damage > 0

        if is_dangerous:
             # 收集防御骰中的坏结果 (空白/眼/错姿态的空心)
             bad_dice = _collect_bad_defense_dice(defense_raw_rolls, ace_entity.stance)

             if bad_dice:
                 # 估算潜在收益 (Heuristic Calculation)
                 # 白骰: 约 50% 概率出有效阻挡 (防御 or 空心防御x2 or 闪避)
                 # 蓝骰: 约 25% 概率出闪避 (在机动姿态下)
                 # 注意：如果当前是机动姿态，空心防御是无效的，所以白骰效率其实较低 (25%)
                 # 如果当前是防御姿态，白骰效率极高 (62.5%)

                 efficiency_white = 0.6 if ace_entity.stance == 'defense' else 0.25
                 efficiency_blue = 0.25 # 机动姿态下才有蓝骰

                 expected_block = 0
                 for d in bad_dice:
                     if d['color'] == 'white': expected_block += efficiency_white
                     if d['color'] == 'blue': expected_block += efficiency_blue

                 # 决策逻辑:
                 # 1. 绝境: 伤害足以摧毁核心 -> 无论概率如何，只要有机会就重投
                 is_fatal = (ace_core.status == 'damaged' and net_damage >= ace_hp) or (ace_core.status == 'ok' and net_damage >= ace_hp + 3) # 估算击穿装甲后的溢出

                 # 2. 高概率防御: 潜在阻挡数 >= 当前伤害的一半
                 is_high_probability = expected_block >= (net_damage * 0.5)

                 if is_fatal:
                     selections.extend(bad_dice)
                 elif is_high_probability:
                     # 如果不是绝境，但我们有很大把握能防住，也重投
                     selections.extend(bad_dice)

    return selections

# --- 辅助函数 ---

def _collect_bad_dice(raw_rolls, stance):
    """收集攻击骰中的坏结果 (空白、眼、不匹配姿态的空心)"""
    bad_selections = []
    # 黄骰: 空白, 眼, 空心轻击(非攻击姿态)
    for i, face_list in enumerate(raw_rolls.get('yellow_rolls', [])):
        face = face_list # 它是字符串

        if face in ['blank', 'eye']:
            bad_selections.append({'color': 'yellow', 'index': i})
        elif face == 'hollow_light_hit' and stance != 'attack':
            bad_selections.append({'color': 'yellow', 'index': i})

    # 红骰: 空白, 眼, 空心重/轻(非攻击姿态)
    for i, face in enumerate(raw_rolls.get('red_rolls', [])):
        if face in ['blank', 'eye']:
            bad_selections.append({'color': 'red', 'index': i})
        elif face in ['hollow_heavy_hit', 'hollow_light_hit'] and stance != 'attack':
            bad_selections.append({'color': 'red', 'index': i})

    return bad_selections

def _collect_dice_by_face(raw_rolls, target_faces, color_filter=None):
    """收集特定面的骰子"""
    selections = []
    colors = color_filter if color_filter else ['yellow', 'red', 'white', 'blue']

    for color in colors:
        key = f"{color}_rolls"
        for i, face in enumerate(raw_rolls.get(key, [])):
            if face in target_faces:
                selections.append({'color': color, 'index': i})
    return selections

def _collect_bad_defense_dice(raw_rolls, stance):
    """收集防御骰中的坏结果"""
    bad_selections = []
    # 白骰
    for i, face in enumerate(raw_rolls.get('white_rolls', [])):
        if face in ['blank', 'eye']:
            bad_selections.append({'color': 'white', 'index': i})
        # 如果不是防御姿态，空心防御也是坏结果
        elif face == 'hollow_defense_2' and stance != 'defense':
            bad_selections.append({'color': 'white', 'index': i})

    # 蓝骰
    for i, face in enumerate(raw_rolls.get('blue_rolls', [])):
        if face in ['blank', 'eye']:
            bad_selections.append({'color': 'blue', 'index': i})

    return bad_selections