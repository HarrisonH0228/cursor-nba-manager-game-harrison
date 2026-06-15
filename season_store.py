import os
import uuid

from errors import get_logger, read_json, write_json

SEASONS_DIR = os.path.join(os.path.dirname(__file__), "data", "seasons")

DEFAULT_SEASON = {
    "season_year": None,
    "phase": "regular",
    "current_day": 1,
    "max_day": 1,
    "trade_deadline_games": 55,
    "next_player_id": 9000001,
    "players": {},
    "draft_picks": {},
    "draft_state": None,
    "trades": [],
    "rosters": {},
    "standings": {},
    "schedule": [],
    "playoffs": None,
    "recent_results": [],
    "free_agents": [],
}

logger = get_logger(__name__)


def is_valid_season_id(season_id):
    if not season_id or not isinstance(season_id, str):
        return False
    try:
        parsed = uuid.UUID(season_id)
    except (ValueError, AttributeError, TypeError):
        return False
    return str(parsed) == season_id


def _season_path(season_id):
    return os.path.join(SEASONS_DIR, f"{season_id}.json")


def create_season_id():
    return str(uuid.uuid4())


def load_season(season_id):
    if not is_valid_season_id(season_id):
        logger.warning("Rejected invalid season id on load: %r", season_id)
        return None

    path = _season_path(season_id)
    if not os.path.exists(path):
        return None

    data = read_json(path, None, f"season {season_id}")
    if not isinstance(data, dict):
        logger.error("Season file invalid (not an object): %s", path)
        return None

    for key, value in DEFAULT_SEASON.items():
        data.setdefault(key, value if not isinstance(value, dict) else dict(value))

    try:
        from season import migrate_season

        migrate_season(data)
    except Exception:
        logger.exception("Season migration failed: %s", path)
        return None

    return data


def save_season(season_id, data):
    if not is_valid_season_id(season_id):
        logger.warning("Rejected invalid season id on save: %r", season_id)
        return False
    path = _season_path(season_id)
    return write_json(path, data, f"season {season_id}")


def delete_season(season_id):
    if not is_valid_season_id(season_id):
        logger.warning("Rejected invalid season id on delete: %r", season_id)
        return False
    path = _season_path(season_id)
    if not os.path.exists(path):
        return True
    try:
        os.remove(path)
        return True
    except OSError:
        logger.exception("Season delete failed: %s", path)
        return False
