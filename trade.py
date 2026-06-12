"""Trade engine: player and draft pick trades with arcade value model."""

import random

from attributes import age_multiplier
from roster import MAX_ROSTER, release_worst_players, roster_size, validate_roster_sizes_after_trade
from season import can_trade, league_lookup, team_name

TRADE_TOLERANCE = 15
VERY_APPEALING_REJECTION_CHANCE = 0.10

ROUND_BASE_VALUE = {1: 80, 2: 35, 3: 15}


def partner_would_consider_trade(partner_net, tolerance):
    """CPU accepts if they are not losing more than their tolerance."""
    return partner_net >= -tolerance


def age_factor(age, peak_age=None):
    return age_multiplier(age, peak_age)


def player_value(player):
    overall = player.get("overall") or 50
    return overall * age_factor(player.get("age"), player.get("peak_age"))


def pick_value(pick, team_count=30, current_draft_year=None):
    round_num = pick.get("round", 1)
    base = ROUND_BASE_VALUE.get(round_num, 10)
    overall = pick.get("overall") or 1
    slot = ((overall - 1) % team_count) + 1
    scale = max(0.3, 1.0 - (slot - 1) / max(team_count, 1))
    value = base * scale
    pick_year = pick.get("year")
    if current_draft_year and pick_year and pick_year > current_draft_year:
        value *= 0.80
    return value


def assets_value(season, player_ids, pick_ids, team_id):
    lookup = league_lookup(season)
    total = 0.0
    draft_year = season.get("season_year", 2026) + 1
    for player_id in player_ids:
        player = lookup.get(int(player_id))
        if player and int(player.get("team_id") or -1) == int(team_id):
            total += player_value(player)
    picks = list(season.get("draft_picks", {}).get(str(team_id), []))
    picks += list(season.get("future_draft_picks", {}).get(str(team_id), []))
    pick_map = {pick["id"]: pick for pick in picks}
    for pick_id in pick_ids:
        pick = pick_map.get(pick_id)
        if pick:
            total += pick_value(pick, current_draft_year=draft_year)
    return total


def trade_window_message(season):
    if can_trade(season):
        phase = season.get("phase", "regular")
        if phase == "regular":
            return "Trade window open until all teams reach 55 games played."
        return f"Trade window open during {phase.replace('_', ' ')}."
    phase = season.get("phase", "regular")
    if phase == "regular":
        return "Trade window closed — deadline passed (55 GP)."
    return "Trades are not available in this phase."


def validate_trade(
    season,
    user_team_id,
    partner_team_id,
    outgoing_players,
    outgoing_picks,
    incoming_players,
    incoming_picks,
):
    if not can_trade(season):
        return False, "Trade window is closed."

    if user_team_id == partner_team_id:
        return False, "Cannot trade with yourself."

    lookup = league_lookup(season)
    all_out = list(outgoing_players) + list(incoming_players)
    all_picks = list(outgoing_picks) + list(incoming_picks)
    if len(set(all_out)) != len(all_out):
        return False, "Duplicate players in trade."
    if len(set(all_picks)) != len(all_picks):
        return False, "Duplicate picks in trade."
    if not all_out and not all_picks:
        return False, "Trade must include at least one asset."

    user_roster_ids = {int(x) for x in season["rosters"].get(str(user_team_id), [])}
    partner_roster_ids = {int(x) for x in season["rosters"].get(str(partner_team_id), [])}

    for player_id in outgoing_players:
        pid = int(player_id)
        player = lookup.get(pid)
        if not player or int(player.get("team_id") or -1) != int(user_team_id):
            return False, "Outgoing player not on your roster."
        if pid not in user_roster_ids:
            return False, "Outgoing player not on your roster."

    for player_id in incoming_players:
        pid = int(player_id)
        player = lookup.get(pid)
        if not player or int(player.get("team_id") or -1) != int(partner_team_id):
            return False, "Incoming player not on partner roster."
        if pid not in partner_roster_ids:
            return False, "Incoming player not on partner roster."

    user_picks = {pick["id"]: pick for pick in season.get("draft_picks", {}).get(str(user_team_id), [])}
    user_picks.update(
        {pick["id"]: pick for pick in season.get("future_draft_picks", {}).get(str(user_team_id), [])}
    )
    partner_picks = {
        pick["id"]: pick for pick in season.get("draft_picks", {}).get(str(partner_team_id), [])
    }
    partner_picks.update(
        {pick["id"]: pick for pick in season.get("future_draft_picks", {}).get(str(partner_team_id), [])}
    )
    for pick_id in outgoing_picks:
        if pick_id not in user_picks:
            return False, "Outgoing pick not owned by your team."
    for pick_id in incoming_picks:
        if pick_id not in partner_picks:
            return False, "Incoming pick not owned by partner."

    ok, message = validate_roster_sizes_after_trade(
        season,
        user_team_id,
        partner_team_id,
        outgoing_players,
        incoming_players,
        check_partner_max=False,
        check_partner_min=False,
    )
    if not ok:
        return False, message

    from contracts import validate_trade_cap

    cap_ok, cap_message = validate_trade_cap(
        season, user_team_id, outgoing_players, incoming_players, lookup
    )
    if not cap_ok:
        return False, cap_message

    return True, None


def cpu_accepts_trade(
    season,
    user_team_id,
    partner_team_id,
    outgoing_players,
    outgoing_picks,
    incoming_players,
    incoming_picks,
    rng=None,
):
    from gm_personalities import partner_trade_tolerance, trade_values_for_partner

    partner_in, partner_out = trade_values_for_partner(
        season,
        user_team_id,
        partner_team_id,
        outgoing_players,
        outgoing_picks,
        incoming_players,
        incoming_picks,
    )
    tolerance = partner_trade_tolerance(season, partner_team_id)
    partner_net = partner_in - partner_out
    if not partner_would_consider_trade(partner_net, tolerance):
        return False
    if partner_net > tolerance:
        rng = rng or random.Random()
        if rng.random() < VERY_APPEALING_REJECTION_CHANCE:
            return False
    return True


def _meter_label(partner_net, has_assets, tolerance=TRADE_TOLERANCE):
    if not has_assets:
        return "Select assets to preview"
    if partner_net < -25:
        return "Hard pass"
    if partner_net < -tolerance:
        return "Unlikely"
    if partner_net <= tolerance:
        return "Likely to accept"
    return "Very appealing"


def evaluate_trade(
    season,
    user_team_id,
    partner_team_id,
    outgoing_players,
    outgoing_picks,
    incoming_players,
    incoming_picks,
):
    from gm_personalities import partner_trade_tolerance, trade_values_for_partner

    has_assets = bool(outgoing_players or outgoing_picks or incoming_players or incoming_picks)
    partner_in, partner_out = trade_values_for_partner(
        season,
        user_team_id,
        partner_team_id,
        outgoing_players,
        outgoing_picks,
        incoming_players,
        incoming_picks,
    )
    tolerance = partner_trade_tolerance(season, partner_team_id)
    partner_net = round(partner_in - partner_out, 1)
    would_accept = has_assets and partner_would_consider_trade(partner_net, tolerance)
    meter = 50 if not has_assets else round(max(0, min(100, 50 + partner_net * 2)))

    return {
        "partner_in": round(partner_in, 1),
        "partner_out": round(partner_out, 1),
        "partner_net": partner_net,
        "tolerance": tolerance,
        "would_accept": would_accept,
        "meter": meter,
        "label": _meter_label(partner_net, has_assets, tolerance),
        "has_assets": has_assets,
    }


def execute_trade(
    season,
    user_team_id,
    partner_team_id,
    outgoing_players,
    outgoing_picks,
    incoming_players,
    incoming_picks,
):
    from roster import repair_roster_sync

    repair_roster_sync(season, user_team_id)
    repair_roster_sync(season, partner_team_id)
    lookup = league_lookup(season)
    partner_size = roster_size(season, partner_team_id)
    partner_after = partner_size - len(incoming_players) + len(outgoing_players)
    released_names = []
    if partner_after > MAX_ROSTER:
        overflow = partner_after - MAX_ROSTER
        release_count = max(2, overflow) if overflow >= 2 else overflow
        released = release_worst_players(season, partner_team_id, release_count, lookup)
        released_names = [player.get("name", player["id"]) for player in released]

    ok, message = validate_trade(
        season,
        user_team_id,
        partner_team_id,
        outgoing_players,
        outgoing_picks,
        incoming_players,
        incoming_picks,
    )
    if not ok:
        return False, message

    user_roster = [int(x) for x in season["rosters"].setdefault(str(user_team_id), [])]
    partner_roster = [int(x) for x in season["rosters"].setdefault(str(partner_team_id), [])]

    for player_id in outgoing_players:
        pid = int(player_id)
        if pid in user_roster:
            user_roster.remove(pid)
        if pid not in partner_roster:
            partner_roster.append(pid)
        if str(pid) in season["players"]:
            season["players"][str(pid)]["team_id"] = partner_team_id
            season["players"][str(pid)]["team"] = team_name(season, partner_team_id)
        elif pid in lookup:
            lookup[pid]["team_id"] = partner_team_id
            lookup[pid]["team"] = team_name(season, partner_team_id)

    for player_id in incoming_players:
        pid = int(player_id)
        if pid in partner_roster:
            partner_roster.remove(pid)
        if pid not in user_roster:
            user_roster.append(pid)
        if str(pid) in season["players"]:
            season["players"][str(pid)]["team_id"] = user_team_id
            season["players"][str(pid)]["team"] = team_name(season, user_team_id)
        elif pid in lookup:
            lookup[pid]["team_id"] = user_team_id
            lookup[pid]["team"] = team_name(season, user_team_id)

    season["rosters"][str(user_team_id)] = user_roster
    season["rosters"][str(partner_team_id)] = partner_roster

    user_pick_list = season["draft_picks"].setdefault(str(user_team_id), [])
    partner_pick_list = season["draft_picks"].setdefault(str(partner_team_id), [])
    user_future = season.setdefault("future_draft_picks", {}).setdefault(str(user_team_id), [])
    partner_future = season.setdefault("future_draft_picks", {}).setdefault(str(partner_team_id), [])

    def _find_pick(pick_id, lists):
        for pick_list in lists:
            for pick in pick_list:
                if pick["id"] == pick_id:
                    return pick, pick_list
        return None, None

    for pick_id in outgoing_picks:
        pick, pick_list = _find_pick(pick_id, [user_pick_list, user_future])
        if pick:
            pick_list.remove(pick)
            target = partner_future if pick.get("year", 0) > season.get("season_year", 2026) + 1 else partner_pick_list
            target.append(pick)

    for pick_id in incoming_picks:
        pick, pick_list = _find_pick(pick_id, [partner_pick_list, partner_future])
        if pick:
            pick_list.remove(pick)
            target = user_future if pick.get("year", 0) > season.get("season_year", 2026) + 1 else user_pick_list
            target.append(pick)

    trade_record = {
        "user_team_id": user_team_id,
        "partner_team_id": partner_team_id,
        "outgoing_players": [int(player_id) for player_id in outgoing_players],
        "outgoing_picks": list(outgoing_picks),
        "incoming_players": [int(player_id) for player_id in incoming_players],
        "incoming_picks": list(incoming_picks),
    }
    if released_names:
        trade_record["partner_released"] = released_names
    season.setdefault("trades", []).append(trade_record)
    message = "Trade completed."
    if released_names:
        message += f" {team_name(season, partner_team_id)} released {', '.join(released_names)} to make room."
    try:
        from news import append_news

        for player_id in outgoing_players:
            player = lookup.get(int(player_id))
            if player:
                append_news(
                    season,
                    "trade",
                    team=team_name(season, partner_team_id),
                    player=player.get("name", player_id),
                    partner=team_name(season, user_team_id),
                )
        for player_id in incoming_players:
            player = lookup.get(int(player_id))
            if player:
                append_news(
                    season,
                    "trade",
                    team=team_name(season, user_team_id),
                    player=player.get("name", player_id),
                    partner=team_name(season, partner_team_id),
                )
    except ImportError:
        pass
    from contracts import refresh_all_team_finances
    from roster import repair_roster_sync

    repair_roster_sync(season, user_team_id)
    repair_roster_sync(season, partner_team_id)
    refresh_all_team_finances(season, lookup)
    return True, message


def team_picks(season, team_id):
    current = list(season.get("draft_picks", {}).get(str(team_id), []))
    future = list(season.get("future_draft_picks", {}).get(str(team_id), []))
    return current + future


def future_team_picks(season, team_id):
    return list(season.get("future_draft_picks", {}).get(str(team_id), []))


def pick_trade_preview(season, outgoing_pick, incoming_pick):
    """Preview pick-for-future trade acceptance."""
    draft_year = season.get("season_year", 2026) + 1
    outgoing_val = round(pick_value(outgoing_pick, current_draft_year=draft_year), 1)
    incoming_val = round(pick_value(incoming_pick, current_draft_year=draft_year), 1)
    diff = round(abs(outgoing_val - incoming_val), 1)
    return {
        "outgoing_val": outgoing_val,
        "incoming_val": incoming_val,
        "diff": diff,
        "would_accept": diff <= TRADE_TOLERANCE,
    }


def other_teams(season, user_team_id):
    teams = []
    for team_id_str, record in season.get("standings", {}).items():
        team_id = int(team_id_str)
        if team_id == user_team_id:
            continue
        teams.append({"team_id": team_id, "team_name": record.get("team_name", str(team_id))})
    teams.sort(key=lambda item: item["team_name"].lower())
    return teams
