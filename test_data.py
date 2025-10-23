from data_models import Action, Part, Mech


def run_test():
    """
    创建示例数据并进行验证。
    """
    print("--- 步骤 1.2: 定义数据类 (Python Classes) 验证 ---")

    # 1. 定义部件上的动作
    action_ciji = Action(name="刺击", action_type="近战", cost="S", dice="3黄1红", range_val="近战")
    action_dianshe = Action(name="点射", action_type="射击", cost="M", dice="1黄3红", range_val=6)
    action_benpao = Action(name="奔跑", action_type="移动", cost="M", dice="", range_val=4)

    # 2. 根据文档数据，创建各个部件的实例
    # 核心: RT-06, “泥沼”, 主战核心
    core = Part(name="RT-06 “泥沼” 主战核心", armor=6, structure=2, electronics=2, evasion=0)

    # 下肢: RL-06, 标准下肢
    # 注意：根据文档表格格式推断，标准下肢的 结构值为3, 闪避值为3
    legs = Part(name="RL-06 标准下肢", armor=5, structure=3, evasion=3, adjust_move=1, actions=[action_benpao])

    # 左臂: CC-3格斗刀
    left_arm = Part(name="CC-3 格斗刀", armor=4, structure=0, parry=1, actions=[action_ciji])

    # 右臂: AC-32自动步枪
    right_arm = Part(name="AC-32 自动步枪", armor=4, structure=0, actions=[action_dianshe])

    # 背包: AMS-190主动防御系统
    backpack = Part(name="AMS-190 主动防御系统", armor=3, structure=0, electronics=1)

    # 3. 将部件组装成一台完整的机甲
    example_mech = Mech(core=core, legs=legs, left_arm=left_arm, right_arm=right_arm, backpack=backpack)
    print("\n一台机甲已成功组装！")

    # 4. 打印机甲各部件的装甲值和结构值
    print("\n--- 各部件属性 ---")
    parts_dict = {
        "核心": example_mech.core,
        "下肢": example_mech.legs,
        "左臂": example_mech.left_arm,
        "右臂": example_mech.right_arm,
        "背包": example_mech.backpack
    }
    for part_name, part_obj in parts_dict.items():
        print(f"[{part_name}] {part_obj.name}: 装甲={part_obj.armor}, 结构={part_obj.structure}")

    # 5. 打印机甲的总回避值
    total_evasion = example_mech.get_total_evasion()
    print("\n--- 机甲总属性 ---")
    print(f"机甲总回避值: {total_evasion}")
    print("\n--- 验证结束 ---")


if __name__ == '__main__':
    run_test()
