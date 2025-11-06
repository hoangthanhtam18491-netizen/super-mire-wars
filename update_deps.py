import subprocess
import sys
import os

# [v_REFACTOR]
# 这是一个辅助脚本，用于在 PyCharm 虚拟环境中安装或更新所有必需的依赖项。
# 它会读取同目录下的 'requirements.txt' 文件。

def update_dependencies():
    """
    安装或更新在 requirements.txt 中列出的所有依赖项。
    """
    # 确定 requirements.txt 文件的路径
    # os.path.abspath(__file__) 获取此脚本的绝对路径
    # os.path.dirname(...) 获取此脚本所在的目录
    # os.path.join(...) 将目录和文件名组合起来
    base_dir = os.path.dirname(os.path.abspath(__file__))
    requirements_file = os.path.join(base_dir, 'requirements.txt')

    if not os.path.exists(requirements_file):
        print(f"错误：在 {requirements_file} 未找到 'requirements.txt'。")
        print("请先创建 'requirements.txt' 文件。")
        return

    print(f"--- 正在从 {requirements_file} 安装/更新依赖项 ---")

    try:
        # sys.executable 是当前运行的 Python 解释器的路径
        # 这可以确保 pip 命令在正确的虚拟环境中运行
        # （例如 PyCharm 的 venv）
        # ['-m', 'pip', 'install', '--upgrade', '-r', requirements_file]
        # 相当于在终端运行：
        # /path/to/your/venv/bin/python -m pip install --upgrade -r requirements.txt
        subprocess.check_call(
            [sys.executable, '-m', 'pip', 'install', '--upgrade', '-r', requirements_file]
        )
        print("\n--- 依赖项更新成功！ ---")

    except subprocess.CalledProcessError as e:
        print(f"\n--- 错误：依赖项更新失败 ---")
        print(f"返回码: {e.returncode}")
        print(f"输出: {e.output}")
    except FileNotFoundError:
        print("\n--- 错误：找不到 'pip' 命令 ---")
        print("请确保你是在一个已激活的 Python 虚拟环境中运行此脚本。")

if __name__ == "__main__":
    update_dependencies()