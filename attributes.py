"""Player attributes for per-game stat prediction."""

import random

from ratings import (
    MIN_GAMES_FOR_RATINGS,
    compute_intrinsic_overall,
    compute_stat_percentiles,
    compute_team_overall,
    team_rating_pool,
)

ATTRIBUTE_KEYS = ("scoring", "playmaking", "rebounding", "defense", "efficiency", "stamina")
MIN_ATTR = 25
MAX_ATTR = 99
TEAM_MINUTES = 240
ROTATION_SIZE = 8
GAME_NOISE_STDEV = 0.25
CAREER_START_AGE = 19
CAREER_START_MULTIPLIER = 0.78
PEAK_AGE_MIN = 28
PEAK_AGE_MAX = 30
RETIRE_AGE_MIN = 38
RETIRE_AGE_MAX = 43
DECLINE_RATE = 0.012
STAMINA_DECLINE_RATE = 0.018
MIN_AGE_MULTIPLIER = 0.55
DEFAULT_PEAK_AGE = 29
POTENTIAL_MIN = 40
POTENTIAL_MAX = 99
VALID_POSITIONS = ("PG", "SG", "SF", "PF", "C")

POSITION_STAT_WEIGHTS = {
    "PG": {"ppg": 0.85, "rpg": 0.55, "apg": 1.35, "spg": 1.05, "bpg": 0.45},
    "SG": {"ppg": 1.10, "rpg": 0.65, "apg": 0.90, "spg": 1.00, "bpg": 0.55},
    "SF": {"ppg": 1.00, "rpg": 0.85, "apg": 0.85, "spg": 1.00, "bpg": 0.75},
    "PF": {"ppg": 0.90, "rpg": 1.15, "apg": 0.70, "spg": 0.95, "bpg": 1.05},
    "C": {"ppg": 0.85, "rpg": 1.25, "apg": 0.55, "spg": 0.90, "bpg": 1.20},
}

POSITION_ATTR_BIAS = {
    "PG": {"scoring": 0.95, "playmaking": 1.15, "rebounding": 0.75, "defense": 0.95, "efficiency": 1.0},
    "SG": {"scoring": 1.10, "playmaking": 0.95, "rebounding": 0.70, "defense": 1.0, "efficiency": 1.0},
    "SF": {"scoring": 1.0, "playmaking": 0.90, "rebounding": 0.90, "defense": 1.0, "efficiency": 1.0},
    "PF": {"scoring": 0.90, "playmaking": 0.80, "rebounding": 1.15, "defense": 1.0, "efficiency": 0.95},
    "C": {"scoring": 0.85, "playmaking": 0.70, "rebounding": 1.20, "defense": 1.05, "efficiency": 0.90},
}

STAT_FROM_ATTR = {
    "ppg": ("scoring", 0.29),
    "rpg": ("rebounding", 0.16),
    "apg": ("playmaking", 0.20),
    "spg": ("defense", 0.025),
    "bpg": ("defense", 0.015),
}

STAT_DISPLAY_CAPS = {
    "ppg": 32.0,
    "rpg": 16.0,
    "apg": 13.0,
    "spg": 3.5,
    "bpg": 4.0,
}

ATTR_BIAS_MIN = 0.90
ATTR_BIAS_MAX = 1.10


def _clamp(value, low=MIN_ATTR, high=MAX_ATTR):
    return max(low, min(high, round(value)))


def parse_nba_position(position_str):
    if not position_str:
        return None
    normalized = str(position_str).strip().upper().replace(" ", "")
    mapping = {
        "GUARD": ["PG", "SG"],
        "FORWARD": ["SF", "PF"],
        "CENTER": ["C"],
        "GUARD-FORWARD": ["SG", "SF"],
        "G-F": ["SG", "SF"],
        "FORWARD-CENTER": ["PF", "C"],
        "F-C": ["PF", "C"],
        "FORWARD-GUARD": ["SG", "SF"],
        "F-G": ["SG", "SF"],
        "CENTER-FORWARD": ["PF", "C"],
        "C-F": ["PF", "C"],
    }
    if normalized in mapping:
        return mapping[normalized]
    if normalized in VALID_POSITIONS:
        return [normalized]
    return None


def infer_positions_from_stats(player):
    apg = player.get("apg") or 0
    rpg = player.get("rpg") or 0
    bpg = player.get("bpg") or 0
    ppg = player.get("ppg") or 0

    if apg >= 6 and rpg < 6:
        return ["PG"]
    if apg >= 4 and ppg >= 14 and rpg < 5:
        return ["SG"]
    if rpg >= 9 and bpg >= 1.2:
        return ["C"]
    if rpg >= 7 and ppg < 18:
        return ["PF"]
    if 5 <= rpg < 7 and apg >= 3:
        return ["SF", "PF"]
    if ppg >= 18 and apg < 3:
        return ["SG", "SF"]
    if apg >= 5:
        return ["PG", "SG"]
    if rpg >= 6:
        return ["PF", "C"]
    return ["SF"]


def ensure_positions(player):
    positions = player.get("positions")
    if positions:
        cleaned = [pos for pos in positions if pos in VALID_POSITIONS]
        if cleaned:
            player["positions"] = cleaned[:2]
            return player["positions"]
    parsed = parse_nba_position(player.get("position"))
    if parsed:
        player["positions"] = parsed[:2]
        return player["positions"]
    inferred = infer_positions_from_stats(player)
    player["positions"] = inferred
    return inferred


def positions_label(positions):
    if not positions:
        return "—"
    return "/".join(positions)


def position_stat_multipliers(positions):
    if not positions:
        return {stat: 1.0 for stat in STAT_FROM_ATTR}
    totals = {stat: 0.0 for stat in STAT_FROM_ATTR}
    for position in positions:
        weights = POSITION_STAT_WEIGHTS.get(position, {})
        for stat in STAT_FROM_ATTR:
            totals[stat] += weights.get(stat, 1.0)
    count = len(positions)
    return {stat: totals[stat] / count for stat in STAT_FROM_ATTR}


def _position_attr_bias(positions):
    if not positions:
        return {key: 1.0 for key in ATTRIBUTE_KEYS}
    totals = {key: 0.0 for key in ATTRIBUTE_KEYS}
    for position in positions:
        bias = POSITION_ATTR_BIAS.get(position, {})
        for key in ATTRIBUTE_KEYS:
            totals[key] += bias.get(key, 1.0)
    count = len(positions)
    return {key: totals[key] / count for key in ATTRIBUTE_KEYS}


def _apply_position_attr_bias(attributes, positions):
    bias = _position_attr_bias(positions)
    adjusted = {}
    for key in ATTRIBUTE_KEYS:
        factor = max(ATTR_BIAS_MIN, min(ATTR_BIAS_MAX, bias.get(key, 1.0)))
        adjusted[key] = _clamp(attributes.get(key, MIN_ATTR) * factor)
    return adjusted


def _player_rng(player, rng=None):
    if rng is None:
        return random.Random(int(player.get("id", 0)))
    seed = rng.randint(0, 2**31) ^ int(player.get("id", 0))
    return random.Random(seed)


def scouting_upside_tier(prospect):
    potential = prospect.get("potential")
    overall = prospect.get("overall") or 50
    if potential is None:
        return "Unknown"
    gap = potential - overall
    if gap >= 15:
        return "High upside"
    if gap >= 8:
        return "Solid upside"
    return "Limited upside"


def _blend(primary, secondary=None, primary_weight=0.85):
    if primary is None:
        return _clamp(secondary if secondary is not None else 50)
    if secondary is None:
        return _clamp(primary)
    return _clamp(primary * primary_weight + secondary * (1 - primary_weight))


def _stamina_from_player(player):
    gp = player.get("gp") or 0
    age = player.get("age") or 25
    gp_factor = min(gp / 82, 1.0) * 40
    age_factor = max(0, 30 - abs(age - 27)) * 1.5
    overall = player.get("overall") or 50
    return _clamp(gp_factor + age_factor + overall * 0.25)


def _efficiency_from_player(player, percentiles):
    ppg_pct = percentiles.get("ppg") or 50
    overall = player.get("overall") or 50
    volume = player.get("ppg") or 0
    volume_bonus = min(volume / 30, 1.0) * 10
    return _clamp(ppg_pct * 0.6 + overall * 0.25 + volume_bonus)


def derive_attributes(player, percentiles=None, overall=None):
    if percentiles is None:
        percentiles = {}
    overall = overall if overall is not None else player.get("overall") or 50
    gp = player.get("gp") or 0
    positions = ensure_positions(player)

    if gp < MIN_GAMES_FOR_RATINGS:
        base = overall * 0.85
        attrs = {
            "scoring": _clamp(base + (player.get("ppg") or 0)),
            "playmaking": _clamp(base * 0.7 + (player.get("apg") or 0) * 3),
            "rebounding": _clamp(base * 0.7 + (player.get("rpg") or 0) * 2),
            "defense": _clamp(base * 0.75 + (player.get("spg") or 0) * 8 + (player.get("bpg") or 0) * 10),
            "efficiency": _clamp(overall * 0.9),
            "stamina": _stamina_from_player(player),
        }
        return _apply_position_attr_bias(attrs, positions)

    spg_pct = percentiles.get("spg") or 50
    bpg_pct = percentiles.get("bpg") or 50
    defense_pct = spg_pct * 0.55 + bpg_pct * 0.45

    attrs = {
        "scoring": _blend(percentiles.get("ppg"), overall),
        "playmaking": _blend(percentiles.get("apg"), overall),
        "rebounding": _blend(percentiles.get("rpg"), overall),
        "defense": _blend(defense_pct, overall),
        "efficiency": _efficiency_from_player(player, percentiles),
        "stamina": _stamina_from_player(player),
    }
    return _apply_position_attr_bias(attrs, positions)


def apply_attributes(players):
    percentiles_by_id = compute_stat_percentiles(players)
    for player in players:
        ensure_positions(player)
        percentiles = percentiles_by_id.get(player["id"], {})
        player["attributes"] = derive_attributes(player, percentiles)
    return players


def needs_attributes(players):
    return any(not player.get("attributes") for player in players)


def generate_rookie_profile(overall, rng=None):
    rng = rng or random.Random()
    base = overall * 0.9
    spread = rng.uniform(-8, 8)
    archetype = rng.random()

    if archetype < 0.25:
        positions = ["SG"]
        scoring = base + spread + 8
        playmaking = base - 5
        rebounding = base - 8
    elif archetype < 0.45:
        positions = ["PG"]
        scoring = base + spread
        playmaking = base + spread + 6
        rebounding = base - 6
    elif archetype < 0.65:
        positions = ["C"] if rng.random() < 0.5 else ["PF"]
        scoring = base + spread - 4
        playmaking = base - 4
        rebounding = base + spread + 8
    elif archetype < 0.80:
        positions = ["SF"]
        scoring = base + spread
        playmaking = base + spread - 2
        rebounding = base + spread - 2
    else:
        positions = ["SG", "SF"] if rng.random() < 0.5 else ["SF", "PF"]
        scoring = base + spread
        playmaking = base + spread - 2
        rebounding = base + spread - 2

    attributes = {
        "scoring": _clamp(scoring),
        "playmaking": _clamp(playmaking),
        "rebounding": _clamp(rebounding),
        "defense": _clamp(base + rng.uniform(-6, 6)),
        "efficiency": _clamp(base + rng.uniform(-4, 4)),
        "stamina": _clamp(75 + rng.uniform(-10, 10)),
    }
    attributes = _apply_position_attr_bias(attributes, positions)
    return {"attributes": attributes, "positions": positions}


def generate_rookie_attributes(overall, rng=None):
    return generate_rookie_profile(overall, rng)["attributes"]


def season_averages_from_attributes(attributes, rng=None, player=None):
    if rng is None:
        return season_averages_from_attributes_deterministic(attributes, player)
    multipliers = position_stat_multipliers(ensure_positions(player) if player else [])
    stat_mods = player.get("stat_modifiers", {}) if player else {}
    stats = {}
    for stat, (attr_key, scale) in STAT_FROM_ATTR.items():
        value = attributes[attr_key] * scale * multipliers.get(stat, 1.0) * stat_mods.get(stat, 1.0)
        value *= rng.uniform(0.92, 1.08)
        cap = STAT_DISPLAY_CAPS.get(stat)
        if cap is not None:
            value = min(value, cap)
        stats[stat] = round(value, 1)
    return stats


def season_averages_from_attributes_deterministic(attributes, player=None):
    multipliers = position_stat_multipliers(ensure_positions(player) if player else [])
    stat_mods = player.get("stat_modifiers", {}) if player else {}
    stats = {}
    for stat, (attr_key, scale) in STAT_FROM_ATTR.items():
        value = attributes[attr_key] * scale * multipliers.get(stat, 1.0) * stat_mods.get(stat, 1.0)
        cap = STAT_DISPLAY_CAPS.get(stat)
        if cap is not None:
            value = min(value, cap)
        stats[stat] = round(value, 1)
    return stats


def age_multiplier(age, peak_age=None, decline_rate=DECLINE_RATE):
    if age is None:
        return 1.0
    peak_age = peak_age or DEFAULT_PEAK_AGE
    age = float(age)
    if age <= peak_age:
        if age <= CAREER_START_AGE or peak_age <= CAREER_START_AGE:
            return CAREER_START_MULTIPLIER
        span = peak_age - CAREER_START_AGE
        progress = (age - CAREER_START_AGE) / span
        return CAREER_START_MULTIPLIER + (1.0 - CAREER_START_MULTIPLIER) * progress
    years_past_peak = age - peak_age
    return max(MIN_AGE_MULTIPLIER, 1.0 - years_past_peak * decline_rate)


def stamina_age_multiplier(age, peak_age=None):
    return age_multiplier(age, peak_age, decline_rate=STAMINA_DECLINE_RATE)


def _scale_base_attributes(effective_attrs, multiplier, stamina_multiplier=None):
    stamina_multiplier = stamina_multiplier if stamina_multiplier is not None else multiplier
    base = {}
    for key in ATTRIBUTE_KEYS:
        effective_value = effective_attrs.get(key, MIN_ATTR)
        divisor = stamina_multiplier if key == "stamina" else multiplier
        if divisor <= 0:
            divisor = 1.0
        base[key] = _clamp(effective_value / divisor)
    return base


def _assign_potential(player, rng):
    if player.get("potential") is not None:
        return
    overall = player.get("overall") or 50
    age = player.get("age") or 25
    peak_age = player.get("peak_age") or DEFAULT_PEAK_AGE
    if player.get("is_rookie"):
        upside = rng.randint(5, 25)
        player["potential"] = _clamp(overall + upside, POTENTIAL_MIN, POTENTIAL_MAX)
    else:
        years_to_peak = max(0, peak_age - age)
        spread = rng.randint(0, 12) + min(years_to_peak, 8)
        player["potential"] = _clamp(overall + spread, POTENTIAL_MIN, POTENTIAL_MAX)
    if player.get("development_rate") is None:
        player["development_rate"] = round(rng.uniform(0.85, 1.15), 3)


def _assign_stat_modifiers(player, rng):
    if player.get("stat_modifiers"):
        return
    player_rng = _player_rng(player, rng)
    player["stat_modifiers"] = {
        stat: round(player_rng.uniform(0.94, 1.06), 3) for stat in STAT_FROM_ATTR
    }


def _assign_peak_attributes(player, rng):
    if player.get("peak_attributes"):
        return
    player_rng = _player_rng(player, rng)
    potential = player.get("potential") or player.get("overall") or 50
    positions = ensure_positions(player)
    weights = _position_attr_bias(positions)
    weight_sum = sum(weights.get(key, 1.0) for key in ATTRIBUTE_KEYS if key != "stamina")
    if weight_sum <= 0:
        weight_sum = 1.0

    peak = {}
    for key in ATTRIBUTE_KEYS:
        if key == "stamina":
            peak[key] = _clamp(potential * 0.95 + player_rng.randint(-3, 3))
            continue
        share = weights.get(key, 1.0) / weight_sum
        base = potential * (0.75 + share * 0.35)
        spread = player_rng.randint(-6, 6)
        peak[key] = _clamp(base + spread, MIN_ATTR, min(MAX_ATTR, potential + 5))
    player["peak_attributes"] = peak


def _attribute_ceiling(player, attr_key):
    peak = player.get("peak_attributes")
    if peak and attr_key in peak:
        return peak[attr_key]
    potential = player.get("potential") or player.get("overall") or 50
    bias = _position_attr_bias(ensure_positions(player))
    multiplier = max(ATTR_BIAS_MIN, min(ATTR_BIAS_MAX, bias.get(attr_key, 1.0)))
    if attr_key == "stamina":
        return _clamp(potential * 0.95 + 5)
    return _clamp(potential * multiplier * 0.85)


def _apply_development(player, rng):
    age = player.get("age", 25)
    peak_age = player.get("peak_age", DEFAULT_PEAK_AGE)
    if age >= peak_age or age <= CAREER_START_AGE:
        return

    base = player.setdefault("base_attributes", {})
    dev_rate = player.get("development_rate") or 1.0
    span = max(peak_age - CAREER_START_AGE, 1)
    growth_rate = 0.08 * dev_rate / span

    for key in ATTRIBUTE_KEYS:
        ceiling = _attribute_ceiling(player, key)
        current = base.get(key, MIN_ATTR)
        if current >= ceiling:
            continue
        delta = max(1, round((ceiling - current) * growth_rate))
        base[key] = _clamp(min(current + delta, ceiling))


def _apply_seasonal_noise(player, rng):
    base = player.get("base_attributes")
    if not base:
        return
    key = rng.choice(list(ATTRIBUTE_KEYS))
    base[key] = _clamp(base.get(key, MIN_ATTR) + rng.randint(-3, 3))


def init_career_profile(player, rng=None):
    rng = rng or random.Random()
    if player.get("age") is None:
        player["age"] = 25

    ensure_positions(player)

    if player.get("peak_age") is None:
        player["peak_age"] = rng.randint(PEAK_AGE_MIN, PEAK_AGE_MAX)
    if player.get("retirement_age") is None:
        player["retirement_age"] = rng.randint(RETIRE_AGE_MIN, RETIRE_AGE_MAX)

    _assign_potential(player, rng)
    _assign_peak_attributes(player, rng)
    _assign_stat_modifiers(player, rng)
    if player.get("season_gp") is None:
        player["season_gp"] = 0

    if player.get("base_attributes"):
        return player

    peak_age = player["peak_age"]
    age = player.get("age", 25)
    multiplier = age_multiplier(age, peak_age)
    stamina_multiplier = stamina_age_multiplier(age, peak_age)

    if not player.get("attributes"):
        player["attributes"] = derive_attributes(player)

    player["base_attributes"] = _scale_base_attributes(
        player["attributes"],
        multiplier,
        stamina_multiplier,
    )
    return player


def init_career_profiles(players, rng=None):
    rng = rng or random.Random()
    for player in players:
        init_career_profile(player, rng)
    return players


def effective_attributes(player):
    init_career_profile(player)
    base = player.get("base_attributes") or player.get("attributes") or derive_attributes(player)
    age = player.get("age", 25)
    peak_age = player.get("peak_age", DEFAULT_PEAK_AGE)
    multiplier = age_multiplier(age, peak_age)
    stamina_multiplier = stamina_age_multiplier(age, peak_age)

    effective = {}
    for key in ATTRIBUTE_KEYS:
        attr_multiplier = stamina_multiplier if key == "stamina" else multiplier
        effective[key] = _clamp(base.get(key, MIN_ATTR) * attr_multiplier)
    return effective


def refresh_player_from_attributes(player, effective_attrs=None):
    if effective_attrs is None:
        effective_attrs = effective_attributes(player)
    player["attributes"] = dict(effective_attrs)
    stats = season_averages_from_attributes_deterministic(effective_attrs, player)
    player.update(stats)
    return player


def _remove_player_from_league(season, player_id):
    season["players"].pop(str(player_id), None)
    for roster in season.get("rosters", {}).values():
        while player_id in roster:
            roster.remove(player_id)
    free_agents = season.get("free_agents", [])
    while player_id in free_agents:
        free_agents.remove(player_id)


def apply_season_aging(season, rng=None):
    rng = rng or random.Random()
    retirements = []
    players = list(season.get("players", {}).values())
    retiring_ids = set()

    for player in players:
        init_career_profile(player, rng)
        player["age"] = int(player.get("age", 25)) + 1

        if player["age"] >= player["retirement_age"]:
            retiring_ids.add(player["id"])
            retirements.append(
                {
                    "player_id": player["id"],
                    "name": player.get("name", str(player["id"])),
                    "age": player["age"],
                    "team": player.get("team"),
                    "team_id": player.get("team_id"),
                }
            )
            continue

        _apply_development(player, rng)
        _apply_seasonal_noise(player, rng)
        refresh_player_from_attributes(player)
        player["overall"] = compute_intrinsic_overall(player)

    for player_id in retiring_ids:
        _remove_player_from_league(season, player_id)

    season["last_retirements"] = retirements
    return retirements


def init_rookie_career_profile(player, effective_attrs, rng=None):
    rng = rng or random.Random()
    player["peak_age"] = rng.randint(PEAK_AGE_MIN, PEAK_AGE_MAX)
    player["retirement_age"] = rng.randint(RETIRE_AGE_MIN, RETIRE_AGE_MAX)
    player["season_gp"] = 0
    _assign_potential(player, rng)
    _assign_peak_attributes(player, rng)
    _assign_stat_modifiers(player, rng)
    age = player.get("age", 20)
    multiplier = age_multiplier(age, player["peak_age"])
    stamina_multiplier = stamina_age_multiplier(age, player["peak_age"])
    player["base_attributes"] = _scale_base_attributes(
        effective_attrs,
        multiplier,
        stamina_multiplier,
    )
    refresh_player_from_attributes(player, effective_attributes(player))
    player["overall"] = compute_intrinsic_overall(player)
    return player


def backfill_career_metadata(player, rng=None):
    """Ensure new career fields exist and refresh display stats."""
    init_career_profile(player, rng)
    refresh_player_from_attributes(player)
    player["overall"] = compute_intrinsic_overall(player)
    return player


def get_attributes(player):
    attrs = player.get("attributes")
    if attrs:
        return attrs
    return derive_attributes(player)


def allocate_minutes(roster):
    pool = team_rating_pool(roster)
    if not pool:
        pool = sorted(roster, key=lambda player: player.get("overall") or 0, reverse=True)

    rotation = pool[:ROTATION_SIZE]
    if not rotation:
        return {}

    weights = []
    for index, player in enumerate(rotation):
        attrs = get_attributes(player)
        rank_factor = max(ROTATION_SIZE - index, 1)
        weight = (player.get("overall") or 50) * attrs["stamina"] * rank_factor
        weights.append(max(weight, 1.0))

    total_weight = sum(weights)
    minutes = {}
    for index, (player, weight) in enumerate(zip(rotation, weights)):
        raw = TEAM_MINUTES * weight / total_weight
        if index < 5:
            raw = max(raw, 22)
        else:
            raw = min(max(raw, 8), 22)
        minutes[player["id"]] = round(raw)

    minute_total = sum(minutes.values())
    if minute_total != TEAM_MINUTES and minutes:
        diff = TEAM_MINUTES - minute_total
        top_id = rotation[0]["id"]
        minutes[top_id] = max(minutes[top_id] + diff, 1)

    for player in roster:
        if player["id"] not in minutes:
            minutes[player["id"]] = 0

    return minutes


def _noisy_weight(base, rng):
    return base * rng.uniform(1 - GAME_NOISE_STDEV, 1 + GAME_NOISE_STDEV)


def _largest_remainder(total, weights):
    if total <= 0 or not weights:
        return [0] * len(weights)
    weight_sum = sum(weights)
    if weight_sum <= 0:
        even = total // len(weights)
        values = [even] * len(weights)
        for index in range(total - even * len(weights)):
            values[index] += 1
        return values

    raw = [total * weight / weight_sum for weight in weights]
    floors = [int(value) for value in raw]
    remainder = total - sum(floors)
    fractions = sorted(
        [(raw[index] - floors[index], index) for index in range(len(weights))],
        reverse=True,
    )
    for _, index in fractions[:remainder]:
        floors[index] += 1
    return floors


def _build_team_box_score(roster, team_score, rng):
    minutes_map = allocate_minutes(roster)
    active = [player for player in roster if minutes_map.get(player["id"], 0) > 0]
    if not active:
        return []

    pts_weights = []
    ast_weights = []
    reb_weights = []
    stl_weights = []
    blk_weights = []

    for player in active:
        attrs = get_attributes(player)
        mins = minutes_map[player["id"]]
        efficiency_factor = 0.75 + attrs["efficiency"] / 200
        pts_weights.append(_noisy_weight(attrs["scoring"] * mins * efficiency_factor, rng))
        ast_weights.append(_noisy_weight(attrs["playmaking"] * mins, rng))
        reb_weights.append(_noisy_weight(attrs["rebounding"] * mins, rng))
        stl_weights.append(_noisy_weight(attrs["defense"] * mins * 0.4, rng))
        blk_weights.append(_noisy_weight(attrs["defense"] * mins * 0.2, rng))

    target_ast = max(18, round(team_score * 0.22))
    target_reb = max(35, round(team_score * 0.39))

    points = _largest_remainder(team_score, pts_weights)
    assists = _largest_remainder(target_ast, ast_weights)
    rebounds = _largest_remainder(target_reb, reb_weights)
    steals = _largest_remainder(max(6, round(target_ast * 0.28)), stl_weights)
    blocks = _largest_remainder(max(4, round(target_reb * 0.09)), blk_weights)

    box = []
    for index, player in enumerate(active):
        box.append(
            {
                "player_id": player["id"],
                "name": player.get("name", str(player["id"])),
                "min": minutes_map[player["id"]],
                "pts": points[index],
                "reb": rebounds[index],
                "ast": assists[index],
                "stl": steals[index],
                "blk": blocks[index],
            }
        )

    box.sort(key=lambda line: line["pts"], reverse=True)
    return box
