import random

# 注意：这个文件位于 game_logic/ 文件夹中。
# 它依赖于同在 game_logic/ 下的 database/ 包。

class Action:
    """
    定义一个可执行的动作 (如攻击、移动)。
    这是所有部件 (Part) 可以执行的操作的基础数据结构。
    """

    def __init__(self, name, action_type, cost, dice, range_val=0, effects=None,
                 action_style='direct', aoe_range=0, projectile_to_spawn=None, ammo=0):
        self.name = name
        self.action_type = action_type  # 类型: '近战', '射击', '移动', '抛射', '被动', '快速'
        self.cost = cost  # 成本: 'S', 'M', 'L'
        self.dice = dice  # 骰子: e.g., '1黄3红'
        self.range_val = range_val  # 射程或移动距离
        self.effects = effects if effects is not None else {}  # 特殊效果: e.g., '穿甲'

        # 抛射/AoE 属性
        self.action_style = action_style  # 'direct' (直射) or 'curved' (曲射)
        self.aoe_range = aoe_range  # 0 = 单体, 1 = 1圈AoE
        self.projectile_to_spawn = projectile_to_spawn  # 要生成的抛射物模板的键
        self.ammo = ammo  # 0 = 无限弹药

    def to_dict(self):
        """将Action对象序列化为字典。"""
        return {
            'name': self.name,
            'action_type': self.action_type,
            'cost': self.cost,
            'dice': self.dice,
            'range_val': self.range_val,
            'effects': self.effects,
            'action_style': self.action_style,
            'aoe_range': self.aoe_range,
            'projectile_to_spawn': self.projectile_to_spawn,
            'ammo': self.ammo,
        }

    @classmethod
    def from_dict(cls, data):
        """从字典创建Action对象, 包含向后兼容逻辑。"""
        action_style = data.get('action_style', 'direct')
        # 兼容旧的/来自效果的 'action_style'
        if data.get('effects', {}).get('action_style') == 'curved':
            action_style = 'curved'

        return cls(
            name=data['name'],
            action_type=data['action_type'],
            cost=data['cost'],
            dice=data['dice'],
            range_val=data.get('range_val', 0),
            effects=data.get('effects', {}),
            action_style=action_style,
            aoe_range=data.get('aoe_range', 0),
            projectile_to_spawn=data.get('projectile_to_spawn', None),
            ammo=data.get('ammo', 0),
        )


class Part:
    """
    定义一个机甲部件 (如核心、手臂、背包)。
    它包含该部件的属性和它可以执行的 Action 列表。
    """

    def __init__(self, name, armor, structure, parry=0, evasion=0, electronics=0, adjust_move=0, actions=None,
                 status='ok', tags=None, image_url=None):
        self.name = name  # 部件名称
        self.armor = armor  # 装甲值 (计算白骰)
        self.structure = structure  # 结构值 (HP)
        self.parry = parry  # 招架值 (增加额外白骰)
        self.evasion = evasion  # 闪避值 (增加蓝骰)
        self.electronics = electronics  # 电子值
        self.adjust_move = adjust_move  # 调整移动的距离
        self.actions = actions if actions is not None else []  # 动作列表 [Action, ...]
        self.status = status  # 'ok', 'damaged', 'destroyed'
        self.tags = tags if tags is not None else []  # 标签 e.g., '【手持】'
        self.image_url = image_url

    def to_dict(self):
        """将Part对象序列化为字典。"""
        return {
            'name': self.name,
            'armor': self.armor,
            'structure': self.structure,
            'parry': self.parry,
            'evasion': self.evasion,
            'electronics': self.electronics,
            'adjust_move': self.adjust_move,
            'actions': [action.to_dict() for action in self.actions],
            'status': self.status,
            'tags': self.tags,
            'image_url': self.image_url,
        }

    @classmethod
    def from_dict(cls, data):
        """从字典创建Part对象，并重建其Action列表。"""
        actions_data = data.get('actions', [])
        actions = [Action.from_dict(a_data) for a_data in actions_data]

        return cls(
            name=data['name'],
            armor=data['armor'],
            structure=data['structure'],
            parry=data.get('parry', 0),
            evasion=data.get('evasion', 0),
            electronics=data.get('electronics', 0),
            adjust_move=data.get('adjust_move', 0),
            actions=actions,
            status=data.get('status', 'ok'),
            tags=data.get('tags', []),
            image_url=data.get('image_url', None)
        )


class GameEntity:
    """
    所有战斗单位 (机甲、抛射物、无人机) 的基类。
    提供共享的基础属性 (ID, 位置, 状态等)。
    """

    def __init__(self, id, entity_type, controller, pos, orientation, name, status='ok'):
        self.id = id  # 唯一ID (e.g., 'player_1')
        self.entity_type = entity_type  # 'mech', 'projectile', 'drone'
        self.controller = controller  # 'player' or 'ai'
        self.pos = pos  # 坐标元组 (x, y)
        self.orientation = orientation  # 'N', 'E', 'S', 'W', 'NONE'
        self.name = name  # 显示名称
        self.status = status  # 'ok' or 'destroyed'

        # 用于前端渲染的 CSS 类名
        if self.controller == 'player':
            self.controller_css = 'player'
        elif self.controller == 'ai':
            self.controller_css = 'ai'
        else:
            self.controller_css = 'neutral'

        self.last_pos = None  # 用于前端动画

    def to_dict(self):
        """序列化基础实体数据。"""
        return {
            'id': self.id,
            'entity_type': self.entity_type,
            'controller': self.controller,
            'controller_css': self.controller_css,
            'pos': self.pos,
            'orientation': self.orientation,
            'name': self.name,
            'status': self.status,
            'last_pos': self.last_pos,
        }

    @classmethod
    def from_dict(cls, data):
        """
        智能反序列化器。
        根据 'entity_type' 自动调用正确的子类 (Mech, Projectile, Drone)。
        """
        entity_type = data.get('entity_type')
        if entity_type == 'mech':
            return Mech.from_dict(data)
        elif entity_type == 'projectile':
            return Projectile.from_dict(data)
        elif entity_type == 'drone':
            return Drone.from_dict(data)

        # 后备：如果类型未知，只创建一个基础实体
        return cls(
            id=data.get('id', f"unknown_{random.randint(0, 999)}"),
            entity_type=entity_type,
            controller=data.get('controller', 'neutral'),
            pos=data.get('pos', (1, 1)),
            orientation=data.get('orientation', 'N'),
            name=data.get('name', 'Unknown Entity'),
            status=data.get('status', 'ok')
        )

    # --- 接口存根 (Interface Stubs) ---
    # 这些方法将被子类覆盖。

    def get_total_evasion(self):
        """获取实体的总闪避值。"""
        return 0

    def get_total_electronics(self):
        """获取实体的总电子值。"""
        return 0

    def get_all_actions(self):
        """获取实体所有可用的动作。"""
        return []

    def get_action_by_name_and_slot(self, action_name, part_slot):
        """根据名称和槽位获取特定动作。"""
        return None

    def get_action_by_timing(self, timing_type):
        """根据时机类型获取动作。"""
        return None, None


class Pilot:
    """
    定义一个驾驶员及其属性 (如链接值和速度)。
    """

    def __init__(self, name, link_points=5, speed_stats=None, skills=None):
        self.name = name
        self.link_points = link_points  # 用于专注重投

        # 速度属性，影响 AI 决策和未来可能的先攻
        if speed_stats is None:
            self.speed_stats = {
                '快速': 5, '近战': 5, '抛射': 5,
                '射击': 5, '移动': 5, '战术': 5
            }
        else:
            self.speed_stats = speed_stats
        self.skills = skills if skills is not None else []  # 未来的技能系统

    def to_dict(self):
        """将Pilot对象序列化为字典。"""
        return {
            'name': self.name,
            'link_points': self.link_points,
            'speed_stats': self.speed_stats,
            'skills': self.skills,
        }

    @classmethod
    def from_dict(cls, data):
        """从字典创建Pilot对象。"""
        if not data:
            return None

        default_speeds = {
            '快速': 5, '近战': 5, '抛射': 5,
            '射击': 5, '移动': 5, '战术': 5
        }

        return cls(
            name=data.get('name', '未知驾驶员'),
            link_points=data.get('link_points', 5),
            speed_stats=data.get('speed_stats', default_speeds),
            skills=data.get('skills', [])
        )


class Mech(GameEntity):
    """
    定义一台完整的机甲。继承自 GameEntity。
    管理部件 (Parts)、驾驶员 (Pilot) 和回合制状态 (AP/TP, 姿态等)。
    """

    def __init__(self, id, controller, pos, orientation, name, core, legs, left_arm, right_arm, backpack, pilot=None):
        super().__init__(id, 'mech', controller, pos, orientation, name)

        # 机甲的核心部件
        self.parts = {
            'core': core,
            'legs': legs,
            'left_arm': left_arm,
            'right_arm': right_arm,
            'backpack': backpack
        }
        self.pilot = pilot  # 关联的驾驶员

        # --- 回合制状态 ---
        self.stance = 'defense'  # 'defense', 'agile', 'attack', 'downed'
        self.player_ap = 2  # 行动时点
        self.player_tp = 1  # 调整时点
        self.turn_phase = 'timing'  # 'timing', 'stance', 'adjustment', 'main'
        self.timing = None  # '近战', '射击', '移动'
        self.opening_move_taken = False  # 是否已执行起手动作
        self.actions_used_this_turn = []  # [(part_slot, action_name), ...]

        # [核心状态] 存储战斗状态机 (CombatState) 的序列化字典
        # 这是管理重投和效果选择中断的唯一来源
        self.pending_combat: dict | None = None
        # ---

    def get_total_evasion(self):
        """计算机甲所有未摧毁部件的总回避值。"""
        return sum(part.evasion for part in self.parts.values() if part and part.status != 'destroyed')

    def get_total_electronics(self):
        """计算机甲所有未摧毁部件的总电子值。"""
        return sum(part.electronics for part in self.parts.values() if part and part.status != 'destroyed')

    def get_all_actions(self):
        """
        获取所有可用动作（来自部件和通用动作）及其所属的部件槽位。
        返回: [(Action, part_slot), ...]
        """
        # [重要] 局部导入以避免循环依赖
        # 此文件位于 game_logic/，它需要从 game_logic/database/ 导入
        try:
            from .database import GENERIC_ACTIONS
        except ImportError:
            GENERIC_ACTIONS = {}  # 安全后备

        all_actions = []
        # 1. 收集所有来自部件的动作
        for part_slot, part in self.parts.items():
            if part and part.status != 'destroyed':
                for action in part.actions:
                    all_actions.append((action, part_slot))

        # 2. 检查并添加通用动作 (如 '拳打脚踢')
        if GENERIC_ACTIONS:
            for generic_action, required_slots in GENERIC_ACTIONS.items():
                is_unlocked = False
                for slot in required_slots:
                    part = self.parts.get(slot)
                    if part and part.status != 'destroyed':
                        is_unlocked = True
                        break  # 找到一个未摧毁的部件就解锁
                if is_unlocked:
                    all_actions.append((generic_action, 'generic'))

        return all_actions

    def get_action_by_name_and_slot(self, action_name, part_slot):
        """通过名称和槽位获取一个动作对象。"""

        # 检查 'generic' (通用) 槽位
        if part_slot == 'generic':
            # [重要] 局部导入以避免循环依赖
            try:
                from .database import GENERIC_ACTIONS
            except ImportError:
                GENERIC_ACTIONS = {}  # 安全后备

            if GENERIC_ACTIONS:
                for generic_action, required_slots in GENERIC_ACTIONS.items():
                    if generic_action.name == action_name:
                        # 再次验证机甲是否真的有权限
                        is_unlocked = False
                        for slot in required_slots:
                            part = self.parts.get(slot)
                            if part and part.status != 'destroyed':
                                is_unlocked = True
                                break
                        if is_unlocked:
                            return generic_action
            return None

        # 检查特定部件槽位
        part = self.parts.get(part_slot)
        if part and part.status != 'destroyed':
            for action in part.actions:
                if action.name == action_name:
                    return action
        return None

    def get_action_by_timing(self, timing_type):
        """获取第一个匹配该时机类型的可用动作。"""
        for action, part_slot in self.get_all_actions():
            if action.action_type == timing_type:
                return action, part_slot
        return None, None

    def get_part_by_name(self, name_or_slot):
        """根据部件的显示名称或其槽位名获取部件对象。"""
        if name_or_slot in self.parts:
            return self.parts[name_or_slot]
        for part in self.parts.values():
            if part and part.name == name_or_slot:
                return part
        return None

    def has_melee_action(self):
        """检查机甲是否有可用的近战动作。"""
        for action, part_slot in self.get_all_actions():
            if action.action_type == '近战':
                return True
        return False

    def get_active_parts_count(self):
        """计算未被摧毁的部件数量。"""
        return sum(1 for part in self.parts.values() if part and part.status != 'destroyed')

    def get_passive_effects(self):
        """收集机甲所有未摧毁部件上的所有被动动作的效果。"""
        passive_effects = []
        for action, part_slot in self.get_all_actions():
            if action.action_type == '被动' and action.effects:
                passive_effects.append(action.effects)
        return passive_effects

    def get_interceptor_actions(self):
        """获取所有可用的拦截器动作（被动，带拦截效果）。"""
        interceptor_actions = []
        for action, part_slot in self.get_all_actions():
            if action.action_type == '被动' and action.effects and 'interceptor' in action.effects:
                interceptor_actions.append((action, part_slot))
        return interceptor_actions

    def to_dict(self):
        """将 Mech 对象转换为 JSON 安全的字典，递归转换 Action、Part 等自定义类。"""
        base_dict = super().to_dict()

        def make_json_safe(obj):
            """(内部辅助函数) 递归地将对象转换为 JSON 可序列化格式"""
            if obj is None:
                return None
            if isinstance(obj, (str, int, float, bool)):
                return obj
            if isinstance(obj, dict):
                return {k: make_json_safe(v) for k, v in obj.items()}
            if isinstance(obj, (list, tuple, set)):
                return [make_json_safe(i) for i in obj]
            if hasattr(obj, "to_dict") and callable(obj.to_dict):
                return make_json_safe(obj.to_dict())
            return str(obj)

        base_dict.update({
            "parts": make_json_safe(self.parts),
            "pilot": make_json_safe(self.pilot),
            "stance": self.stance,
            "player_ap": self.player_ap,
            "player_tp": self.player_tp,
            "turn_phase": self.turn_phase,
            "timing": self.timing,
            "opening_move_taken": self.opening_move_taken,
            "actions_used_this_turn": make_json_safe(self.actions_used_this_turn),

            # [核心状态] 序列化新的 pending_combat 状态
            "pending_combat": make_json_safe(self.pending_combat),
        })
        return base_dict

    @classmethod
    def from_dict(cls, data):
        """从字典创建Mech对象，并重建其所有Part。"""
        parts_data = data.get('parts', {})

        def safe_part_load(slot_name):
            part_data = parts_data.get(slot_name)
            return Part.from_dict(part_data) if part_data else None

        pilot_data = data.get('pilot')
        pilot_obj = Pilot.from_dict(pilot_data) if pilot_data else None

        mech = cls(
            id=data.get('id', f"mech_{random.randint(0, 999)}"),
            controller=data.get('controller', 'neutral'),
            pos=data.get('pos', (1, 1)),
            orientation=data.get('orientation', 'N'),
            name=data.get('name', 'Unknown Mech'),
            core=safe_part_load('core'),
            legs=safe_part_load('legs'),
            left_arm=safe_part_load('left_arm'),
            right_arm=safe_part_load('right_arm'),
            backpack=safe_part_load('backpack'),
            pilot=pilot_obj
        )

        # 加载回合制状态
        mech.stance = data.get('stance', 'defense')
        mech.player_ap = data.get('player_ap', 2)
        mech.player_tp = data.get('player_tp', 1)
        mech.turn_phase = data.get('turn_phase', 'timing')
        mech.timing = data.get('timing', None)
        mech.opening_move_taken = data.get('opening_move_taken', False)
        mech.actions_used_this_turn = data.get('actions_used_this_turn', [])

        # [核心修复] 确保在从 session 加载时恢复 pending_combat 状态
        mech.pending_combat = data.get('pending_combat', None)
        mech.last_pos = data.get('last_pos', None)

        mech.controller_css = data.get('controller_css', 'neutral')
        if mech.controller == 'player':
            mech.controller_css = 'player'
        elif mech.controller == 'ai':
            mech.controller_css = 'ai'

        return mech


class Projectile(GameEntity):
    """
    抛射物实体 (例如，导弹)。
    它有简化的属性，只有一个 'core' 部件代表其生命值。
    """

    def __init__(self, id, controller, pos, name, evasion, stance, actions, life_span,
                 electronics=0, move_range=0):
        super().__init__(id, 'projectile', controller, pos, 'NONE', name)  # 抛射物没有朝向

        self.evasion = evasion  # 固定的闪避值
        self.stance = stance  # 通常是 'agile'
        self.life_span = life_span  # 存活的回合数
        self.electronics = electronics  # 电子值
        self.move_range = move_range  # '延迟' 动作的移动范围

        # 抛射物只有一个 'core' 部件，代表它的 HP (通常 structure=1)
        self.parts = {
            'core': Part(name=f"{name} 核心", armor=0, structure=1, actions=actions, electronics=electronics)
        }

    def get_total_evasion(self):
        """抛射物有固定的闪避值。"""
        return self.evasion if self.status == 'ok' else 0

    def get_total_electronics(self):
        """抛射物有固定的电子值。"""
        return self.electronics if self.status == 'ok' else 0

    def get_all_actions(self):
        """获取抛射物核心上的所有动作 (通常是 '立即' 或 '延迟')。"""
        all_actions = []
        part = self.parts.get('core')
        if part and part.status != 'destroyed':
            for action in part.actions:
                all_actions.append((action, 'core'))
        return all_actions

    def get_action_by_name_and_slot(self, action_name, part_slot):
        """通过名称和槽位获取一个动作对象。"""
        part = self.parts.get(part_slot)
        if part and part.status != 'destroyed':
            for action in part.actions:
                if action.name == action_name:
                    return action
        return None

    def get_action_by_timing(self, timing_type):
        """获取第一个匹配该时机类型的可用动作。"""
        for action, part_slot in self.get_all_actions():
            if action.action_type == timing_type:
                return action, part_slot
        return None, None

    def to_dict(self):
        """序列化抛射物数据。"""
        base_dict = super().to_dict()
        base_dict.update({
            'evasion': self.evasion,
            'stance': self.stance,
            'life_span': self.life_span,
            'parts': {'core': self.parts['core'].to_dict() if self.parts.get('core') else None},
            'electronics': self.electronics,
            'move_range': self.move_range,
        })
        return base_dict

    @classmethod
    def from_dict(cls, data):
        """从字典重建抛射物。"""
        core_part_data = data.get('parts', {}).get('core')
        core_part = Part.from_dict(core_part_data) if core_part_data else None
        actions = core_part.actions if core_part else []

        projectile = cls(
            id=data.get('id', f"proj_{random.randint(0, 999)}"),
            controller=data.get('controller', 'neutral'),
            pos=data.get('pos', (1, 1)),
            name=data.get('name', 'Unknown Projectile'),
            evasion=data.get('evasion', 0),
            stance=data.get('stance', 'agile'),
            actions=actions,
            life_span=data.get('life_span', 1),
            electronics=data.get('electronics', 0),
            move_range=data.get('move_range', 0)
        )
        projectile.last_pos = data.get('last_pos', None)
        projectile.status = data.get('status', 'ok')
        projectile.controller_css = data.get('controller_css', 'neutral')
        if projectile.controller == 'player':
            projectile.controller_css = 'player'
        elif projectile.controller == 'ai':
            projectile.controller_css = 'ai'

        if core_part:
            projectile.parts['core'].status = core_part_data.get('status', 'ok')

        return projectile


class Drone(GameEntity):
    """
    无人机实体 (目前是一个骨架，未来可以扩展)。
    """

    def __init__(self, id, controller, pos, orientation, name):
        super().__init__(id, 'drone', controller, pos, orientation, name)
        # TODO: 添加无人机特有的属性 (例如 部件, HP, 动作)

    def to_dict(self):
        """序列化无人机数据。"""
        base_dict = super().to_dict()
        # TODO: 添加无人机特有的序列化
        return base_dict

    @classmethod
    def from_dict(cls, data):
        """从字典重建无人机。"""
        drone = cls(
            id=data.get('id', f"drone_{random.randint(0, 999)}"),
            controller=data.get('controller', 'neutral'),
            pos=data.get('pos', (1, 1)),
            orientation=data.get('orientation', 'N'),
            name=data.get('name', 'Unknown Drone')
        )
        drone.last_pos = data.get('last_pos', None)
        drone.status = data.get('status', 'ok')
        drone.controller_css = data.get('controller_css', 'neutral')
        if drone.controller == 'player':
            drone.controller_css = 'player'
        elif drone.controller == 'ai':
            drone.controller_css = 'ai'

        return drone