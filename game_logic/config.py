"""
Shared configuration constants and helpers.
"""

import json
import os

# --- Constants ---

MAX_LOG_ENTRIES = 50

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
