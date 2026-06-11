import json
import logging
import os
import shutil
import tempfile
import uuid

logger = logging.getLogger(__name__)

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
    "news_feed": [],
    "injury_week_counts": {},
    "team_finances": {},
    "pending_fa_offers": {},
    "free_agents": [],
    "championships": {},
}


def _season_path(season_id):
    return os.path.join(SEASONS_DIR, f"{season_id}.json")


def _backup_path(season_id):
    return _season_path(season_id) + ".bak"


def _corrupt_path(season_id):
    return _season_path(season_id) + ".corrupt"


def create_season_id():
    return str(uuid.uuid4())


def _try_load_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle), None
    except (json.JSONDecodeError, OSError) as exc:
        return None, exc


def _prepare_season_data(data):
    for key, value in DEFAULT_SEASON.items():
        data.setdefault(key, value if not isinstance(value, dict) else dict(value))

    from season import migrate_season

    migrate_season(data)
    return data


def load_season(season_id):
    """Load season data. Returns (data, recovery_status).

    recovery_status is None on success, "restored" when recovered from .bak,
    or "corrupt" when the save could not be loaded.
    """
    path = _season_path(season_id)
    if not os.path.exists(path):
        return None, None

    data, err = _try_load_json(path)
    if data is not None:
        return _prepare_season_data(data), None

    logger.warning("Corrupt season JSON for %s: %s", season_id, err)

    backup = _backup_path(season_id)
    backup_data, backup_err = _try_load_json(backup)
    if backup_data is not None:
        logger.warning("Restoring season %s from backup", season_id)
        try:
            shutil.copy2(backup, path)
        except OSError:
            logger.warning("Could not overwrite corrupt season file for %s", season_id)
        return _prepare_season_data(backup_data), "restored"

    try:
        os.replace(path, _corrupt_path(season_id))
    except OSError:
        logger.warning("Could not move corrupt season file for %s", season_id)

    logger.warning("Season %s unrecoverable; moved to .corrupt", season_id)
    return None, "corrupt"


def save_season(season_id, data):
    os.makedirs(SEASONS_DIR, exist_ok=True)
    path = _season_path(season_id)

    fd, temp_path = tempfile.mkstemp(
        dir=SEASONS_DIR, suffix=".tmp", prefix=f"{season_id}-"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)

        with open(temp_path, encoding="utf-8") as handle:
            json.loads(handle.read())

        if os.path.exists(path):
            try:
                shutil.copy2(path, _backup_path(season_id))
            except OSError:
                logger.warning("Could not write season backup for %s", season_id)

        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


def delete_season(season_id):
    for path in (_season_path(season_id), _backup_path(season_id), _corrupt_path(season_id)):
        if os.path.exists(path):
            os.remove(path)
