import math
import heapq
from data_models import Mech, Part, Action
# [修正] 导入所有部件和动作，以及 AI_LOADOUTS
from parts_database import (
    ALL_PARTS, CORES, LEGS, LEFT_ARMS, RIGHT_ARMS, BACKPACKS,
    ACTION_BENPAO, ACTION_JINGJU, ACTION_JUJI, ACTION_PAOJI,
    ACTION_CIJI, ACTION_DIANSHE, ACTION_HUIZHAN, ACTION_TIAOYUE,
    ACTION_SUSHE, ACTION_DIANSHE_ZHAN, ACTION_DIANSHE_CI, ACTION_SUSHE_BIPAO,
    ACTION_BENPAO_MA, # [修正] 导入漏掉的动作
    # Ensure effects are imported if needed, although they are not used in this file directly
    # Example: EFFECT_FLIGHT_MOVEMENT
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
    [修改] 移除朝向检查，现在锁定周围8格。
    """
    if not b_mech or b_mech.parts['core'].status == 'destroyed':
        return False # 对手不存在或核心已毁，无法锁定
    if not b_mech.has_melee_action():
        return False # 对手没有近战能力，无法锁定
    if not _is_adjacent(tile_pos, b_pos):
        return False # 必须相邻才能锁定

    # [移除] 不再检查朝向
    # if not is_in_forward_arc(b_pos, b_mech.orientation, tile_pos):
    #    return False

    return True # 满足以上条件即可锁定


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
        # 从数据库字典创建部件实例的副本，防止修改原始数据
        core_part = Part.from_dict(CORES[selection['core']].to_dict())
        legs_part = Part.from_dict(LEGS[selection['legs']].to_dict())
        left_arm_part = Part.from_dict(LEFT_ARMS[selection['left_arm']].to_dict())
        right_arm_part = Part.from_dict(RIGHT_ARMS[selection['right_arm']].to_dict())
        backpack_part = Part.from_dict(BACKPACKS[selection['backpack']].to_dict())

    except KeyError as e:
        print(f"创建机甲时出错：找不到部件 {e}。使用默认部件。")
        # 使用列表中的第一个作为后备，确保创建副本
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
        'right_arm': 'LGP-80 长程火炮',
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
        'backpack': 'TB-600 跳跃背包'
    }
}

AI_LOADOUT_LIGHTB = {
    'name': "AI机甲 (高速近战型)",
    'selection': {
        'core': 'GK-08 "哨兵"核心',
        'legs': 'RL-03D “快马”高速下肢',
        'left_arm': '62型 臂盾 + CC-20 单手剑（左）',
        'right_arm': '63型 臂炮 + CC-20 单手剑（右）',
        'backpack': 'TB-600 跳跃背包'
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
        print(f"警告: AI配置键 '{ai_loadout_key}' 无效。将使用 'standard' 后备AI。")
        ai_loadout_key = "standard"

    chosen_loadout = AI_LOADOUTS[ai_loadout_key]
    selection = chosen_loadout['selection']
    name = chosen_loadout['name']

    # 验证所选部件是否存在于数据库中
    missing_parts = [part_name for part_name in selection.values() if part_name not in ALL_PARTS]
    if missing_parts:
        print(f"警告: AI配置 '{name}' 中的部件 {missing_parts} 在数据库中不存在。将使用 'standard' 后备AI。")
        ai_loadout_key = "standard" # 重置key
        chosen_loadout = AI_LOADOUTS[ai_loadout_key] # 重新获取标准配置
        selection = chosen_loadout['selection']
        name = chosen_loadout['name']
        # 再次验证标准配置是否存在 (理论上应该存在)
        missing_standard_parts = [part_name for part_name in selection.values() if part_name not in ALL_PARTS]
        if missing_standard_parts:
             print(f"严重错误: 标准AI配置中的部件 {missing_standard_parts} 也不存在！请检查 parts_database.py。")
             # 这里可能需要更健壮的错误处理，比如抛出异常或返回 None
             return None # 无法创建AI机甲

    # 使用确认有效的配置创建机甲
    mech = create_mech_from_selection(name, selection)
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
            if self.player_mech: self.player_mech.orientation = 'N'
            self._spawn_horde_ai(ai_loadout_key)  # 生成第一个AI
        elif self.game_mode == 'duel':
            # 决斗模式：(1,5) vs (10,5) 相对
            self.player_pos = (1, 5)
            if self.player_mech: self.player_mech.orientation = 'E'
            self.ai_pos = (10, 5)
            self.ai_mech = create_ai_mech(ai_loadout_key)
            if self.ai_mech: self.ai_mech.orientation = 'W'
        else:  # 'standard' 或其他后备
            # 原始模式：(5,2) vs (5,8)
            self.player_pos = (5, 2)
            if self.player_mech: self.player_mech.orientation = 'N'
            self.ai_pos = (5, 8)
            self.ai_mech = create_ai_mech(ai_loadout_key)
            if self.ai_mech: self.ai_mech.orientation = 'S'

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
        valid_spawn_points = []
        for y in [self.board_height -1, self.board_height]: # 最后两行
             for x in range(1, self.board_width + 1):
                  pos = (x, y)
                  if pos != self.player_pos: # 不能生成在玩家身上
                       valid_spawn_points.append(pos)

        if not valid_spawn_points:
             print("错误：生存模式下没有有效的AI生成点！")
             # 可能需要添加游戏结束逻辑或在其他位置生成
             self.ai_pos = (1, self.board_height) # 随便选一个点
        else:
            self.ai_pos = random.choice(valid_spawn_points)

        # 随机选择一个AI配置 (除了第一个)
        if self.ai_defeat_count > 0:
            ai_loadout_key = random.choice(list(AI_LOADOUTS.keys()))
        elif ai_loadout_key is None: # 第一个AI也随机（如果在机库没选）
             ai_loadout_key = random.choice(list(AI_LOADOUTS.keys()))

        self.ai_mech = create_ai_mech(ai_loadout_key)
        if self.ai_mech:
             self.ai_mech.orientation = 'N'  # 总是朝向玩家
             self.ai_actions_used_this_turn = [] # 重置AI动作

    def check_game_over(self):
        """
        检查游戏是否结束。
        在 'horde' 模式下，AI被击败会重生。
        返回 True 表示游戏结束, False 表示游戏继续。
        """
        player_dead = not self.player_mech or self.player_mech.parts[
                          'core'].status == 'destroyed' or self.player_mech.get_active_parts_count() < 3
        ai_dead = not self.ai_mech or self.ai_mech.parts[
                      'core'].status == 'destroyed' or self.ai_mech.get_active_parts_count() < 3

        if player_dead:
            self.game_over = 'ai_win'
            return True  # 游戏结束

        if ai_dead:
            if self.game_mode == 'horde':
                self.ai_defeat_count += 1
                self._spawn_horde_ai(None)  # 传入 None 以触发随机生成
                if not self.ai_mech: # 如果生成失败
                     print("严重错误：无法生成新的AI，游戏可能无法继续。")
                     self.game_over = 'error' # 或者其他状态
                     return True
                return False  # 游戏继续
            else:
                self.game_over = 'player_win'
                return True  # 游戏结束

        return False  # 游戏继续

    def to_dict(self):
        return {
            'player_mech': self.player_mech.to_dict() if self.player_mech else None,
            'ai_mech': self.ai_mech.to_dict() if self.ai_mech else None, # 处理AI可能为None的情况
            'player_pos': self.player_pos,
            'ai_pos': self.ai_pos,
            'current_turn': self.current_turn,
            'player_ap': self.player_ap,
            'player_tp': self.player_tp,
            'turn_phase': self.turn_phase,
            'timing': self.timing,
            'opening_move_taken': self.opening_move_taken,
            'game_over': self.game_over,
            'player_actions_used_this_turn': self.player_actions_used_this_turn,
            'ai_actions_used_this_turn': self.ai_actions_used_this_turn,
            'game_mode': self.game_mode,
            'ai_defeat_count': self.ai_defeat_count,
        }

    @classmethod
    def from_dict(cls, data):
        game_state = cls.__new__(cls)
        game_state.board_width = 10
        game_state.board_height = 10

        game_state.player_mech = Mech.from_dict(data['player_mech']) if data.get('player_mech') else None
        game_state.ai_mech = Mech.from_dict(data['ai_mech']) if data.get('ai_mech') else None # 处理AI可能为None的情况

        game_state.player_pos = tuple(data.get('player_pos', (1, 1)))
        game_state.ai_pos = tuple(data.get('ai_pos', (1, 1)))
        game_state.current_turn = data.get('current_turn', 'player')
        game_state.player_ap = data.get('player_ap', 2)
        game_state.player_tp = data.get('player_tp', 1)
        game_state.turn_phase = data.get('turn_phase', 'timing')
        game_state.timing = data.get('timing', None)
        game_state.opening_move_taken = data.get('opening_move_taken', False)
        game_state.game_over = data.get('game_over', None)
        game_state.player_actions_used_this_turn = data.get('player_actions_used_this_turn', [])
        game_state.ai_actions_used_this_turn = data.get('ai_actions_used_this_turn', [])
        game_state.game_mode = data.get('game_mode', 'duel')
        game_state.ai_defeat_count = data.get('ai_defeat_count', 0)
        return game_state

    def calculate_move_range(self, start_pos, move_distance, is_flight=False):
        """
         计算从 'start_pos' 出发在 'move_distance' 内所有可达的格子。
         [修改] 增加 is_flight 参数以处理空中移动逻辑。
         空中移动无视地形、单位和近战锁定成本。
        """
        valid_moves = []
        sx, sy = start_pos

        if is_flight:
            # --- 空中移动逻辑 ---
            for dx in range(-move_distance, move_distance + 1):
                for dy in range(-move_distance, move_distance + 1):
                    # 检查曼哈顿距离
                    if abs(dx) + abs(dy) > move_distance:
                        continue
                    if dx == 0 and dy == 0: # 不能停在原地
                        continue

                    nx, ny = sx + dx, sy + dy
                    next_pos = (nx, ny)

                    # 检查边界
                    if not (1 <= nx <= self.board_width and 1 <= ny <= self.board_height):
                        continue
                    # 检查终点是否被对手占据
                    if self.ai_mech and next_pos == self.ai_pos: # 检查 ai_mech 是否存在
                        continue

                    valid_moves.append(next_pos)

        else:
            # --- 地面移动逻辑 (A*) ---
            pq = [(0, start_pos)]  # (cost, pos)
            visited = {start_pos: 0}

            # 确定锁定者 (AI)
            locker_mech = self.ai_mech
            locker_pos = self.ai_pos
            # 检查 locker_mech 是否存在
            locker_can_lock = locker_mech and locker_mech.has_melee_action() and locker_mech.parts['core'].status != 'destroyed'

            while pq:
                cost, (x, y) = heapq.heappop(pq)

                if cost > move_distance:
                    continue

                # 只有移动了才算有效落点
                if cost > 0:
                    current_pos = (x, y)
                    # 检查落点是否被对手占据 (A* 可能探索到，但不能作为最终落点)
                    if not self.ai_mech or current_pos != self.ai_pos: # 检查 ai_mech
                        valid_moves.append(current_pos)


                current_is_locked = False
                if locker_can_lock:
                    current_is_locked = _is_tile_locked_by_opponent(
                        self, (x, y), self.player_mech, locker_pos, locker_mech
                    )

                for dx_step, dy_step in [(0, 1), (0, -1), (1, 0), (-1, 0)]: # 只检查四向移动
                    nx, ny = x + dx_step, y + dy_step
                    next_pos = (nx, ny)

                    # 检查边界
                    if not (1 <= nx <= self.board_width and 1 <= ny <= self.board_height):
                        continue
                    # [修改] 检查是否碰到对手 (路径可以通过，但不能停下)
                    # A* 算法本身会探索路径，但在添加 valid_moves 时检查了落点
                    # if self.ai_mech and next_pos == self.ai_pos:
                    #     continue

                    move_cost = 1
                    if current_is_locked:
                        move_cost += 1 # 脱离锁定需要额外成本
                    new_cost = cost + move_cost

                    # 检查目标格子是否被占据 (如果被占据，路径成本可以计算，但不应加入 visited 或 pq)
                    is_occupied_by_ai = self.ai_mech and next_pos == self.ai_pos
                    if is_occupied_by_ai:
                        # 虽然不能停留，但可以计算经过这里的成本（如果规则允许穿过）
                        # 如果不允许穿过，这里应该 continue
                        pass # 或者根据规则决定是否 continue

                    if new_cost <= move_distance and (next_pos not in visited or new_cost < visited[next_pos]) and not is_occupied_by_ai:
                        visited[next_pos] = new_cost
                        heapq.heappush(pq, (new_cost, next_pos))

        # 确保最终返回的列表不包含AI当前位置
        final_valid_moves = [move for move in set(valid_moves) if not self.ai_mech or move != self.ai_pos]
        return final_valid_moves


    def calculate_attack_range(self, attacker_mech, start_pos, action, current_tp=0):
        """
        计算一个攻击动作（近战或射击）的有效目标。
        处理近战朝向、射击视线和动态射程（如【静止】、【双手】效果）。
        """
        targets = []
        # 目标总是对手（如果存在）
        if not self.ai_mech: return [] # 如果没有AI，不能攻击
        target_pos = self.ai_pos

        sx, sy = start_pos
        tx, ty = target_pos
        orientation = attacker_mech.orientation

        is_valid_target = False

        if action.action_type == '近战':
            # 近战范围检查
            valid_melee_targets = []
            if orientation == 'N': valid_melee_targets = [(sx - 1, sy - 1), (sx, sy - 1), (sx + 1, sy - 1)]
            elif orientation == 'S': valid_melee_targets = [(sx - 1, sy + 1), (sx, sy + 1), (sx + 1, sy + 1)]
            elif orientation == 'E': valid_melee_targets = [(sx + 1, sy - 1), (sx + 1, sy), (sx + 1, sy + 1)]
            elif orientation == 'W': valid_melee_targets = [(sx - 1, sy - 1), (sx - 1, sy), (sx - 1, sy + 1)]

            if target_pos in valid_melee_targets:
                is_valid_target = True

        elif action.action_type == '射击':
            # 检查视线
            if not is_in_forward_arc(start_pos, orientation, target_pos):
                return [] # 不在视线内

            # 计算最终射程
            final_range = action.range_val
            if action.effects:
                # 检查【静止】效果
                static_bonus = action.effects.get("static_range_bonus", 0)
                if static_bonus > 0 and current_tp >= 1: # 检查TP是否>=1
                    final_range += static_bonus

                # 检查【双手】效果
                two_handed_bonus = action.effects.get("two_handed_range_bonus", 0)
                if two_handed_bonus > 0:
                     # 确定持有武器的手臂 和 另一只手臂
                     action_slot = None
                     for slot, part in attacker_mech.parts.items():
                         if part.status != 'destroyed':
                              for act in part.actions:
                                   if act.name == action.name: # 找到执行此动作的部件槽位
                                       action_slot = slot
                                       break
                         if action_slot: break

                     if action_slot in ['left_arm', 'right_arm']:
                          other_arm_slot = 'right_arm' if action_slot == 'left_arm' else 'left_arm'
                          other_arm_part = attacker_mech.parts.get(other_arm_slot)
                          if other_arm_part and other_arm_part.status != 'destroyed' and "【空手】" in other_arm_part.tags:
                               final_range += two_handed_bonus
                     else:
                          # 如果动作不在手臂上（例如背包武器），则双手效果不适用
                          pass


            # 检查距离
            dist = _get_distance(start_pos, target_pos)
            if dist <= final_range:
                is_valid_target = True

        if is_valid_target:
            back_attack = is_back_attack(start_pos, target_pos, self.ai_mech.orientation)
            targets.append({'pos': target_pos, 'is_back_attack': back_attack})

        return targets

