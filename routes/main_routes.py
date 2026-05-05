import os
import markdown
import bleach
from flask import Blueprint, render_template, request, session, redirect, url_for

from game_logic.game_logic import GameState
from game_logic.database import (
    PLAYER_CORES, PLAYER_LEGS, PLAYER_LEFT_ARMS, PLAYER_RIGHT_ARMS, PLAYER_BACKPACKS,
    AI_LOADOUTS, PLAYER_PILOTS
)
from game_logic.config import MAX_LOG_ENTRIES, load_firebase_config, get_firebase_app_id, get_firebase_auth_token, ROOT_DIR

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    """
    渲染游戏的主索引/开始页面 (/)。
    同时加载并解析 Game Introduction.md 以显示规则。
    """
    update_notes = [
        "版本 v2.5: 彩蛋",
        "- [新增] 一个AI，一个部件，数个新效果。",
        "- [优化] 代码结构。",
        "- [修正] 拦截问题。",
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


@main_bp.route('/analytics')
def analytics():
    """
    渲染分析数据统计页面 (/analytics)。
    """
    firebase_config_dict = load_firebase_config()
    app_id = get_firebase_app_id()
    auth_token = get_firebase_auth_token()

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
    player_left_arms = {k: v for k, v in PLAYER_LEFT_ARMS.items() if '（弃置）' not in k}
    player_right_arms = {k: v for k, v in PLAYER_RIGHT_ARMS.items() if '（弃置）' not in k}
    player_cores = {k: v for k, v in PLAYER_CORES.items() if '（弃置）' not in k}
    player_legs = {k: v for k, v in PLAYER_LEGS.items() if '（弃置）' not in k}
    player_backpacks = {k: v for k, v in PLAYER_BACKPACKS.items() if '（弃置）' not in k}

    firebase_config_dict = load_firebase_config()
    app_id = get_firebase_app_id()
    auth_token = get_firebase_auth_token()

    return render_template(
        'hangar.html',
        cores=player_cores,
        legs=player_legs,
        left_arms=player_left_arms,
        right_arms=player_right_arms,
        backpacks=player_backpacks,
        player_pilots=PLAYER_PILOTS,
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
    selection = {
        'core': request.form.get('core'),
        'legs': request.form.get('legs'),
        'left_arm': request.form.get('left_arm'),
        'right_arm': request.form.get('right_arm'),
        'backpack': request.form.get('backpack')
    }
    game_mode = request.form.get('game_mode', 'duel')
    ai_opponent_key = request.form.get('ai_opponent')
    player_pilot_name = request.form.get('pilot')

    if ai_opponent_key == 'raven':
        session['show_raven_intro'] = True

    game = GameState(
        player_mech_selection=selection,
        ai_loadout_key=ai_opponent_key,
        game_mode=game_mode,
        player_pilot_name=player_pilot_name
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

    if len(log) > MAX_LOG_ENTRIES:
        log = log[-MAX_LOG_ENTRIES:]
    session['combat_log'] = log

    session['visual_feedback_events'] = []
    session.pop('run_projectile_phase', None)

    return redirect(url_for('game.game'))
