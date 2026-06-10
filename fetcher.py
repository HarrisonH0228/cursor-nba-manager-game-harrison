import os

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.balldontlie.io"


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


def fetch_players(search=None, per_page=25, team_ids=None):
    """GET /nba/v1/players — player lookup and team rosters."""
    pass


def fetch_player(player_id):
    """GET /nba/v1/players/{id} — single player detail."""
    pass


def fetch_teams():
    """GET /nba/v1/teams — all NBA teams."""
    pass


def fetch_team(team_id):
    """GET /nba/v1/teams/{id} — single team detail."""
    pass


def fetch_season_averages(season, player_id):
    """GET /nba/v1/season_averages — PPG, RPG, APG, SPG, BPG."""
    pass


def refresh_cache():
    """Orchestrator called by scheduler to refresh cached data."""
    pass
