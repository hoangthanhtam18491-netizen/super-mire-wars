import random


# [v1.23 修复] 移除下面这行错误的循环自导入
# from data_models import Part # [v1.18 修复] 移除错误的循环导入

class Action:
    """
    [v1.17]
    定义一个动作，如攻击或移动。
    """

    def __init__(self, name, action_type, cost, dice, range_val=0, effects=None,
                 action_style='direct', aoe_range=0, projectile_to_spawn=None, ammo=0):  # [修改 v1.17]
        self.name = name
        self.action_type = action_type  # '近战', '射击', '移动', '抛射' [v1.17 新增]
        self.cost = cost
        self.dice = dice
        self.range_val = range_val
        self.effects = effects if effects is not None else {}

        # [新增 v1.17] 抛射/AoE 属性
        self.action_style = action_style  # 'direct' (直射) or 'curved' (曲射)
        self.aoe_range = aoe_range  # 0 = 单体, 1 = 1圈AoE
        self.projectile_to_spawn = projectile_to_spawn  # e.g., 'RA-81_ROCKET'
        self.ammo = ammo  # 0 = 无限

    def to_dict(self):
        """将Action对象序列化为字典。"""
        return {
            'name': self.name,
            'action_type': self.action_type,
            'cost': self.cost,
            'dice': self.dice,
            'range_val': self.range_val,
            'effects': self.effects,
            # [新增 v1.g]
            'action_style': self.action_style,
            'aoe_range': self.aoe_range,
            'projectile_to_spawn': self.projectile_to_spawn,
            'ammo': self.ammo,
        }

    @classmethod
    def from_dict(cls, data):
        """从字典创建Action对象。"""
        # [v_MODIFIED] 增加 action_style 的向后兼容
        action_style = data.get('action_style', 'direct')
        # [v_MODIFIED] 检查 effects 字典中是否也定义了 'action_style' (例如来自【曲射】)
        if data.get('effects', {}).get('action_style') == 'curved':
            action_style = 'curved'

        return cls(
            name=data['name'],
            action_type=data['action_type'],
            cost=data['cost'],
            dice=data['dice'],
            range_val=data.get('range_val', 0),
            effects=data.get('effects', {}),
            # [修改] 使用兼容后的 action_style
            action_style=action_style,
            aoe_range=data.get('aoe_range', 0),
            projectile_to_spawn=data.get('projectile_to_spawn', None),
            ammo=data.get('ammo', 0),
        )


class Part:
    """
    [v1.18 修复]
    从 v1.15 恢复 Part 类的定义。
    """

    def __init__(self, name, armor, structure, parry=0, evasion=0, electronics=0, adjust_move=0, actions=None,
                 status='ok', tags=None, image_url=None):
        self.name = name
        self.armor = armor
        self.structure = structure
        self.parry = parry
        self.evasion = evasion
        self.electronics = electronics
        self.adjust_move = adjust_move
        self.actions = actions if actions is not None else []
        self.status = status  # 'ok', 'damaged', 'destroyed'
        self.tags = tags if tags is not None else []
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
        # Action 类在顶部定义，所以这里可以安全使用
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


# --- [v1.17] 游戏实体框架 ---

class GameEntity:
    """
    [v1.22]
    所有战斗单位（机甲、无人机、抛射物）的基类。
    """

    def __init__(self, id, entity_type, controller, pos, orientation, name, status='ok'):
        self.id = id
        self.entity_type = entity_type  # 'mech', 'projectile', 'drone'
        self.controller = controller  # 'player' or 'ai'
        self.pos = pos
        self.orientation = orientation  # 'N', 'E', 'S', 'W', 'NONE'
        self.name = name
        self.status = status  # 'ok' or 'destroyed'

        # [新增 v1.22] CSS 类名，用于前端渲染
        if self.controller == 'player':
            self.controller_css = 'player'
        elif self.controller == 'ai':
            self.controller_css = 'ai'
        else:
            self.controller_css = 'neutral'

        self.last_pos = None  # 用于动画

    def to_dict(self):
        """序列化基础实体数据。"""
        return {
            'id': self.id,
            'entity_type': self.entity_type,
            'controller': self.controller,
            'controller_css': self.controller_css,  # [v1.22]
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
        根据 'entity_type' 自动调用正确的子类 (Mech, Projectile) 的 from_dict。
        """
        entity_type = data.get('entity_type')
        if entity_type == 'mech':
            return Mech.from_dict(data)
        elif entity_type == 'projectile':
            return Projectile.from_dict(data)
        elif entity_type == 'drone':
            return Drone.from_dict(data)

        # 后备：如果类型未知，只创建一个基础实体
        # （这不应该发生，但作为安全措施）
        return cls(
            id=data.get('id', f"unknown_{random.randint(0, 999)}"),
            entity_type=entity_type,
            controller=data.get('controller', 'neutral'),
            pos=data.get('pos', (1, 1)),
            orientation=data.get('orientation', 'N'),
            name=data.get('name', 'Unknown Entity'),
            status=data.get('status', 'ok')
        )

    def get_total_evasion(self):
        """基础实体没有闪避。"""
        return 0

    # [新增]
    def get_total_electronics(self):
        """基础实体没有电子值。"""
        return 0

    def get_all_actions(self):
        """基础实体没有动作。"""
        return []

    # [v1.21] 新增
    def get_action_by_name_and_slot(self, action_name, part_slot):
        """基础实体没有部件或动作。"""
        return None

    # [v1.20] 新增
    def get_action_by_timing(self, timing_type):
        """基础实体没有动作。"""
        return None


class Mech(GameEntity):
    """
    [v1.22]
    定义一台完整的机甲。现在继承自 GameEntity。
    包含了 v1.19 中添加的回合制状态属性。
    """

    def __init__(self, id, controller, pos, orientation, name, core, legs, left_arm, right_arm, backpack):
        super().__init__(id, 'mech', controller, pos, orientation, name)

        self.parts = {
            'core': core,
            'legs': legs,
            'left_arm': left_arm,
            'right_arm': right_arm,
            'backpack': backpack
        }

        # --- [v1.19] 回合制状态 ---
        self.stance = 'defense'
        self.player_ap = 2
        self.player_tp = 1
        self.turn_phase = 'timing'
        self.timing = None
        self.opening_move_taken = False
        self.actions_used_this_turn = []
        self.pending_effect_data = None
        # ---

    def get_total_evasion(self):
        """计算机甲的总回避值。"""
        return sum(part.evasion for part in self.parts.values() if part and part.status != 'destroyed')

    # [新增]
    def get_total_electronics(self):
        """计算机甲的总电子值。"""
        return sum(part.electronics for part in self.parts.values() if part and part.status != 'destroyed')

    def get_all_actions(self):
        """获取所有动作及其所属的部件槽位。"""
        all_actions = []
        for part_slot, part in self.parts.items():
            if part and part.status != 'destroyed':
                for action in part.actions:
                    all_actions.append((action, part_slot))
        return all_actions

    # [v1.21] 新增
    def get_action_by_name_and_slot(self, action_name, part_slot):
        """通过名称和槽位获取一个动作对象。"""
        part = self.parts.get(part_slot)
        if part and part.status != 'destroyed':
            for action in part.actions:
                if action.name == action_name:
                    return action
        return None

    # [v1.20] 新增
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
        for part_slot, part in self.parts.items():
            if part and part.status != 'destroyed':
                for action in part.actions:
                    if action.action_type == '近战':
                        return True
        return False

    def get_active_parts_count(self):
        """计算未被摧毁的部件数量。"""
        return sum(1 for part in self.parts.values() if part and part.status != 'destroyed')

    def get_passive_effects(self):
        """收集机甲所有未摧毁部件上的所有被动动作的效果。"""
        passive_effects = []
        for part_slot, part in self.parts.items():
            if part and part.status != 'destroyed':
                for action in part.actions:
                    if action.action_type == '被动' and action.effects:
                        passive_effects.append(action.effects)
        return passive_effects

    def get_interceptor_actions(self):
        """[新增] 获取所有可用的拦截器动作（被动，带拦截效果）。"""
        interceptor_actions = []
        for part_slot, part in self.parts.items():
            if part and part.status != 'destroyed':
                for action in part.actions:
                    # 必须是被动动作，并且在 effects 中有 'interceptor' 键
                    if action.action_type == '被动' and action.effects and 'interceptor' in action.effects:
                        interceptor_actions.append((action, part_slot))
        return interceptor_actions

    def to_dict(self):
        """将 Mech 对象转换为 JSON 安全的字典，递归转换 Action、Part 等自定义类。"""
        base_dict = super().to_dict()

        def make_json_safe(obj):
            """递归地将对象转换为 JSON 可序列化格式"""
            if obj is None:
                return None
            if isinstance(obj, (str, int, float, bool)):
                return obj
            if isinstance(obj, dict):
                return {k: make_json_safe(v) for k, v in obj.items()}
            if isinstance(obj, (list, tuple, set)):
                return [make_json_safe(i) for i in obj]
            # 关键：如果对象有 to_dict，则递归展开
            if hasattr(obj, "to_dict") and callable(obj.to_dict):
                return make_json_safe(obj.to_dict())
            # fallback
            return str(obj)

        base_dict.update({
            "parts": make_json_safe(self.parts),
            "stance": self.stance,
            "player_ap": self.player_ap,
            "player_tp": self.player_tp,
            "turn_phase": self.turn_phase,
            "timing": self.timing,
            "opening_move_taken": self.opening_move_taken,
            "actions_used_this_turn": make_json_safe(self.actions_used_this_turn),
            "pending_effect_data": make_json_safe(self.pending_effect_data),
        })
        return base_dict

    @classmethod
    def from_dict(cls, data):
        """从字典创建Mech对象，并重建其所有Part。"""
        parts_data = data.get('parts', {})

        def safe_part_load(slot_name):
            part_data = parts_data.get(slot_name)
            return Part.from_dict(part_data) if part_data else None

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
            backpack=safe_part_load('backpack')
        )

        # [v1.19] 加载回合制状态
        mech.stance = data.get('stance', 'defense')
        mech.player_ap = data.get('player_ap', 2)
        mech.player_tp = data.get('player_tp', 1)
        mech.turn_phase = data.get('turn_phase', 'timing')
        mech.timing = data.get('timing', None)
        mech.opening_move_taken = data.get('opening_move_taken', False)
        mech.actions_used_this_turn = data.get('actions_used_this_turn', [])
        mech.pending_effect_data = data.get('pending_effect_data', None)
        mech.last_pos = data.get('last_pos', None)

        # [v1.22] 确保 controller_css 被设置
        mech.controller_css = data.get('controller_css', 'neutral')
        if mech.controller == 'player':
            mech.controller_css = 'player'
        elif mech.controller == 'ai':
            mech.controller_css = 'ai'

        return mech


class Projectile(GameEntity):
    """
    [v_MODIFIED]
    抛射物实体（例如，导弹）。
    """

    def __init__(self, id, controller, pos, name, evasion, stance, actions, life_span,
                 electronics=0, move_range=0): # [修改] 添加新属性
        super().__init__(id, 'projectile', controller, pos, 'NONE', name)  # 抛射物没有朝向

        self.evasion = evasion
        self.stance = stance  # 通常是 'agile'
        self.life_span = life_span  # 存活的回合数

        # [新增] 导弹属性
        self.electronics = electronics
        self.move_range = move_range

        # [v1.17] 抛射物有一个简化的“部件”系统，只有一个核心，代表它的HP
        # [修改] 将 electronics 属性添加到核心部件，以便于机甲统一处理
        self.parts = {
            'core': Part(name=f"{name} 核心", armor=0, structure=1, actions=actions, electronics=electronics)
        }

    def get_total_evasion(self):
        """[v1.17] 抛射物有固定的闪避值。"""
        return self.evasion if self.status == 'ok' else 0

    # [新增]
    def get_total_electronics(self):
        """[新增] 抛射物有固定的电子值。"""
        return self.electronics if self.status == 'ok' else 0

    def get_all_actions(self):
        """[v1.20] 获取抛射物核心上的所有动作。"""
        all_actions = []
        part = self.parts.get('core')
        if part and part.status != 'destroyed':
            for action in part.actions:
                all_actions.append((action, 'core'))  # 槽位总是 'core'
        return all_actions

    # [v1.21] 新增
    def get_action_by_name_and_slot(self, action_name, part_slot):
        """通过名称和槽位获取一个动作对象。"""
        part = self.parts.get(part_slot)
        if part and part.status != 'destroyed':
            for action in part.actions:
                if action.name == action_name:
                    return action
        return None

    # [v1.20] 新增
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
            # [新增]
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
            # [新增]
            electronics=data.get('electronics', 0),
            move_range=data.get('move_range', 0)
        )
        projectile.last_pos = data.get('last_pos', None)
        projectile.status = data.get('status', 'ok')
        # [v1.22] 确保 controller_css 被设置
        projectile.controller_css = data.get('controller_css', 'neutral')
        if projectile.controller == 'player':
            projectile.controller_css = 'player'
        elif projectile.controller == 'ai':
            projectile.controller_css = 'ai'

        # [v1.17] 确保核心部件的状态被正确加载
        if core_part:
            projectile.parts['core'].status = core_part_data.get('status', 'ok')

        return projectile


class Drone(GameEntity):
    """
    [v1.22]
    无人机实体（骨架）。
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
        # [v1.22] 确保 controller_css 被设置
        drone.controller_css = data.get('controller_css', 'neutral')
        if drone.controller == 'player':
            drone.controller_css = 'player'
        elif drone.controller == 'ai':
            drone.controller_css = 'ai'

        return drone

