"""骰子系统测试：roll_dice, process_rolls, reroll_specific_dice, roll_black_die"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game_logic.dice_roller import (
    roll_dice, process_rolls, reroll_specific_dice, roll_black_die,
    DICE_FACES, BLACK_DIE_FACES, RESULT_MAP
)


class TestRollDice:
    """roll_dice 基础功能测试"""

    def test_zero_dice_returns_empty(self):
        result = roll_dice(yellow_count=0, red_count=0, white_count=0, blue_count=0)
        assert result['yellow_rolls'] == []
        assert result['red_rolls'] == []
        assert result['white_rolls'] == []
        assert result['blue_rolls'] == []

    def test_single_yellow_roll(self):
        result = roll_dice(yellow_count=1)
        assert len(result['yellow_rolls']) == 1
        assert result['yellow_rolls'][0] in DICE_FACES['yellow']

    def test_single_red_roll(self):
        result = roll_dice(red_count=1)
        assert len(result['red_rolls']) == 1
        assert result['red_rolls'][0] in DICE_FACES['red']

    def test_single_white_roll(self):
        result = roll_dice(white_count=1)
        assert len(result['white_rolls']) == 1
        assert result['white_rolls'][0] in DICE_FACES['white']

    def test_single_blue_roll(self):
        result = roll_dice(blue_count=1)
        assert len(result['blue_rolls']) == 1
        assert result['blue_rolls'][0] in DICE_FACES['blue']

    def test_mixed_dice_counts(self):
        result = roll_dice(yellow_count=2, red_count=3, white_count=1, blue_count=4)
        assert len(result['yellow_rolls']) == 2
        assert len(result['red_rolls']) == 3
        assert len(result['white_rolls']) == 1
        assert len(result['blue_rolls']) == 4

    def test_all_results_valid(self):
        for _ in range(100):
            result = roll_dice(yellow_count=5, red_count=5, white_count=5, blue_count=5)
            for roll in result['yellow_rolls']:
                assert roll in DICE_FACES['yellow']
            for roll in result['red_rolls']:
                assert roll in DICE_FACES['red']
            for roll in result['white_rolls']:
                assert roll in DICE_FACES['white']
            for roll in result['blue_rolls']:
                assert roll in DICE_FACES['blue']


class TestProcessRolls:
    """process_rolls 处理逻辑测试"""

    def test_empty_rolls(self):
        raw = {'yellow_rolls': [], 'red_rolls': [], 'white_rolls': [], 'blue_rolls': []}
        processed, summary = process_rolls(raw)
        assert processed == {}
        assert summary == {}

    def test_attack_stance_upgrades_hollow(self):
        raw = {'yellow_rolls': ['hollow_light_hit'], 'red_rolls': ['hollow_heavy_hit', 'hollow_light_hit'],
               'white_rolls': [], 'blue_rolls': []}
        processed, summary = process_rolls(raw, stance='attack')
        assert summary.get('轻击', 0) >= 1
        assert summary.get('重击', 0) >= 1

    def test_defense_stance_upgrades_hollow_defense(self):
        raw = {'yellow_rolls': [], 'red_rolls': [],
               'white_rolls': ['hollow_defense_2'], 'blue_rolls': []}
        processed, summary = process_rolls(raw, stance='defense')
        assert '防御' in summary
        assert summary['防御'] >= 2  # hollow_defense_2 → 2x defense in defense stance

    def test_convert_lightning_to_crit(self):
        raw = {'yellow_rolls': ['lightning'], 'red_rolls': [],
               'white_rolls': [], 'blue_rolls': []}
        processed, summary = process_rolls(raw, stance='attack', convert_lightning_to_crit=True)
        assert '重击' in summary
        assert summary.get('闪电', 0) == 0

    def test_light_hit_2_produces_two_hits(self):
        raw = {'yellow_rolls': ['light_hit_2'], 'red_rolls': [],
               'white_rolls': [], 'blue_rolls': []}
        processed, summary = process_rolls(raw, stance='attack')
        assert summary.get('轻击', 0) >= 2

    def test_agile_stance_hollow_defense_stays_hollow(self):
        raw = {'yellow_rolls': [], 'red_rolls': [],
               'white_rolls': ['hollow_defense_2'], 'blue_rolls': []}
        processed, summary = process_rolls(raw, stance='agile')
        # 机动姿态下空心防御不升级为防御
        assert '防御' not in summary


class TestRerollSpecificDice:
    """专注重投测试"""

    def test_empty_selections_noop(self):
        raw = roll_dice(yellow_count=3, red_count=2)
        original = {k: list(v) for k, v in raw.items()}
        result = reroll_specific_dice(raw, [])
        assert result == raw
        assert result == original

    def test_reroll_single_yellow(self):
        raw = roll_dice(yellow_count=3)
        original_first = raw['yellow_rolls'][0]
        # 重试多次，确保重投有概率改变结果
        changed = False
        for _ in range(30):
            raw_copy = {'yellow_rolls': list(raw['yellow_rolls']),
                        'red_rolls': [], 'white_rolls': [], 'blue_rolls': []}
            result = reroll_specific_dice(raw_copy, [{'color': 'yellow', 'index': 0}])
            if result['yellow_rolls'][0] != original_first:
                changed = True
                break
        assert changed, "重投30次后结果未改变，概率极低"

    def test_reroll_result_is_valid_face(self):
        raw = roll_dice(yellow_count=2, red_count=3)
        selections = [
            {'color': 'yellow', 'index': 0},
            {'color': 'red', 'index': 1}
        ]
        result = reroll_specific_dice(raw, selections)
        assert result['yellow_rolls'][0] in DICE_FACES['yellow']
        assert result['red_rolls'][1] in DICE_FACES['red']

    def test_invalid_index_noop(self):
        raw = roll_dice(yellow_count=2)
        original = {k: list(v) for k, v in raw.items()}
        result = reroll_specific_dice(raw, [{'color': 'yellow', 'index': 99}])
        assert result == original

    def test_invalid_color_noop(self):
        raw = roll_dice(yellow_count=2)
        original = {k: list(v) for k, v in raw.items()}
        result = reroll_specific_dice(raw, [{'color': 'purple', 'index': 0}])
        assert result == original


class TestBlackDie:
    """黑骰子（部位骰）测试"""

    def test_valid_faces(self):
        for _ in range(50):
            result = roll_black_die()
            assert result in BLACK_DIE_FACES

    def test_covers_all_faces(self):
        results = set()
        for _ in range(200):
            results.add(roll_black_die())
        # 200 次投掷几乎保证覆盖全部 6 面
        assert len(results) == len(BLACK_DIE_FACES), \
            f"只覆盖了 {len(results)}/{len(BLACK_DIE_FACES)} 面: {results}"
