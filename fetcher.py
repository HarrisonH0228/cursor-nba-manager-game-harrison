import time
import threading
from datetime import datetime, timezone

from dotenv import load_dotenv
from nba_api.stats.endpoints import commonplayerinfo, leaguedashplayerbiostats, leaguedashplayerstats
from nba_api.stats.static import teams as nba_teams

import cache
from attributes import apply_attributes, ensure_positions, init_career_profiles, parse_nba_position
from errors import get_logger
from ratings import apply_ratings

load_dotenv()

logger = get_logger(__name__)

CURRENT_SEASON = 2026
REQUEST_DELAY = 0.6
_refresh_lock = threading.Lock()


def season_string(end_year: int) -> str:
    return f"{end_year - 1}-{str(end_year)[2:]}"


def _team_name_by_id():
    return {team["id"]: team["full_name"] for team in nba_teams.get_teams()}


def _fetch_league_player_stats(season_end_year):
    time.sleep(REQUEST_DELAY)
    try:
        response = leaguedashplayerstats.LeagueDashPlayerStats(
            season=season_string(season_end_year),
            season_type_all_star="Regular Season",
            per_mode_detailed="PerGame",
            measure_type_detailed="Base",
        )
        rows = response.get_normalized_dict().get("LeagueDashPlayerStats", [])
    except Exception:
        logger.exception("LeagueDashPlayerStats request failed")
        raise

    if not isinstance(rows, list):
        raise ValueError("nba_api returned unexpected player stats format")
    return rows


def _fetch_player_positions(season_end_year):
    time.sleep(REQUEST_DELAY)
    try:
        response = leaguedashplayerbiostats.LeagueDashPlayerBioStats(
            season=season_string(season_end_year),
            season_type_all_star="Regular Season",
        )
        rows = response.get_normalized_dict().get("LeagueDashPlayerBioStats", [])
    except Exception:
        logger.exception("LeagueDashPlayerBioStats request failed")
        return {}

    if not isinstance(rows, list):
        logger.warning("nba_api returned unexpected bio stats format")
        return {}

    positions = {}
    for row in rows:
        player_id = row.get("PLAYER_ID")
        if not player_id:
            continue
        parsed = parse_nba_position(row.get("PLAYER_POSITION"))
        if parsed:
            positions[player_id] = parsed
    return positions


def _player_record(row, team_lookup, position_lookup=None):
    player_id = row.get("PLAYER_ID")
    player_name = row.get("PLAYER_NAME")
    if not player_id or not player_name:
        return None

    team_id = row.get("TEAM_ID")
    team_name = team_lookup.get(team_id, row.get("TEAM_ABBREVIATION", "Free Agent"))
    positions = (position_lookup or {}).get(player_id)

    record = {
        "id": player_id,
        "name": player_name,
        "team": team_name,
        "team_id": team_id,
        "ppg": row.get("PTS"),
        "rpg": row.get("REB"),
        "apg": row.get("AST"),
        "spg": row.get("STL"),
        "bpg": row.get("BLK"),
        "gp": row.get("GP"),
        "age": row.get("AGE"),
    }
    if positions:
        record["positions"] = positions
    return record


def fetch_teams():
    """All NBA teams from embedded static data (no HTTP)."""
    return nba_teams.get_teams()


def fetch_team(team_id):
    """Single team by ID from embedded static data."""
    return nba_teams.find_team_name_by_id(team_id)


def fetch_player(player_id):
    """Single player detail from stats.nba.com."""
    time.sleep(REQUEST_DELAY)
    try:
        response = commonplayerinfo.CommonPlayerInfo(player_id=player_id)
        rows = response.get_normalized_dict().get("CommonPlayerInfo", [])
    except Exception:
        logger.exception("CommonPlayerInfo request failed for player %s", player_id)
        return None
    return rows[0] if rows else None


def refresh_cache():
    """Refresh cached player data from stats.nba.com.

    Returns:
        {"ok": bool, "used_cache": bool, "last_updated": str|None, "error": str|None}
    """
    cache.ensure_cache_file()

    with _refresh_lock:
        try:
            rows = _fetch_league_player_stats(CURRENT_SEASON)
            if not rows:
                raise ValueError("nba_api returned no player stats")

            team_lookup = _team_name_by_id()
            position_lookup = _fetch_player_positions(CURRENT_SEASON)
            skipped_rows = 0
            records = []
            for row in rows:
                if (row.get("GP") or 0) <= 0:
                    continue
                record = _player_record(row, team_lookup, position_lookup)
                if record is None:
                    skipped_rows += 1
                    continue
                records.append(record)

            if skipped_rows:
                logger.warning("Skipped %s malformed player stat rows", skipped_rows)

            if not records:
                raise ValueError("No players with games played in API response")

            for player in records:
                ensure_positions(player)

            records = apply_ratings(records)
            if not records:
                raise ValueError("Ratings step produced no players")

            records = apply_attributes(records)
            if not records:
                raise ValueError("Attributes step produced no players")

            init_career_profiles(records)

            last_updated = (
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            )
            cache.save_cache(
                {
                    "last_updated": last_updated,
                    "season": CURRENT_SEASON,
                    "source": "nba_api",
                    "players": records,
                }
            )
            logger.info("Cache refreshed: %s players", len(records))
            return {
                "ok": True,
                "used_cache": False,
                "last_updated": last_updated,
                "error": None,
            }
        except Exception as exc:
            logger.exception("refresh_cache failed")
            existing = cache.load_cache()
            if existing.get("players"):
                return {
                    "ok": False,
                    "used_cache": True,
                    "last_updated": existing.get("last_updated"),
                    "error": str(exc),
                }
            return {
                "ok": False,
                "used_cache": False,
                "last_updated": None,
                "error": str(exc),
            }


if __name__ == "__main__":
    result = refresh_cache()
    if result["ok"]:
        count = len(cache.get_players())
        print(f"Cache refreshed: {count} players")
    elif result["used_cache"]:
        print(
            "Refresh failed; kept existing cache from "
            f"{result.get('last_updated') or 'unknown time'}"
        )
    else:
        print(f"Refresh failed: {result.get('error') or 'unknown error'}")
