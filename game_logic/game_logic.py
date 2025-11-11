import math
import heapq
import random
# [v_REFACTOR]
# 文件已移至 game_logic/
# 更新导入以使用相对路径 (..) 来引用根目录的 parts_database
# 并使用相对路径 (.) 来引用此包中的 data_models
from .data_models import (
    Mech, Part, Action, GameEntity, Projectile, Drone, Pilot  # [MODIFIED v2.2] 导入 Pilot
)
# [v_REFACTOR] 使用 '..' 访问上一级目录
# [v_REFACTOR_FIX] 修复 ImportError。使用从项目根目录开始的绝对导入
from parts_database import (
    ALL_PARTS, CORES, LEGS, LEFT_ARMS, RIGHT_ARMS, BACKPACKS,
    PROJECTILE_TEMPLATES,  # [v1.17] 导入抛射物模板
    AI_LOADOUTS  # [v1.22] 从 parts_database 导入
)


# --- [v1.17] 辅助函数 ---

def _get_distance(pos1, pos2):
    """计算两个位置的曼哈顿距离。"""
    if not pos1 or not pos2: return 999
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
    [v1.17] 更新为使用实体。
    """
    if not b_mech or b_mech.status == 'destroyed':
        return False

    # [新规则：宕机检查]
    if b_mech.stance == 'downed':
        return False  # 宕机单位无法锁定

    if not b_mech.has_melee_action():
        return False
    if not _is_adjacent(tile_pos, b_pos):
        return False
    # 规则：锁定周围8格
    return True


def get_player_lock_status(game_state, player_mech):
    """[v1.17] 检查玩家是否被任何AI机甲锁定。"""
    if not player_mech: return False, None
    for entity in game_state.entities.values():
        if entity.controller == 'ai' and entity.entity_type == 'mech' and entity.status != 'destroyed':
            is_locked = _is_tile_locked_by_opponent(
                game_state,
                player_mech.pos, player_mech,
                entity.pos, entity
            )
            if is_locked:
                return True, entity.pos
    return False, None


def get_ai_lock_status(game_state, ai_mech):
    """[v1.17] 检查AI是否被任何玩家机甲锁定。"""
    if not ai_mech: return False, None
    for entity in game_state.entities.values():
        if entity.controller == 'player' and entity.entity_type == 'mech' and entity.status != 'destroyed':
            is_locked = _is_tile_locked_by_opponent(
                game_state,
                ai_mech.pos, ai_mech,
                entity.pos, entity
            )
            if is_locked:
                return True, entity.pos
    return False, None


# --- [v_MODIFIED] 逻辑从 ai_system.py 移动到这里 ---

# [v1.32 新增] 拦截检查辅助函数
# [v1.33 修复] 重命名 (移除 _ ) 以便导入
def check_interception(projectile, game_state):
    """
    检查是否有任何敌方单位可以拦截此抛射物（在它当前的位置）。
    返回 (log_list, attacks_to_resolve_list)
    """
    log = []
    attacks_to_resolve = []
    landing_pos = projectile.pos

    # 遍历所有实体，寻找拦截者
    for entity in game_state.entities.values():
        # 拦截者必须： 1. 是抛射物的敌人  2. 是机甲  3. 存活
        if entity.controller != projectile.controller and entity.entity_type == 'mech' and entity.status != 'destroyed':

            interceptor_actions = entity.get_interceptor_actions()
            if not interceptor_actions:
                continue  # 这个机甲没有拦截系统

            # 遍历该机甲的所有拦截动作 (例如，如果它有2个AMS背包)
            for intercept_action, part_slot in interceptor_actions:
                # 检查射程
                intercept_range = intercept_action.range_val
                dist_to_landing = _get_distance(entity.pos, landing_pos)

                if dist_to_landing <= intercept_range:
                    # 检查弹药
                    ammo_key = (entity.id, part_slot, intercept_action.name)
                    current_ammo = game_state.ammo_counts.get(ammo_key, 0)

                    if current_ammo > 0:
                        log.append(
                            f"> [拦截] {entity.name} 的 [{intercept_action.name}] 侦测到 {projectile.name} (在 {landing_pos})！")
                        log.append(f"> [拦截] 距离 {dist_to_landing}格 (范围 {intercept_range}格)。")

                        # 消耗弹药
                        game_state.ammo_counts[ammo_key] -= 1
                        log.append(f"> [拦截] 消耗 1 弹药 (剩余 {game_state.ammo_counts[ammo_key]})。")

                        # [关键] 将拦截攻击添加到待处理队列
                        attacks_to_resolve.append({
                            'attacker': entity,  # 拦截者是攻击方
                            'defender': projectile,  # 抛射物是防御方
                            'action': intercept_action
                        })
                        log.append(f"> [拦截] {entity.name} 立即对 {projectile.name} 发动拦截攻击！")

                        # [v1.32 修复] 移除 break。
                        # 允许一个机甲使用多个拦截系统 (如果装备了多个) 拦截同一个抛射物。
                    else:
                        log.append(
                            f"> [拦截] {entity.name} 侦测到 {projectile.name}，但 [{intercept_action.name}] 弹药耗尽。")
    return log, attacks_to_resolve


def run_projectile_logic(projectile, game_state, timing_to_run='立即'):
    """
    [v_MODIFIED v1.35]
    为单个抛射物实体运行其AI逻辑。
    修复了 '立即' 动作会过早自毁的BUG。
    """
    log = []
    attacks_to_resolve = []

    # 1. 检查是否匹配请求的
    action_tuple = projectile.get_action_by_timing(timing_to_run)
    if not action_tuple or not action_tuple[0]:
        # log.append(f"> [抛射物] {projectile.name} (在 {projectile.pos}) 没有找到时机为 '{timing_to_run}' 的动作。")
        return log, attacks_to_resolve

    action_obj, part_slot = action_tuple

    if timing_to_run == '立即':
        log.append(f"> [抛射物] {projectile.name} (在 {projectile.pos}) 立即执行 [{action_obj.name}]！")

        # [v1.32] 立即检查拦截 (例如，火箭弹发射时)
        # 拦截攻击会优先于抛射物自己的攻击
        intercept_log, intercept_attacks = check_interception(projectile, game_state)
        log.extend(intercept_log)
        attacks_to_resolve.extend(intercept_attacks)

        # 查找目标：在抛射物 *自己* 格子上的所有 *敌方* 单位
        targets = game_state.get_entities_at_pos(projectile.pos, exclude_id=projectile.id)
        for target_entity in targets:
            if target_entity.controller != projectile.controller:
                log.append(f"> [抛射物] 瞄准了同一格子上的 {target_entity.name}！")
                attacks_to_resolve.append({
                    'attacker': projectile,
                    'defender': target_entity,
                    'action': action_obj
                })

        # [v1.35 BUG 修复] 移除以下两行！
        # 抛射物的销毁工作由 combat_system.py 在攻击结算后处理。
        # projectile.status = 'destroyed'
        # log.append(f"> [抛射物] {projectile.name} 已引爆并被移除。")

    elif timing_to_run == '延迟':
        log.append(f"> [抛射物] {projectile.name} (在 {projectile.pos}) 激活【延迟】动作 [{action_obj.name}]！")

        # 1. 查找最近的敌人
        closest_enemy = None
        min_dist = 999
        for entity in game_state.entities.values():
            if entity.controller != projectile.controller and entity.status != 'destroyed':
                dist = _get_distance(projectile.pos, entity.pos)
                if dist < min_dist:
                    min_dist = dist
                    closest_enemy = entity

        if not closest_enemy:
            log.append(f"> [抛射物] {projectile.name} 未找到敌方目标，自我销毁。")
            projectile.status = 'destroyed'
            return log, attacks_to_resolve

        log.append(f"> [抛射物] 锁定最近的目标: {closest_enemy.name} (在 {closest_enemy.pos})。")

        # 2. 计算【空中移动】路径
        move_range = projectile.move_range
        possible_moves = game_state.calculate_move_range(
            projectile,
            move_range,
            is_flight=True  # 【空中移动】
        )

        # 3. 寻找最佳移动位置
        # 目标：移动后距离敌人为0 (同一格) 或尽可能近
        best_pos = projectile.pos
        min_dist_after_move = min_dist

        if min_dist > 0:  # 只有在没有命中时才需要移动
            best_landing_spot = None
            for pos in possible_moves:
                dist_to_target = _get_distance(pos, closest_enemy.pos)
                if dist_to_target < min_dist_after_move:
                    min_dist_after_move = dist_to_target
                    best_landing_spot = pos

                # 如果能直接命中（距离为0），就采用
                if min_dist_after_move == 0:
                    break

            if best_landing_spot:
                best_pos = best_landing_spot
                projectile.last_pos = projectile.pos
                projectile.pos = best_pos
                log.append(
                    f"> [抛射物] {projectile.name} 【空中移动】 {move_range} 格到 {best_pos} (距离目标 {min_dist_after_move} 格)。")
            else:
                log.append(f"> [抛射物] {projectile.name} 无法找到更近的位置，停留在 {projectile.pos}。")

        # 4. [v1.32] 检查拦截 (例如，导弹飞行后)
        # 拦截攻击会优先于抛射物自己的攻击
        intercept_log, intercept_attacks = check_interception(projectile, game_state)
        log.extend(intercept_log)
        attacks_to_resolve.extend(intercept_attacks)

        # 5. 在最终位置引爆 (如果自己还活着)
        # 查找目标：在抛射物 *自己* 格子上的所有 *敌方* 单位
        targets_at_destination = game_state.get_entities_at_pos(projectile.pos, exclude_id=projectile.id)
        for target_entity in targets_at_destination:
            if target_entity.controller != projectile.controller:
                log.append(f"> [抛射物] 在 {projectile.pos} 尝试命中目标 {target_entity.name}！")
                attacks_to_resolve.append({
                    'attacker': projectile,
                    'defender': target_entity,
                    'action': action_obj
                })

        # [v1.29 BUG 修复] 移除此行！攻击结算系统 (combat_system.py) 将在攻击后处理此问题。

    return log, attacks_to_resolve


def run_drone_logic(drone, game_state):
    """
    (骨架) 为单个无人机实体运行其AI逻辑。
    """
    log = []
    attacks_to_resolve = []
    log.append(f"> [无人机] {drone.name} 逻辑（未实现）。")
    return log, attacks_to_resolve


# --- [v1.17] 实体创建函数 ---

# [MODIFIED v2.2] 添加 pilot_name
def create_mech_from_selection(name, selection, entity_id, controller, pilot_name=None):
    """
    [v1.23]
    根据机库页面的部件名称选择，从数据库动态创建一台机甲。
    现在需要 entity_id 和 controller。
    [v2.2]
    现在还会根据 pilot_name 加载 Pilot。
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

    pilot_obj = None
    if pilot_name:
        # [v2.2] 尝试加载 Pilot
        # [v_REFACTOR_FIX] 修复导入错误。从 parts_database 导入
        try:
            from parts_database import PLAYER_PILOTS, AI_PILOTS
            pilot_data_source = PLAYER_PILOTS if controller == 'player' else AI_PILOTS

            if pilot_name in pilot_data_source:
                # [MODIFIED v2.2] 从字典中获取 Pilot 对象
                pilot_obj = pilot_data_source[pilot_name]
            else:
                print(f"警告: 找不到驾驶员 '{pilot_name}' (controller: {controller})。将不分配驾驶员。")
        except ImportError:
            print(f"警告: 无法从 parts_database 导入 PLAYER_PILOTS 或 AI_PILOTS。")

    # [v1.23 修复] 传递所有 GameEntity 所需的参数
    # [MODIFIED v2.2] 传递 pilot_obj
    return Mech(
        id=entity_id,
        controller=controller,
        pos=(1, 1),  # 默认位置, 将在 GameState 中被覆盖
        orientation='N',  # 默认朝向, 将在 GameState 中被覆盖
        name=name,
        core=core_part,
        legs=legs_part,
        left_arm=left_arm_part,
        right_arm=right_arm_part,
        backpack=backpack_part,
        pilot=pilot_obj
    )


def create_ai_mech(ai_loadout_key=None, entity_id="ai_1"):
    """
    [v1.17]
    创建一个AI机甲。
    """
    if ai_loadout_key not in AI_LOADOUTS:
        print(f"警告: AI配置键 '{ai_loadout_key}' 无效。将使用 'standard' 后备AI。")
        ai_loadout_key = "standard"

    chosen_loadout = AI_LOADOUTS[ai_loadout_key]
    selection = chosen_loadout['selection']
    name = chosen_loadout['name']

    missing_parts = [part_name for part_name in selection.values() if part_name not in ALL_PARTS]
    if missing_parts:
        print(f"警告: AI配置 '{name}' 中的部件 {missing_parts} 在数据库中不存在。将使用 'standard' 后备AI。")
        chosen_loadout = AI_LOADOUTS["standard"]
        selection = chosen_loadout['selection']
        name = chosen_loadout['name']
        missing_standard_parts = [part_name for part_name in selection.values() if part_name not in ALL_PARTS]
        if missing_standard_parts:
            print(f"严重错误: 标准AI配置中的部件 {missing_standard_parts} 也不存在！请检查 parts_database.py。")
            return None

    mech = create_mech_from_selection(
        name,
        selection,
        entity_id=entity_id,
        controller='ai',
        pilot_name=chosen_loadout.get("pilot")  # [MODIFIED v2.2] 从配置中获取 pilot
    )
    return mech


class GameState:
    """
    [v1.26]
    管理整个游戏的状态，现在基于实体字典。
    """

    # [MODIFIED v2.2] 添加 player_pilot_name
    def __init__(self, player_mech_selection=None, ai_loadout_key=None, game_mode='duel', player_pilot_name=None):
        self.board_width = 10
        self.board_height = 10
        self.entities = {}  # [v1.17] 核心状态：{ 'player_1': <Mech>, 'ai_1': <Mech>, 'proj_123': <Projectile> }

        self.game_mode = game_mode
        self.ai_defeat_count = 0
        self.game_over = None

        # [v1.17] 弹药追踪
        self.ammo_counts = {}  # { ('player_1', 'left_arm', '火箭弹'): 2 }

        # [v1.26] 视觉事件
        self.visual_events = []

        # --- 初始化玩家机甲 ---
        if player_mech_selection:
            player_mech = create_mech_from_selection(
                "玩家机甲",
                player_mech_selection,
                entity_id='player_1',
                controller='player',
                pilot_name=player_pilot_name  # [MODIFIED v2.2]
            )
            # [v1.17] 初始化玩家机甲的弹药
            for part_slot, part in player_mech.parts.items():
                if part:
                    for action in part.actions:
                        if action.ammo > 0:
                            ammo_key = ('player_1', part_slot, action.name)
                            self.ammo_counts[ammo_key] = action.ammo
            self.entities['player_1'] = player_mech

        # --- 初始化AI机甲并设置位置 ---
        ai_mech = create_ai_mech(ai_loadout_key, entity_id='ai_1')
        if ai_mech:
            # [BUG 修复 v1.30] 初始化 AI 机甲的弹药
            for part_slot, part in ai_mech.parts.items():
                if part:
                    for action in part.actions:
                        if action.ammo > 0:
                            # [BUG 修复] 使用 ai_mech.id (e.g., 'ai_1')
                            ammo_key = (ai_mech.id, part_slot, action.name)
                            self.ammo_counts[ammo_key] = action.ammo
            self.entities[ai_mech.id] = ai_mech

            # [BUG 修复 v1.30] ai_mech 变量现在可能为 None，移动到 if 块内
            player_mech = self.get_player_mech()  # 获取实例

            if self.game_mode == 'horde':
                if player_mech: player_mech.pos, player_mech.orientation = (5, 2), 'N'
                self._spawn_horde_ai(ai_loadout_key)
            elif self.game_mode == 'duel':
                if player_mech: player_mech.pos, player_mech.orientation = (1, 5), 'E'
                if ai_mech: ai_mech.pos, ai_mech.orientation = (10, 5), 'W'
            elif self.game_mode == 'range':
                if player_mech: player_mech.pos, player_mech.orientation = (5, 3), 'S'
                if ai_mech: ai_mech.pos, ai_mech.orientation = (5, 8), 'N'
            else:  # 'standard'
                if player_mech: player_mech.pos, player_mech.orientation = (5, 2), 'N'
                if ai_mech: ai_mech.pos, ai_mech.orientation = (5, 8), 'S'

        # [BUG 修复 v1.30] 如果 ai_mech 为 None (例如创建失败)，player_mech 仍需被设置
        elif player_mech_selection:
            player_mech = self.get_player_mech()
            if player_mech: player_mech.pos, player_mech.orientation = (5, 2), 'N'

    def _spawn_horde_ai(self, ai_loadout_key):
        """[v1.17] 生存模式下，在底部两行随机生成一个AI。"""
        player_pos = self.get_player_mech().pos if self.get_player_mech() else None
        valid_spawn_points = []
        for y in [self.board_height - 1, self.board_height]:
            for x in range(1, self.board_width + 1):
                pos = (x, y)
                if pos != player_pos:
                    valid_spawn_points.append(pos)

        spawn_pos = random.choice(valid_spawn_points) if valid_spawn_points else (1, self.board_height)

        if self.ai_defeat_count > 0:
            ai_loadout_key = random.choice(list(AI_LOADOUTS.keys()))
        elif ai_loadout_key is None:
            ai_loadout_key = random.choice(list(AI_LOADOUTS.keys()))

        ai_id = f"ai_{self.ai_defeat_count + 1}"
        ai_mech = create_ai_mech(ai_loadout_key, entity_id=ai_id)
        if ai_mech:
            ai_mech.pos = spawn_pos
            ai_mech.orientation = 'N'

            # [BUG 修复 v1.30] 为新生成的 AI 初始化弹药
            for part_slot, part in ai_mech.parts.items():
                if part:
                    for action in part.actions:
                        if action.ammo > 0:
                            ammo_key = (ai_mech.id, part_slot, action.name)
                            self.ammo_counts[ammo_key] = action.ammo

            self.entities[ai_id] = ai_mech

    def _spawn_range_ai(self):
        """[v1.17] 靶场模式下，在 (5, 8) 重新生成一个AI。"""
        # 移除所有旧的AI和抛射物
        ids_to_remove = [eid for eid, e in self.entities.items() if e.controller == 'ai']
        for eid in ids_to_remove:
            del self.entities[eid]

        ai_loadout_key = random.choice(list(AI_LOADOUTS.keys()))
        ai_id = f"ai_range_{self.ai_defeat_count + 1}"
        ai_mech = create_ai_mech(ai_loadout_key, entity_id=ai_id)
        if ai_mech:
            ai_mech.pos = (5, 8)
            ai_mech.orientation = 'N'

            # [BUG 修复 v1.30] 为新生成的 AI 初始化弹药
            for part_slot, part in ai_mech.parts.items():
                if part:
                    for action in part.actions:
                        if action.ammo > 0:
                            ammo_key = (ai_mech.id, part_slot, action.name)
                            self.ammo_counts[ammo_key] = action.ammo

            self.entities[ai_id] = ai_mech

        # 重置玩家状态
        player_mech = self.get_player_mech()
        if player_mech:
            player_mech.player_ap = 2
            player_mech.player_tp = 1
            player_mech.turn_phase = 'timing'
            player_mech.timing = None
            player_mech.opening_move_taken = False
            player_mech.actions_used_this_turn = []
            player_mech.pending_effect_data = None
            player_mech.last_pos = None

            # [BUG 修复 v1.30] 重置玩家弹药
            for part_slot, part in player_mech.parts.items():
                if part:
                    for action in part.actions:
                        if action.ammo > 0:
                            ammo_key = (player_mech.id, part_slot, action.name)
                            self.ammo_counts[ammo_key] = action.ammo

        self.game_over = None
        self.visual_events = []  # [v1.26] 重置事件

    # [v1.26] 添加视觉事件的辅助方法
    def add_visual_event(self, event_type, **kwargs):
        """
        向当前状态添加一个视觉反馈事件。
        """
        if not hasattr(self, 'visual_events'):
            self.visual_events = []
        event = {'type': event_type, **kwargs}
        self.visual_events.append(event)

    # [v1.17] 新增：生成抛射物
    def spawn_projectile(self, launcher_entity, target_pos, projectile_key):
        """
        [v1.27]
        在目标位置生成一个抛射物实体。
        """
        if projectile_key not in PROJECTILE_TEMPLATES:
            print(f"错误: 找不到抛射物模板 '{projectile_key}'")
            return None, None

        template = PROJECTILE_TEMPLATES[projectile_key]

        # [v1.25 修复] 'a' 已经是一个字典了，不需要 a.to_dict()
        actions = [Action.from_dict(a) for a in template.get('actions', [])]

        new_id = f"proj_{random.randint(10000, 99999)}"

        # [v1.27 修复] 移除 'orientation'，因为它在 Projectile.__init__ 中是硬编码的
        # [v_MODIFIED] 添加新属性
        new_projectile = Projectile(
            id=new_id,
            controller=launcher_entity.controller,  # 抛射物的控制权归发射者
            pos=target_pos,
            name=template.get('name', '抛射物'),
            evasion=template.get('evasion', 0),
            stance=template.get('stance', 'agile'),
            actions=actions,
            life_span=template.get('life_span', 1),
            electronics=template.get('electronics', 0),  # [新增]
            move_range=template.get('move_range', 0)  # [新增]
        )

        self.entities[new_id] = new_projectile
        print(f"生成了实体: {new_id} at {target_pos}")
        return new_id, new_projectile

    def check_game_over(self):
        """
        [v1.17]
        检查游戏是否结束。现在基于实体列表。
        """
        player_mech = self.get_player_mech()
        ai_mech = self.get_ai_mech()  # 假设是1v1

        player_dead = not player_mech or player_mech.status == 'destroyed' or player_mech.get_active_parts_count() < 3
        ai_dead = not ai_mech or ai_mech.status == 'destroyed' or ai_mech.get_active_parts_count() < 3

        if player_dead:
            self.game_over = 'ai_win'
            return True

        if ai_dead:
            if self.game_mode == 'horde':
                self.ai_defeat_count += 1
                self.entities[ai_mech.id].status = 'destroyed'  # 标记旧AI为已摧毁
                self._spawn_horde_ai(None)
                if self.get_ai_mech():  # 检查新AI是否生成成功
                    self.get_ai_mech().last_ai_pos = None
                return False  # 游戏继续
            elif self.game_mode == 'range':
                self.game_over = 'ai_defeated_in_range'
                return True  # 游戏暂停
            else:
                self.game_over = 'player_win'
                return True

        return False

    # --- [v1.17] 实体辅助函数 ---

    def get_player_mech(self):
        """获取 'player_1' 机甲实体。"""
        return self.entities.get('player_1')

    def get_ai_mech(self):
        """获取第一个 'ai' 控制的机甲实体。"""
        # [v1.17] 假设在 duel/range 模式下只有一个 'ai_1' 或 'ai_range_X'
        # 在 horde 模式下, 它会找到当前的 'ai_X'
        for entity in self.entities.values():
            if entity.controller == 'ai' and entity.entity_type == 'mech' and entity.status != 'destroyed':
                return entity
        return None  # 如果所有AI都被击败（例如在 horde 模式的间隙）

    # [v1.24] 新增
    def get_entity_by_id(self, entity_id):
        """通过 ID 获取任何实体。"""
        return self.entities.get(entity_id)

    def get_all_renderable_entities(self):
        """[v1.17] 返回所有未被摧毁的实体的列表，用于Jinja渲染。"""
        return [e for e in self.entities.values() if e.status != 'destroyed']

    def get_all_entities_as_dict(self):
        """[v1.20] 返回所有未被摧毁的实体的 *可序列化字典* 列表。"""
        return [e.to_dict() for e in self.entities.values() if e.status != 'destroyed']

    def get_entities_at_pos(self, pos, exclude_id=None):
        """[v1.17] 获取特定坐标上的所有实体列表。"""
        entities_found = []
        for entity in self.entities.values():
            if entity.pos == pos and entity.status != 'destroyed':
                if exclude_id and entity.id == exclude_id:
                    continue
                entities_found.append(entity)
        return entities_found

    def get_occupied_tiles(self, exclude_id=None):
        """[v1.17] 获取所有被实体占据的格子。"""
        occupied = set()
        for entity in self.entities.values():
            if entity.status != 'destroyed':
                if exclude_id and entity.id == exclude_id:
                    continue
                occupied.add(entity.pos)
        return occupied

    def to_dict(self):
        """[v1.26] 序列化整个游戏状态，包括所有实体。"""
        return {
            'entities': {eid: entity.to_dict() for eid, entity in self.entities.items()},
            'game_mode': self.game_mode,
            'ai_defeat_count': self.ai_defeat_count,
            'game_over': self.game_over,
            'ammo_counts': self.ammo_counts,
            'visual_events': self.visual_events,  # [v1.26]
        }

    @classmethod
    def from_dict(cls, data):
        """[v1.26] 从字典重建游戏状态，包括所有实体。"""
        game_state = cls.__new__(cls)
        game_state.board_width = 10
        game_state.board_height = 10

        game_state.entities = {}
        entities_data = data.get('entities', {})
        for eid, entity_data in entities_data.items():
            if entity_data:
                # [v1.19 修复] 使用 GameEntity.from_dict 进行智能重建
                game_state.entities[eid] = GameEntity.from_dict(entity_data)

        game_state.game_mode = data.get('game_mode', 'duel')
        game_state.ai_defeat_count = data.get('ai_defeat_count', 0)
        game_state.game_over = data.get('game_over', None)
        game_state.ammo_counts = data.get('ammo_counts', {})
        game_state.visual_events = data.get('visual_events', [])  # [v1.26]
        return game_state

    def calculate_move_range(self, entity, move_distance, is_flight=False):
        """
         [v_MODIFIED]
         计算从 'start_pos' 出发在 'move_distance' 内所有可达的格子。
         现在基于实体。
         新增: is_flight (空中移动) 逻辑。
        """
        valid_moves = []
        start_pos = entity.pos
        sx, sy = start_pos

        # [v1.17] 获取所有被占据的格子，排除移动者自己
        occupied_tiles = self.get_occupied_tiles(exclude_id=entity.id)

        # [v1.17] 确定锁定者 (所有与移动者敌对的单位)
        lockers = []
        for e in self.entities.values():
            if e.controller != entity.controller and e.entity_type == 'mech' and e.status != 'destroyed':
                if e.has_melee_action():
                    lockers.append(e)

        if is_flight:
            # --- [新增] 空中移动逻辑 (无视锁定，可穿过单位) ---
            pq = [(0, start_pos)]  # (cost, pos)
            visited = {start_pos: 0}

            while pq:
                cost, (x, y) = heapq.heappop(pq)
                current_pos = (x, y)

                if cost > move_distance:
                    continue

                if cost > 0:
                    valid_moves.append(current_pos)

                for dx_step, dy_step in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
                    nx, ny = x + dx_step, y + dy_step
                    next_pos = (nx, ny)

                    if not (1 <= nx <= self.board_width and 1 <= ny <= self.board_height): continue

                    # [空中移动] 飞行单位 *可以* 降落在被占据的格子上
                    # 但它们不能在起始格降落
                    if next_pos == start_pos: continue

                    new_cost = cost + 1

                    if new_cost <= move_distance and (next_pos not in visited or new_cost < visited[next_pos]):
                        visited[next_pos] = new_cost
                        heapq.heappush(pq, (new_cost, next_pos))
        else:
            # --- 地面移动逻辑 (A*) ---
            pq = [(0, start_pos)]  # (cost, pos)
            visited = {start_pos: 0}

            while pq:
                cost, (x, y) = heapq.heappop(pq)
                current_pos = (x, y)

                if cost > move_distance:
                    continue

                if cost > 0:
                    valid_moves.append(current_pos)

                # 检查当前格子是否被锁定
                current_is_locked = False
                for locker_mech in lockers:
                    if _is_tile_locked_by_opponent(self, current_pos, entity, locker_mech.pos, locker_mech):
                        current_is_locked = True
                        break

                for dx_step, dy_step in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
                    nx, ny = x + dx_step, y + dy_step
                    next_pos = (nx, ny)

                    if not (1 <= nx <= self.board_width and 1 <= ny <= self.board_height): continue
                    if next_pos in occupied_tiles: continue  # 路径不能穿过其他单位

                    move_cost = 1
                    if current_is_locked:
                        # 检查新格子是否仍然被锁定
                        next_is_locked = False
                        for locker_mech in lockers:
                            if _is_tile_locked_by_opponent(self, next_pos, entity, locker_mech.pos, locker_mech):
                                next_is_locked = True
                                break
                        if not next_is_locked:
                            move_cost += 1  # 脱离锁定需要额外成本

                    new_cost = cost + move_cost

                    if new_cost <= move_distance and (next_pos not in visited or new_cost < visited[next_pos]):
                        visited[next_pos] = new_cost
                        heapq.heappush(pq, (new_cost, next_pos))

        return list(set(valid_moves))  # 去重

    def calculate_attack_range(self, attacker_entity, action):
        """
        [v1.28]
        计算一个攻击动作（近战、射击、抛射）的有效目标。
        返回 (valid_targets, valid_launch_cells)
        valid_targets: [ {'pos': (x,y), 'entity': <Entity>, 'is_back_attack': bool}, ... ]
        valid_launch_cells: [ (x,y), ... ] (仅用于抛射)
        """
        valid_targets = []
        valid_launch_cells = []  # 用于抛射

        start_pos = attacker_entity.pos
        orientation = attacker_entity.orientation

        # [v1.21 修复] 从攻击者实体获取TP
        current_tp = 0
        if isinstance(attacker_entity, Mech):
            current_tp = attacker_entity.player_tp

        # 1. 确定射程和风格
        final_range = action.range_val
        # [v_MODIFIED] 修复 'curved_fire' 为 'curved'
        is_curved = (action.action_style == 'curved')

        if action.effects:
            static_bonus = action.effects.get("static_range_bonus", 0)
            if static_bonus > 0 and current_tp >= 1:
                final_range += static_bonus

            if isinstance(attacker_entity, Mech):  # 只有机甲能用双手
                two_handed_bonus = action.effects.get("two_handed_range_bonus", 0)
                if two_handed_bonus > 0:
                    action_slot = None
                    for slot, part in attacker_entity.parts.items():
                        if part and part.status != 'destroyed':
                            if any(act.name == action.name for act in part.actions):
                                action_slot = slot
                                break
                    if action_slot in ['left_arm', 'right_arm']:
                        other_arm_slot = 'right_arm' if action_slot == 'left_arm' else 'left_arm'
                        other_arm_part = attacker_entity.parts.get(other_arm_slot)
                        if other_arm_part and other_arm_part.status != 'destroyed' and "【空手】" in other_arm_part.tags:
                            final_range += two_handed_bonus

        # 2. 根据动作类型遍历目标
        if action.action_type == '近战':
            sx, sy = start_pos
            valid_melee_cells = []
            if orientation == 'N':
                valid_melee_cells = [(sx - 1, sy - 1), (sx, sy - 1), (sx + 1, sy - 1)]
            elif orientation == 'S':
                valid_melee_cells = [(sx - 1, sy + 1), (sx, sy + 1), (sx + 1, sy + 1)]
            elif orientation == 'E':
                valid_melee_cells = [(sx + 1, sy - 1), (sx + 1, sy), (sx + 1, sy + 1)]
            elif orientation == 'W':
                valid_melee_cells = [(sx - 1, sy - 1), (sx - 1, sy), (sx - 1, sy + 1)]

            for cell in valid_melee_cells:
                for entity in self.get_entities_at_pos(cell):
                    if entity.controller != attacker_entity.controller:  # 是敌人
                        back_attack = False
                        if isinstance(entity, Mech):  # 只有机甲才能被背击
                            back_attack = is_back_attack(start_pos, entity.pos, entity.orientation)
                        valid_targets.append({'pos': entity.pos, 'entity': entity, 'is_back_attack': back_attack})

        # [v1.28 修复] 合并射击和抛射的 *目标* 查找逻辑
        elif action.action_type == '射击' or action.action_type == '抛射':
            # 遍历所有敌方实体
            for entity in self.entities.values():
                if entity.controller != attacker_entity.controller and entity.status != 'destroyed':
                    dist = _get_distance(start_pos, entity.pos)
                    if dist <= final_range:
                        # [BUG FIX] 抛射 (action_type == '抛射') 应该总是无视朝向 (LOS)
                        # [v_MODIFIED] is_curved 现在的逻辑是正确的
                        if action.action_type == '抛射' or is_curved or is_in_forward_arc(start_pos, orientation,
                                                                                          entity.pos):  # 曲射无视朝向
                            back_attack = False
                            if isinstance(entity, Mech):
                                back_attack = is_back_attack(start_pos, entity.pos, entity.orientation)
                            valid_targets.append({'pos': entity.pos, 'entity': entity, 'is_back_attack': back_attack})

            # [v1.28] 如果是抛射, *额外* 查找所有可发射的空格子
            if action.action_type == '抛射':
                occupied_tiles = self.get_occupied_tiles()
                for x in range(1, self.board_width + 1):
                    for y in range(1, self.board_height + 1):
                        cell_pos = (x, y)
                        if cell_pos in occupied_tiles: continue  # 只查找空格子

                        dist = _get_distance(start_pos, cell_pos)
                        if 0 < dist <= final_range:  # 距离必须 > 0
                            # [BUG FIX] 抛射 (action_type == '抛射') 应该总是无视朝向 (LOS)
                            # [v_MODIFIED] is_curved 现在的逻辑是正确的
                            if action.action_type == '抛射' or is_curved or is_in_forward_arc(start_pos, orientation,
                                                                                              cell_pos):  # 曲射无视朝向
                                valid_launch_cells.append(cell_pos)

        # [v1.29 新增] 检查被动动作 (拦截)
        elif action.action_type == '被动':
            # 拦截动作的目标是抛射物，由 run_projectile_logic 动态决定
            # 但 calculate_attack_range 仍需返回一个范围，用于前端（如果需要高亮）
            # 目前, 我们只在后端处理拦截，所以这里返回空
            pass

        return valid_targets, valid_launch_cells