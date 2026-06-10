import time
from datetime import datetime, timezone

from dotenv import load_dotenv
from nba_api.stats.endpoints import commonplayerinfo, leaguedashplayerstats
from nba_api.stats.static import teams as nba_teams

import cache

load_dotenv()

CURRENT_SEASON = 2026
REQUEST_DELAY = 0.6


def season_string(end_year: int) -> str:
    return f"{end_year - 1}-{str(end_year)[2:]}"


def _team_name_by_id():
    return {team["id"]: team["full_name"] for team in nba_teams.get_teams()}


def _fetch_league_player_stats(season_end_year):
    time.sleep(REQUEST_DELAY)
    response = leaguedashplayerstats.LeagueDashPlayerStats(
        season=season_string(season_end_year),
        season_type_all_star="Regular Season",
        per_mode_detailed="PerGame",
        measure_type_detailed_defense="Base",
    )
    return response.get_normalized_dict().get("LeagueDashPlayerStats", [])


def _player_record(row, team_lookup):
    team_id = row.get("TEAM_ID")
    team_name = team_lookup.get(team_id, row.get("TEAM_ABBREVIATION", "Free Agent"))

    return {
        "id": row["PLAYER_ID"],
        "name": row["PLAYER_NAME"],
        "team": team_name,
        "team_id": team_id,
        "ppg": row.get("PTS"),
        "rpg": row.get("REB"),
        "apg": row.get("AST"),
        "spg": row.get("STL"),
        "bpg": row.get("BLK"),
        "age": row.get("AGE"),
    }


def fetch_teams():
    """All NBA teams from embedded static data (no HTTP)."""
    return nba_teams.get_teams()


def fetch_team(team_id):
    """Single team by ID from embedded static data."""
    return nba_teams.find_team_name_by_id(team_id)


def fetch_player(player_id):
    """Single player detail from stats.nba.com."""
    time.sleep(REQUEST_DELAY)
    response = commonplayerinfo.CommonPlayerInfo(player_id=player_id)
    rows = response.get_normalized_dict().get("CommonPlayerInfo", [])
    return rows[0] if rows else None


def refresh_cache():
    """Orchestrator called by scheduler to refresh cached data.

    Returns True on success, False if refresh failed but stale cache was kept.
    """
    try:
        rows = _fetch_league_player_stats(CURRENT_SEASON)
        if not rows:
            raise ValueError("nba_api returned no player stats")

        team_lookup = _team_name_by_id()
        records = [
            _player_record(row, team_lookup)
            for row in rows
            if (row.get("GP") or 0) > 0
        ]

        if not records:
            raise ValueError("No players with games played in API response")

        cache.save_cache(
            {
                "last_updated": datetime.now(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                "season": CURRENT_SEASON,
                "source": "nba_api",
                "players": records,
            }
        )
        return True
    except Exception:
        existing = cache.load_cache()
        if existing.get("players"):
            return False
        raise


if __name__ == "__main__":
    success = refresh_cache()
    if success:
        count = len(cache.get_players())
        print(f"Cache refreshed: {count} players")
    else:
        print("Refresh failed; kept existing cache")
