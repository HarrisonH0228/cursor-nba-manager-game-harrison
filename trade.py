"""Trade engine: player and draft pick trades with arcade value model."""

from attributes import age_multiplier
from roster import validate_roster_sizes_after_trade
from season import can_trade, league_lookup, team_name

TRADE_TOLERANCE = 15

ROUND_BASE_VALUE = {1: 80, 2: 35, 3: 15}


def age_factor(age, peak_age=None):
    return age_multiplier(age, peak_age)


def player_value(player):
    overall = player.get("overall") or 50
    return overall * age_factor(player.get("age"), player.get("peak_age"))


def pick_value(pick, team_count=30):
    round_num = pick.get("round", 1)
    base = ROUND_BASE_VALUE.get(round_num, 10)
    overall = pick.get("overall") or 1
    slot = ((overall - 1) % team_count) + 1
    scale = max(0.3, 1.0 - (slot - 1) / max(team_count, 1))
    return base * scale


def assets_value(season, player_ids, pick_ids, team_id):
    lookup = league_lookup(season)
    total = 0.0
    for player_id in player_ids:
        player = lookup.get(int(player_id))
        if player and player.get("team_id") == team_id:
            total += player_value(player)
    picks = season.get("draft_picks", {}).get(str(team_id), [])
    pick_map = {pick["id"]: pick for pick in picks}
    for pick_id in pick_ids:
        pick = pick_map.get(pick_id)
        if pick:
            total += pick_value(pick)
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

    for player_id in outgoing_players:
        player = lookup.get(int(player_id))
        if not player or player.get("team_id") != user_team_id:
            return False, "Outgoing player not on your roster."

    for player_id in incoming_players:
        player = lookup.get(int(player_id))
        if not player or player.get("team_id") != partner_team_id:
            return False, "Incoming player not on partner roster."

    user_picks = {pick["id"]: pick for pick in season.get("draft_picks", {}).get(str(user_team_id), [])}
    partner_picks = {
        pick["id"]: pick for pick in season.get("draft_picks", {}).get(str(partner_team_id), [])
    }
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
    )
    if not ok:
        return False, message

    return True, None


def cpu_accepts_trade(season, user_team_id, partner_team_id, outgoing_players, outgoing_picks, incoming_players, incoming_picks):
    user_out = assets_value(season, outgoing_players, outgoing_picks, user_team_id)
    user_in = assets_value(season, incoming_players, incoming_picks, partner_team_id)
    partner_out = user_in
    partner_in = user_out
    return abs(partner_out - partner_in) <= TRADE_TOLERANCE


def _meter_label(partner_net, has_assets):
    if not has_assets:
        return "Select assets to preview"
    if partner_net < -25:
        return "Hard pass"
    if partner_net < -TRADE_TOLERANCE:
        return "Unlikely"
    if partner_net <= TRADE_TOLERANCE:
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
    has_assets = bool(outgoing_players or outgoing_picks or incoming_players or incoming_picks)
    partner_in = assets_value(season, outgoing_players, outgoing_picks, user_team_id)
    partner_out = assets_value(season, incoming_players, incoming_picks, partner_team_id)
    partner_net = round(partner_in - partner_out, 1)
    would_accept = has_assets and abs(partner_net) <= TRADE_TOLERANCE
    meter = 50 if not has_assets else round(max(0, min(100, 50 + partner_net * 2)))

    return {
        "partner_in": round(partner_in, 1),
        "partner_out": round(partner_out, 1),
        "partner_net": partner_net,
        "would_accept": would_accept,
        "meter": meter,
        "label": _meter_label(partner_net, has_assets),
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

    lookup = league_lookup(season)
    user_roster = season["rosters"].setdefault(str(user_team_id), [])
    partner_roster = season["rosters"].setdefault(str(partner_team_id), [])

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

    user_pick_list = season["draft_picks"].setdefault(str(user_team_id), [])
    partner_pick_list = season["draft_picks"].setdefault(str(partner_team_id), [])

    for pick_id in outgoing_picks:
        pick = next((item for item in user_pick_list if item["id"] == pick_id), None)
        if pick:
            user_pick_list.remove(pick)
            partner_pick_list.append(pick)

    for pick_id in incoming_picks:
        pick = next((item for item in partner_pick_list if item["id"] == pick_id), None)
        if pick:
            partner_pick_list.remove(pick)
            user_pick_list.append(pick)

    season.setdefault("trades", []).append(
        {
            "user_team_id": user_team_id,
            "partner_team_id": partner_team_id,
            "outgoing_players": [int(player_id) for player_id in outgoing_players],
            "outgoing_picks": list(outgoing_picks),
            "incoming_players": [int(player_id) for player_id in incoming_players],
            "incoming_picks": list(incoming_picks),
        }
    )
    return True, "Trade completed."


def team_picks(season, team_id):
    return list(season.get("draft_picks", {}).get(str(team_id), []))


def other_teams(season, user_team_id):
    teams = []
    for team_id_str, record in season.get("standings", {}).items():
        team_id = int(team_id_str)
        if team_id == user_team_id:
            continue
        teams.append({"team_id": team_id, "team_name": record.get("team_name", str(team_id))})
    teams.sort(key=lambda item: item["team_name"].lower())
    return teams
