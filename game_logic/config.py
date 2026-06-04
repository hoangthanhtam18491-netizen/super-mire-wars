"""
Shared configuration constants and helpers.
"""

import json
import os

# --- Constants ---

MAX_LOG_ENTRIES = 50


def make_log_entry(message, level='info', category='action', collapsible=False):
    """创建结构化战斗日志条目。
    level: 'info' | 'warn' | 'error'
    category: 'phase' | 'combat' | 'action' | 'system' | 'drone' | 'intercept'
    collapsible: True 用于骰子详情等可折叠行
    """
    return {'l': level, 'c': category, 'm': message, 'd': collapsible}


def log_action(msg):
    return make_log_entry(msg)

def log_phase(msg):
    return make_log_entry(msg, category='phase')

def log_combat(msg):
    return make_log_entry(msg, category='combat')

def log_system(msg, level='info'):
    return make_log_entry(msg, level=level, category='system')

def log_err(msg):
    return make_log_entry(msg, level='error', category='system')

def log_warn(msg):
    return make_log_entry(msg, level='warn', category='system')

def log_drone(msg):
    return make_log_entry(msg, category='drone')

def log_intercept(msg):
    return make_log_entry(msg, category='intercept')

def log_detail(msg):
    """骰子详情等可折叠行。"""
    return make_log_entry(msg, category='combat', collapsible=True)

# --- Board ---

BOARD_WIDTH = 10
BOARD_HEIGHT = 10

# --- Game defaults ---

DEFAULT_PLAYER_AP = 2
DEFAULT_PLAYER_TP = 1
DEFAULT_LINK_POINTS = 5
DEFAULT_PILOT_SPEED = 5
DEFAULT_PROJECTILE_LIFESPAN = 3

# --- Stance bonuses ---

AGILE_ADJUST_MOVE_MULTIPLIER = 2

# --- Drone ---

MAX_DRONES_PER_TILE = 4
MAX_DRONES_DEPLOYED = 4

# --- Turn phases ---

PHASE_ORDER = ['指令', '快速', '近战', '抛射', '射击', '移动', '战术', '自动', '延迟']

# --- Paths ---

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(_BASE_DIR)


# --- Firebase helpers ---

def load_firebase_config():
    """Load Firebase config from file or environment variable."""
    firebase_config_json_str = None
    try:
        config_path = os.path.join(ROOT_DIR, 'firebase_config.json')
        with open(config_path, 'r', encoding='utf-8') as f:
            firebase_config_json_str = f.read()
    except (FileNotFoundError, IOError):
        firebase_config_json_str = os.environ.get('__firebase_config', '{}')

    try:
        return json.loads(firebase_config_json_str)
    except json.JSONDecodeError:
        return {}


def get_firebase_app_id():
    """Get Firebase app ID from environment."""
    return os.environ.get('__app_id', 'default-app-id')


def get_firebase_auth_token():
    """Get Firebase auth token from environment."""
    return os.environ.get('__initial_auth_token', 'undefined')
