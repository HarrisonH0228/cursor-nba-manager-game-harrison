"""Draft system: 3-round user-driven draft with CPU auto-picks."""

import random

from attributes import generate_rookie_profile, init_rookie_career_profile
from names import ensure_unique_name, generate_player_name
from roster import can_add_player, ensure_draft_roster_room, MAX_ROSTER
from season import (
    allocate_player_id,
    draft_order,
    league_lookup,
    team_name,
)

PROSPECT_OPTIONS = 4
DRAFT_ROUNDS = 3


def _global_pick_number(round_num, pick_in_round, team_count):
    return (round_num - 1) * team_count + pick_in_round


def _scout_grade_range(global_pick, team_count):
    round_num = (global_pick - 1) // team_count + 1
    pick_in_round = ((global_pick - 1) % team_count) + 1

    if round_num == 1:
        if pick_in_round <= 3:
            return 62, 70
        if pick_in_round <= 14:
            return 54, 64
        return 48, 58
    if round_num == 2:
        return 38, 48
    return 22, 32


def _roll_career_arc(scout_grade, global_pick, team_count, rng):
    round_num = (global_pick - 1) // team_count + 1
    pick_in_round = ((global_pick - 1) % team_count) + 1

    if round_num == 1 and pick_in_round <= 3 and rng.random() < 0.03:
        return "generational"
    if round_num == 1 and pick_in_round <= 14:
        star_chance = 0.08 if pick_in_round <= 3 else 0.01
        if rng.random() < star_chance:
            return "star"
    if round_num == 1 and pick_in_round > 14 and rng.random() < 0.005:
        return "star"

    bust_chance = 0.18 if round_num == 1 and pick_in_round <= 14 else 0.22
    if rng.random() < bust_chance:
        return "bust"
    if scout_grade >= 64 and round_num == 1:
        return "starter"
    return "role"


def _scout_grade_for_pick(global_pick, team_count, rng):
    low, high = _scout_grade_range(global_pick, team_count)
    round_num = (global_pick - 1) // team_count + 1
    pick_in_round = ((global_pick - 1) % team_count) + 1

    if round_num == 1 and pick_in_round <= 3 and rng.random() < 0.03:
        return round(rng.uniform(78, 82), 1)
    if round_num == 1 and pick_in_round <= 14 and rng.random() < 0.01:
        return round(rng.uniform(72, 78), 1)
    if round_num == 1 and pick_in_round > 14 and rng.random() < 0.005:
        return round(rng.uniform(68, 74), 1)

    return round(rng.uniform(low, high), 1)


def _build_prospect(season, global_pick, team_count, rng):
    rng = rng or random.Random()
    scout_grade = _scout_grade_for_pick(global_pick, team_count, rng)
    career_arc = _roll_career_arc(scout_grade, global_pick, team_count, rng)
    age = rng.randint(19, 22)
    player_id = allocate_player_id(season)
    name = generate_player_name(rng)
    existing = {p.get("name", "") for p in season.get("players", {}).values()}
    for prospect in (season.get("draft_state") or {}).get("prospect_pool", []):
        existing.add(prospect.get("name", ""))
    name = ensure_unique_name(name, existing)
    profile = generate_rookie_profile(scout_grade, rng)
    attributes = profile["attributes"]
    prospect = {
        "id": player_id,
        "name": name,
        "team_id": None,
        "team": None,
        "scout_grade": scout_grade,
        "overall": scout_grade,
        "age": age,
        "gp": 0,
        "is_rookie": True,
        "positions": profile["positions"],
        "draft_rank": global_pick,
        "career_arc": career_arc,
    }
    init_rookie_career_profile(prospect, attributes, rng, scout_grade=scout_grade)
    return prospect


def generate_draft_class(season, team_count, rng=None):
    rng = rng or random.Random()
    total = team_count * DRAFT_ROUNDS
    pool = []
    for rank in range(1, total + 1):
        pool.append(_build_prospect(season, rank, team_count, rng))
    pool.sort(key=lambda prospect: prospect.get("draft_rank", 999))
    return pool


def generate_prospect(season, round_num, pick_in_round, team_count, rng=None):
    """Standalone prospect generation (tests / fallback without draft pool)."""
    global_pick = _global_pick_number(round_num, pick_in_round, team_count)
    return _build_prospect(season, global_pick, team_count, rng)


def _available_pool(state):
    return [
        prospect
        for prospect in state.get("prospect_pool", [])
        if not prospect.get("drafted")
    ]


def generate_prospect_options(season, pick_number, team_count, rng=None):
    rng = rng or random.Random()
    state = season.get("draft_state")
    if state and state.get("prospect_pool"):
        pool = _available_pool(state)
        if not pool:
            return []
        candidates = [
            prospect
            for prospect in pool
            if prospect.get("draft_rank", 999) <= pick_number + 8
        ]
        candidates.sort(key=lambda prospect: prospect.get("draft_rank", 999))
        window = [
            prospect
            for prospect in candidates
            if pick_number <= prospect.get("draft_rank", 999) <= pick_number + 6
        ]
        if len(window) < PROSPECT_OPTIONS:
            window = candidates[: max(PROSPECT_OPTIONS + 2, pick_number + 4)]
        shuffled = list(window)
        rng.shuffle(shuffled)
        options = sorted(shuffled[:PROSPECT_OPTIONS], key=lambda p: p.get("draft_rank", 999))
        return options

    round_num = (pick_number - 1) // team_count + 1
    pick_in_round = ((pick_number - 1) % team_count) + 1
    options = []
    for _ in range(PROSPECT_OPTIONS):
        options.append(generate_prospect(season, round_num, pick_in_round, team_count, rng))
    options.sort(key=lambda prospect: prospect.get("draft_rank", prospect.get("overall", 0)))
    return options


def _best_available(options):
    return min(options, key=lambda prospect: prospect.get("draft_rank", 999))


def resolve_pick_owner(season, slot_team_id, round_num):
    """Return team_id that currently holds the pick for this lottery slot and round."""
    for team_id_str, picks in season.get("draft_picks", {}).items():
        for pick in picks:
            if pick.get("round") == round_num and pick.get("original_team_id") == slot_team_id:
                return int(team_id_str)
    return int(slot_team_id)


def _pick_owner(slot):
    return slot.get("owner_team_id", slot["team_id"])


def _enrich_draft_queue(season, queue):
    for slot in queue:
        slot_team_id = slot["team_id"]
        round_num = slot["round"]
        owner_id = resolve_pick_owner(season, slot_team_id, round_num)
        slot["owner_team_id"] = owner_id
        picks = season.get("draft_picks", {}).get(str(owner_id), [])
        for pick in picks:
            if (
                pick.get("round") == round_num
                and pick.get("original_team_id") == slot_team_id
            ):
                pick["overall"] = slot["pick_number"]
                break
    return queue


def start_draft(season, lookup=None, rng=None):
    lookup = lookup or league_lookup(season)
    rng = rng or random.Random()
    lottery_result = draft_order(season, lookup, rng=rng)
    queue = _enrich_draft_queue(season, lottery_result["queue"])
    team_count = len(season.get("rosters", {})) or 30
    season["phase"] = "draft"
    season["draft_state"] = {
        "current_index": 0,
        "queue": queue,
        "team_count": team_count,
        "recent_picks": [],
        "prospect_options": [],
        "prospect_pool": generate_draft_class(season, team_count, rng),
        "lottery_order": lottery_result["lottery_order"],
        "playoff_order": lottery_result["playoff_order"],
    }
    return season["draft_state"]


def draft_pick_trade_context(season, team_id):
    """Build UI context for pick-for-future trade preview."""
    from trade import pick_trade_preview, pick_value, TRADE_TOLERANCE

    slot = current_pick(season)
    if not slot:
        return None
    owner_id = _pick_owner(slot)
    if owner_id != team_id:
        return None

    round_num = slot["round"]
    picks = list(season.get("draft_picks", {}).get(str(owner_id), []))
    outgoing = None
    for pick in picks:
        if pick.get("round") == round_num and pick.get("original_team_id") == slot["team_id"]:
            outgoing = pick
            break
    if outgoing is None:
        for pick in picks:
            if pick.get("round") == round_num:
                outgoing = pick
                break

    draft_year = season.get("season_year", 2026) + 1
    outgoing_val = round(pick_value(outgoing, current_draft_year=draft_year), 1) if outgoing else 0

    return {
        "slot": slot,
        "outgoing_pick": outgoing,
        "outgoing_val": outgoing_val,
        "trade_tolerance": TRADE_TOLERANCE,
        "pick_trade_preview": pick_trade_preview,
    }


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


def _consume_pick_asset_for_slot(season, owner_team_id, slot_team_id, round_num):
    picks = season.get("draft_picks", {}).get(str(owner_team_id), [])
    for index, pick in enumerate(picks):
        if pick.get("round") == round_num and pick.get("original_team_id") == slot_team_id:
            return picks.pop(index)
    for index, pick in enumerate(picks):
        if pick.get("round") == round_num:
            return picks.pop(index)
    return None


def _assign_rookie(season, prospect, team_id, draft_round=1):
    prospect["team_id"] = team_id
    prospect["team"] = team_name(season, team_id)
    prospect["drafted"] = True
    prospect["stats_source"] = "generated"
    from contracts import assign_rookie_contract

    assign_rookie_contract(prospect, draft_round=draft_round)
    season["players"][str(prospect["id"])] = prospect
    roster = season["rosters"].setdefault(str(team_id), [])
    if prospect["id"] not in roster:
        roster.append(prospect["id"])
    from roster import reconcile_team_roster

    reconcile_team_roster(season, team_id)


def _advance_pick_state(season):
    state = season.get("draft_state")
    if not state:
        return
    state["current_index"] += 1
    state["prospect_options"] = []
    if state["current_index"] >= len(state["queue"]):
        season["phase"] = "offseason"
        season["draft_state"] = None


def make_pick(season, team_id, prospect=None, rng=None, auto_trim=False):
    rng = rng or random.Random()
    state = season.get("draft_state")
    if not state:
        return False, "Draft has not started."

    slot = current_pick(season)
    if not slot:
        return False, "Draft is complete."

    owner_id = _pick_owner(slot)
    if owner_id != team_id:
        return False, "Not your pick."

    lookup = league_lookup(season)
    if auto_trim and not can_add_player(season, team_id):
        ensure_draft_roster_room(season, team_id, lookup)

    if not can_add_player(season, team_id):
        return False, f"Roster is full ({MAX_ROSTER} players). Release a player before drafting."

    team_count = state.get("team_count", 30)
    round_num = slot["round"]
    pick_number = slot["pick_number"]

    if prospect is None:
        options = state.get("prospect_options") or generate_prospect_options(
            season, pick_number, team_count, rng
        )
        if not options:
            return False, "No prospects available."
        from gm_personalities import pick_for_team

        prospect = pick_for_team(season, team_id, options)
    else:
        prospect = dict(prospect)

    consumed = _consume_pick_asset_for_slot(season, owner_id, slot["team_id"], round_num)
    if consumed is None:
        return False, "No pick asset available for this slot."

    _assign_rookie(season, prospect, team_id, draft_round=round_num)

    try:
        from news import append_news

        append_news(
            season,
            "draft",
            team=team_name(season, team_id),
            player=prospect["name"],
        )
        if (prospect.get("overall") or 0) >= 78:
            append_news(
                season,
                "rookie",
                player=prospect["name"],
                team=team_name(season, team_id),
                overall=prospect.get("overall", 78),
            )
    except ImportError:
        pass
    from contracts import refresh_all_team_finances

    refresh_all_team_finances(season, lookup)

    state["recent_picks"].insert(
        0,
        {
            "pick_number": slot["pick_number"],
            "round": round_num,
            "team_id": team_id,
            "team_name": team_name(season, team_id),
            "player_name": prospect["name"],
            "overall": prospect["overall"],
            "career_arc": prospect.get("career_arc"),
        },
    )
    state["recent_picks"] = state["recent_picks"][:20]
    _advance_pick_state(season)

    return True, f"Drafted {prospect['name']} (OVR {prospect['overall']})."


def skip_pick(season, team_id):
    state = season.get("draft_state")
    if not state:
        return False, "Draft has not started."

    slot = current_pick(season)
    if not slot:
        return False, "Draft is complete."

    owner_id = _pick_owner(slot)
    if owner_id != team_id:
        return False, "Not your pick."

    round_num = slot["round"]
    consumed = _consume_pick_asset_for_slot(season, owner_id, slot["team_id"], round_num)
    if consumed is None:
        return False, "No pick asset available for this slot."

    state["recent_picks"].insert(
        0,
        {
            "pick_number": slot["pick_number"],
            "round": round_num,
            "team_id": team_id,
            "team_name": team_name(season, team_id),
            "player_name": "— (skipped)",
            "overall": None,
            "career_arc": None,
            "skipped": True,
        },
    )
    state["recent_picks"] = state["recent_picks"][:20]
    _advance_pick_state(season)

    return True, f"Skipped pick #{slot['pick_number']} (Round {round_num})."


def trade_pick_for_future(season, team_id, partner_team_id, incoming_future_pick_id):
    """Trade the current pick slot for a partner's future-year pick."""
    from trade import TRADE_TOLERANCE, pick_value

    state = season.get("draft_state")
    if not state:
        return False, "Draft has not started."

    slot = current_pick(season)
    if not slot:
        return False, "Draft is complete."

    owner_id = _pick_owner(slot)
    if owner_id != team_id:
        return False, "Not your pick."

    partner_team_id = int(partner_team_id)
    if partner_team_id == team_id:
        return False, "Cannot trade with yourself."

    partner_future = season.get("future_draft_picks", {}).get(str(partner_team_id), [])
    incoming_pick = next((pick for pick in partner_future if pick["id"] == incoming_future_pick_id), None)
    if not incoming_pick:
        return False, "Partner does not own that future pick."

    round_num = slot["round"]
    consumed = _consume_pick_asset_for_slot(season, owner_id, slot["team_id"], round_num)
    if consumed is None:
        return False, "No pick asset available for this slot."

    draft_year = season.get("season_year", 2026) + 1
    outgoing_val = pick_value(consumed, current_draft_year=draft_year)
    incoming_val = pick_value(incoming_pick, current_draft_year=draft_year)
    if abs(outgoing_val - incoming_val) > TRADE_TOLERANCE:
        season["draft_picks"].setdefault(str(owner_id), []).append(consumed)
        return False, "Partner won't trade that future pick for this slot."

    season["draft_picks"].setdefault(str(partner_team_id), []).append(consumed)
    partner_future.remove(incoming_pick)
    season.setdefault("future_draft_picks", {}).setdefault(str(team_id), []).append(incoming_pick)

    state["recent_picks"].insert(
        0,
        {
            "pick_number": slot["pick_number"],
            "round": round_num,
            "team_id": team_id,
            "team_name": team_name(season, team_id),
            "player_name": f"— (traded for {incoming_pick['year']} R{incoming_pick['round']})",
            "overall": None,
            "career_arc": None,
            "skipped": True,
        },
    )
    state["recent_picks"] = state["recent_picks"][:20]
    _advance_pick_state(season)

    try:
        from news import append_news

        append_news(
            season,
            "pick_trade",
            team=team_name(season, team_id),
            year=incoming_pick["year"],
            round=incoming_pick["round"],
        )
    except ImportError:
        pass

    return True, (
        f"Traded pick #{slot['pick_number']} for "
        f"{incoming_pick['year']} Round {incoming_pick['round']} pick."
    )


def _prepare_user_options(season, rng=None):
    state = season.get("draft_state")
    if not state:
        return []
    slot = current_pick(season)
    if not slot:
        return []
    team_count = state.get("team_count", 30)
    options = generate_prospect_options(season, slot["pick_number"], team_count, rng)
    state["prospect_options"] = options
    return options


def sim_cpu_picks_until(season, stop_owner_id=None, rng=None):
    rng = rng or random.Random()
    picks_made = 0

    while True:
        slot = current_pick(season)
        if not slot:
            break
        owner_id = _pick_owner(slot)
        if stop_owner_id is not None and owner_id == stop_owner_id:
            _prepare_user_options(season, rng)
            break
        ok, _ = make_pick(season, owner_id, rng=rng, auto_trim=True)
        if not ok:
            ok_skip, _ = skip_pick(season, owner_id)
            if not ok_skip:
                break
        picks_made += 1

    return picks_made


def sim_draft_to_user_pick(season, user_team_id, rng=None):
    return sim_cpu_picks_until(season, stop_owner_id=user_team_id, rng=rng)


def sim_rest_of_draft(season, user_team_id=None, rng=None, auto_user_picks=False):
    rng = rng or random.Random()
    picks_made = 0
    while current_pick(season):
        slot = current_pick(season)
        owner_id = _pick_owner(slot)
        if user_team_id is not None and owner_id == user_team_id and not auto_user_picks:
            state = season.get("draft_state")
            if state and not state.get("prospect_options"):
                _prepare_user_options(season, rng)
            break
        ok, _ = make_pick(season, owner_id, rng=rng, auto_trim=True)
        if not ok:
            ok_skip, _ = skip_pick(season, owner_id)
            if not ok_skip:
                break
        picks_made += 1
    return picks_made


def draft_board_context(season, user_team_id, lookup=None):
    lookup = lookup or league_lookup(season)
    slot = current_pick(season)
    state = season.get("draft_state")
    options = []
    is_user_turn = False
    if slot and _pick_owner(slot) == user_team_id:
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

    owner_team_name = None
    if slot:
        owner_id = _pick_owner(slot)
        owner_team_name = team_name(season, owner_id)

    return {
        "current_pick": slot,
        "owner_team_name": owner_team_name,
        "is_user_turn": is_user_turn,
        "prospect_options": options,
        "recent_picks": recent,
        "picks_made": current_index,
        "total_picks": total_picks,
        "draft_complete": season.get("phase") == "offseason",
        "lottery_order": lottery_order,
        "playoff_order": playoff_order,
    }
