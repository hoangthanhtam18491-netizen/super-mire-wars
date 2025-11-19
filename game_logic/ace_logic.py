"""
【Ace Logic】
负责处理 Ace (王牌) AI 的特殊行为，包括：
1. 抢先手 (Initiative Clash) 判定逻辑
2. 王牌 AI 在玩家回合开始时的战术决策 (Pre-computation)
3. [NEW] 指令重投决策 (Reroll Decision)

依赖于:
- game_logic (基础计算函数)
- ai_system (用于部分评估逻辑)
"""

import random
from .ai_system import _evaluate_action_strength, _get_distance
# 需要了解骰子面及其含义来做决策
from .dice_roller import DICE_FACES

# === 1. 优先级定义 (Priority Constants) ===
# 数值越小，优先级越高
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
    这种决策比普通 AI 更具侵略性和预判性。
    """
    if not player_mech or player_mech.status == 'destroyed':
        return '移动'

    dist = _get_distance(ai_mech.pos, player_mech.pos)

    # --- 战术分析 ---

    # 1. 斩杀检查 (Kill Shot)
    # 如果玩家核心受损且在近战范围，尝试斩杀
    player_core = player_mech.parts.get('core')
    if player_core and player_core.status == 'damaged' and dist <= 2:
        # 检查是否有近战武器
        if any(a.action_type == '近战' for a, s in ai_mech.get_all_actions()):
            return '近战'

    # 2. 距离与武装分析
    # 检查可用动作
    melee_actions = []
    shoot_actions = []
    projectile_actions = []

    for action, slot in ai_mech.get_all_actions():
        # 过滤掉不可用的部件和无弹药的动作
        part = ai_mech.parts.get(slot)
        if not part or part.status == 'destroyed': continue
        if action.ammo > 0:
            ammo_key = (ai_mech.id, slot, action.name)
            if game_state.ammo_counts.get(ammo_key, 0) <= 0: continue

        if action.action_type == '近战':
            melee_actions.append(action)
        elif action.action_type == '射击':
            shoot_actions.append(action)
        elif action.action_type == '抛射':
            projectile_actions.append(action)

    # A. 极近距离 (1-2格)
    if dist <= 2:
        # 优先近战，拼刀！
        if melee_actions: return '近战'
        # 如果没近战，可能是射击型 Ace，尝试拉开距离或贴脸射击
        pass

    # B. 中距离 (3-5格)
    if 3 <= dist <= 5:
        # 抛射物此时很有威胁 (特别是直射火箭或近距离导弹)
        if projectile_actions: return '抛射'
        if shoot_actions: return '射击'
        pass

    # C. 远距离 (6+格)
    if dist >= 6:
        # 只有射击或抛射
        best_shoot = max(shoot_actions, key=lambda a: a.range_val, default=None)
        best_proj = max(projectile_actions, key=lambda a: a.range_val, default=None)

        shoot_range = best_shoot.range_val if best_shoot else 0
        proj_range = best_proj.range_val if best_proj else 0

        if shoot_range >= dist: return '射击'
        if proj_range >= dist: return '抛射'
        # 都够不着，必须移动
        return '移动'

    # --- 默认回退逻辑 (基于 Raven 的性格：压迫感) ---
    if melee_actions: return '近战'
    if shoot_actions: return '射击'
    if projectile_actions: return '抛射'

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


# === 4. [NEW] 重投决策逻辑 (Reroll Decision) ===

def decide_reroll(ace_entity, enemy_entity, action, attack_roll_summary, defense_roll_summary, attack_raw_rolls, defense_raw_rolls, is_attacker):
    """
    决定 Ace 是否应该消耗链接值进行重投。

    Args:
        ace_entity: Ace 机甲实体
        enemy_entity: 对手机甲实体
        action: 当前使用的 Action 对象
        attack_roll_summary: 攻击结果摘要 (e.g. {'轻击': 2, '重击': 1})
        defense_roll_summary: 防御结果摘要 (e.g. {'防御': 1, '闪避': 0})
        attack_raw_rolls: 原始攻击骰子 (dict of lists)
        defense_raw_rolls: 原始防御骰子 (dict of lists)
        is_attacker: Ace 是否是攻击方

    Returns:
        list: 需要重投的骰子列表 [{'color': 'yellow', 'index': 0}, ...]，如果不重投则返回 []
    """
    if not ace_entity.pilot or ace_entity.pilot.link_points <= 0:
        return []

    selections = []

    # 计算当前净伤害
    hits = attack_roll_summary.get('轻击', 0)
    crits = attack_roll_summary.get('重击', 0)
    defenses = defense_roll_summary.get('防御', 0)
    dodges = defense_roll_summary.get('闪避', 0)

    # 简单模拟伤害结算
    cancelled_hits = min(hits, defenses)
    hits_remaining = hits - cancelled_hits

    cancelled_crits = min(crits, dodges)
    crits_remaining = crits - cancelled_crits
    dodges_remaining = dodges - cancelled_crits

    cancelled_hits_by_dodge = min(hits_remaining, dodges_remaining)
    hits_remaining -= cancelled_hits_by_dodge

    net_damage = hits_remaining + crits_remaining

    # --- 场景 A: Ace 是攻击方 ---
    if is_attacker:
        # 策略 1: 斩杀 (Kill Confirm)
        # 如果目标核心受损且伤害不足以击杀(假设1点结构)，或者目标濒临宕机
        target_critical = False
        enemy_core = enemy_entity.parts.get('core')
        if enemy_core and enemy_core.status == 'damaged':
            target_critical = True

        # 如果本来能杀掉 (伤害>0) 就不重投了。如果杀不掉 (伤害=0) 且有机会，就重投。
        if target_critical and net_damage == 0:
            # 重投所有无效骰子 (空白, 空心)
            selections.extend(_collect_bad_dice(attack_raw_rolls, ace_entity.stance))

        # 策略 2: 高价值动作挽救 (High Value)
        # L 动作成本高，如果全空，必须救
        elif action.cost == 'L' and net_damage == 0:
             selections.extend(_collect_bad_dice(attack_raw_rolls, ace_entity.stance))

        # 策略 3: 爆发 (Burst)
        # 如果有大量红骰子但没出重击
        elif '红' in action.dice and crits == 0:
            selections.extend(_collect_dice_by_face(attack_raw_rolls, ['blank', 'hollow_heavy_hit', 'hollow_light_hit', 'eye']))

    # --- 场景 B: Ace 是防御方 ---
    else:
        # 策略 1: 保命 (Survival)
        # 如果将被击穿且核心受损 -> 必须重投
        ace_core = ace_entity.parts.get('core')
        if ace_core and ace_core.status == 'damaged' and net_damage > 0:
            selections.extend(_collect_bad_defense_dice(defense_raw_rolls, ace_entity.stance))

        # 策略 2: 止损 (Damage Control)
        # 如果伤害极高 (>=3)，尝试减少伤害
        elif net_damage >= 3:
             selections.extend(_collect_bad_defense_dice(defense_raw_rolls, ace_entity.stance))

    return selections

def _collect_bad_dice(raw_rolls, stance):
    """收集攻击骰中的坏结果 (空白、眼睛、非姿态加成的空心)"""
    bad_selections = []

    # 黄骰: 空白, 眼睛, 空心(如果不是攻击姿态)
    for i, face in enumerate(raw_rolls.get('yellow_rolls', [])):
        if face in ['blank', 'eye'] or (face == 'hollow_light_hit' and stance != 'attack'):
            bad_selections.append({'color': 'yellow', 'index': i})

    # 红骰: 眼睛, 空心(如果不是攻击姿态)
    for i, face in enumerate(raw_rolls.get('red_rolls', [])):
        if face in ['blank', 'eye'] or (face in ['hollow_heavy_hit', 'hollow_light_hit'] and stance != 'attack'):
            bad_selections.append({'color': 'red', 'index': i})

    return bad_selections

def _collect_dice_by_face(raw_rolls, target_faces):
    """收集特定面的骰子"""
    selections = []
    for color in ['yellow', 'red', 'white', 'blue']:
        key = f"{color}_rolls"
        for i, face in enumerate(raw_rolls.get(key, [])):
            if face in target_faces:
                selections.append({'color': color, 'index': i})
    return selections

def _collect_bad_defense_dice(raw_rolls, stance):
    """收集防御骰中的坏结果"""
    bad_selections = []

    # 白骰: 空白, 眼睛, 空心(如果不是防御姿态)
    for i, face in enumerate(raw_rolls.get('white_rolls', [])):
        if face in ['blank', 'eye'] or (face == 'hollow_defense_2' and stance != 'defense'):
            bad_selections.append({'color': 'white', 'index': i})

    # 蓝骰: 空白, 眼睛
    for i, face in enumerate(raw_rolls.get('blue_rolls', [])):
        if face in ['blank', 'eye']:
            bad_selections.append({'color': 'blue', 'index': i})

    return bad_selections