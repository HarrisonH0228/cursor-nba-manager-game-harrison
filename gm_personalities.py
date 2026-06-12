"""Per-team GM personality archetypes for CPU trade, draft, and FA behavior."""

import random

from difficulty import get_difficulty_settings
from trade import TRADE_TOLERANCE

ARCHETYPES = (
    "cheap",
    "super_team_builder",
    "young_blood",
    "balanced",
    "vet_centric",
)

ARCHETYPE_LABELS = {
    "cheap": "Cheap",
    "super_team_builder": "Super Team Builder",
    "young_blood": "Young Blood",
    "balanced": "Balanced",
    "vet_centric": "Vet Centric",
}

TOLERANCE_BY_ARCHETYPE = {
    "cheap": -7,
    "super_team_builder": 5,
    "young_blood": -1,
    "balanced": 0,
    "vet_centric": -3,
}


def _base_trade_tolerance(season):
    return get_difficulty_settings(season)["trade_tolerance"]


def _tolerance_for_archetype(season, archetype):
    base = _base_trade_tolerance(season)
    return base + TOLERANCE_BY_ARCHETYPE.get(archetype, 0)


def personalities_enabled(season):
    return bool(season.get("gm_personalities_enabled"))


def get_gm_profile(season, team_id):
    if not personalities_enabled(season):
        return {"archetype": "balanced", "trade_tolerance": _base_trade_tolerance(season)}
    profiles = season.get("gm_profiles") or {}
    profile = profiles.get(str(team_id))
    if not profile:
        return {"archetype": "balanced", "trade_tolerance": _base_trade_tolerance(season)}
    return profile


def partner_trade_tolerance(season, partner_team_id):
    return get_gm_profile(season, partner_team_id).get(
        "trade_tolerance", _base_trade_tolerance(season)
    )


def archetype_label(archetype):
    return ARCHETYPE_LABELS.get(archetype, archetype.replace("_", " ").title())


def _weighted_player_value(season, player, team_id, is_incoming):
    from trade import player_value

    if not player:
        return 0.0
    value = player_value(player)
    if not personalities_enabled(season):
        return value

    profile = get_gm_profile(season, team_id)
    archetype = profile.get("archetype", "balanced")
    age = player.get("age") or 25
    overall = player.get("overall") or 50

    if archetype == "super_team_builder":
        if is_incoming and overall >= 80:
            value *= 1.25
        elif not is_incoming and overall >= 80:
            value *= 1.15
    elif archetype == "young_blood":
        if age <= 26:
            value *= 1.15
        elif age >= 30:
            value *= 0.88
    elif archetype == "vet_centric":
        if age >= 28:
            value *= 1.12
        elif age <= 23:
            value *= 0.92
    elif archetype == "cheap":
        if not is_incoming:
            value *= 1.08
        else:
            value *= 0.95
    return value


def _weighted_pick_value(season, pick, team_id, is_incoming, current_draft_year=None):
    from trade import pick_value

    if not pick:
        return 0.0
    value = pick_value(pick, current_draft_year=current_draft_year)
    if not personalities_enabled(season):
        return value

    archetype = get_gm_profile(season, team_id).get("archetype", "balanced")
    if archetype == "young_blood" and is_incoming:
        value *= 1.2
    elif archetype == "vet_centric" and is_incoming:
        value *= 0.88
    elif archetype == "super_team_builder" and not is_incoming:
        value *= 0.9
    elif archetype == "cheap" and is_incoming:
        value *= 0.92
    return value


def trade_values_for_partner(
    season,
    user_team_id,
    partner_team_id,
    outgoing_players,
    outgoing_picks,
    incoming_players,
    incoming_picks,
):
    from trade import assets_value

    if not personalities_enabled(season):
        partner_in = assets_value(season, outgoing_players, outgoing_picks, user_team_id)
        partner_out = assets_value(season, incoming_players, incoming_picks, partner_team_id)
        return partner_in, partner_out

    from season import league_lookup

    lookup = league_lookup(season)
    draft_year = season.get("season_year", 2026) + 1
    partner_in = 0.0
    partner_out = 0.0

    for player_id in outgoing_players:
        player = lookup.get(int(player_id))
        if player:
            partner_in += _weighted_player_value(season, player, partner_team_id, True)

    for pick_id in outgoing_picks:
        pick = _find_pick(season, user_team_id, pick_id)
        if pick:
            partner_in += _weighted_pick_value(
                season, pick, partner_team_id, True, current_draft_year=draft_year
            )

    for player_id in incoming_players:
        player = lookup.get(int(player_id))
        if player:
            partner_out += _weighted_player_value(season, player, partner_team_id, False)

    for pick_id in incoming_picks:
        pick = _find_pick(season, partner_team_id, pick_id)
        if pick:
            partner_out += _weighted_pick_value(
                season, pick, partner_team_id, False, current_draft_year=draft_year
            )

    return partner_in, partner_out


def _find_pick(season, team_id, pick_id):
    for pick_list in (
        season.get("draft_picks", {}).get(str(team_id), []),
        season.get("future_draft_picks", {}).get(str(team_id), []),
    ):
        for pick in pick_list:
            if pick.get("id") == pick_id:
                return pick
    return None


def pick_for_team(season, team_id, options):
    if not options:
        return None
    if not personalities_enabled(season):
        return min(options, key=lambda prospect: prospect.get("draft_rank", 999))

    archetype = get_gm_profile(season, team_id).get("archetype", "balanced")
    if archetype == "super_team_builder":
        return max(options, key=lambda prospect: prospect.get("overall") or 0)
    if archetype == "young_blood":
        return max(
            options,
            key=lambda prospect: (
                -(prospect.get("age") or 22),
                -(prospect.get("overall") or 0),
            ),
        )
    if archetype == "vet_centric":
        return max(
            options,
            key=lambda prospect: (
                prospect.get("overall") or 0,
                prospect.get("age") or 20,
            ),
        )
    return min(options, key=lambda prospect: prospect.get("draft_rank", 999))


def cpu_fa_offer_multiplier(season, team_id, player):
    if not personalities_enabled(season):
        return 1.04
    archetype = get_gm_profile(season, team_id).get("archetype", "balanced")
    overall = player.get("overall") or 50
    age = player.get("age") or 25
    if archetype == "cheap":
        return 0.96
    if archetype == "super_team_builder":
        return 1.1 if overall >= 85 else 1.02
    if archetype == "young_blood":
        return 1.08 if age <= 26 else 0.98
    if archetype == "vet_centric":
        return 1.08 if age >= 28 else 0.95
    return 1.04


def cpu_fa_team_priority(season, team_id, player):
    from contracts import _team_win_pct

    priority = 0
    settings = get_difficulty_settings(season)
    win_pct = _team_win_pct(season, team_id)
    if win_pct < 0.45:
        priority += settings["weak_team_fa_boost"]

    if not personalities_enabled(season):
        return priority

    archetype = get_gm_profile(season, team_id).get("archetype", "balanced")
    overall = player.get("overall") or 50
    age = player.get("age") or 25
    if archetype == "cheap" and overall >= 85:
        return priority - 5
    if archetype == "super_team_builder" and overall >= 85:
        return priority + 15
    if archetype == "young_blood" and age <= 26:
        return priority + 10
    if archetype == "vet_centric" and age >= 28:
        return priority + 10
    return priority


def reroll_gm_personalities(season, rng=None):
    rng = rng or random.Random()
    season["gm_personalities_enabled"] = True
    user_team_id = season.get("user_team_id")
    profiles = {}
    for team_id_str in season.get("rosters", {}).keys():
        team_id = int(team_id_str)
        if user_team_id and int(user_team_id) == team_id:
            continue
        archetype = rng.choice(ARCHETYPES)
        profiles[team_id_str] = {
            "archetype": archetype,
            "trade_tolerance": _tolerance_for_archetype(season, archetype),
        }
    season["gm_profiles"] = profiles
    try:
        from news import append_news

        sample_team = next(iter(profiles.values()), None)
        if sample_team:
            append_news(
                season,
                "gm_personality",
                archetype=archetype_label(sample_team["archetype"]),
            )
    except ImportError:
        pass
    return profiles
