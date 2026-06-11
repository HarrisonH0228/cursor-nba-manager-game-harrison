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

INJURY_CHANCE_PER_GAME = 0.03
SEVERE_INJURY_CHANCE = 0.15


def player_is_injured(player) -> bool:
    injury = player.get("injury")
    if not injury:
        return False
    return int(injury.get("games_remaining") or 0) > 0


def injured_player_ids(roster) -> set[int]:
    return {player["id"] for player in roster if player_is_injured(player)}


def _injury_duration(rng, severe):
    if severe:
        return rng.randint(6, 15)
    return rng.randint(1, 5)


def roll_game_injuries(season, team_id, roster, day, rng=None) -> list[dict]:
    """Roll new injuries for rotation players; return notification dicts."""
    rng = rng or random.Random()
    pool = team_rating_pool(roster)
    if not pool:
        pool = sorted(roster, key=lambda player: player.get("overall") or 0, reverse=True)
    rotation = pool[:ROTATION_SIZE]

    events = []
    injury_log = season.setdefault("injury_log", [])
    pending = season.setdefault("pending_notifications", [])

    for player in rotation:
        if player_is_injured(player):
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
        pending.append(
            f"{event['player_name']} ({injury_type}) — out {games_out} game"
            f"{'s' if games_out != 1 else ''}"
        )

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


def drain_pending_notifications(season) -> list[str]:
    pending = list(season.get("pending_notifications") or [])
    season["pending_notifications"] = []
    return pending
