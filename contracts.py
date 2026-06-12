"""Salary cap, contracts, and free-agent offer evaluation."""

import random

from season import league_lookup, roster_players, team_name

SALARY_CAP_M = 170.0
MIN_SALARY_M = 1.0
LUXURY_TAX_LINE_M = 195.0
TWO_WAY_CAP_HIT_PCT = 0.5
MIN_TEAM_SALARY_PCT = 0.90
MAX_FA_YEARS = 4
MAX_ROOKIE_YEARS = 4
MAX_PLAYER_PCT = 0.35
TRADE_SALARY_TOLERANCE_M = 5.0

ROOKIE_SALARY_BY_ROUND = {1: 8.0, 2: 3.5, 3: 1.5}
CONTRACT_WARNING_YEARS = 1

CHAMPIONSHIP_BONUS_BY_OVR = (
    (90, 2.0),
    (85, 1.5),
    (78, 1.0),
    (70, 0.6),
    (0, 0.3),
)


def _round_salary(value):
    return round(max(MIN_SALARY_M, value), 1)


def market_salary(player):
    """Compute fair annual salary ($M) from OVR and age."""
    overall = player.get("overall") or 50
    age = player.get("age") or 25
    base = 0.8 + (overall / 100) ** 1.6 * 38
    if age <= 23:
        base *= 0.75
    elif age <= 26:
        base *= 0.90
    elif age <= 31:
        base *= 1.05
    elif age >= 34:
        base *= 0.85
    max_single = SALARY_CAP_M * MAX_PLAYER_PCT
    return _round_salary(min(base, max_single))


def max_player_salary(overall):
    """Max annual offer for a player based on tier."""
    if overall >= 88:
        pct = MAX_PLAYER_PCT
    elif overall >= 78:
        pct = 0.25
    elif overall >= 68:
        pct = 0.18
    else:
        pct = 0.12
    return _round_salary(SALARY_CAP_M * pct)


def min_acceptable_salary(player):
    """Floor salary a player will consider."""
    ask = player.get("asking_salary") or market_salary(player)
    prev = player.get("previous_salary") or 0
    floor = max(MIN_SALARY_M, ask * 0.80, prev * 0.85 if prev else 0)
    overall = player.get("overall") or 50
    if overall < 65:
        floor = max(MIN_SALARY_M, floor * 0.85)
    return _round_salary(floor)


def compute_asking_salary(player):
    """FA market ask — slightly above market for stars."""
    market = market_salary(player)
    overall = player.get("overall") or 50
    prev = player.get("previous_salary") or market
    ask = max(market, prev * 1.05)
    if overall >= 85:
        ask = max(ask, market * 1.10)
    elif overall >= 75:
        ask = max(ask, market * 1.05)
    return _round_salary(ask)


def roll_initial_contract_years(player, rng=None):
    """Roll contract length for non-staggered assignments (minimum 2 years)."""
    rng = rng or random.Random()
    overall = player.get("overall") or 50
    age = player.get("age") or 25
    if overall >= 90:
        choices, weights = [3, 4], [1, 3]
    elif overall >= 85:
        choices, weights = [2, 3, 4], [1, 2, 3]
    elif overall >= 78:
        choices, weights = [2, 3, 4], [2, 3, 2]
    elif overall >= 68:
        choices, weights = [2, 3, 4], [1, 4, 3]
    else:
        choices, weights = [2, 3, 4], [1, 4, 3]
    if age <= 23:
        weights = [w + (1 if y >= 3 else 0) for w, y in zip(weights, choices)]
    elif age >= 34:
        weights = [w + (1 if y <= 2 else 0) for w, y in zip(weights, choices)]
    return int(rng.choices(choices, weights=weights, k=1)[0])


def championship_bonus_amount(player):
    overall = player.get("overall") or 50
    for threshold, amount in CHAMPIONSHIP_BONUS_BY_OVR:
        if overall >= threshold:
            return amount
    return 0.3


def assign_player_contract(player, years=None, salary=None):
    """Seed or refresh contract fields on a player dict."""
    if salary is None:
        salary = market_salary(player)
    if years is None:
        years = random.randint(2, 3)
    player["salary"] = _round_salary(salary)
    player["contract_years"] = int(years)
    player.setdefault("previous_salary", player["salary"])
    player.setdefault("previous_team_id", player.get("team_id"))


def assign_rookie_contract(player, draft_round=1):
    """Rookie scale deal on draft."""
    salary = ROOKIE_SALARY_BY_ROUND.get(draft_round, MIN_SALARY_M)
    player["salary"] = _round_salary(salary)
    player["contract_years"] = MAX_ROOKIE_YEARS
    player["previous_salary"] = player["salary"]
    player["previous_team_id"] = player.get("team_id")


def team_payroll(season, team_id, lookup=None):
    lookup = lookup or league_lookup(season)
    total = 0.0
    for player in roster_players(season, team_id, lookup):
        total += float(player.get("salary") or 0)
    try:
        from roster import two_way_players

        for player in two_way_players(season, team_id, lookup):
            total += float(player.get("salary") or 0) * TWO_WAY_CAP_HIT_PCT
    except ImportError:
        pass
    return round(total, 1)


def team_finances(season, team_id, lookup=None):
    lookup = lookup or league_lookup(season)
    payroll = team_payroll(season, team_id, lookup)
    bonus_paid = float(
        season.get("team_finances", {}).get(str(team_id), {}).get("bonus_paid") or 0
    )
    cap_space = round(SALARY_CAP_M - payroll, 1)
    min_floor = round(SALARY_CAP_M * MIN_TEAM_SALARY_PCT, 1)
    return {
        "payroll": payroll,
        "cap_space": cap_space,
        "salary_cap": SALARY_CAP_M,
        "luxury_tax_line": LUXURY_TAX_LINE_M,
        "min_team_salary": min_floor,
        "below_min_warning": payroll < min_floor,
        "bonus_paid": round(bonus_paid, 1),
    }


def refresh_all_team_finances(season, lookup=None):
    lookup = lookup or league_lookup(season)
    finances = season.setdefault("team_finances", {})
    for team_id_str in season.get("rosters", {}).keys():
        finances[team_id_str] = team_finances(season, int(team_id_str), lookup)
    return finances


def ensure_contract_fields(season, rng=None):
    """Backfill contracts and finances for older saves."""
    rng = rng or random.Random()
    lookup = league_lookup(season)
    for player in season.get("players", {}).values():
        needs_contract = (
            player.get("salary") is None
            or player.get("contract_years") is None
            or int(player.get("contract_years") or 0) <= 0
        )
        if player.get("team_id") and needs_contract:
            years = roll_initial_contract_years(player, rng)
            assign_player_contract(player, years=years)
        if not player.get("team_id") and player.get("asking_salary") is None:
            player["asking_salary"] = compute_asking_salary(player)
    _normalize_team_payrolls(season, lookup)
    refresh_all_team_finances(season, lookup)
    season.setdefault("news_feed", [])
    season.setdefault("pending_fa_offers", {})
    return season


def _normalize_team_payrolls(season, lookup):
    """Scale roster salaries so no team exceeds the hard cap."""
    for team_id_str in season.get("rosters", {}):
        roster = roster_players(season, int(team_id_str), lookup)
        payroll = sum(float(p.get("salary") or 0) for p in roster)
        if payroll <= SALARY_CAP_M or payroll <= 0:
            continue
        scale = (SALARY_CAP_M * 0.92) / payroll
        for player in roster:
            player["salary"] = _round_salary(float(player.get("salary") or 0) * scale)


def assign_initial_contracts(season, rng=None):
    rng = rng or random.Random()
    lookup = league_lookup(season)
    for team_id_str in season.get("rosters", {}):
        roster_ids = list(season["rosters"][team_id_str])
        short_count = min(len(roster_ids), rng.randint(2, 3))
        bottom_half = sorted(
            roster_ids,
            key=lambda pid: lookup.get(int(pid), {}).get("overall") or 0,
        )
        short_pool = bottom_half[: max(short_count, len(bottom_half) // 2 + 1)]
        short_ids = set(rng.sample(short_pool, short_count)) if short_count else set()
        for player_id in roster_ids:
            player = lookup.get(int(player_id))
            if not player:
                continue
            if player_id in short_ids:
                years = 2
            else:
                years = roll_initial_contract_years(player, rng)
                if years < 3:
                    years = 3 if (player.get("overall") or 0) < 78 else rng.choice([3, 4])
            salary = market_salary(player)
            overall = player.get("overall") or 50
            if overall >= 85 and years >= 3:
                salary = _round_salary(salary * rng.uniform(1.03, 1.08))
            assign_player_contract(player, years=years, salary=salary)
    for player in season.get("players", {}).values():
        if not player.get("team_id"):
            player["asking_salary"] = compute_asking_salary(player)
    _normalize_team_payrolls(season, lookup)
    refresh_all_team_finances(season, lookup)


def compute_extension_ask(player):
    current = float(player.get("salary") or market_salary(player))
    market = market_salary(player)
    overall = player.get("overall") or 50
    base = max(current * 1.08, market)
    if overall >= 85:
        base = max(base, market * 1.12)
    elif overall >= 75:
        base = max(base, market * 1.06)
    return _round_salary(base)


def suggested_extension_offer(player, season, team_id, lookup=None):
    """Salary/years that meet the player's extension ask within cap space."""
    lookup = lookup or league_lookup(season)
    ask = compute_extension_ask(player)
    current = float(player.get("salary") or 0)
    overall = player.get("overall") or 50
    finances = team_finances(season, team_id, lookup)
    max_sal = max_player_salary(overall)
    salary = _round_salary(min(max(ask, ask * 1.02), max_sal))
    delta = salary - current
    if delta > finances["cap_space"]:
        salary = _round_salary(current + max(0.0, finances["cap_space"]))
    if salary < ask:
        salary = min(_round_salary(ask), max_sal)
    years = 3 if overall >= 78 else 2
    return {"salary": salary, "years": years, "ask": ask}


def validate_extension_terms(player, salary, years, team_id, season, lookup=None):
    """Pre-check extension offer before player evaluation."""
    salary = _round_salary(float(salary))
    years = int(years)
    lookup = lookup or league_lookup(season)
    finances = team_finances(season, team_id, lookup)
    overall = player.get("overall") or 50
    current = float(player.get("salary") or 0)

    if years < 1 or years > MAX_FA_YEARS:
        return False, f"Extensions must be 1–{MAX_FA_YEARS} years."
    if salary < MIN_SALARY_M:
        return False, f"Minimum salary is ${MIN_SALARY_M}M."
    delta = salary - current
    if delta > finances["cap_space"]:
        return False, f"Extension exceeds cap space (${finances['cap_space']}M available)."
    max_sal = max_player_salary(overall)
    if salary > max_sal:
        return False, f"Maximum offer for this player is ${max_sal}M/yr."
    ask = compute_extension_ask(player)
    if salary < ask * 0.95:
        return False, f"Offer too low — player wants at least ${ask}M/yr."
    return True, None


def expiring_contract_report(season, user_team_id, lookup=None):
    lookup = lookup or league_lookup(season)
    if not user_team_id:
        return []
    report = []
    for player in roster_players(season, int(user_team_id), lookup):
        years = int(player.get("contract_years") or 0)
        if years > CONTRACT_WARNING_YEARS:
            continue
        report.append(
            {
                "player_id": player["id"],
                "player_name": player.get("name", str(player["id"])),
                "salary": player.get("salary"),
                "contract_years": years,
                "extension_ask": compute_extension_ask(player),
            }
        )
    report.sort(key=lambda item: item["contract_years"])
    return report


def evaluate_extension(player, salary, years, season, team_id):
    salary = _round_salary(float(salary))
    years = int(years)
    ask = compute_extension_ask(player)
    current = float(player.get("salary") or 0)
    win_pct = _team_win_pct(season, team_id)
    score = 15.0
    if salary >= ask:
        score += 40
    elif salary >= ask * 0.95:
        score += 25
    elif salary >= current * 1.05:
        score += 15
    else:
        score -= 20
    if years >= 3:
        score += 10
    elif years == 2:
        score += 5
    if win_pct >= 0.5:
        score += 8
    threshold = 45 if (player.get("overall") or 50) >= 78 else 35
    if score >= threshold:
        return True, (
            f"{player.get('name', 'Player')} signed an extension: "
            f"${salary}M/yr × {years} years."
        )
    return False, (
        f"{player.get('name', 'Player')} wants at least ${ask}M/yr to extend."
    )


def propose_extension(season, team_id, player_id, salary, years):
    from roster import reconcile_team_roster
    from season import can_trade

    if not can_trade(season):
        return False, "Extensions are not available in this phase.", False

    lookup = league_lookup(season)
    player_id = int(player_id)
    player = lookup.get(player_id)
    if not player:
        return False, "Player not found.", False
    roster_ids = season.get("rosters", {}).get(str(team_id), [])
    if player_id not in roster_ids:
        return False, "Player is not on your roster.", False

    current_salary = float(player.get("salary") or 0)
    delta = _round_salary(float(salary)) - current_salary
    finances = team_finances(season, team_id, lookup)
    if delta > finances["cap_space"]:
        return False, f"Extension exceeds cap space (${finances['cap_space']}M available).", False

    ok, message = validate_extension_terms(player, salary, years, team_id, season, lookup)
    if not ok:
        return False, message, False

    accepted, result_message = evaluate_extension(player, salary, years, season, team_id)
    if accepted:
        player["previous_salary"] = player.get("salary")
        player["salary"] = _round_salary(float(salary))
        player["contract_years"] = int(years)
        refresh_all_team_finances(season, lookup)
        reconcile_team_roster(season, team_id)
        return True, result_message, True
    return False, result_message, False


def apply_championship_bonuses(season, team_id, lookup=None):
    lookup = lookup or league_lookup(season)
    total = 0.0
    for player in roster_players(season, int(team_id), lookup):
        bonus = championship_bonus_amount(player)
        player["championship_bonus"] = bonus
        total += bonus
    finances = season.setdefault("team_finances", {}).setdefault(str(team_id), {})
    finances["bonus_paid"] = round(float(finances.get("bonus_paid") or 0) + total, 1)
    refresh_all_team_finances(season, lookup)
    try:
        from news import append_news

        append_news(
            season,
            "championship_bonus",
            team=team_name(season, team_id),
            total=round(total, 1),
        )
    except ImportError:
        pass
    return round(total, 1)


def clear_championship_bonuses(season):
    for player in season.get("players", {}).values():
        player.pop("championship_bonus", None)
    for finances in season.get("team_finances", {}).values():
        if isinstance(finances, dict):
            finances.pop("bonus_paid", None)


def validate_offer_terms(player, salary, years, team_id, season, lookup=None):
    """Pre-check offer before player evaluation."""
    salary = _round_salary(float(salary))
    years = int(years)
    lookup = lookup or league_lookup(season)
    finances = team_finances(season, team_id, lookup)
    overall = player.get("overall") or 50

    if years < 1 or years > MAX_FA_YEARS:
        return False, f"Offers must be 1–{MAX_FA_YEARS} years."
    if salary < MIN_SALARY_M:
        return False, f"Minimum salary is ${MIN_SALARY_M}M."
    if salary > finances["cap_space"]:
        return False, f"Offer exceeds cap space (${finances['cap_space']}M available)."
    max_sal = max_player_salary(overall)
    if salary > max_sal:
        return False, f"Maximum offer for this player is ${max_sal}M/yr."
    min_sal = min_acceptable_salary(player)
    if salary < min_sal:
        return False, f"Offer too low — player wants at least ${min_sal}M/yr."

    return True, None


def _team_win_pct(season, team_id):
    record = season.get("standings", {}).get(str(team_id), {})
    gp = record.get("gp", 0) or (record.get("w", 0) + record.get("l", 0))
    if gp <= 0:
        return 0.5
    return record.get("w", 0) / gp


def evaluate_offer(player, salary, years, season, team_id):
    """
    Decide if a FA accepts an offer.
    Returns (accepted, message).
    """
    salary = _round_salary(float(salary))
    years = int(years)
    overall = player.get("overall") or 50
    ask = player.get("asking_salary") or compute_asking_salary(player)
    prev = player.get("previous_salary") or 0
    win_pct = _team_win_pct(season, team_id)

    score = 0.0
    if salary >= ask:
        score += 40
    elif salary >= ask * 0.95:
        score += 25
    elif salary >= ask * 0.90:
        score += 10
    else:
        score -= 20

    if prev and salary >= prev:
        score += 20
    elif prev and salary >= prev * 0.95:
        score += 10
    elif prev:
        score -= 15

    if years >= 3:
        score += 10
    elif years == 2:
        score += 5

    if win_pct >= 0.55:
        score += 10
    elif win_pct >= 0.45:
        score += 5
    elif win_pct < 0.35:
        score -= 10

    if overall >= 85:
        threshold = 55
    elif overall >= 75:
        threshold = 45
    else:
        threshold = 35

    if score >= threshold:
        team = team_name(season, team_id)
        return True, f"{player.get('name', 'Player')} signed with {team} for ${salary}M/yr × {years} years."

    reasons = [
        f"{player.get('name', 'Player')} wants at least ${ask}M/yr — your ${salary}M wasn't enough.",
        f"{player.get('name', 'Player')} declined: 'I have standards, and so does my agent.'",
        f"{player.get('name', 'Player')} passed — reportedly waiting for a better offer.",
    ]
    if prev and salary < prev:
        reasons.append(
            f"{player.get('name', 'Player')} won't take a pay cut from ${prev}M to ${salary}M."
        )
    return False, random.choice(reasons)


def _apply_signing(season, team_id, player, salary, years, lookup):
    player_id = player["id"]
    roster = season["rosters"].setdefault(str(team_id), [])
    if player_id not in roster:
        roster.append(player_id)
    player["previous_salary"] = player.get("salary") or salary
    player["previous_team_id"] = player.get("team_id")
    player["salary"] = _round_salary(salary)
    player["contract_years"] = int(years)
    player["team_id"] = team_id
    player["team"] = team_name(season, team_id)
    player.pop("asking_salary", None)
    player.pop("unsigned_seasons", None)
    player.pop("two_way", None)
    from roster import _remove_from_two_way

    _remove_from_two_way(season, team_id, player_id)
    refresh_all_team_finances(season, lookup)
    try:
        from news import append_news

        append_news(
            season,
            "signing",
            player=player.get("name", player_id),
            team=team_name(season, team_id),
            salary=salary,
        )
    except ImportError:
        pass
    from roster import reconcile_team_roster

    reconcile_team_roster(season, team_id)


def propose_offer(season, team_id, player_id, salary, years):
    """Submit FA offer; returns (ok, message, accepted)."""
    from roster import can_add_player, _sync_free_agents

    player_id = int(player_id)
    lookup = league_lookup(season)

    if not can_add_player(season, team_id):
        from roster import MAX_ROSTER
        return False, f"Roster is full ({MAX_ROSTER} players).", False

    player = lookup.get(player_id)
    if not player:
        return False, "Player not found.", False
    if player.get("team_id"):
        return False, "Player is already on a team.", False
    if player_id not in season.get("free_agents", []):
        return False, "Player is not a free agent.", False

    pending = season.setdefault("pending_fa_offers", {})
    if str(player_id) in pending:
        return False, "You already have a pending offer to this player.", False

    ok, message = validate_offer_terms(player, salary, years, team_id, season, lookup)
    if not ok:
        return False, message, False

    accepted, result_message = evaluate_offer(player, salary, years, season, team_id)
    if accepted:
        _apply_signing(season, team_id, player, salary, years, lookup)
        _sync_free_agents(season)
        return True, result_message, True

    try:
        from news import append_news
        append_news(
            season,
            "rejection",
            player=player.get("name", player_id),
            team=team_name(season, team_id),
            salary=salary,
        )
    except ImportError:
        pass
    return False, result_message, False


def expire_contracts(season, lookup=None):
    """Decrement years; expired players become FAs."""
    from roster import _sync_free_agents

    lookup = lookup or league_lookup(season)
    expired = []
    for player in season.get("players", {}).values():
        if not player.get("team_id"):
            continue
        years = int(player.get("contract_years") or 0)
        if years <= 0:
            continue
        years -= 1
        player["contract_years"] = years
        if years <= 0:
            team_id = player.get("team_id")
            player_id = player["id"]
            roster = season.get("rosters", {}).get(str(team_id), [])
            if player_id in roster:
                roster.remove(player_id)
            player["previous_salary"] = player.get("salary")
            player["previous_team_id"] = team_id
            tw_ids = season.setdefault("two_way_assignments", {}).get(str(team_id), [])
            if player_id in tw_ids:
                tw_ids.remove(player_id)
            player.pop("two_way", None)
            player["team_id"] = None
            player["team"] = "Free Agent"
            player["unsigned_seasons"] = 0
            player["asking_salary"] = compute_asking_salary(player)
            expired.append(player)

    _sync_free_agents(season)
    refresh_all_team_finances(season, lookup)
    return expired


def incoming_trade_salary_delta(season, user_team_id, outgoing_players, incoming_players, lookup=None):
    """Net salary change for user if trade executes."""
    lookup = lookup or league_lookup(season)
    out_sal = sum(float(lookup[int(pid)].get("salary") or 0) for pid in outgoing_players if lookup.get(int(pid)))
    in_sal = sum(float(lookup[int(pid)].get("salary") or 0) for pid in incoming_players if lookup.get(int(pid)))
    return round(in_sal - out_sal, 1)


def validate_trade_cap(season, user_team_id, outgoing_players, incoming_players, lookup=None):
    """Ensure trade fits under hard cap with tolerance."""
    lookup = lookup or league_lookup(season)
    delta = incoming_trade_salary_delta(season, user_team_id, outgoing_players, incoming_players, lookup)
    if delta <= 0:
        return True, None
    finances = team_finances(season, user_team_id, lookup)
    if delta <= finances["cap_space"] + TRADE_SALARY_TOLERANCE_M:
        return True, None
    needed = delta - finances["cap_space"]
    return False, f"Trade would exceed cap space by ${round(needed, 1)}M (max exception ${TRADE_SALARY_TOLERANCE_M}M)."


def sim_cpu_free_agency(season, rng=None, max_signings=8):
    """CPU teams sign top free agents during offseason/draft."""
    rng = rng or random.Random()
    lookup = league_lookup(season)
    free_agents = [
        lookup[pid]
        for pid in season.get("free_agents", [])
        if pid in lookup and not lookup[pid].get("team_id")
    ]
    free_agents.sort(key=lambda p: p.get("overall") or 0, reverse=True)
    signed = []
    team_ids = [int(tid) for tid in season.get("rosters", {}).keys()]

    for player in free_agents[: max_signings * 3]:
        if len(signed) >= max_signings:
            break
        ask = player.get("asking_salary") or compute_asking_salary(player)
        candidates = []
        for team_id in team_ids:
            from roster import can_add_player
            if not can_add_player(season, team_id):
                continue
            fin = team_finances(season, team_id, lookup)
            if fin["cap_space"] < ask:
                continue
            candidates.append((team_id, fin["cap_space"]))
        if not candidates:
            continue
        from gm_personalities import cpu_fa_offer_multiplier, cpu_fa_team_priority

        candidates.sort(
            key=lambda item: item[1] + cpu_fa_team_priority(season, item[0], player),
            reverse=True,
        )
        team_id = rng.choice(candidates[:5])[0]
        multiplier = cpu_fa_offer_multiplier(season, team_id, player)
        offer = min(
            ask * rng.uniform(multiplier - 0.02, multiplier + 0.04),
            max_player_salary(player.get("overall") or 50),
        )
        years = rng.randint(1, MAX_FA_YEARS)
        accepted, _ = evaluate_offer(player, offer, years, season, team_id)
        if accepted:
            _apply_signing(season, team_id, player, offer, years, lookup)
            signed.append((player, team_id))
    from roster import _sync_free_agents
    _sync_free_agents(season)
    return signed
