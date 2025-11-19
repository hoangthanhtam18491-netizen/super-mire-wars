import random
import re
import traceback
from .dice_roller import roll_dice, process_rolls, reroll_specific_dice
from .data_models import Mech, Projectile, Part, Action
# [NEW] 导入 Ace 逻辑
from . import ace_logic


def parse_dice_string(dice_str):
    """
    (辅助函数) 使用正则表达式解析骰子字符串，例如 '1黄3红'。
    """
    counts = {'yellow_count': 0, 'red_count': 0, 'white_count': 0, 'blue_count': 0}
    if not dice_str: return counts
    patterns = {'yellow_count': r'(\d+)\s*黄', 'red_count': r'(\d+)\s*红'}
    for key, pattern in patterns.items():
        match = re.search(pattern, dice_str)
        if match: counts[key] = int(match.group(1))
    return counts


class CombatState:
    """
    战斗状态机。
    此类封装了一次完整攻击（包括重投和效果选择）的所有状态和逻辑。
    """

    def __init__(self, attacker_entity, defender_entity, action, target_part_name,
                 is_back_attack=False, is_interception_attack=False):
        """
        初始化一个新的战斗会话。
        """
        # --- 核心上下文 (在战斗中不变) ---
        self.attacker_entity = attacker_entity
        self.defender_entity = defender_entity
        self.action = action
        self.target_part_name = target_part_name
        self.is_back_attack = is_back_attack
        self.is_interception_attack = is_interception_attack  # 拦截攻击不能被重投

        # --- 状态管理 ---
        self.stage = 'INITIAL_ROLL'

        # --- 战斗中可变的数据 ---
        self.attack_raw_rolls = {}
        self.defense_raw_rolls = {}
        self.overflow_hits = 0
        self.overflow_crits = 0
        self.available_effect_options = []
        self.initial_dice_roll_details = {}  # 存储第一次掷骰的视觉结果
        self.pending_effect_reroll_data = {}  # 存储效果重投所需的数据

        # [NEW] 标记是否已经触发过 Ace 重投 (防止死循环)
        self.ace_rerolled = False

    def to_dict(self):
        """将当前战斗状态序列化为字典，以便存储在 Mech.pending_combat 中。"""
        return {
            'attacker_id': self.attacker_entity.id,
            'defender_id': self.defender_entity.id,
            'action_dict': self.action.to_dict(),
            'target_part_name': self.target_part_name,
            'is_back_attack': self.is_back_attack,
            'is_interception_attack': self.is_interception_attack,
            'stage': self.stage,
            'attack_raw_rolls': self.attack_raw_rolls,
            'defense_raw_rolls': self.defense_raw_rolls,
            'overflow_hits': self.overflow_hits,
            'overflow_crits': self.overflow_crits,
            'available_effect_options': self.available_effect_options,
            'initial_dice_roll_details': self.initial_dice_roll_details,
            'pending_effect_reroll_data': self.pending_effect_reroll_data,
            'ace_rerolled': self.ace_rerolled,
        }

    @classmethod
    def from_dict(cls, data, game_state):
        """从字典和 game_state 恢复战斗状态机。"""
        attacker = game_state.get_entity_by_id(data['attacker_id'])
        defender = game_state.get_entity_by_id(data['defender_id'])
        action = Action.from_dict(data['action_dict'])

        if not attacker or not defender or not action:
            raise ValueError("无法从字典中恢复 CombatState：找不到实体或动作。")

        session = cls(
            attacker,
            defender,
            action,
            data['target_part_name'],
            data.get('is_back_attack', False),
            data.get('is_interception_attack', False)
        )

        # 恢复所有内部状态
        session.stage = data.get('stage', 'INITIAL_ROLL')
        session.attack_raw_rolls = data.get('attack_raw_rolls', {})
        session.defense_raw_rolls = data.get('defense_raw_rolls', {})
        session.overflow_hits = data.get('overflow_hits', 0)
        session.overflow_crits = data.get('overflow_crits', 0)
        session.available_effect_options = data.get('available_effect_options', [])
        session.initial_dice_roll_details = data.get('initial_dice_roll_details', {})
        session.pending_effect_reroll_data = data.get('pending_effect_reroll_data', {})
        session.ace_rerolled = data.get('ace_rerolled', False)

        return session

    # --- 公共接口方法 (由 Controller 调用) ---

    def resolve(self, log, chosen_effect=None, rerolled_attack_raw=None, rerolled_defense_raw=None):
        """
        推进战斗状态机。
        这是此类的主要入口点，根据 self.stage 路由到不同的解析器。
        """

        # --- 状态路由 ---
        try:
            if self.stage == 'AWAITING_ATTACK_REROLL':
                return self._resolve_rerolled_attack(log, rerolled_attack_raw, rerolled_defense_raw)

            elif self.stage == 'AWAITING_EFFECT_CHOICE':
                return self._resolve_chosen_effect(log, chosen_effect)

            elif self.stage == 'AWAITING_EFFECT_REROLL':
                return self._resolve_rerolled_effect(log, rerolled_defense_raw)

            elif self.stage == 'INITIAL_ROLL':
                return self._resolve_initial_roll(log)

        except Exception as e:
            log.append(f"[!!] 战斗计算时发生严重错误: {e}")
            log.append(traceback.format_exc())
            self.stage = 'RESOLVED'
            return log, self._create_empty_packet('invalid')

        log.append(f"[系统错误] CombatState 处于无效或已解决的状态: {self.stage}")
        self.stage = 'RESOLVED'
        return log, self._create_empty_packet('invalid')

    def submit_reroll(self, log, selections_attacker, selections_defender, rerolling_player):
        """
        (公共接口) 玩家提交了重投选择。
        此方法计算新骰子，然后调用 resolve() 来推进状态机。
        """

        # 确定我们是在重投攻击还是效果
        current_stage = self.stage

        if current_stage not in ['AWAITING_ATTACK_REROLL', 'AWAITING_EFFECT_REROLL']:
            log.append(f"[系统错误] 试图在 {current_stage} 阶段提交重投。")
            return log, self._create_empty_packet('invalid')

        player_did_reroll = False
        link_cost_applied = False

        # 准备骰子
        new_attack_rolls = self.attack_raw_rolls
        new_defense_rolls = {}

        if current_stage == 'AWAITING_ATTACK_REROLL':
            new_defense_rolls = self.defense_raw_rolls
        elif current_stage == 'AWAITING_EFFECT_REROLL':
            # 如果是效果重投，我们只关心防御骰
            new_defense_rolls = self.pending_effect_reroll_data.get('defense_raw_rolls', {})

        # --- 1. 执行玩家的重投 ---
        # 检查攻击骰
        if selections_attacker:
            if rerolling_player and rerolling_player.pilot and rerolling_player.pilot.link_points > 0:
                log.append(f"  > 玩家 (攻击方) 消耗 1 链接值重投 {len(selections_attacker)} 枚骰子！")
                rerolling_player.pilot.link_points -= 1  # 状态修改：消耗链接值
                player_did_reroll = True
                link_cost_applied = True
                new_attack_rolls = reroll_specific_dice(new_attack_rolls, selections_attacker)
            else:
                log.append("  > [警告] 玩家试图重投攻击骰，但链接值不足！")

        # 检查防御骰
        if selections_defender:
            if rerolling_player and rerolling_player.pilot and rerolling_player.pilot.link_points > 0:
                log.append(f"  > 玩家 (防御方) 消耗 1 链接值重投 {len(selections_defender)} 枚骰子！")
                if not link_cost_applied:
                    rerolling_player.pilot.link_points -= 1  # 状态修改：消耗链接值
                player_did_reroll = True
                new_defense_rolls = reroll_specific_dice(new_defense_rolls, selections_defender)
            else:
                log.append("  > [警告] 玩家试图重投防御骰，但链接值不足！")

        # 记录日志
        if not player_did_reroll and (selections_attacker or selections_defender):
            log.append("  > 玩家选择不重投。")
        elif not player_did_reroll:
            log.append("  > 玩家跳过重投。")

        # --- 2. 推进状态机 ---
        # resolve() 将根据 self.stage 自动路由到正确的函数
        return self.resolve(log,
                            rerolled_attack_raw=new_attack_rolls,
                            rerolled_defense_raw=new_defense_rolls)

    def submit_effect_choice(self, log, choice):
        """
        (公共接口) 玩家提交了效果选择。
        """
        if self.stage != 'AWAITING_EFFECT_CHOICE':
            log.append(f"[系统错误] 试图在 {self.stage} 阶段提交效果选择。")
            return log, self._create_empty_packet('invalid')

        if choice not in self.available_effect_options:
            log.append(f"[系统错误] 玩家选择了无效的效果: {choice}")
            return log, self._create_empty_packet('invalid')

        # 推进状态机：resolve() 将路由到 _resolve_chosen_effect
        return self.resolve(log, chosen_effect=choice)

    # --- 私有辅助方法 ---

    def _create_empty_packet(self, status='invalid'):
        """(私有辅助函数) 创建一个空的、安全的结果包。"""
        return {
            'attacker_id': self.attacker_entity.id,
            'defender_id': self.defender_entity.id,
            'action_name': self.action.name,
            'status': status,
            'dice_roll_details': {},  # 确保 dice_roll_details 始终是一个字典
            'part_changes': [],
            'pilot_changes': [],
            'entity_changes': [],
        }

    def _resolve_initial_roll(self, log):
        """
        (私有) 执行战斗的第一次掷骰和结算。
        [NEW] 这里包含了 Ace AI 的同步重投逻辑。
        """
        # --- 1. 初始化 ---
        log.append(f"> {self.attacker_entity.name} 使用 [{self.action.name}] 攻击 {self.defender_entity.name}。")
        result_packet = self._create_empty_packet('miss')
        dice_roll_details = {
            'type': 'attack_roll',
            'attack_dice_input': {}, 'attack_dice_result': {},
            'defense_dice_input': {}, 'defense_dice_result': {},
            'secondary_roll': None
        }
        result_packet['dice_roll_details'] = dice_roll_details

        # --- 2. 确定目标部件 ---
        target_part = None
        if isinstance(self.defender_entity, Projectile):
            target_part = self.defender_entity.parts.get('core')
            if target_part:
                self.target_part_name = 'core'
            log.append(f"  > 目标是抛射物，自动瞄准 [核心]。")
        elif isinstance(self.defender_entity, Mech):
            target_part = self.defender_entity.get_part_by_name(self.target_part_name)

        if not target_part:
            log.append(f"  > [错误] 无法找到目标部件 '{self.target_part_name}'。攻击中止。")
            self.stage = 'RESOLVED'
            return log, self._create_empty_packet('invalid')

        original_status = target_part.status

        # --- 3. 投掷攻击骰 ---
        attack_dice_counts = parse_dice_string(self.action.dice)
        is_mech_attacker = isinstance(self.attacker_entity, Mech)
        is_mech_defender = isinstance(self.defender_entity, Mech)

        if is_mech_attacker:
            passive_effects = self.attacker_entity.get_passive_effects()
            for effect_dict in passive_effects:
                if "passive_dice_boost" in effect_dict:
                    boost_rule = effect_dict["passive_dice_boost"]
                    if (self.attacker_entity.stance == boost_rule.get("trigger_stance") and
                            self.action.action_type == boost_rule.get("trigger_type")):
                        dice_type_to_check = boost_rule.get("dice_type")
                        base_count = attack_dice_counts.get(dice_type_to_check, 0)
                        if base_count > 0:
                            ratio_base = boost_rule.get("ratio_base", 3)
                            ratio_add = boost_rule.get("ratio_add", 1)
                            bonus_dice = (base_count // ratio_base) * ratio_add
                            if bonus_dice > 0:
                                log.append(
                                    f"  > [被动效果: {effect_dict.get('display_effects', ['未知效果'])[0]}] 触发！")
                                attack_dice_counts[dice_type_to_check] = base_count + bonus_dice

                if effect_dict.get("stance_mastery"):
                    if self.attacker_entity.stance == 'attack':
                        if self.action.action_type in ['近战', '射击', '战术']:
                            log.append(f"  > [被动效果: 战斗型OS] 触发！攻击姿态下攻击骰 +1黄。")
                            attack_dice_counts['yellow_count'] = attack_dice_counts.get('yellow_count', 0) + 1

        dice_roll_details['attack_dice_input'] = attack_dice_counts.copy()

        # 存储原始骰子，以便重投
        self.attack_raw_rolls = roll_dice(**attack_dice_counts)

        attacker_stance = 'attack' if (is_mech_attacker and self.attacker_entity.stance == 'attack') else 'defense'
        convert_lightning = self.action.effects and self.action.effects.get("convert_lightning_to_crit", False)

        processed_attack_rolls, attack_roll_summary = process_rolls(
            self.attack_raw_rolls,
            stance=attacker_stance,
            convert_lightning_to_crit=convert_lightning
        )
        dice_roll_details['attack_dice_result'] = processed_attack_rolls
        log.append(f"  > 攻击方投掷结果 (处理后): {attack_roll_summary or '无'}")

        # --- 4. 投掷受击骰 ---
        white_dice_count = target_part.structure if original_status == 'damaged' else target_part.armor
        log_dice_source = "结构值" if original_status == 'damaged' else "装甲值"

        if self.action.effects:
            ap_value = self.action.effects.get("armor_piercing", 0)
            if ap_value > 0 and original_status != 'damaged':
                log.append(f"  > 动作效果【穿甲{ap_value}】触发！")
                white_dice_count = max(0, white_dice_count - ap_value)

        blue_dice_count = self.defender_entity.get_total_evasion() if self.defender_entity.stance == 'agile' else 0

        if isinstance(self.defender_entity,
                      Mech) and self.action.action_type == '近战' and target_part.parry > 0 and not self.is_back_attack and self.defender_entity.stance != 'downed':
            white_dice_count += target_part.parry
            log.append(f"  > [招架] 额外增加 {target_part.parry} 个白骰。")

        if is_mech_defender:
            passive_effects = self.defender_entity.get_passive_effects()
            for effect_dict in passive_effects:
                if effect_dict.get("stance_mastery"):
                    if self.defender_entity.stance == 'defense':
                        white_dice_count += 1
                        log.append(f"  > [被动效果: 战斗型OS] 触发！防御姿态下白骰 +1。")
                    elif self.defender_entity.stance == 'agile':
                        blue_dice_count += 2
                        log.append(f"  > [被动效果: 战斗型OS] 触发！机动姿态下蓝骰 +2。")

        dice_roll_details['defense_dice_input'] = {'white_count': white_dice_count, 'blue_count': blue_dice_count}

        self.defense_raw_rolls = roll_dice(white_count=white_dice_count, blue_count=blue_dice_count)

        processed_defense_rolls, defense_roll_summary = process_rolls(
            self.defense_raw_rolls,
            stance=self.defender_entity.stance
        )
        dice_roll_details['defense_dice_result'] = processed_defense_rolls
        log.append(f"  > 防御方结果 (处理后): {defense_roll_summary or '无'}")

        # === [NEW] Ace AI 指令重投逻辑 (Synchronous) ===
        # 在玩家做出决定前，Ace AI 优先决定是否重投

        if not self.ace_rerolled and not self.is_interception_attack:
            # A. Ace 是攻击方
            if is_mech_attacker and self.attacker_entity.controller == 'ai':
                # 检测 Ace 特征 (有 Link Points)
                if self.attacker_entity.pilot and self.attacker_entity.pilot.link_points > 0:
                    reroll_selections = ace_logic.decide_reroll(
                        self.attacker_entity, self.defender_entity, self.action,
                        attack_roll_summary, defense_roll_summary,
                        self.attack_raw_rolls, self.defense_raw_rolls,
                        is_attacker=True
                    )
                    if reroll_selections:
                        log.append(f"> [警告] 王牌机师 {self.attacker_entity.name} 消耗 1 链接值强制修正攻击弹道！")
                        self.attacker_entity.pilot.link_points -= 1
                        self.attack_raw_rolls = reroll_specific_dice(self.attack_raw_rolls, reroll_selections)
                        self.ace_rerolled = True

                        # 重新处理攻击骰
                        processed_attack_rolls, attack_roll_summary = process_rolls(
                            self.attack_raw_rolls,
                            stance=attacker_stance,
                            convert_lightning_to_crit=convert_lightning
                        )
                        dice_roll_details['attack_dice_result'] = processed_attack_rolls
                        log.append(f"  > (修正后) 攻击结果: {attack_roll_summary or '无'}")

            # B. Ace 是防御方
            if is_mech_defender and self.defender_entity.controller == 'ai':
                # 检测 Ace 特征
                if self.defender_entity.pilot and self.defender_entity.pilot.link_points > 0:
                    reroll_selections = ace_logic.decide_reroll(
                        self.defender_entity, self.attacker_entity, self.action,
                        attack_roll_summary, defense_roll_summary,
                        self.attack_raw_rolls, self.defense_raw_rolls,
                        is_attacker=False
                    )
                    if reroll_selections:
                        log.append(f"> [警告] 王牌机师 {self.defender_entity.name} 消耗 1 链接值强制修正防御机动！")
                        self.defender_entity.pilot.link_points -= 1
                        self.defense_raw_rolls = reroll_specific_dice(self.defense_raw_rolls, reroll_selections)
                        self.ace_rerolled = True

                        # 重新处理防御骰
                        processed_defense_rolls, defense_roll_summary = process_rolls(
                            self.defense_raw_rolls,
                            stance=self.defender_entity.stance
                        )
                        dice_roll_details['defense_dice_result'] = processed_defense_rolls
                        log.append(f"  > (修正后) 防御结果: {defense_roll_summary or '无'}")

        # === Ace 重投逻辑结束 ===

        self.initial_dice_roll_details = dice_roll_details.copy()

        # --- 5. [中断点] 玩家专注重投检查 ---
        # 即使 Ace 已经重投，玩家依然有权选择是否重投 (双方博弈)
        if not self.is_interception_attack:
            player_is_attacker = (self.attacker_entity.controller == 'player')
            player_is_defender = (self.defender_entity.controller == 'player')
            attacker_can_reroll = (
                    player_is_attacker and isinstance(self.attacker_entity, Mech) and
                    self.attacker_entity.pilot and self.attacker_entity.pilot.link_points > 0
            )
            defender_can_reroll = (
                    player_is_defender and isinstance(self.defender_entity, Mech) and
                    self.defender_entity.pilot and self.defender_entity.pilot.link_points > 0
            )

            if attacker_can_reroll or defender_can_reroll:
                player_link_points = 0
                if player_is_attacker and isinstance(self.attacker_entity, Mech):
                    player_link_points = self.attacker_entity.pilot.link_points
                elif player_is_defender and isinstance(self.defender_entity, Mech):
                    player_link_points = self.defender_entity.pilot.link_points

                log.append(f"  > 玩家链接值: {player_link_points}。等待重投决策...")

                self.stage = 'AWAITING_ATTACK_REROLL'
                result_packet['status'] = 'reroll_choice_required'
                return log, result_packet

        # --- 如果没有重投，则直接进入重投后的结算逻辑 ---
        return self._resolve_rerolled_attack(log, self.attack_raw_rolls, self.defense_raw_rolls)

    def _resolve_rerolled_attack(self, log, rerolled_attack_raw, rerolled_defense_raw):
        """
        (私有) 结算已经（或跳过）重投的攻击。
        这可能会导致 'RESOLVED' 或 'AWAITING_EFFECT_CHOICE'。
        """

        # --- 1. 初始化 ---
        result_packet = self._create_empty_packet('miss')
        # 复用（或更新）初始掷骰详情
        dice_roll_details = self.initial_dice_roll_details
        result_packet['dice_roll_details'] = dice_roll_details

        target_part = None
        if isinstance(self.defender_entity, Projectile):
            target_part = self.defender_entity.parts.get('core')
            if target_part:
                self.target_part_name = 'core'
        elif isinstance(self.defender_entity, Mech):
            target_part = self.defender_entity.get_part_by_name(self.target_part_name)

        if not target_part:
            log.append(f"  > [错误] 重投后无法找到目标部件 '{self.target_part_name}'。")
            self.stage = 'RESOLVED'
            return log, self._create_empty_packet('invalid')

        original_status = target_part.status
        is_mech_attacker = isinstance(self.attacker_entity, Mech)
        is_mech_defender = isinstance(self.defender_entity, Mech)

        # --- 2. 处理重投后的攻击骰 ---
        attacker_stance = 'attack' if (is_mech_attacker and self.attacker_entity.stance == 'attack') else 'defense'
        convert_lightning = self.action.effects and self.action.effects.get("convert_lightning_to_crit", False)

        processed_attack_rolls, attack_roll = process_rolls(
            rerolled_attack_raw,
            stance=attacker_stance,
            convert_lightning_to_crit=convert_lightning
        )
        # 更新掷骰详情
        dice_roll_details['attack_dice_result'] = processed_attack_rolls

        hits = attack_roll.get('轻击', 0)
        crits = attack_roll.get('重击', 0)
        attack_lightning = attack_roll.get('闪电', 0)

        # --- 3. 处理重投后的防御骰 ---
        processed_defense_rolls, defense_roll = process_rolls(
            rerolled_defense_raw,
            stance=self.defender_entity.stance
        )
        # 更新掷骰详情
        dice_roll_details['defense_dice_result'] = processed_defense_rolls

        # --- 4. 结算伤害 ---
        defenses = defense_roll.get('防御', 0)
        dodges = defense_roll.get('闪避', 0)

        cancelled_hits = min(hits, defenses)
        hits -= cancelled_hits
        log.append(f"  > {cancelled_hits}个[防御]抵消了{cancelled_hits}个[轻击]。")

        cancelled_crits = min(crits, dodges)
        crits -= cancelled_crits
        dodges -= cancelled_crits

        cancelled_hits_by_dodge = min(hits, dodges)
        hits -= cancelled_hits_by_dodge
        dodges -= cancelled_hits_by_dodge

        log.append(
            f"  > {defense_roll.get('闪避', 0)}个[闪避]抵消了{cancelled_crits}个[重击]和{cancelled_hits_by_dodge}个[轻击]。")

        # --- 4.1 结算【震撼】效果 ---
        has_shock = self.action.effects.get("shock", False)
        if has_shock and attack_lightning > 0:
            log.append(f"  > 动作效果【震撼】触发！")
            log.append(f"  > 攻击方投出 {attack_lightning} [闪电]。")

            cancelled_lightning = min(attack_lightning, dodges)
            net_lightning = max(0, attack_lightning - cancelled_lightning)

            if cancelled_lightning > 0:
                log.append(f"  > {cancelled_lightning} 个剩余[闪避]抵消了 {cancelled_lightning} [闪电]。")
                dodges -= cancelled_lightning

            if net_lightning > 0:
                if is_mech_defender and self.defender_entity.pilot and self.defender_entity.pilot.link_points > 0:
                    link_loss = min(self.defender_entity.pilot.link_points, net_lightning)
                    result_packet['pilot_changes'].append(
                        {'target_id': self.defender_entity.id, 'link_loss': link_loss})
                    log.append(
                        f"  > {link_loss} 点净[闪电]使驾驶员 [{self.defender_entity.pilot.name}] 失去 {link_loss} 点链接值 (剩余: {self.defender_entity.pilot.link_points - link_loss})！")

                    if (
                            self.defender_entity.pilot.link_points - link_loss) <= 0 and self.defender_entity.stance != 'downed':
                        result_packet['entity_changes'].append(
                            {'target_id': self.defender_entity.id, 'stance': 'downed'})
                        log.append(f"  > 驾驶员链接值归零！机甲 [{self.defender_entity.name}] 进入 [宕机姿态]！")
                elif is_mech_defender:
                    log.append(f"  > 目标驾驶员没有链接值，【震撼】无效。")
                else:
                    log.append(f"  > 目标不是机甲，【震撼】无效。")
            else:
                log.append(f"  > 所有[闪电]均被[闪避]抵消，【震撼】无效。")

        # --- 5. 判断结果 ---
        final_damage = hits + crits
        self.overflow_hits = hits  # 存储溢出伤害
        self.overflow_crits = crits  # 存储溢出伤害

        if final_damage > 0:
            log.append(f"  > 最终造成了 [击穿]！")
            result_packet['status'] = 'penetration'

            # [新增] 驾驶员技能：乘胜追击 (Pursuit)
            if is_mech_attacker and self.attacker_entity.pilot and "pursuit" in self.attacker_entity.pilot.skills:
                self.attacker_entity.player_tp += 1
                log.append(f"  > [驾驶员技能: 乘胜追击] 触发！{self.attacker_entity.name} 获得 1 TP。")

            # 5.1 更新状态 (记录变更)
            new_status = original_status
            if isinstance(self.defender_entity, Projectile):
                new_status = 'destroyed'
                log.append(f"  > [抛射物] 目标 [{target_part.name}] 被 [摧毁]！")
            elif target_part.structure == 0:
                new_status = 'destroyed'
                log.append(f"  > (无结构) 部件 [{target_part.name}] 被 [摧毁]！")
            elif original_status == 'ok':
                new_status = 'damaged'
                log.append(f"  > 部件 [{target_part.name}] 状态变为 [破损]。")
            elif original_status == 'damaged':
                new_status = 'destroyed'
                log.append(f"  > 已破损的部件 [{target_part.name}] 被 [摧毁]！")

            if new_status != original_status:
                result_packet['part_changes'].append({
                    'target_id': self.defender_entity.id,
                    'part_slot': self.target_part_name,
                    'new_status': new_status
                })

            if is_mech_defender and new_status == 'destroyed':
                if self.defender_entity.pilot and self.defender_entity.pilot.link_points > 0:
                    result_packet['pilot_changes'].append({'target_id': self.defender_entity.id, 'link_loss': 1})
                    log.append(
                        f"  > 驾驶员 [{self.defender_entity.pilot.name}] 失去 1 点链接值 (剩余: {self.defender_entity.pilot.link_points - 1})！")

                    if (self.defender_entity.pilot.link_points - 1) <= 0 and self.defender_entity.stance != 'downed':
                        result_packet['entity_changes'].append(
                            {'target_id': self.defender_entity.id, 'stance': 'downed'})
                        log.append(f"  > 驾驶员链接值归零！机甲 [{self.defender_entity.name}] 进入 [宕机姿态]！")

            if new_status == 'destroyed' and self.target_part_name == 'core':
                result_packet['entity_changes'].append({'target_id': self.defender_entity.id, 'status': 'destroyed'})
                log.append(f"  > 实体 [{self.defender_entity.name}] 的核心被摧毁，实体被移除！")

            # --- 5.2 [中断点] 效果选择 ---
            if not is_mech_defender:
                log.append(f"  > 目标不是机甲，跳过【毁伤】/【霰射】/【顺劈】效果结算。")
                if isinstance(self.attacker_entity, Projectile):
                    result_packet['entity_changes'].append(
                        {'target_id': self.attacker_entity.id, 'status': 'destroyed'})
                    log.append(f"  > [抛射物] {self.attacker_entity.name} 在攻击后引爆并移除。")
                self.stage = 'RESOLVED'
                return log, result_packet

            # 检查动态效果
            has_devastating = self.action.effects.get("devastating", False)
            if is_mech_attacker and not has_devastating and self.action.effects.get("two_handed_devastating", False):
                action_slot = None
                for slot, part in self.attacker_entity.parts.items():
                    if part and part.status != 'destroyed':
                        for act in part.actions:
                            if act.name == self.action.name: action_slot = slot; break
                    if action_slot: break
                if action_slot in ['left_arm', 'right_arm']:
                    other_arm_slot = 'right_arm' if action_slot == 'left_arm' else 'left_arm'
                    other_arm_part = self.attacker_entity.parts.get(other_arm_slot)
                    if other_arm_part and other_arm_part.status != 'destroyed' and "【空手】" in other_arm_part.tags:
                        log.append(f"  > 动作效果【【双手】获得毁伤】触发 (另一只手为【空手】)！")
                        has_devastating = True

            has_scattershot = self.action.effects.get("scattershot", False)
            has_cleave = self.action.effects.get("cleave", False)
            has_overflow = (self.overflow_hits > 0 or self.overflow_crits > 0)

            devastating_conditions_met = (
                    has_devastating and
                    target_part.structure > 0 and
                    original_status == 'ok' and
                    new_status == 'damaged' and
                    has_overflow
            )
            scattershot_conditions_met = (has_scattershot and has_overflow)
            cleave_conditions_met = (has_cleave and has_overflow)

            self.available_effect_options = []
            if devastating_conditions_met: self.available_effect_options.append('devastating')
            if scattershot_conditions_met: self.available_effect_options.append('scattershot')
            if cleave_conditions_met: self.available_effect_options.append('cleave')

            if len(self.available_effect_options) > 1:
                if is_mech_attacker and self.attacker_entity.controller == 'player':
                    log.append(f"> [玩家决策] 攻击同时触发 {len(self.available_effect_options)} 个效果！")
                    log.append("> 请选择要发动的效果...")

                    self.stage = 'AWAITING_EFFECT_CHOICE'
                    result_packet['status'] = 'effect_choice_required'
                    return log, result_packet
                else:
                    chosen_effect = 'devastating' if 'devastating' in self.available_effect_options else \
                        'cleave' if 'cleave' in self.available_effect_options else 'scattershot'
                    log.append(f"> [AI决策] AI 优先选择【{chosen_effect}】。")
                    return self._resolve_chosen_effect(log, chosen_effect, result_packet)

            elif len(self.available_effect_options) == 1:
                chosen_effect = self.available_effect_options[0]
                return self._resolve_chosen_effect(log, chosen_effect, result_packet)

        # --- 6. 最终步骤 (无伤害或无效果) ---
        if isinstance(self.attacker_entity, Projectile):
            result_packet['entity_changes'].append({'target_id': self.attacker_entity.id, 'status': 'destroyed'})
            log.append(f"  > [抛射物] {self.attacker_entity.name} 在攻击后引爆并移除。")

        self.stage = 'RESOLVED'
        return log, result_packet

    def _resolve_rerolled_effect(self, log, rerolled_defense_raw):
        """
        (私有) 结算已经（或跳过）重投的效果掷骰。
        这 *必须* 导致 'RESOLVED'。
        """

        log.append(f"> 玩家提交了对【{self.pending_effect_reroll_data.get('chosen_effect')}】的重投。")

        # --- 1. 准备 ---
        result_packet = self._create_empty_packet('penetration')
        result_packet['dice_roll_details'] = self.initial_dice_roll_details.copy()

        pending_data = self.pending_effect_reroll_data
        target_part = self.defender_entity.get_part_by_name(pending_data['target_part_name'])

        if not target_part:
            log.append(f"  > [错误] 效果重投结算时找不到部件 '{pending_data['target_part_name']}'。")
            self.stage = 'RESOLVED'
            return log, self._create_empty_packet('invalid')

        # --- 2. 重新计算效果 ---
        log, secondary_roll_details, effect_packet_ext = self._calculate_effect_logic(
            log, self.attacker_entity, self.defender_entity, target_part,
            pending_data['overflow_hits'], pending_data['overflow_crits'], pending_data['chosen_effect'],
            skip_reroll_phase=True,  # 关键：防止无限循环
            rerolled_defense_raw=rerolled_defense_raw
        )

        # --- 3. 合并结果 ---
        if secondary_roll_details:
            result_packet['dice_roll_details']['secondary_roll'] = secondary_roll_details

        result_packet['part_changes'].extend(effect_packet_ext.get('part_changes', []))
        result_packet['pilot_changes'].extend(effect_packet_ext.get('pilot_changes', []))
        result_packet['entity_changes'].extend(effect_packet_ext.get('entity_changes', []))

        # --- 4. 战斗完全结束 ---
        if effect_packet_ext.get('status') == 'reroll_choice_required':
            # 这不应该发生，但作为安全措施
            log.append("[系统警告] 效果重投后再次触发了重投！战斗强制结束。")

        if isinstance(self.attacker_entity, Projectile):
            result_packet['entity_changes'].append({'target_id': self.attacker_entity.id, 'status': 'destroyed'})
            log.append(f"  > [抛射物] {self.attacker_entity.name} 在攻击后引爆并移除。")

        self.stage = 'RESOLVED'
        return log, result_packet

    def _resolve_chosen_effect(self, log, chosen_effect, result_packet=None):
        """
        (私有) 结算选定的效果 (手动选择或自动单选)。
        """
        if result_packet is None:
            result_packet = self._create_empty_packet('penetration')
            # 如果是从 submit_effect_choice 恢复的，我们需要重新填充 dice_roll_details
            result_packet['dice_roll_details'] = self.initial_dice_roll_details.copy()

        log.append(f"> 选定效果: 【{chosen_effect}】")

        # 1. 计算效果逻辑
        target_part = self.defender_entity.get_part_by_name(self.target_part_name)
        if not target_part:
            log.append(f"  > [错误] 无法找到目标部件 '{self.target_part_name}'。")
            self.stage = 'RESOLVED'
            return log, result_packet

        # 调用 _calculate_effect_logic
        # 注意：_calculate_effect_logic 内部会处理重投检查
        log, dice_roll_details_2, packet_extension = self._calculate_effect_logic(
            log, self.attacker_entity, self.defender_entity, target_part,
            self.overflow_hits, self.overflow_crits, chosen_effect
        )

        # 2. 处理结果
        if packet_extension.get('status') == 'reroll_choice_required':
            # 发生重投中断
            self.stage = 'AWAITING_EFFECT_REROLL'
            # 保存重投所需的数据 (在 _calculate_effect_logic 中可能已经构建了部分，但我们需要保存它)
            self.pending_effect_reroll_data = packet_extension['pending_reroll_data']

            # 合并 status 到 result_packet
            result_packet['status'] = 'reroll_choice_required'
            # 添加第二次掷骰的详情到 result_packet
            if dice_roll_details_2:
                result_packet['dice_roll_details']['secondary_roll'] = dice_roll_details_2

            return log, result_packet

        # 3. 正常结算
        if dice_roll_details_2:
            result_packet['dice_roll_details']['secondary_roll'] = dice_roll_details_2

        result_packet['part_changes'].extend(packet_extension.get('part_changes', []))
        result_packet['pilot_changes'].extend(packet_extension.get('pilot_changes', []))
        result_packet['entity_changes'].extend(packet_extension.get('entity_changes', []))

        # 4. 结束战斗
        if isinstance(self.attacker_entity, Projectile):
            result_packet['entity_changes'].append({'target_id': self.attacker_entity.id, 'status': 'destroyed'})
            log.append(f"  > [抛射物] {self.attacker_entity.name} 在攻击后引爆并移除。")

        self.stage = 'RESOLVED'
        return log, result_packet

    def _calculate_effect_logic(self, log, attacker_entity, defender_entity, target_part, overflow_hits, overflow_crits,
                                chosen_effect, skip_reroll_phase=False, rerolled_defense_raw=None):
        """
        (私有) 纯计算函数：计算【毁伤】/【霰射】/【顺劈】效果的结果。
        """

        # 初始化此效果包
        packet_extension = {
            'status': 'resolved',
            'part_changes': [],
            'pilot_changes': [],
            'entity_changes': []
        }
        dice_roll_details_2 = None
        pending_reroll_data = None

        if not isinstance(defender_entity, Mech):
            log.append(f"  > [效果：{chosen_effect}] 触发，但目标不是机甲，效果跳过。")
            return log, dice_roll_details_2, packet_extension

        # 检查 [战斗型OS] 效果加成 (用于所有效果掷骰的防御方)
        stance_mastery_bonus_white = 0
        stance_mastery_bonus_blue = 0
        if isinstance(defender_entity, Mech):
            passive_effects = defender_entity.get_passive_effects()
            for effect_dict in passive_effects:
                if effect_dict.get("stance_mastery"):
                    if defender_entity.stance == 'defense':
                        stance_mastery_bonus_white += 1
                    elif defender_entity.stance == 'agile':
                        stance_mastery_bonus_blue += 2

        if stance_mastery_bonus_white > 0:
            log.append(f"  > [被动效果: 战斗型OS] 触发！防御姿态下额外增加 +{stance_mastery_bonus_white}白。")
        if stance_mastery_bonus_blue > 0:
            log.append(f"  > [被动效果: 战斗型OS] 触发！机动姿态下额外增加 +{stance_mastery_bonus_blue}蓝。")

        # 5.2.A 【毁伤】
        if chosen_effect == 'devastating':
            log.append(f"  > [效果：毁伤] 触发！")
            log.append(f"  > 计算对结构值的溢出伤害: {overflow_crits}重, {overflow_hits}轻。")
            white_dice_count_2 = target_part.structure + stance_mastery_bonus_white
            blue_dice_count_2 = (
                    defender_entity.get_total_evasion() + stance_mastery_bonus_blue) if defender_entity.stance == 'agile' else 0

            dice_roll_details_2 = {
                'type': 'devastating_roll',
                'defense_dice_input': {'white_count': white_dice_count_2, 'blue_count': blue_dice_count_2},
                'attack_dice_input': {},
                'attack_dice_result': {}
            }

            if rerolled_defense_raw:
                defense_raw_rolls_2 = rerolled_defense_raw
                log.append("  > (使用重投后的毁伤防御骰...)")
            else:
                defense_raw_rolls_2 = roll_dice(white_count=white_dice_count_2, blue_count=blue_dice_count_2)

            # --- 重投中断检查 ---
            if not skip_reroll_phase:
                player_is_defender = (defender_entity.controller == 'player')
                defender_can_reroll = (
                        player_is_defender and
                        isinstance(defender_entity, Mech) and
                        defender_entity.pilot and
                        defender_entity.pilot.link_points > 0
                )
                if defender_can_reroll:
                    log.append(f"  > [毁伤结算] 玩家链接值: {defender_entity.pilot.link_points}。等待重投决策...")

                    processed_rolls, _ = process_rolls(defense_raw_rolls_2, stance=defender_entity.stance)
                    dice_roll_details_2['defense_dice_result'] = processed_rolls

                    pending_reroll_data = {
                        'type': 'effect_reroll',
                        'attacker_id': attacker_entity.id,
                        'defender_id': defender_entity.id,
                        'target_part_name': target_part.name,
                        'overflow_hits': overflow_hits,
                        'overflow_crits': overflow_crits,
                        'chosen_effect': chosen_effect,
                        'attack_raw_rolls': {},
                        'defense_raw_rolls': defense_raw_rolls_2,
                        'player_is_attacker': False,
                        'player_is_defender': True,
                    }

                    packet_extension['status'] = 'reroll_choice_required'
                    packet_extension['pending_reroll_data'] = pending_reroll_data
                    return log, dice_roll_details_2, packet_extension
            # --- 重投检查结束 ---

            processed_defense_rolls_2, defense_roll_2 = process_rolls(
                defense_raw_rolls_2,
                stance=defender_entity.stance
            )
            dice_roll_details_2['defense_dice_result'] = processed_defense_rolls_2

            log_msg_2 = f"  > [毁伤结算] 防御方 (基于结构值) 投掷 {white_dice_count_2}白"
            if blue_dice_count_2 > 0: log_msg_2 += f" {blue_dice_count_2}蓝 (机动姿态)"
            log_msg_2 += f", 结果: {defense_roll_2 or '无'}"
            log.append(log_msg_2)

            defenses_2 = defense_roll_2.get('防御', 0)
            dodges_2 = defense_roll_2.get('闪避', 0)
            hits_2 = overflow_hits
            crits_2 = overflow_crits

            cancelled_hits_2 = min(hits_2, defenses_2)
            hits_2 -= cancelled_hits_2
            log.append(f"  > [毁伤结算] {cancelled_hits_2}个[防御]抵消了{cancelled_hits_2}个[轻击]。")

            cancelled_crits_2 = min(crits_2, dodges_2)
            crits_2 -= cancelled_crits_2
            dodges_2 -= cancelled_crits_2

            cancelled_hits_by_dodge_2 = min(hits_2, dodges_2)
            hits_2 -= cancelled_hits_by_dodge_2
            log.append(
                f"  > [毁伤结算] {dodges_2 + cancelled_crits_2}个[闪避]抵消了{cancelled_crits_2}个[重击]和{cancelled_hits_by_dodge_2}个[轻击]。")

            final_damage_2 = hits_2 + crits_2
            if final_damage_2 > 0:
                log.append(f"  > [毁伤结算] 结构值被击穿！")

                # [新增] 驾驶员技能：乘胜追击 (Pursuit) - 毁伤效果也算作击穿
                if isinstance(attacker_entity,
                              Mech) and attacker_entity.pilot and "pursuit" in attacker_entity.pilot.skills:
                    attacker_entity.player_tp += 1
                    log.append(f"  > [驾驶员技能: 乘胜追击] 触发 (毁伤)！{attacker_entity.name} 获得 1 TP。")

                packet_extension['part_changes'].append({
                    'target_id': defender_entity.id,
                    'part_slot': target_part.name,  # 毁伤总是命中原始部件
                    'new_status': 'destroyed'
                })
                log.append(f"  > (毁伤) 部件 [{target_part.name}] 被 [摧毁]！")

                if defender_entity.pilot and defender_entity.pilot.link_points > 0:
                    packet_extension['pilot_changes'].append({
                        'target_id': defender_entity.id,
                        'link_loss': 1
                    })
                    log.append(
                        f"  > 驾驶员 [{defender_entity.pilot.name}] 失去 1 点链接值 (剩余: {defender_entity.pilot.link_points - 1})！")

                    if (defender_entity.pilot.link_points - 1) <= 0 and defender_entity.stance != 'downed':
                        packet_extension['entity_changes'].append({
                            'target_id': defender_entity.id,
                            'stance': 'downed'
                        })
                        log.append(f"  > 驾驶员链接值归零！机甲 [{defender_entity.name}] 进入 [宕机姿态]！")

                if target_part.name.endswith("核心"):
                    packet_extension['entity_changes'].append({
                        'target_id': defender_entity.id,
                        'status': 'destroyed'
                    })
                    log.append(f"  > [毁伤结算] 实体 [{defender_entity.name}] 的核心被摧毁，实体被移除！")

        # 5.2.B 【霰射】 / 5.2.C 【顺劈】
        elif chosen_effect in ['scattershot', 'cleave']:
            log_effect_name = "霰射" if chosen_effect == 'scattershot' else "顺劈"
            log.append(f"  > [效果：{log_effect_name}] 触发！")

            other_parts = [(slot, p) for slot, p in defender_entity.parts.items() if
                           p and p.status != 'destroyed' and p.name != target_part.name]

            if not other_parts:
                log.append(f"  > [{log_effect_name}] 没有其他有效部件可以作为目标。")
            else:
                secondary_target_slot, secondary_target = random.choice(other_parts)
                secondary_status = secondary_target.status
                log.append(
                    f"  > [{log_effect_name}] 溢出伤害 ({overflow_crits}重, {overflow_hits}轻) 结算至随机部件: [{secondary_target.name}] ({secondary_target_slot})！")

                white_dice_2 = (
                                   secondary_target.structure if secondary_status == 'damaged' else secondary_target.armor) + stance_mastery_bonus_white
                log_dice_source_2 = "结构值" if secondary_status == 'damaged' else "装甲值"
                blue_dice_2 = (
                        defender_entity.get_total_evasion() + stance_mastery_bonus_blue) if defender_entity.stance == 'agile' else 0

                dice_roll_details_2 = {
                    'type': f'{chosen_effect}_roll',
                    'defense_dice_input': {'white_count': white_dice_2, 'blue_count': blue_dice_2},
                    'attack_dice_input': {},
                    'attack_dice_result': {}
                }

                if rerolled_defense_raw:
                    defense_raw_rolls_2 = rerolled_defense_raw
                    log.append(f"  > (使用重投后的{log_effect_name}防御骰...)")
                else:
                    defense_raw_rolls_2 = roll_dice(white_count=white_dice_2, blue_count=blue_dice_2)

                # --- 重投中断检查 ---
                if not skip_reroll_phase:
                    player_is_defender = (defender_entity.controller == 'player')
                    defender_can_reroll = (
                            player_is_defender and
                            isinstance(defender_entity, Mech) and
                            defender_entity.pilot and
                            defender_entity.pilot.link_points > 0
                    )
                    if defender_can_reroll:
                        log.append(
                            f"  > [{log_effect_name}结算] 玩家链接值: {defender_entity.pilot.link_points}。等待重投决策...")

                        processed_rolls, _ = process_rolls(defense_raw_rolls_2, stance=defender_entity.stance)
                        dice_roll_details_2['defense_dice_result'] = processed_rolls

                        pending_reroll_data = {
                            'type': 'effect_reroll',
                            'attacker_id': attacker_entity.id,
                            'defender_id': defender_entity.id,
                            'target_part_name': secondary_target.name,
                            'overflow_hits': overflow_hits,
                            'overflow_crits': overflow_crits,
                            'chosen_effect': chosen_effect,
                            'attack_raw_rolls': {},
                            'defense_raw_rolls': defense_raw_rolls_2,
                            'player_is_attacker': False,
                            'player_is_defender': True,
                        }

                        packet_extension['status'] = 'reroll_choice_required'
                        packet_extension['pending_reroll_data'] = pending_reroll_data
                        return log, dice_roll_details_2, packet_extension
                # --- 重投检查结束 ---

                processed_defense_rolls_2, defense_roll_2 = process_rolls(
                    defense_raw_rolls_2,
                    stance=defender_entity.stance
                )
                dice_roll_details_2['defense_dice_result'] = processed_defense_rolls_2

                log_msg_2 = f"  > [{log_effect_name}结算] 防御方 (基于{log_dice_source_2}) 投掷 {white_dice_2}白"
                if blue_dice_2 > 0: log_msg_2 += f" {blue_dice_2}蓝 (机动姿态)"
                log_msg_2 += f", 结果: {defense_roll_2 or '无'}"
                log.append(log_msg_2)

                defenses_2 = defense_roll_2.get('防御', 0)
                dodges_2 = defense_roll_2.get('闪避', 0)
                hits_2 = overflow_hits
                crits_2 = overflow_crits

                cancelled_hits_2 = min(hits_2, defenses_2)
                hits_2 -= cancelled_hits_2
                log.append(f"  > [{log_effect_name}结算] {cancelled_hits_2}个[防御]抵消了{cancelled_hits_2}个[轻击]。")

                cancelled_crits_2 = min(crits_2, dodges_2)
                crits_2 -= cancelled_crits_2
                dodges_2 -= cancelled_crits_2

                cancelled_hits_by_dodge_2 = min(hits_2, dodges_2)
                hits_2 -= cancelled_hits_by_dodge_2
                log.append(
                    f"  > [{log_effect_name}结算] {dodges_2 + cancelled_crits_2}个[闪避]抵消了{cancelled_crits_2}个[重击]和{cancelled_hits_by_dodge_2}个[轻击]。")

                final_damage_2 = hits_2 + crits_2
                if final_damage_2 > 0:
                    log.append(f"  > [{log_effect_name}结算] 击穿了 [{secondary_target.name}]！")

                    # [新增] 驾驶员技能：乘胜追击 (Pursuit) - 顺劈/霰射击穿也算
                    if isinstance(attacker_entity,
                                  Mech) and attacker_entity.pilot and "pursuit" in attacker_entity.pilot.skills:
                        attacker_entity.player_tp += 1
                        log.append(
                            f"  > [驾驶员技能: 乘胜追击] 触发 ({log_effect_name})！{attacker_entity.name} 获得 1 TP。")

                    new_status = 'destroyed'
                    if secondary_target.structure == 0:
                        new_status = 'destroyed'
                    elif secondary_status == 'ok':
                        new_status = 'damaged'
                    elif secondary_status == 'damaged':
                        new_status = 'destroyed'

                    packet_extension['part_changes'].append({
                        'target_id': defender_entity.id,
                        'part_slot': secondary_target_slot,
                        'new_status': new_status
                    })
                    log.append(f"  > ({log_effect_name}) 部件 [{secondary_target.name}] 状态变为 [{new_status}]！")

                    if new_status == 'destroyed':
                        if defender_entity.pilot and defender_entity.pilot.link_points > 0:
                            packet_extension['pilot_changes'].append({
                                'target_id': defender_entity.id,
                                'link_loss': 1
                            })
                            log.append(
                                f"  > 驾驶员 [{defender_entity.pilot.name}] 失去 1 点链接值 (剩余: {defender_entity.pilot.link_points - 1})！")

                            if (defender_entity.pilot.link_points - 1) <= 0 and defender_entity.stance != 'downed':
                                packet_extension['entity_changes'].append({
                                    'target_id': defender_entity.id,
                                    'stance': 'downed'
                                })
                                log.append(f"  > 驾驶员链接值归零！机甲 [{defender_entity.name}] 进入 [宕机姿态]！")

                    if new_status == 'destroyed' and secondary_target.name.endswith("核心"):
                        packet_extension['entity_changes'].append({
                            'target_id': defender_entity.id,
                            'status': 'destroyed'
                        })
                        log.append(
                            f"  > [{log_effect_name}结算] 实体 [{defender_entity.name}] 的核心被摧毁，实体被移除！")
                else:
                    log.append(f"  > [{log_effect_name}结算] 第二个部件抵消了所有溢出伤害。")

        return log, dice_roll_details_2, packet_extension