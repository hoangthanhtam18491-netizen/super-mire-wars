class Action:
    """定义一个动作，如攻击或移动。"""

    def __init__(self, name, action_type, cost, dice, range_val=0, effects=None):
        self.name = name
        self.action_type = action_type  # '近战', '射击', '移动'
        self.cost = cost  # 'S', 'M', 'L'
        self.dice = dice  # e.g., '1黄3红'
        self.range_val = range_val
        self.effects = effects if effects is not None else {}  # [新增] 效果字典

    def to_dict(self):
        """将Action对象序列化为字典。"""
        return {
            'name': self.name,
            'action_type': self.action_type,
            'cost': self.cost,
            'dice': self.dice,
            'range_val': self.range_val,
            'effects': self.effects,  # [新增]
        }

    @classmethod
    def from_dict(cls, data):
        """从字典创建Action对象。"""
        return cls(
            name=data['name'],
            action_type=data['action_type'],
            cost=data['cost'],
            dice=data['dice'],
            range_val=data.get('range_val', 0),
            effects=data.get('effects', {}),  # [新增]
        )


class Part:
    """定义一个机甲部件。"""

    def __init__(self, name, armor, structure, parry=0, evasion=0, electronics=0, adjust_move=0, actions=None,
                 status='ok', tags=None): # [新增] tags 属性
        self.name = name
        self.armor = armor
        self.structure = structure
        self.parry = parry
        self.evasion = evasion
        self.electronics = electronics
        self.adjust_move = adjust_move
        self.actions = actions if actions is not None else []
        self.status = status  # 'ok', 'damaged', 'destroyed'
        self.tags = tags if tags is not None else [] # [新增] tags 列表

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
            'tags': self.tags,  # [新增]
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
            tags=data.get('tags', []) # [新增]
        )


class Mech:
    """定义一台完整的机甲。"""

    def __init__(self, name, core, legs, left_arm, right_arm, backpack):
        self.name = name
        self.parts = {
            'core': core,
            'legs': legs,
            'left_arm': left_arm,
            'right_arm': right_arm,
            'backpack': backpack
        }
        self.stance = 'defense'  # 'defense', 'agile', 'attack'
        self.orientation = 'N'  # 'N', 'E', 'S', 'W'

    def get_total_evasion(self):
        """计算机甲的总回避值。"""
        return sum(part.evasion for part in self.parts.values() if part.status != 'destroyed')

    def get_all_actions(self):
        """
        [修改] 获取所有动作及其所属的部件槽位。
        返回一个元组列表: [(Action, 'part_slot'), ...]
        """
        all_actions = []
        for part_slot, part in self.parts.items():
            if part.status != 'destroyed':
                for action in part.actions:
                    all_actions.append((action, part_slot))
        return all_actions

    def get_part_by_name(self, name_or_slot):
        """
        根据部件的显示名称或其槽位名（'core', 'legs'等）获取部件对象。
        优先匹配显示名称。
        """
        for part in self.parts.values():
            if part.name == name_or_slot:
                return part
        if name_or_slot in self.parts:
            return self.parts[name_or_slot]
        return None

    def has_melee_action(self):
        """检查机甲是否有可用的近战动作。"""
        # [修改] 适配 get_all_actions 的新返回格式
        for action, part_slot in self.get_all_actions():
            if action.action_type == '近战':
                return True
        return False

    def get_active_parts_count(self):
        """计算未被摧毁的部件数量。"""
        return sum(1 for part in self.parts.values() if part.status != 'destroyed')

    def get_passive_effects(self):
        """
        [新增] 收集机甲所有未摧毁部件上的所有被动动作的效果。
        返回一个效果字典列表: [{'effect_name': {...}}, ...]
        """
        passive_effects = []
        for part_slot, part in self.parts.items():
            if part.status != 'destroyed':
                for action in part.actions:
                    if action.action_type == '被动' and action.effects:
                        passive_effects.append(action.effects)
        return passive_effects

    def to_dict(self):
        """将Mech对象序列化为字典。"""
        return {
            'name': self.name,
            'parts': {name: part.to_dict() for name, part in self.parts.items()},
            'stance': self.stance,
            'orientation': self.orientation
        }

    @classmethod
    def from_dict(cls, data):
        """从字典创建Mech对象，并重建其所有Part。"""
        parts_data = data['parts']
        mech = cls(
            name=data.get('name', 'Unknown Mech'),
            core=Part.from_dict(parts_data['core']),
            legs=Part.from_dict(parts_data['legs']),
            left_arm=Part.from_dict(parts_data['left_arm']),
            right_arm=Part.from_dict(parts_data['right_arm']),
            backpack=Part.from_dict(parts_data['backpack'])
        )
        mech.stance = data.get('stance', 'defense')
        mech.orientation = data.get('orientation', 'N')
        return mech

