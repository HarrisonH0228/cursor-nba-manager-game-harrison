"""Draft system: 3-round user-driven draft with CPU auto-picks."""

import random

from attributes import generate_rookie_profile, init_rookie_career_profile, season_averages_from_attributes
from custom_players import (
    available_custom_templates,
    build_prospect_from_template,
    mark_custom_player_drafted,
)
from roster import can_add_player, ensure_draft_roster_room, MAX_ROSTER
from season import (
    allocate_player_id,
    draft_order,
    league_lookup,
    roster_players,
    team_name,
)

FIRST_NAMES = [
    "Marcus", "Jaylen", "Deandre", "Malik", "Terrence", "Darius", "Khalil", "Andre",
    "Jordan", "Tyler", "Brandon", "Xavier", "Isaiah", "Cameron", "Devonte", "Jamal",
    "Quincy", "Rashad", "Elijah", "Noah", "Liam", "Ethan", "Mason", "Logan",
]

LAST_NAMES = [
    "Johnson", "Williams", "Brown", "Davis", "Miller", "Wilson", "Moore", "Taylor",
    "Anderson", "Thomas", "Jackson", "White", "Harris", "Martin", "Thompson", "Robinson",
    "Clark", "Lewis", "Walker", "Hall", "Allen", "Young", "King", "Wright",
]

PROSPECT_OPTIONS = 4


def _round_ovr_range(round_num, pick_in_round, team_count):
    if round_num == 1:
        if pick_in_round <= 3:
            return (82, 88)
        if pick_in_round <= 10:
            return (78, 85)
        return (72, 82)
    if round_num == 2:
        return (52, 68)
    return (42, 58)


def generate_prospect(season, round_num, pick_in_round, team_count, rng=None):
    rng = rng or random.Random()
    low, high = _round_ovr_range(round_num, pick_in_round, team_count)
    overall = round(rng.uniform(low, high), 1)
    age = rng.randint(19, 22)
    player_id = allocate_player_id(season)
    name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
    profile = generate_rookie_profile(overall, rng)
    attributes = profile["attributes"]
    prospect = {
        "id": player_id,
        "name": name,
        "team_id": None,
        "team": None,
        "overall": overall,
        "age": age,
        "gp": 0,
        "is_rookie": True,
        "positions": profile["positions"],
    }
    init_rookie_career_profile(prospect, attributes, rng)
    return prospect


def generate_prospect_options(season, round_num, pick_in_round, team_count, rng=None):
    rng = rng or random.Random()
    options = []
    for _ in range(PROSPECT_OPTIONS):
        options.append(generate_prospect(season, round_num, pick_in_round, team_count, rng))
    _inject_custom_prospect(season, options, rng)
    options.sort(key=lambda prospect: prospect["overall"], reverse=True)
    return options


def _inject_custom_prospect(season, options, rng):
    available = available_custom_templates(season)
    if not available:
        return
    template = rng.choice(available)
    prospect = build_prospect_from_template(season, template, rng)
    options[rng.randrange(len(options))] = prospect


def start_draft(season, lookup=None, rng=None):
    lookup = lookup or league_lookup(season)
    rng = rng or random.Random()
    lottery_result = draft_order(season, lookup, rng=rng)
    queue = lottery_result["queue"]
    team_count = len(season.get("rosters", {})) or 30
    season["phase"] = "draft"
    season["draft_state"] = {
        "current_index": 0,
        "queue": queue,
        "team_count": team_count,
        "recent_picks": [],
        "prospect_options": [],
        "lottery_order": lottery_result["lottery_order"],
        "playoff_order": lottery_result["playoff_order"],
        "drafted_custom_ids": [],
    }
    return season["draft_state"]


def current_pick(season):
    state = season.get("draft_state")
    if not state:
        return None
    index = state.get("current_index", 0)
    queue = state.get("queue", [])
    if index >= len(queue):
        return None
    return queue[index]


def _pick_in_round(pick_number, team_count):
    return ((pick_number - 1) % team_count) + 1


def _consume_pick_asset(season, team_id, pick_id=None, round_num=None):
    del round_num
    if not pick_id:
        raise ValueError("pick_id is required to consume a draft pick")
    picks = season.get("draft_picks", {}).get(str(team_id), [])
    for index, pick in enumerate(picks):
        if pick.get("id") == pick_id:
            return picks.pop(index)
    return None


def _assign_rookie(season, prospect, team_id):
    prospect["team_id"] = team_id
    prospect["team"] = team_name(season, team_id)
    season["players"][str(prospect["id"])] = prospect
    roster = season["rosters"].setdefault(str(team_id), [])
    if prospect["id"] not in roster:
        roster.append(prospect["id"])


def make_pick(season, team_id, prospect=None, rng=None, auto_trim=False):
    rng = rng or random.Random()
    state = season.get("draft_state")
    if not state:
        return False, "Draft has not started."

    slot = current_pick(season)
    if not slot:
        return False, "Draft is complete."
    if slot["team_id"] != team_id:
        return False, "Not your pick."

    lookup = league_lookup(season)
    if auto_trim and not can_add_player(season, team_id):
        ensure_draft_roster_room(season, team_id, lookup)

    if not can_add_player(season, team_id):
        return False, f"Roster is full ({MAX_ROSTER} players). Release a player before drafting."

    team_count = state.get("team_count", 30)
    round_num = slot["round"]
    pick_in_round = _pick_in_round(slot["pick_number"], team_count)

    if prospect is None:
        options = state.get("prospect_options") or generate_prospect_options(
            season, round_num, pick_in_round, team_count, rng
        )
        prospect = options[0]
    else:
        prospect = dict(prospect)

    _consume_pick_asset(season, team_id, pick_id=slot.get("pick_id"))
    _assign_rookie(season, prospect, team_id)
    if prospect.get("custom_id"):
        mark_custom_player_drafted(season, prospect["custom_id"])

    state["recent_picks"].insert(
        0,
        {
            "pick_number": slot["pick_number"],
            "round": round_num,
            "team_id": team_id,
            "team_name": slot["team_name"],
            "player_name": prospect["name"],
            "overall": prospect["overall"],
        },
    )
    state["recent_picks"] = state["recent_picks"][:20]
    state["current_index"] += 1
    state["prospect_options"] = []

    if state["current_index"] >= len(state["queue"]):
        season["phase"] = "offseason"
        season["draft_state"] = None

    return True, f"Drafted {prospect['name']} (OVR {prospect['overall']})."


def _prepare_user_options(season, rng=None):
    state = season.get("draft_state")
    if not state:
        return []
    slot = current_pick(season)
    if not slot:
        return []
    team_count = state.get("team_count", 30)
    pick_in_round = _pick_in_round(slot["pick_number"], team_count)
    options = generate_prospect_options(season, slot["round"], pick_in_round, team_count, rng)
    state["prospect_options"] = options
    return options


def sim_cpu_picks_until(season, stop_team_id=None, rng=None):
    rng = rng or random.Random()
    picks_made = 0

    while True:
        slot = current_pick(season)
        if not slot:
            break
        if stop_team_id is not None and slot["team_id"] == stop_team_id:
            _prepare_user_options(season, rng)
            break
        make_pick(season, slot["team_id"], rng=rng, auto_trim=True)
        picks_made += 1

    return picks_made


def sim_draft_to_user_pick(season, user_team_id, rng=None):
    return sim_cpu_picks_until(season, stop_team_id=user_team_id, rng=rng)


def sim_rest_of_draft(season, user_team_id=None, rng=None, auto_user_picks=False):
    rng = rng or random.Random()
    picks_made = 0
    while current_pick(season):
        slot = current_pick(season)
        if (
            user_team_id is not None
            and slot["team_id"] == user_team_id
            and not auto_user_picks
        ):
            state = season.get("draft_state")
            if state and not state.get("prospect_options"):
                _prepare_user_options(season, rng)
            break
        make_pick(season, slot["team_id"], rng=rng, auto_trim=True)
        picks_made += 1
    return picks_made


def draft_board_context(season, user_team_id, lookup=None):
    lookup = lookup or league_lookup(season)
    slot = current_pick(season)
    state = season.get("draft_state")
    options = []
    is_user_turn = False
    if slot and slot["team_id"] == user_team_id:
        is_user_turn = True
        if state:
            if not state.get("prospect_options"):
                _prepare_user_options(season)
            options = state.get("prospect_options", [])

    recent = state.get("recent_picks", []) if state else []
    total_picks = len(state.get("queue", [])) if state else 0
    current_index = state.get("current_index", 0) if state else 0
    lottery_order = state.get("lottery_order", []) if state else []
    playoff_order = state.get("playoff_order", []) if state else []

    return {
        "current_pick": slot,
        "is_user_turn": is_user_turn,
        "prospect_options": options,
        "recent_picks": recent,
        "picks_made": current_index,
        "total_picks": total_picks,
        "draft_complete": season.get("phase") == "offseason",
        "lottery_order": lottery_order,
        "playoff_order": playoff_order,
    }
