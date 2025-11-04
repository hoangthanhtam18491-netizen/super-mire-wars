import random
from collections import Counter

# 定义每种颜色骰子的面
# 注意: 'light_hit_2' 代表结果为2个轻击, 'hollow_defense_2' 代表2个空心防御
DICE_FACES = {
    'yellow': ['light_hit_2', 'light_hit_2', 'light_hit', 'light_hit', 'hollow_light_hit', 'lightning', 'eye', 'blank'],
    'red': ['heavy_hit', 'heavy_hit', 'heavy_hit', 'heavy_hit', 'hollow_heavy_hit', 'hollow_light_hit', 'lightning',
            'eye'],
    'white': ['defense', 'hollow_defense_2', 'hollow_defense_2', 'evasion', 'lightning', 'lightning', 'eye', 'blank'],
    'blue': ['evasion', 'evasion', 'eye', 'eye', 'lightning', 'blank', 'blank', 'blank']
}

# [新增] 定义黑骰子的面
BLACK_DIE_FACES = ['core', 'legs', 'left_arm', 'right_arm', 'backpack', 'any']

def roll_black_die():
    """投掷一个黑骰子（部位骰）并返回结果。"""
    return random.choice(BLACK_DIE_FACES)

# 用于将骰面结果映射到中文名称
RESULT_MAP = {
    'heavy_hit': '重击',
    'light_hit': '轻击',
    'defense': '防御',
    'evasion': '闪避',
    'hollow_heavy_hit': '空心重击',
    'hollow_light_hit': '空心轻击',
    'hollow_defense': '空心防御',
    'lightning': '闪电',
    'eye': '眼睛',
    'blank': '空白'
}


def roll_dice(yellow_count=0, red_count=0, white_count=0, blue_count=0):
    """
    [v_MODIFIED]
    模拟投掷指定数量的四种颜色骰子。
    不再汇总结果，而是返回每个骰子颜色的原始投掷结果列表。

    Returns:
        dict: 一个包含每种颜色骰子原始结果列表的字典。
              e.g., {'yellow_rolls': ['light_hit_2', 'blank'], 'red_rolls': ['heavy_hit'], ...}
    """
    rolls_by_color = {
        'yellow_rolls': [],
        'red_rolls': [],
        'white_rolls': [],
        'blue_rolls': []
    }

    # 收集所有投掷结果
    for _ in range(yellow_count):
        rolls_by_color['yellow_rolls'].append(random.choice(DICE_FACES['yellow']))
    for _ in range(red_count):
        rolls_by_color['red_rolls'].append(random.choice(DICE_FACES['red']))
    for _ in range(white_count):
        rolls_by_color['white_rolls'].append(random.choice(DICE_FACES['white']))
    for _ in range(blue_count):
        rolls_by_color['blue_rolls'].append(random.choice(DICE_FACES['blue']))

    return rolls_by_color


def process_rolls(raw_rolls_dict, stance='defense', convert_lightning_to_crit=False):
    """
    [v_MODIFIED]
    一个辅助函数，用于将在 `roll_dice` 中获得的原始投掷结果
    处理成最终的、可汇总的中文结果。

    [修改]:
    processed_results_by_color 现在是一个 list-of-lists 结构,
    e.g., {'yellow': [['轻击', '轻击'], ['空白']], ...}
    其中每个内部列表代表一颗骰子的结果 (例如 'light_hit_2' 会产生 ['轻击', '轻击'])

    Args:
        raw_rolls_dict (dict): 来自 roll_dice 的原始结果, e.g., {'yellow_rolls': [...], ...}
        stance (str): 防御方姿态 ('defense', 'attack', 'agile')
        convert_lightning_to_crit (bool): 是否激活【频闪武器】

    Returns:
        tuple: (
            processed_results_by_color (dict): e.g., {'yellow': [['轻击', '轻击'], ['空白']]}
            aggregated_summary (dict): e.g., {'轻击': 3, '重击': 1, '空白': 1}
        )
    """

    # [修改] 字典的值现在是列表的列表
    processed_results_by_color = {
        'yellow': [],  # e.g., [['轻击', '轻击'], ['空白']]
        'red': [],
        'white': [],
        'blue': []
    }

    aggregated_summary = {}

    def add_results_to_aggregator(results_list):
        """[修改] 辅助函数，用于将 *一颗骰子* 的结果（可能多于一个）添加到总聚合中"""
        for res in results_list:
            aggregated_summary[res] = aggregated_summary.get(res, 0) + 1

    # --- 处理黄骰 ---
    for roll in raw_rolls_dict.get('yellow_rolls', []):
        die_results = []  # 来自这 *一颗* 黄骰的结果
        result = ''
        if roll == 'light_hit_2':
            die_results = [RESULT_MAP['light_hit'], RESULT_MAP['light_hit']]
        elif roll == 'light_hit':
            die_results = [RESULT_MAP['light_hit']]
        elif roll == 'hollow_light_hit':
            result = RESULT_MAP['light_hit'] if stance == 'attack' else RESULT_MAP['hollow_light_hit']
            die_results = [result]
        elif roll == 'lightning':
            result = RESULT_MAP['heavy_hit'] if convert_lightning_to_crit else RESULT_MAP['lightning']
            die_results = [result]
        elif roll == 'eye':
            die_results = [RESULT_MAP['eye']]
        else:  # 'blank'
            die_results = [RESULT_MAP['blank']]

        processed_results_by_color['yellow'].append(die_results)  # 添加这颗骰子的结果列表
        add_results_to_aggregator(die_results)  # 更新聚合

    # --- 处理红骰 ---
    for roll in raw_rolls_dict.get('red_rolls', []):
        die_results = []
        result = ''
        if roll == 'heavy_hit':
            die_results = [RESULT_MAP['heavy_hit']]
        elif roll == 'hollow_heavy_hit':
            result = RESULT_MAP['heavy_hit'] if stance == 'attack' else RESULT_MAP['hollow_heavy_hit']
            die_results = [result]
        elif roll == 'hollow_light_hit':
            result = RESULT_MAP['light_hit'] if stance == 'attack' else RESULT_MAP['hollow_light_hit']
            die_results = [result]
        elif roll == 'lightning':
            result = RESULT_MAP['heavy_hit'] if convert_lightning_to_crit else RESULT_MAP['lightning']
            die_results = [result]
        elif roll == 'eye':
            die_results = [RESULT_MAP['eye']]
        else:  # 'blank' (red dice don't have blank, but for safety)
            die_results = [RESULT_MAP['blank']]

        processed_results_by_color['red'].append(die_results)
        add_results_to_aggregator(die_results)

    # --- 处理白骰 ---
    for roll in raw_rolls_dict.get('white_rolls', []):
        die_results = []
        result = ''
        if roll == 'defense':
            die_results = [RESULT_MAP['defense']]
        elif roll == 'hollow_defense_2':
            result = RESULT_MAP['defense'] if stance == 'defense' else RESULT_MAP['hollow_defense']
            die_results = [result, result]  # 两个结果来自同一颗骰子
        elif roll == 'evasion':
            die_results = [RESULT_MAP['evasion']]
        elif roll == 'lightning':
            result = RESULT_MAP['heavy_hit'] if convert_lightning_to_crit else RESULT_MAP['lightning']
            die_results = [result]
        elif roll == 'eye':
            die_results = [RESULT_MAP['eye']]
        else:  # 'blank'
            die_results = [RESULT_MAP['blank']]

        processed_results_by_color['white'].append(die_results)
        add_results_to_aggregator(die_results)

    # --- 处理蓝骰 ---
    for roll in raw_rolls_dict.get('blue_rolls', []):
        die_results = []
        result = ''
        if roll == 'evasion':
            die_results = [RESULT_MAP['evasion']]
        elif roll == 'eye':
            die_results = [RESULT_MAP['eye']]
        elif roll == 'lightning':
            result = RESULT_MAP['heavy_hit'] if convert_lightning_to_crit else RESULT_MAP['lightning']
            die_results = [result]
        else:  # 'blank'
            die_results = [RESULT_MAP['blank']]

        processed_results_by_color['blue'].append(die_results)
        add_results_to_aggregator(die_results)

    # 清理空的颜色列表
    processed_results_by_color = {k: v for k, v in processed_results_by_color.items() if v}
    # 清理0计数的聚合结果
    aggregated_summary = {k: v for k, v in aggregated_summary.items() if v > 0}

    return processed_results_by_color, aggregated_summary

