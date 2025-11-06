import os
import tempfile
from flask import Flask
from flask_session import Session

# 导入新的蓝图
from routes.main_routes import main_bp
from routes.game_routes import game_bp
from routes.api_routes import api_bp

# [v_REFACTOR]
# app.py 现在是项目的入口点
# 它只负责创建应用和注册蓝图
# 所有路由逻辑都已移至 routes/ 目录
# 所有游戏逻辑都已移至 game_logic/ 目录

app = Flask(__name__)
app.secret_key = os.urandom(24)

# --- 服务器端会话配置 ---
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_FILE_DIR"] = tempfile.mkdtemp()
app.config["SESSION_PERMANENT"] = False
Session(app)

# --- 注册蓝图 ---
app.register_blueprint(main_bp)
app.register_blueprint(game_bp)
app.register_blueprint(api_bp)

if __name__ == '__main__':
    # 注意：在生产环境中，应使用 Gunicorn 或 uWSGI
    app.run(debug=True)