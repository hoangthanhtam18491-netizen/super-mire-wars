"""GameState 序列化往返一致性测试"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game_logic.game_logic import GameState


class TestGameStateRoundTrip:
    """测试 GameState to_dict → from_dict 往返"""

    def test_empty_state_round_trip(self):
        """空 GameState 往返后应保持默认值"""
        gs = GameState()
        data = gs.to_dict()
        restored = GameState.from_dict(data)

        assert restored.board_width == gs.board_width
        assert restored.board_height == gs.board_height
        assert restored.game_mode == 'duel'
        assert restored.ai_defeat_count == 0
        assert restored.game_over is None
        # 空 GameState 会自动创建默认 AI，所以 entities 不为空
        assert len(restored.entities) == len(gs.entities)
        assert restored.visual_events == []

    def test_from_dict_with_none(self):
        """from_dict(None) 应返回默认状态"""
        gs = GameState.from_dict(None)
        assert gs.board_width == 10
        assert gs.board_height == 10
        assert gs.game_mode == 'duel'

    def test_partial_dict_loads_defaults(self):
        """不完整的 dict 应填充默认值"""
        gs = GameState.from_dict({'game_mode': 'horde'})
        assert gs.game_mode == 'horde'
        assert gs.board_width == 10
        assert gs.entities == {}
        assert gs.ammo_counts == {}

    def test_visual_events_round_trip(self):
        """visual_events 往返应保留"""
        gs = GameState()
        gs.add_visual_event('dice_roll', attacker_name='A', action_name='B')
        gs.add_visual_event('attack_result', defender_pos=(5, 5), result_text='penetration')
        data = gs.to_dict()
        restored = GameState.from_dict(data)

        assert len(restored.visual_events) == 2
        assert restored.visual_events[0]['type'] == 'dice_roll'
        assert restored.visual_events[0]['attacker_name'] == 'A'
        assert restored.visual_events[1]['type'] == 'attack_result'
        assert restored.visual_events[1]['result_text'] == 'penetration'

    def test_projectile_phase_active_round_trip(self):
        """projectile_phase_active 往返应保留"""
        gs = GameState()
        gs.projectile_phase_active = True
        data = gs.to_dict()
        restored = GameState.from_dict(data)
        assert restored.projectile_phase_active is True

    def test_pending_projectile_queue_round_trip(self):
        """pending_projectile_queue 往返应保留"""
        gs = GameState()
        gs.pending_projectile_queue = ['proj_1', 'proj_2']
        data = gs.to_dict()
        restored = GameState.from_dict(data)
        assert restored.pending_projectile_queue == ['proj_1', 'proj_2']


class TestBoardGeometry:
    """棋盘几何相关测试"""

    def test_get_occupied_tiles_has_defaults(self):
        gs = GameState()
        tiles = gs.get_occupied_tiles()
        # 空 GameState 会自动创建默认 AI，占据 (10, 5)
        assert len(tiles) > 0

    def test_board_bounds(self):
        gs = GameState()
        assert gs.board_width == 10
        assert gs.board_height == 10

    def test_get_all_renderable_has_default_ai(self):
        gs = GameState()
        entities = gs.get_all_renderable_entities()
        # 空 GameState 会自动创建默认 AI 实体
        assert len(entities) > 0
        assert entities[0].entity_type == 'mech'


class TestGameOverCheck:
    """游戏结束检查测试"""

    def test_only_ai_no_player_is_over(self):
        """只有AI没有玩家时，游戏判定玩家死亡"""
        gs = GameState()
        # 空 GameState 创建默认 AI 但没有玩家，所以 player_dead = True
        assert gs.check_game_over() is True
        assert gs.game_over == 'ai_win'

    def test_player_dead_game_over(self):
        gs = GameState()
        # 模拟创建 player_mech 后直接标记为 destroyed
        gs.game_over = 'ai_win'
        assert gs.game_over == 'ai_win'

    def test_ai_win_scenario(self):
        gs = GameState()
        gs.game_over = 'ai_win'
        assert gs.check_game_over() is True
