import json
import os
import uuid

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


def create_season_id():
    return str(uuid.uuid4())


def load_season(season_id):
    path = _season_path(season_id)
    if not os.path.exists(path):
        return None

    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)

    for key, value in DEFAULT_SEASON.items():
        data.setdefault(key, value if not isinstance(value, dict) else dict(value))

    from season import migrate_season

    migrate_season(data)
    return data


def save_season(season_id, data):
    os.makedirs(SEASONS_DIR, exist_ok=True)
    path = _season_path(season_id)
    temp_path = path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
    os.replace(temp_path, path)


def delete_season(season_id):
    path = _season_path(season_id)
    if os.path.exists(path):
        os.remove(path)
