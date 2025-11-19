"""
【Ace Logic】
负责处理 Ace (王牌) AI 的特殊行为，包括：
1. 抢先手 (Initiative Clash) 判定逻辑
2. 王牌 AI 在玩家回合开始时的战术决策 (Pre-computation)

依赖于:
- game_logic (基础计算函数)
- ai_system (用于部分评估逻辑)
"""

import random
from .ai_system import _evaluate_action_strength, _get_distance

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

    Args:
        ai_mech (Mech): Ace AI 机甲
        player_mech (Mech): 玩家机甲
        game_state (GameState): 当前游戏状态

    Returns:
        str: AI 选择的时机 ('快速', '近战', '射击', '抛射', '移动')
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
        # 如果有打桩机等强力近战，Raven 肯定选近战
        pass

    # B. 中距离 (3-5格)
    if 3 <= dist <= 5:
        # 抛射物此时很有威胁 (特别是直射火箭或近距离导弹)
        if projectile_actions: return '抛射'
        if shoot_actions: return '射击'
        # 如果是近战机体，可能尝试 '移动' 来突进，或者用 '快速' 动作（如有）
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
    # 如果以上都没命中，且有近战，偏好近战压制
    if melee_actions: return '近战'
    if shoot_actions: return '射击'
    if projectile_actions: return '抛射'

    return '移动'


# === 3. 拼点裁判 (Clash Resolution) ===

def check_initiative(player_timing, ai_timing, player_pilot, ai_pilot):
    """
    判定谁赢得先手。

    Args:
        player_timing (str): 玩家选择的时机
        ai_timing (str): AI 选择的时机
        player_pilot (Pilot): 玩家驾驶员对象 (可能为 None)
        ai_pilot (Pilot): AI 驾驶员对象

    Returns:
        tuple: (winner, log_reason)
               winner: 'player' 或 'ai'
               log_reason: 描述胜负原因的字符串
    """
    p_priority = get_timing_priority(player_timing)
    a_priority = get_timing_priority(ai_timing)

    # 1. 比较类型优先级 (数值小者胜)
    if p_priority < a_priority:
        return 'player', f"玩家 [{player_timing}] 优先级 ({p_priority}) 高于 AI [{ai_timing}] ({a_priority})。"
    elif a_priority < p_priority:
        return 'ai', f"AI [{ai_timing}] 优先级 ({a_priority}) 高于 玩家 [{player_timing}] ({p_priority})。"

    # 2. 优先级相同，比较驾驶员速度属性
    # 双方都必须有 Pilot 才能比，否则默认 AI 赢 (因为 AI 肯定有 Pilot，玩家如果是白板就输了)
    if not player_pilot:
        return 'ai', f"时机相同 [{player_timing}]，但玩家无驾驶员数据，AI 胜出。"

    # 获取对应的速度属性值
    # 注意: 在 Pilot 定义中，数值代表"速度/能力"，通常越大越好？
    # 让我们查看 _pilots.py 中的 PILOT_RAVEN: '快速': 3, '近战': 2 ...
    # 之前的设定是 "数值小的优先" (代表延迟低)。
    # 我们沿用这个设定：Speed Stat 越小越快。

    p_speed = player_pilot.speed_stats.get(player_timing, 5)  # 默认 5
    a_speed = ai_pilot.speed_stats.get(ai_timing, 5)

    if p_speed < a_speed:
        return 'player', f"同为 [{player_timing}]，玩家反应速度 ({p_speed}) 快于 AI ({a_speed})。"
    elif a_speed < p_speed:
        return 'ai', f"同为 [{ai_timing}]，AI 反应速度 ({a_speed}) 快于 玩家 ({p_speed})。"

    # 3. 完全平局 -> 玩家胜 (主角光环)
    return 'player', f"时机与速度完全一致，玩家险胜。"