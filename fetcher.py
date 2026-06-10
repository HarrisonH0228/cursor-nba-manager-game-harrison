import os
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

import cache

load_dotenv()

BASE_URL = "https://api.balldontlie.io"
CURRENT_SEASON = 2025
MAX_PLAYER_PAGES = 2
RATE_LIMIT_DELAY = 12


def _get_api_key():
    api_key = os.getenv("BALLDONTLIE_API_KEY")
    if not api_key:
        raise ValueError(
            "BALLDONTLIE_API_KEY is missing. Add it to your .env file."
        )
    return api_key


def _get(path, params=None):
    response = requests.get(
        f"{BASE_URL}{path}",
        headers={"Authorization": _get_api_key()},
        params=params,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def fetch_players(search=None, per_page=25, team_ids=None, cursor=None):
    """GET /nba/v1/players/active — player lookup and team rosters."""
    params = [("per_page", per_page)]
    if search:
        params.append(("search", search))
    if team_ids:
        for team_id in team_ids:
            params.append(("team_ids[]", team_id))
    if cursor:
        params.append(("cursor", cursor))

    payload = _get("/nba/v1/players/active", params=params)
    return payload.get("data", []), payload.get("meta", {})


def fetch_player(player_id):
    """GET /nba/v1/players/{id} — single player detail."""
    return _get(f"/nba/v1/players/{player_id}")["data"]


def fetch_teams():
    """GET /nba/v1/teams — all NBA teams."""
    pass


def fetch_team(team_id):
    """GET /nba/v1/teams/{id} — single team detail."""
    pass


def fetch_season_averages(season, player_id):
    """GET /nba/v1/season_averages — PPG, RPG, APG, SPG, BPG."""
    payload = _get(
        "/nba/v1/season_averages",
        params={"season": season, "player_id": player_id},
    )
    rows = payload.get("data", [])
    return rows[0] if rows else None


def _fetch_season_averages_bulk(player_ids, season):
    if not player_ids:
        return {}

    params = [
        ("season", season),
        ("season_type", "regular"),
        ("type", "base"),
        ("per_page", 100),
    ]
    for player_id in player_ids:
        params.append(("player_ids[]", player_id))

    payload = _get("/nba/v1/season_averages/general", params=params)
    stats_by_id = {}

    for row in payload.get("data", []):
        player = row.get("player") or {}
        player_id = row.get("player_id") or player.get("id")
        if player_id is None:
            continue

        if "stats" in row:
            stats = row["stats"]
        else:
            stats = row

        stats_by_id[player_id] = {
            "pts": stats.get("pts"),
            "reb": stats.get("reb"),
            "ast": stats.get("ast"),
        }

    return stats_by_id


def _player_record(player, stats):
    team = player.get("team") or {}
    return {
        "id": player["id"],
        "name": f"{player['first_name']} {player['last_name']}",
        "team": team.get("full_name", "Free Agent"),
        "ppg": stats.get("pts"),
        "rpg": stats.get("reb"),
        "apg": stats.get("ast"),
    }


def refresh_cache():
    """Orchestrator called by scheduler to refresh cached data."""
    all_players = []
    cursor = None

    for page in range(MAX_PLAYER_PAGES):
        players, meta = fetch_players(per_page=25, cursor=cursor)
        all_players.extend(players)
        cursor = meta.get("next_cursor")
        if not cursor:
            break
        if page < MAX_PLAYER_PAGES - 1:
            time.sleep(RATE_LIMIT_DELAY)

    player_ids = [player["id"] for player in all_players]
    stats_by_id = {}

    if player_ids:
        time.sleep(RATE_LIMIT_DELAY)
        stats_by_id = _fetch_season_averages_bulk(player_ids, CURRENT_SEASON)

        missing_ids = [pid for pid in player_ids if pid not in stats_by_id]
        for index, player_id in enumerate(missing_ids):
            if index > 0:
                time.sleep(RATE_LIMIT_DELAY)
            averages = fetch_season_averages(CURRENT_SEASON, player_id)
            if averages:
                stats_by_id[player_id] = {
                    "pts": averages.get("pts"),
                    "reb": averages.get("reb"),
                    "ast": averages.get("ast"),
                }

    records = [
        _player_record(player, stats_by_id.get(player["id"], {}))
        for player in all_players
    ]

    cache.save_cache(
        {
            "last_updated": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "season": CURRENT_SEASON,
            "players": records,
        }
    )
