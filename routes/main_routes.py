import os
import markdown
import bleach
import json  # [FIX #9] 导入 json 模块
from flask import Blueprint, render_template, request, session, redirect, url_for

# [v_REFACTOR]
# “优化 1” - 这是一个新的蓝图文件
# 它包含与核心游戏循环无关的路由 (/, /hangar, /start_game)

# [v_REFACTOR] 导入 game_logic 和 parts_database
# '..' 代表上一级目录
from game_logic.game_logic import GameState
from parts_database import (
    PLAYER_CORES, PLAYER_LEGS, PLAYER_LEFT_ARMS, PLAYER_RIGHT_ARMS, PLAYER_BACKPACKS,
    AI_LOADOUTS, PLAYER_PILOTS # [MODIFIED v2.2] 导入 PLAYER_PILOTS
)

main_bp = Blueprint('main', __name__)

# [v_REFACTOR] 调整基础目录路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# '..' 返回到 routes/ 的父目录 (即项目根目录)
ROOT_DIR = os.path.dirname(BASE_DIR)

MAX_LOG_ENTRIES = 50


@main_bp.route('/')
def index():
    """渲染游戏的主索引/开始页面。"""
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

    rules_file_path = os.path.join(ROOT_DIR, "Game Introduction.md")

    try:
        with open(rules_file_path, "r", encoding="utf-8") as f:
            md_content = f.read()
            html = markdown.markdown(md_content)
            allowed_tags = ['h1', 'h2', 'h3', 'p', 'ul', 'ol', 'li', 'strong', 'em', 'br', 'div']
            rules_html = bleach.clean(html, tags=allowed_tags)
    except FileNotFoundError:
        rules_html = f"<p>错误：在 {rules_file_path} 未找到 Game Introduction.md 文件。</p>"
    except Exception as e:
        rules_html = f"<p>加载规则时出错: {e}</p>"

    return render_template('index.html', update_notes=update_notes, rules_html=rules_html)


# [NEW] 新增的统计数据页面路由
@main_bp.route('/analytics')
def analytics():
    """渲染分析数据统计页面。"""

    firebase_config_json_str = None

    # [FIX #9] 优先从本地文件加载配置，用于本地开发
    try:
        config_path = os.path.join(ROOT_DIR, 'firebase_config.json')
        with open(config_path, 'r', encoding='utf-8') as f:
            firebase_config_json_str = f.read()
    except (FileNotFoundError, IOError):
        # 如果文件不存在，则回退到环境变量（用于生产环境）
        firebase_config_json_str = os.environ.get('__firebase_config', '{}')

    # [NEW] 无论从哪里获取，都尝试将其解析为 Python 字典
    # 以便 tojson 过滤器能正确处理它
    try:
        # 尝试解析 JSON 字符串
        firebase_config_dict = json.loads(firebase_config_json_str)
    except json.JSONDecodeError:
        # 如果解析失败 (例如，它是一个空字符串或无效JSON)
        firebase_config_dict = {}  # 回退为空字典

    app_id = os.environ.get('__app_id', 'default-app-id')
    auth_token = os.environ.get('__initial_auth_token', 'undefined')

    return render_template(
        'analytics.html',
        # [MODIFIED] 传递 Python 字典，而不是 JSON 字符串
        firebase_config=firebase_config_dict,
        app_id=app_id,
        initial_auth_token=auth_token
    )


@main_bp.route('/hangar')
def hangar():
    """渲染机库页面，用于机甲组装和模式选择。"""
    # [MODIFIED] 过滤掉所有包含“（弃置）”的部件
    player_left_arms = {k: v for k, v in PLAYER_LEFT_ARMS.items() if '（弃置）' not in k}
    player_right_arms = {k: v for k, v in PLAYER_RIGHT_ARMS.items() if '（弃置）' not in k}
    player_cores = {k: v for k, v in PLAYER_CORES.items() if '（弃置）' not in k}
    player_legs = {k: v for k, v in PLAYER_LEGS.items() if '（弃置）' not in k}
    player_backpacks = {k: v for k, v in PLAYER_BACKPACKS.items() if '（弃置）' not in k}

    # [MODIFIED] 重用 /analytics 路由中的 Firebase 配置加载逻辑
    firebase_config_json_str = None
    try:
        config_path = os.path.join(ROOT_DIR, 'firebase_config.json')
        with open(config_path, 'r', encoding='utf-8') as f:
            firebase_config_json_str = f.read()
    except (FileNotFoundError, IOError):
        firebase_config_json_str = os.environ.get('__firebase_config', '{}')

    try:
        firebase_config_dict = json.loads(firebase_config_json_str)
    except json.JSONDecodeError:
        firebase_config_dict = {}

    app_id = os.environ.get('__app_id', 'default-app-id')
    auth_token = os.environ.get('__initial_auth_token', 'undefined')

    return render_template(
        'hangar.html',
        cores=player_cores,
        legs=player_legs,
        left_arms=player_left_arms,
        right_arms=player_right_arms,
        backpacks=player_backpacks,
        player_pilots=PLAYER_PILOTS, # [MODIFIED v2.2] 传递驾驶员列表
        ai_loadouts=AI_LOADOUTS,
        # [MODIFIED] 传递 Python 字典
        firebase_config=firebase_config_dict,
        app_id=app_id,
        initial_auth_token=auth_token
    )


@main_bp.route('/start_game', methods=['POST'])
def start_game():
    """
    [v1.17]
    处理来自机库的表单，初始化游戏状态并重定向到游戏界面。
    [v2.2 修改] 新增接收 pilot
    """
    selection = {
        'core': request.form.get('core'),
        'legs': request.form.get('legs'),
        'left_arm': request.form.get('left_arm'),
        'right_arm': request.form.get('right_arm'),
        'backpack': request.form.get('backpack')
    }
    game_mode = request.form.get('game_mode', 'duel')
    ai_opponent_key = request.form.get('ai_opponent')
    player_pilot_name = request.form.get('pilot') # [MODIFIED v2.2] 获取玩家选择的驾驶员

    game = GameState(
        player_mech_selection=selection,
        ai_loadout_key=ai_opponent_key,
        game_mode=game_mode,
        player_pilot_name=player_pilot_name # [MODIFIED v2.2] 传递给GameState
    )

    session['game_state'] = game.to_dict()
    log = [f"> 玩家机甲组装完毕。"]

    ai_mech = game.get_ai_mech()
    ai_name = ai_mech.name if ai_mech else "未知AI"

    if game_mode == 'horde':
        log.append(f"> [生存模式] 已启动。")
        log.append(f"> 第一波遭遇: {ai_name}。")
    elif game_mode == 'range':
        log.append(f"> [靶场模式] 已启动。")
        log.append(f"> 遭遇敌机: {ai_name}。")
    else:
        log.append(f"> [决斗模式] 已启动。")
        log.append(f"> 遭遇敌机: {ai_name}。")
    log.append("> 战斗开始！")

    if len(log) > MAX_LOG_ENTRIES: log = log[-MAX_LOG_ENTRIES:]
    session['combat_log'] = log
    session['visual_feedback_events'] = []
    # [v1.28] 清除回合过渡标志
    session.pop('run_projectile_phase', None)
    # [v_REFACTOR] 重定向到 'game.game' (game 蓝图的 game 函数)
    return redirect(url_for('game.game'))