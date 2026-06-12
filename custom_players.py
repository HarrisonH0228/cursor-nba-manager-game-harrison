"""Admin-created custom draft prospects."""

import os
import uuid
from datetime import datetime, timezone

from attributes import (
    ADMIN_ATTR_MAX,
    ADMIN_POTENTIAL_MAX,
    ATTRIBUTE_KEYS,
    MAX_ATTR,
    MIN_ATTR,
    POTENTIAL_MAX,
    VALID_POSITIONS,
    init_custom_rookie_career_profile,
    season_averages_from_attributes_deterministic,
)
from errors import CustomPlayersWriteError, read_json, write_json
from season import allocate_player_id

CUSTOM_PLAYERS_PATH = os.path.join(os.path.dirname(__file__), "data", "custom_players.json")

DEFAULT_STORE = {"players": []}
ADMIN_ATTR_MIN = 1
ADMIN_PEAK_AGE_MIN = 22
ADMIN_PEAK_AGE_MAX = 40
ADMIN_RETIRE_AGE_MIN = 30
ADMIN_RETIRE_AGE_MAX = 50
ADMIN_DEV_RATE_MIN = 0.3
ADMIN_DEV_RATE_MAX = 2.5
ADMIN_OC_PEAK_AGE_MIN = 18
ADMIN_OC_PEAK_AGE_MAX = 999
ADMIN_OC_RETIRE_AGE_MIN = 19
ADMIN_OC_RETIRE_AGE_MAX = 999
ADMIN_OC_DEV_RATE_MIN = 0.01
ADMIN_OC_DEV_RATE_MAX = 999


def _clamp_admin(value, low=ADMIN_ATTR_MIN, high=ADMIN_ATTR_MAX):
    return max(low, min(high, round(value)))


def _is_overclocked(attributes, potential=None, explicit=False):
    if explicit:
        return True
    if potential is not None and int(potential) > POTENTIAL_MAX:
        return True
    return any(int(value) > MAX_ATTR for value in attributes.values())


def load_custom_players():
    data = read_json(CUSTOM_PLAYERS_PATH, DEFAULT_STORE, "custom players")
    if not isinstance(data, dict):
        return dict(DEFAULT_STORE)
    if not data:
        return dict(DEFAULT_STORE)
    data.setdefault("players", [])
    return data


def save_custom_players(data):
    if not write_json(CUSTOM_PLAYERS_PATH, data, "custom players"):
        raise CustomPlayersWriteError("Could not save custom players.")


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


def _parse_optional_int(raw, low=None, high=None):
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if low is not None:
        value = max(low, value)
    if high is not None:
        value = min(high, value)
    return value


def _parse_optional_float(raw, low=None, high=None):
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if low is not None:
        value = max(low, value)
    if high is not None:
        value = min(high, value)
    return round(value, 3)


def _parse_peak_attributes(form_peaks, overclocked=False):
    peaks = {}
    low = ADMIN_ATTR_MIN if overclocked else MIN_ATTR
    for key in ATTRIBUTE_KEYS:
        raw = form_peaks.get(key)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        peaks[key] = max(low, round(value))
    return peaks or None


def parse_career_from_form(form, overclocked=False):
    if overclocked:
        peak_low, peak_high = ADMIN_OC_PEAK_AGE_MIN, ADMIN_OC_PEAK_AGE_MAX
        retire_low, retire_high = ADMIN_OC_RETIRE_AGE_MIN, ADMIN_OC_RETIRE_AGE_MAX
        dev_low, dev_high = ADMIN_OC_DEV_RATE_MIN, ADMIN_OC_DEV_RATE_MAX
    else:
        peak_low, peak_high = ADMIN_PEAK_AGE_MIN, ADMIN_PEAK_AGE_MAX
        retire_low, retire_high = ADMIN_RETIRE_AGE_MIN, ADMIN_RETIRE_AGE_MAX
        dev_low, dev_high = ADMIN_DEV_RATE_MIN, ADMIN_DEV_RATE_MAX

    peak_age = _parse_optional_int(form.get("peak_age"), peak_low, peak_high)
    retirement_age = _parse_optional_int(form.get("retirement_age"), retire_low, retire_high)
    development_rate = _parse_optional_float(form.get("development_rate"), dev_low, dev_high)
    peak_attributes = _parse_peak_attributes(
        {key: form.get(f"peak_{key}") for key in ATTRIBUTE_KEYS},
        overclocked=overclocked,
    )

    career = {}
    if peak_age is not None:
        career["peak_age"] = peak_age
    if retirement_age is not None:
        career["retirement_age"] = retirement_age
    if development_rate is not None:
        career["development_rate"] = development_rate
    if peak_attributes:
        career["peak_attributes"] = peak_attributes
    return career or None


def _parse_attributes(form_attrs, overall=None, overclocked=False):
    attrs = {}
    fallback = overall or 50
    high = ADMIN_ATTR_MAX if overclocked else MAX_ATTR
    low = ADMIN_ATTR_MIN if overclocked else MIN_ATTR
    for key in ATTRIBUTE_KEYS:
        raw = form_attrs.get(key, fallback)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = fallback
        attrs[key] = max(low, min(high, round(value)))
    return attrs


def parse_attributes_from_form(form, overclocked=False):
    return _parse_attributes(
        {key: form.get(key) for key in ATTRIBUTE_KEYS},
        overclocked=overclocked,
    )


def preview_custom_player(
    name,
    age,
    positions,
    attributes,
    potential=None,
    overclock=False,
    career=None,
):
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
        "career": career,
        **stats,
    }


def _entry_from_preview(preview, custom_id=None):
    entry = {
        "custom_id": custom_id or str(uuid.uuid4()),
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
    if preview.get("career"):
        entry["career"] = preview["career"]
    return entry


def add_custom_player(
    name,
    age,
    positions,
    attributes,
    potential=None,
    overclock=False,
    career=None,
):
    name = (name or "").strip()
    if not name:
        raise ValueError("Name is required.")

    preview = preview_custom_player(
        name,
        age,
        positions,
        attributes,
        potential,
        overclock=overclock,
        career=career,
    )
    entry = _entry_from_preview(preview)

    data = load_custom_players()
    data.setdefault("players", []).append(entry)
    save_custom_players(data)
    return entry


def update_custom_player(
    custom_id,
    name,
    age,
    positions,
    attributes,
    potential=None,
    overclock=False,
    career=None,
):
    name = (name or "").strip()
    if not name:
        raise ValueError("Name is required.")

    preview = preview_custom_player(
        name,
        age,
        positions,
        attributes,
        potential,
        overclock=overclock,
        career=career,
    )
    entry = _entry_from_preview(preview, custom_id=custom_id)

    data = load_custom_players()
    players = data.get("players", [])
    updated = False
    for index, player in enumerate(players):
        if player.get("custom_id") == custom_id:
            entry["created_at"] = player.get("created_at", entry["created_at"])
            players[index] = entry
            updated = True
            break
    if not updated:
        return None

    data["players"] = players
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
    state = season.get("draft_state")
    if not isinstance(state, dict):
        state = {}
        season["draft_state"] = state
    drafted = state.setdefault("drafted_custom_ids", [])
    if custom_id not in drafted:
        drafted.append(custom_id)


def build_prospect_from_template(season, template, rng=None, career=None):
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
        career=career if career is not None else template.get("career"),
    )
    return prospect
