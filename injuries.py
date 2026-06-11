"""In-season injury rolls and player availability."""

import random

from attributes import ROTATION_SIZE, team_rating_pool

INJURY_TYPES = (
    "ankle",
    "knee",
    "hamstring",
    "back",
    "shoulder",
    "groin",
    "foot",
    "illness",
    "concussion",
    "wrist",
)

INJURY_CHANCE_PER_GAME = 0.0015
SEVERE_INJURY_CHANCE = 0.15
MAX_INJURIES_PER_WEEK = 2
MIN_GAME_PLAYERS = 5


def _league_week(day):
    return (int(day) - 1) // 7


def _can_add_league_injury(season, day) -> bool:
    counts = season.setdefault("injury_week_counts", {})
    return counts.get(str(_league_week(day)), 0) < MAX_INJURIES_PER_WEEK


def _record_league_injury(season, day) -> None:
    counts = season.setdefault("injury_week_counts", {})
    week_key = str(_league_week(day))
    counts[week_key] = counts.get(week_key, 0) + 1


def player_is_injured(player) -> bool:
    injury = player.get("injury")
    if not injury:
        return False
    return int(injury.get("games_remaining") or 0) > 0


def injured_player_ids(roster) -> set[int]:
    return {player["id"] for player in roster if player_is_injured(player)}


def game_exclude_ids(roster, min_players=MIN_GAME_PLAYERS) -> set[int]:
    """Injured ids to exclude; activate injured with lowest games_remaining if too few healthy."""
    injured = {
        player["id"]: int((player.get("injury") or {}).get("games_remaining") or 0)
        for player in roster
        if player_is_injured(player)
    }
    if not injured:
        return set()

    excluded = set(injured.keys())
    available = len(roster) - len(excluded)
    target = min(min_players, len(roster))

    while available < target and excluded:
        activate_id = min(excluded, key=lambda player_id: injured[player_id])
        excluded.discard(activate_id)
        available += 1

    return excluded


def build_dnp_list(roster, exclude_ids):
    return [
        {
            "player_id": player["id"],
            "name": player.get("name", str(player["id"])),
            "reason": (player.get("injury") or {}).get("type", "injury"),
        }
        for player in roster
        if player["id"] in exclude_ids
    ]


def _injury_duration(rng, severe):
    if severe:
        return rng.randint(6, 15)
    return rng.randint(1, 5)


def roll_game_injuries(season, team_id, roster, day, rng=None, user_team_id=None) -> list[dict]:
    """Roll new injuries for rotation players; return notification dicts."""
    rng = rng or random.Random()
    pool = team_rating_pool(roster)
    if not pool:
        pool = sorted(roster, key=lambda player: player.get("overall") or 0, reverse=True)
    rotation = pool[:ROTATION_SIZE]

    events = []
    injury_log = season.setdefault("injury_log", [])
    pending = season.setdefault("pending_notifications", [])
    notify_user = user_team_id is not None and int(team_id) == int(user_team_id)

    for player in rotation:
        if player_is_injured(player):
            continue
        if not _can_add_league_injury(season, day):
            continue
        if rng.random() >= INJURY_CHANCE_PER_GAME:
            continue

        severe = rng.random() < SEVERE_INJURY_CHANCE
        injury_type = rng.choice(INJURY_TYPES)
        games_out = _injury_duration(rng, severe)
        player["injury"] = {
            "type": injury_type,
            "games_remaining": games_out,
            "day_reported": day,
            "severe": severe,
        }
        _record_league_injury(season, day)

        event = {
            "player_id": player["id"],
            "player_name": player.get("name", str(player["id"])),
            "team_id": team_id,
            "type": injury_type,
            "games_out": games_out,
            "day": day,
        }
        events.append(event)
        injury_log.append(event)
        injury_log[:] = injury_log[-50:]
        if notify_user:
            pending.append(
                f"{event['player_name']} ({injury_type}) — out {games_out} game"
                f"{'s' if games_out != 1 else ''}"
            )
        try:
            from news import append_news
            from season import team_name

            append_news(
                season,
                "injury",
                player=event["player_name"],
                team=team_name(season, team_id),
                detail=injury_type,
            )
        except ImportError:
            pass

    return events


def tick_injuries_after_game(roster) -> None:
    """Decrement injury counters for players who were on the roster."""
    for player in roster:
        injury = player.get("injury")
        if not injury:
            continue
        remaining = int(injury.get("games_remaining") or 0)
        if remaining <= 1:
            player.pop("injury", None)
        else:
            injury["games_remaining"] = remaining - 1


def user_team_injury_report(season, user_team_id, lookup):
    """Currently injured players on the user's roster."""
    if not user_team_id:
        return []
    from season import roster_players

    roster = roster_players(season, int(user_team_id), lookup)
    report = []
    for player in roster:
        injury = player.get("injury")
        if not injury:
            continue
        remaining = int(injury.get("games_remaining") or 0)
        if remaining <= 0:
            continue
        report.append(
            {
                "player_id": player["id"],
                "player_name": player.get("name", str(player["id"])),
                "team_id": int(user_team_id),
                "type": injury.get("type", "injury"),
                "games_remaining": remaining,
            }
        )
    report.sort(key=lambda item: item["games_remaining"], reverse=True)
    return report


def drain_pending_notifications(season, user_team_id=None) -> list[str]:
    pending = list(season.get("pending_notifications") or [])
    season["pending_notifications"] = []
    if user_team_id is None:
        return pending
    return pending
