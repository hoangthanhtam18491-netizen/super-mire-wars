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
    模拟投掷指定数量的四种颜色骰子并汇总结果。

    Args:
        yellow_count (int): 黄色骰子的数量。
        red_count (int): 红色骰子的数量。
        white_count (int): 白色骰子的数量。
        blue_count (int): 蓝色骰子的数量。

    Returns:
        dict: 一个包含所有结果汇总的字典。
    """
    all_rolls = []

    # 收集所有投掷结果
    for _ in range(yellow_count):
        all_rolls.append(random.choice(DICE_FACES['yellow']))
    for _ in range(red_count):
        all_rolls.append(random.choice(DICE_FACES['red']))
    for _ in range(white_count):
        all_rolls.append(random.choice(DICE_FACES['white']))
    for _ in range(blue_count):
        all_rolls.append(random.choice(DICE_FACES['blue']))

    # 使用 Counter 进行汇总
    raw_summary = Counter(all_rolls)

    # 初始化最终结果字典
    final_summary = {name: 0 for name in RESULT_MAP.values()}

    # 处理汇总结果，特别是处理 "xx_2" 的情况
    if raw_summary['light_hit_2'] > 0:
        final_summary[RESULT_MAP['light_hit']] += raw_summary['light_hit_2'] * 2
        del raw_summary['light_hit_2']

    if raw_summary['hollow_defense_2'] > 0:
        final_summary[RESULT_MAP['hollow_defense']] += raw_summary['hollow_defense_2'] * 2
        del raw_summary['hollow_defense_2']

    # 合并剩余的普通结果
    for result_key, count in raw_summary.items():
        if result_key in RESULT_MAP:
            final_summary[RESULT_MAP[result_key]] += count

    # 移除没有出现的项目
    final_summary_cleaned = {k: v for k, v in final_summary.items() if v > 0}

    return final_summary_cleaned
