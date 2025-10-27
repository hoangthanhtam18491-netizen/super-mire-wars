import math
import heapq
from data_models import Mech, Part, Action
# [修正] 导入所有部件和动作，以及 AI_LOADOUTS
from parts_database import (
    ALL_PARTS, CORES, LEGS, LEFT_ARMS, RIGHT_ARMS, BACKPACKS,
    ACTION_BENPAO, ACTION_JINGJU, ACTION_JUJI, ACTION_PAOJI,
    ACTION_CIJI, ACTION_DIANSHE, ACTION_HUIZHAN, ACTION_TIAOYUE,
    ACTION_SUSHE, ACTION_DIANSHE_ZHAN, ACTION_DIANSHE_CI, ACTION_SUSHE_BIPAO,
    ACTION_BENPAO_MA  # [修正] 导入漏掉的动作
)
import random  # 导入 random


# [新增] 辅助函数，也供 AI 使用
def _get_distance(pos1, pos2):
    """计算两个位置的曼哈顿距离。"""
    return abs(pos1[0] - pos2[0]) + abs(pos1[1] - pos2[1])


def is_in_forward_arc(viewer_pos, viewer_orientation, target_pos):
    """检查目标是否在观察者的前向90度弧形区域内。"""
    vx, vy = viewer_pos
    tx, ty = target_pos
    if viewer_orientation == 'N' and ty <= vy: return abs(tx - vx) <= (vy - ty)
    if viewer_orientation == 'S' and ty >= vy: return abs(tx - vx) <= (ty - vy)
    if viewer_orientation == 'E' and tx >= vx: return abs(ty - vy) <= (tx - vx)
    if viewer_orientation == 'W' and tx <= vx: return abs(ty - vy) <= (vx - tx)
    return False


def is_back_attack(attacker_pos, defender_pos, defender_orientation):
    """检查攻击是否来自防御者的后方90度弧形区域。"""
    if defender_orientation == 'N': return is_in_forward_arc(defender_pos, 'S', attacker_pos)
    if defender_orientation == 'S': return is_in_forward_arc(defender_pos, 'N', attacker_pos)
    if defender_orientation == 'E': return is_in_forward_arc(defender_pos, 'W', attacker_pos)
    if defender_orientation == 'W': return is_in_forward_arc(defender_pos, 'E', attacker_pos)
    return False


def _is_adjacent(pos1, pos2):
    """检查两个坐标是否相邻（包括对角线）。"""
    dx = abs(pos1[0] - pos2[0])
    dy = abs(pos1[1] - pos2[1])
    return dx <= 1 and dy <= 1 and (dx + dy > 0)


def _is_tile_locked_by_opponent(game_state, tile_pos, a_mech, b_pos, b_mech):
    """
    检查 tile_pos 上的单位是否被对手近战锁定。
    a_mech 是在 tile_pos 上的单位（即移动者）。
    b_mech 是对手。
    """
    if not b_mech or b_mech.parts['core'].status == 'destroyed':
        return False
    if not b_mech.has_melee_action():
        return False
    if not _is_adjacent(tile_pos, b_pos):
        return False
    if not is_in_forward_arc(b_pos, b_mech.orientation, tile_pos):
        return False
    return True


def get_player_lock_status(game_state):
    """检查玩家是否被AI锁定。"""
    is_locked = _is_tile_locked_by_opponent(
        game_state,
        game_state.player_pos, game_state.player_mech,
        game_state.ai_pos, game_state.ai_mech
    )
    return is_locked, game_state.ai_pos if is_locked else None


def get_ai_lock_status(game_state):
    """检查AI是否被玩家锁定。"""
    is_locked = _is_tile_locked_by_opponent(
        game_state,
        game_state.ai_pos, game_state.ai_mech,
        game_state.player_pos, game_state.player_mech
    )
    return is_locked, game_state.player_pos if is_locked else None


def create_mech_from_selection(name, selection):
    """
    根据机库页面的部件名称选择，从数据库动态创建一台机甲。
    """
    try:
        core_part = Part.from_dict(CORES[selection['core']].to_dict())
        legs_part = Part.from_dict(LEGS[selection['legs']].to_dict())
        left_arm_part = Part.from_dict(LEFT_ARMS[selection['left_arm']].to_dict())
        right_arm_part = Part.from_dict(RIGHT_ARMS[selection['right_arm']].to_dict())
        backpack_part = Part.from_dict(BACKPACKS[selection['backpack']].to_dict())
    except KeyError as e:
        print(f"创建机甲时出错：找不到部件 {e}。使用默认部件。")
        core_part = Part.from_dict(list(CORES.values())[0].to_dict())
        legs_part = Part.from_dict(list(LEGS.values())[0].to_dict())
        left_arm_part = Part.from_dict(list(LEFT_ARMS.values())[0].to_dict())
        right_arm_part = Part.from_dict(list(RIGHT_ARMS.values())[0].to_dict())
        backpack_part = Part.from_dict(list(BACKPACKS.values())[0].to_dict())

    return Mech(name=name, core=core_part, legs=legs_part, left_arm=left_arm_part, right_arm=right_arm_part,
                backpack=backpack_part)


# --- AI 配置 ---
AI_LOADOUT_HEAVY = {
    'name': "AI机甲 (重火炮型)",
    'selection': {
        'core': 'GK-09 "壁垒"核心',
        'legs': 'TK-05 坦克履带',
        'left_arm': 'LH-8 早期型霰弹破片炮',
        'right_arm': 'LGP-70 长程火炮',
        'backpack': 'EB-03 扩容电池'
    }
}

AI_LOADOUT_STANDARD = {
    'name': "AI机甲 (标准泥沼型)",
    'selection': {
        'core': 'RT-06 "泥沼"核心',
        'legs': 'RL-06 标准下肢',
        'left_arm': 'CC-3 格斗刀',
        'right_arm': 'AC-32 自动步枪',
        'backpack': 'AMS-190 主动防御'
    }
}

AI_LOADOUT_LIGHTA = {
    'name': "AI机甲 (高速射手型)",
    'selection': {
        'core': 'GK-08 "哨兵"核心',
        'legs': 'RL-03D “快马”高速下肢',
        'left_arm': 'R-20 肩置磁轨炮（左）',
        'right_arm': 'R-20 肩置磁轨炮（右）',
        'backpack': '未完成的TB-600 跳跃背包'
    }
}

AI_LOADOUT_LIGHTB = {
    'name': "AI机甲 (高速近战型)",
    'selection': {
        'core': 'GK-08 "哨兵"核心',
        'legs': 'RL-03D “快马”高速下肢',
        'left_arm': '62型 臂盾 + 未完成的CC-20 单手剑（左）',
        'right_arm': '63型 臂炮 + 未完成CC-20 单手剑（右）',
        'backpack': '未完成的TB-600 跳跃背包'
    }
}

AI_LOADOUTS = {
    "heavy": AI_LOADOUT_HEAVY,
    "standard": AI_LOADOUT_STANDARD,
    "lighta": AI_LOADOUT_LIGHTA,
    "lightb": AI_LOADOUT_LIGHTB,
}


# --- AI 配置结束 ---


def create_ai_mech(ai_loadout_key=None):
    """
    创建一个AI机甲。
    """
    if ai_loadout_key not in AI_LOADOUTS:
        ai_loadout_key = "standard"

    chosen_loadout = AI_LOADOUTS[ai_loadout_key]
    selection = chosen_loadout['selection']
    name = chosen_loadout['name']

    if not all(part_name in ALL_PARTS for part_name in selection.values()):
        print(f"警告: AI配置 '{name}' 中的一个或多个部件在数据库中不存在。将使用 'standard' 后备AI。")
        selection = AI_LOADOUTS["standard"]['selection']
        name = AI_LOADOUTS["standard"]['name']
        mech = create_mech_from_selection(name, selection)
    else:
        mech = create_mech_from_selection(name, selection)

    # 注意：朝向现在在 GameState 中设置
    return mech


class GameState:
    """管理整个游戏的状态"""

    def __init__(self, player_mech=None, ai_loadout_key=None, game_mode='duel'):
        self.board_width = 10
        self.board_height = 10
        self.player_mech = player_mech
        self.ai_mech = None  # 将在下面根据模式初始化
        self.player_pos = (1, 1)  # 默认
        self.ai_pos = (1, 1)  # 默认

        self.game_mode = game_mode
        self.ai_defeat_count = 0

        # [新增] 根据游戏模式设置起始位置和朝向
        if self.game_mode == 'horde':
            self.player_pos = (5, 2)
            self.player_mech.orientation = 'N'
            self._spawn_horde_ai(ai_loadout_key)  # 生成第一个AI
        elif self.game_mode == 'duel':
            # 决斗模式：(1,5) vs (10,5) 相对
            self.player_pos = (1, 5)
            self.player_mech.orientation = 'E'
            self.ai_pos = (10, 5)
            self.ai_mech = create_ai_mech(ai_loadout_key)
            self.ai_mech.orientation = 'W'
        else:  # 'standard' 或其他后备
            # 原始模式：(5,2) vs (5,8)
            self.player_pos = (5, 2)
            self.player_mech.orientation = 'N'
            self.ai_pos = (5, 8)
            self.ai_mech = create_ai_mech(ai_loadout_key)
            self.ai_mech.orientation = 'S'

        self.current_turn = 'player'
        self.player_ap = 2
        self.player_tp = 1
        self.turn_phase = 'timing'
        self.timing = None
        self.opening_move_taken = False
        self.game_over = None  # 'player_win', 'ai_win'

        self.player_actions_used_this_turn = []
        self.ai_actions_used_this_turn = []

    def _spawn_horde_ai(self, ai_loadout_key):
        """[新增] 生存模式下，在底部两行随机生成一个AI。"""
        spawn_x = random.randint(1, self.board_width)
        spawn_y = random.choice([self.board_height - 1, self.board_height])  # 9 或 10

        # 确保不会生成在玩家身上 (虽然概率极低)
        if (spawn_x, spawn_y) == self.player_pos:
            spawn_x = (spawn_x % self.board_width) + 1  # 换一列

        self.ai_pos = (spawn_x, spawn_y)

        # 随机选择一个AI配置
        if ai_loadout_key is None or self.ai_defeat_count > 0:  # 第一个AI使用选择的，后续随机
            ai_loadout_key = random.choice(list(AI_LOADOUTS.keys()))

        self.ai_mech = create_ai_mech(ai_loadout_key)
        self.ai_mech.orientation = 'N'  # 总是朝向玩家
        # 重置AI的已用动作列表 (如果需要)
        self.ai_actions_used_this_turn = []

    def check_game_over(self):
        """
        检查游戏是否结束。
        在 'horde' 模式下，AI被击败会重生。
        返回 True 表示游戏结束, False 表示游戏继续。
        """
        player_dead = self.player_mech.parts[
                          'core'].status == 'destroyed' or self.player_mech.get_active_parts_count() < 3
        ai_dead = self.ai_mech.parts['core'].status == 'destroyed' or self.ai_mech.get_active_parts_count() < 3

        if player_dead:
            self.game_over = 'ai_win'
            return True  # 游戏结束

        if ai_dead:
            if self.game_mode == 'horde':
                self.ai_defeat_count += 1
                self._spawn_horde_ai(None)  # 传入 None 以触发随机生成
                return False  # 游戏继续
            else:
                self.game_over = 'player_win'
                return True  # 游戏结束

        return False  # 游戏继续

    def to_dict(self):
        return {
            'player_mech': self.player_mech.to_dict() if self.player_mech else None,
            'ai_mech': self.ai_mech.to_dict(),
            'player_pos': self.player_pos, 'ai_pos': self.ai_pos,
            'current_turn': self.current_turn, 'player_ap': self.player_ap, 'player_tp': self.player_tp,
            'turn_phase': self.turn_phase, 'timing': self.timing,
            'opening_move_taken': self.opening_move_taken,
            'game_over': self.game_over,
            'player_actions_used_this_turn': self.player_actions_used_this_turn,
            'ai_actions_used_this_turn': self.ai_actions_used_this_turn,
            # [新增] 序列化新状态
            'game_mode': self.game_mode,
            'ai_defeat_count': self.ai_defeat_count,
        }

    @classmethod
    def from_dict(cls, data):
        game_state = cls.__new__(cls)
        game_state.board_width = 10
        game_state.board_height = 10

        if data.get('player_mech'):
            game_state.player_mech = Mech.from_dict(data['player_mech'])
        else:
            game_state.player_mech = None

        game_state.ai_mech = Mech.from_dict(data['ai_mech'])
        game_state.player_pos = tuple(data.get('player_pos', (0, 0)))
        game_state.ai_pos = tuple(data.get('ai_pos', (0, 0)))
        game_state.current_turn = data.get('current_turn', 'player')
        game_state.player_ap = data.get('player_ap', 2)
        game_state.player_tp = data.get('player_tp', 1)
        game_state.turn_phase = data.get('turn_phase', 'timing')
        game_state.timing = data.get('timing', None)
        game_state.opening_move_taken = data.get('opening_move_taken', False)
        game_state.game_over = data.get('game_over', None)

        game_state.player_actions_used_this_turn = data.get('player_actions_used_this_turn', [])
        game_state.ai_actions_used_this_turn = data.get('ai_actions_used_this_turn', [])

        # [新增] 反序列化新状态
        game_state.game_mode = data.get('game_mode', 'duel')  # 默认新模式为 'duel'
        game_state.ai_defeat_count = data.get('ai_defeat_count', 0)
        return game_state

    def calculate_move_range(self, start_pos, move_distance):
        """
         使用 A* (Dijkstra) 算法计算从 'start_pos' 出发在 'move_distance' 内所有可达的格子。
        会计算因“近战锁定”导致的额外移动成本。
        """
        pq = [(0, start_pos)]  # (cost, pos)
        visited = {start_pos: 0}
        valid_moves = []

        # 确定锁定者 (AI)
        locker_mech = self.ai_mech
        locker_pos = self.ai_pos
        locker_can_lock = locker_mech.has_melee_action() and locker_mech.parts['core'].status != 'destroyed'

        while pq:
            cost, (x, y) = heapq.heappop(pq)

            if cost > move_distance:
                continue

            if cost > 0:
                valid_moves.append((x, y))

            # [采用] 检查当前格子是否被锁定
            current_is_locked = False
            if locker_can_lock:
                current_is_locked = _is_tile_locked_by_opponent(
                    self, (x, y), self.player_mech, locker_pos, locker_mech
                )

            for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
                nx, ny = x + dx, y + dy
                next_pos = (nx, ny)

                if not (1 <= nx <= self.board_width and 1 <= ny <= self.board_height):
                    continue
                if next_pos == self.ai_pos:  # 不能移动到 AI 格子上
                    continue

                # --- [采用] 移动成本计算 ---
                move_cost = 1
                if current_is_locked:
                    move_cost += 1
                new_cost = cost + move_cost
                # --- 移动成本计算结束 ---

                if new_cost <= move_distance and (next_pos not in visited or new_cost < visited[next_pos]):
                    visited[next_pos] = new_cost
                    heapq.heappush(pq, (new_cost, next_pos))

        return list(set(valid_moves))  # 去重

    def calculate_attack_range(self, attacker_mech, start_pos, action, current_tp=0):
        """
        计算一个攻击动作（近战或射击）的有效目标。
        处理近战朝向、射击视线和动态射程（如【静止】效果）。
        """
        targets = []
        target_pos = self.ai_pos
        sx, sy = start_pos
        tx, ty = target_pos
        orientation = attacker_mech.orientation

        is_valid_target = False

        if action.action_type == '近战':
            valid_melee_targets = []
            if orientation == 'N':  # Y-
                valid_melee_targets = [(sx - 1, sy - 1), (sx, sy - 1), (sx + 1, sy - 1)]
            elif orientation == 'S':  # Y+
                valid_melee_targets = [(sx - 1, sy + 1), (sx, sy + 1), (sx + 1, sy + 1)]
            elif orientation == 'E':  # X+
                valid_melee_targets = [(sx + 1, sy - 1), (sx + 1, sy), (sx + 1, sy + 1)]
            elif orientation == 'W':  # X-
                valid_melee_targets = [(sx - 1, sy - 1), (sx - 1, sy), (sx - 1, sy + 1)]

            if target_pos in valid_melee_targets:
                is_valid_target = True

        elif action.action_type == '射击':
            if not is_in_forward_arc(start_pos, orientation, target_pos):
                return []

            # [新增] 计算动态射程
            final_range = action.range_val
            if action.effects:
                bonus = action.effects.get("static_range_bonus", 0)
                if bonus > 0 and current_tp >= 1:  # 检查TP是否>=1
                    final_range += bonus

            dist = _get_distance(start_pos, target_pos)
            if dist <= final_range:  # [修改] 使用 final_range
                is_valid_target = True

        if is_valid_target:
            back_attack = is_back_attack(start_pos, target_pos, self.ai_mech.orientation)
            targets.append({'pos': target_pos, 'is_back_attack': back_attack})
        return targets

