"""Admin-created custom draft prospects."""

import json
import os
import uuid
from datetime import datetime, timezone

from attributes import (
    ADMIN_ATTR_MAX,
    ADMIN_POTENTIAL_MAX,
    ATTRIBUTE_KEYS,
    MAX_ATTR,
    POTENTIAL_MAX,
    VALID_POSITIONS,
    init_custom_rookie_career_profile,
    season_averages_from_attributes_deterministic,
)
from season import allocate_player_id

CUSTOM_PLAYERS_PATH = os.path.join(os.path.dirname(__file__), "data", "custom_players.json")

DEFAULT_STORE = {"players": []}
ADMIN_ATTR_MIN = 1


def _clamp_admin(value, low=ADMIN_ATTR_MIN, high=ADMIN_ATTR_MAX):
    return max(low, min(high, round(value)))


def _is_overclocked(attributes, potential=None, explicit=False):
    if explicit:
        return True
    if potential is not None and int(potential) > POTENTIAL_MAX:
        return True
    return any(int(value) > MAX_ATTR for value in attributes.values())


def load_custom_players():
    if not os.path.exists(CUSTOM_PLAYERS_PATH):
        return dict(DEFAULT_STORE)

    with open(CUSTOM_PLAYERS_PATH, encoding="utf-8") as handle:
        data = json.load(handle)

    if not data:
        return dict(DEFAULT_STORE)

    data.setdefault("players", [])
    return data


def save_custom_players(data):
    os.makedirs(os.path.dirname(CUSTOM_PLAYERS_PATH), exist_ok=True)
    temp_path = CUSTOM_PLAYERS_PATH + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
    os.replace(temp_path, CUSTOM_PLAYERS_PATH)


def list_custom_players():
    return list(load_custom_players().get("players", []))


def get_custom_player(custom_id):
    for player in list_custom_players():
        if player.get("custom_id") == custom_id:
            return player
    return None


def delete_custom_player(custom_id):
    data = load_custom_players()
    players = data.get("players", [])
    remaining = [player for player in players if player.get("custom_id") != custom_id]
    if len(remaining) == len(players):
        return False
    data["players"] = remaining
    save_custom_players(data)
    return True


def _parse_positions(raw_positions):
    if not raw_positions:
        return ["SF"]
    if isinstance(raw_positions, str):
        raw_positions = [item.strip() for item in raw_positions.split(",") if item.strip()]
    cleaned = [pos for pos in raw_positions if pos in VALID_POSITIONS]
    return cleaned[:2] or ["SF"]


def _parse_potential(potential, overclocked=False):
    if potential is None:
        return None
    if isinstance(potential, str):
        potential = potential.strip()
        if not potential:
            return None
    try:
        high = ADMIN_POTENTIAL_MAX if overclocked else POTENTIAL_MAX
        return max(40, min(high, int(potential)))
    except (TypeError, ValueError):
        return None


def _parse_attributes(form_attrs, overall=None, overclocked=False):
    attrs = {}
    fallback = overall or 50
    high = ADMIN_ATTR_MAX if overclocked else MAX_ATTR
    low = ADMIN_ATTR_MIN if overclocked else 25
    for key in ATTRIBUTE_KEYS:
        raw = form_attrs.get(key, fallback)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = fallback
        attrs[key] = max(low, min(high, round(value)))
    return attrs


def preview_custom_player(name, age, positions, attributes, potential=None, overclock=False):
    age = max(18, min(30, int(age or 19)))
    positions = _parse_positions(positions)
    attrs = _parse_attributes(attributes, overclocked=overclock)
    overclocked = _is_overclocked(attrs, potential, explicit=overclock)
    preview_player = {"positions": positions, "is_overclocked": overclocked}
    stats = season_averages_from_attributes_deterministic(attrs, preview_player)
    overall = round(sum(attrs.values()) / len(attrs), 1)
    parsed_potential = _parse_potential(potential, overclocked=overclocked)
    return {
        "name": name.strip(),
        "age": age,
        "positions": positions,
        "attributes": attrs,
        "potential": parsed_potential,
        "overall": overall,
        "is_overclocked": overclocked,
        **stats,
    }


def add_custom_player(name, age, positions, attributes, potential=None, overclock=False):
    name = (name or "").strip()
    if not name:
        raise ValueError("Name is required.")

    preview = preview_custom_player(name, age, positions, attributes, potential, overclock=overclock)
    entry = {
        "custom_id": str(uuid.uuid4()),
        "name": preview["name"],
        "age": preview["age"],
        "positions": preview["positions"],
        "attributes": preview["attributes"],
        "potential": preview["potential"],
        "overall": preview["overall"],
        "is_overclocked": preview["is_overclocked"],
        "ppg": preview["ppg"],
        "rpg": preview["rpg"],
        "apg": preview["apg"],
        "spg": preview["spg"],
        "bpg": preview["bpg"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    data = load_custom_players()
    data.setdefault("players", []).append(entry)
    save_custom_players(data)
    return entry


def available_custom_templates(season):
    drafted = set(season.get("draft_state", {}).get("drafted_custom_ids", []))
    return [
        player for player in list_custom_players()
        if player.get("custom_id") not in drafted
    ]


def mark_custom_player_drafted(season, custom_id):
    if not custom_id:
        return
    state = season.setdefault("draft_state", {})
    drafted = state.setdefault("drafted_custom_ids", [])
    if custom_id not in drafted:
        drafted.append(custom_id)


def build_prospect_from_template(season, template, rng=None):
    import random

    rng = rng or random.Random()
    player_id = allocate_player_id(season)
    attributes = dict(template.get("attributes") or {})
    prospect = {
        "id": player_id,
        "name": template["name"],
        "team_id": None,
        "team": None,
        "age": template.get("age", 19),
        "gp": 0,
        "is_rookie": True,
        "is_custom": True,
        "custom_id": template["custom_id"],
        "positions": list(template.get("positions") or ["SF"]),
        "is_overclocked": template.get("is_overclocked", False),
    }
    init_custom_rookie_career_profile(
        prospect,
        attributes,
        rng=rng,
        potential=template.get("potential"),
        overclocked=prospect["is_overclocked"],
    )
    return prospect
