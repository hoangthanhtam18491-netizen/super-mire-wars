import os
import markdown  # 用于解析 Game Introduction.md
import bleach  # 用于清理 HTML，防止 XSS
import json  # 用于解析 Firebase 配置文件
from flask import Blueprint, render_template, request, session, redirect, url_for

# 导入游戏核心状态
from game_logic.game_logic import GameState

# 从新的 game_logic.database 包导入机库所需的数据
from game_logic.database import (
    PLAYER_CORES, PLAYER_LEGS, PLAYER_LEFT_ARMS, PLAYER_RIGHT_ARMS, PLAYER_BACKPACKS,
    AI_LOADOUTS, PLAYER_PILOTS
)

# 创建主蓝图
main_bp = Blueprint('main', __name__)

# -----------------------------------------------------------------
# 路径和常量
# -----------------------------------------------------------------

# BASE_DIR 是 routes/ 目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# ROOT_DIR 是 routes/ 的父目录 (即项目根目录)
ROOT_DIR = os.path.dirname(BASE_DIR)

MAX_LOG_ENTRIES = 50


# -----------------------------------------------------------------
# 辅助函数 (用于加载配置)
# -----------------------------------------------------------------

def _load_firebase_config():
    """
    辅助函数：安全地从文件或环境变量加载 Firebase 配置。
    优先读取 firebase_config.json (用于本地开发)，
    如果失败则回退到环境变量 (用于生产环境)。

    Returns:
        dict: Firebase 配置字典。
    """
    firebase_config_json_str = None
    try:
        # 优先从本地文件加载
        config_path = os.path.join(ROOT_DIR, 'firebase_config.json')
        with open(config_path, 'r', encoding='utf-8') as f:
            firebase_config_json_str = f.read()
    except (FileNotFoundError, IOError):
        # 回退到环境变量
        firebase_config_json_str = os.environ.get('__firebase_config', '{}')

    try:
        # 尝试解析 JSON 字符串
        firebase_config_dict = json.loads(firebase_config_json_str)
    except json.JSONDecodeError:
        # 回退为空字典
        firebase_config_dict = {}

    return firebase_config_dict


# -----------------------------------------------------------------
# 路由定义
# -----------------------------------------------------------------

@main_bp.route('/')
def index():
    """
    渲染游戏的主索引/开始页面 (/)。
    同时加载并解析 Game Introduction.md 以显示规则。
    """
    update_notes = [
        "版本 v2.3: 基本系统补完",
        "- [新增] 驾驶员与链接值部分。",
        "- [新增] 专注重投。",
        "- [新增] 宕机姿态。",
        "- [新增] 多个新部件。",
        "- [修复] 修复近战锁定下移动距离出错的问题。",
        "- [优化] 程序结构。",
        "- [问题] 抛射物拦截难以进行专注重投拦截。",
    ]
    rules_html = ""

    # 构造规则文件的绝对路径
    rules_file_path = os.path.join(ROOT_DIR, "Game Introduction.md")

    try:
        # 读取 Markdown 文件
        with open(rules_file_path, "r", encoding="utf-8") as f:
            md_content = f.read()
        # 转换为 HTML
        html = markdown.markdown(md_content)
        # 清理 HTML，只允许安全的标签
        allowed_tags = ['h1', 'h2', 'h3', 'p', 'ul', 'ol', 'li', 'strong', 'em', 'br', 'div']
        rules_html = bleach.clean(html, tags=allowed_tags)
    except FileNotFoundError:
        rules_html = f"<p>错误：在 {rules_file_path} 未找到 Game Introduction.md 文件。</p>"
    except Exception as e:
        rules_html = f"<p>加载规则时出错: {e}</p>"

    return render_template('index.html', update_notes=update_notes, rules_html=rules_html)


@main_bp.route('/analytics')
def analytics():
    """
    渲染分析数据统计页面 (/analytics)。
    这个页面会连接到 Firebase Firestore 来实时显示统计数据。
    """

    # 加载 Firebase 配置并传递给模板
    firebase_config_dict = _load_firebase_config()

    # 从环境变量获取 App ID 和 Auth Token (由部署环境注入)
    app_id = os.environ.get('__app_id', 'default-app-id')
    auth_token = os.environ.get('__initial_auth_token', 'undefined')

    return render_template(
        'analytics.html',
        firebase_config=firebase_config_dict,
        app_id=app_id,
        initial_auth_token=auth_token
    )


@main_bp.route('/hangar')
def hangar():
    """
    渲染机库页面 (/hangar)。
    从数据库加载所有玩家可用的部件、驾驶员和AI配置。
    """

    # 过滤掉所有包含“（弃置）”的部件，这些部件不应在机库中被选择
    player_left_arms = {k: v for k, v in PLAYER_LEFT_ARMS.items() if '（弃置）' not in k}
    player_right_arms = {k: v for k, v in PLAYER_RIGHT_ARMS.items() if '（弃置）' not in k}
    player_cores = {k: v for k, v in PLAYER_CORES.items() if '（弃置）' not in k}
    player_legs = {k: v for k, v in PLAYER_LEGS.items() if '（弃置）' not in k}
    player_backpacks = {k: v for k, v in PLAYER_BACKPACKS.items() if '（弃置）' not in k}

    # 加载 Firebase 配置，机库页面也需要它来进行分析
    firebase_config_dict = _load_firebase_config()
    app_id = os.environ.get('__app_id', 'default-app-id')
    auth_token = os.environ.get('__initial_auth_token', 'undefined')

    return render_template(
        'hangar.html',
        cores=player_cores,
        legs=player_legs,
        left_arms=player_left_arms,
        right_arms=player_right_arms,
        backpacks=player_backpacks,
        player_pilots=PLAYER_PILOTS,  # 传递驾驶员列表
        ai_loadouts=AI_LOADOUTS,
        firebase_config=firebase_config_dict,
        app_id=app_id,
        initial_auth_token=auth_token
    )


@main_bp.route('/start_game', methods=['POST'])
def start_game():
    """
    处理来自机库的 POST 请求 (/start_game)。
    根据表单数据创建新的 GameState，将其存入 session，并重定向到游戏主界面。
    """
    # 1. 从表单接收玩家的选择
    selection = {
        'core': request.form.get('core'),
        'legs': request.form.get('legs'),
        'left_arm': request.form.get('left_arm'),
        'right_arm': request.form.get('right_arm'),
        'backpack': request.form.get('backpack')
    }
    game_mode = request.form.get('game_mode', 'duel')
    ai_opponent_key = request.form.get('ai_opponent')
    player_pilot_name = request.form.get('pilot')  # 获取玩家选择的驾驶员

    # 2. 创建一个新的 GameState 实例
    game = GameState(
        player_mech_selection=selection,
        ai_loadout_key=ai_opponent_key,
        game_mode=game_mode,
        player_pilot_name=player_pilot_name  # 传递给 GameState
    )

    # 3. 将游戏状态序列化并存入服务器 session
    session['game_state'] = game.to_dict()

    # 4. 初始化战斗日志
    log = [f"> 玩家机甲组装完毕。"]
    ai_mech = game.get_ai_mech()
    ai_name = ai_mech.name if ai_mech else "未知AI"

    if game_mode == 'horde':
        log.append(f"> [生存模式] 已启动。")
        log.append(f"> 第一波遭遇: {ai_name}。")
    elif game_mode == 'range':
        log.append(f"> [靶场模式] 已启动。")
        log.append(f"> 遭遇敌机: {ai_name}。")
    else:  # 'duel'
        log.append(f"> [决斗模式] 已启动。")
        log.append(f"> 遭遇敌机: {ai_name}。")
    log.append("> 战斗开始！")

    if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
    session['combat_log'] = log

    # 5. 清理上一局游戏可能残留的会话标志
    session['visual_feedback_events'] = []
    session.pop('run_projectile_phase', None)

    # 6. 重定向到游戏界面 (game.game)
    return redirect(url_for('game.game'))