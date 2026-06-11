import json
import random
import time

from attributes import (
    apply_attributes,
    apply_season_aging,
    backfill_career_metadata,
    ensure_positions,
    init_career_profile,
    mark_nba_cache_stats,
    needs_attributes,
    refresh_team_roster_stats,
)
from names import dedupe_all_player_names
from ratings import compute_team_overall
from simulation import simulate_game, simulate_game_with_box_score

GAMES_PER_TEAM = 82
EXTRA_HOME_GAMES = 12
TRADE_DEADLINE_GAMES = 55
PLAYOFF_SERIES_LENGTH = 7
PLAYOFF_WINS_NEEDED = 4

TEAM_CONFERENCES = {
    1610612737: "East",
    1610612738: "East",
    1610612751: "East",
    1610612766: "East",
    1610612741: "East",
    1610612739: "East",
    1610612765: "East",
    1610612754: "East",
    1610612748: "East",
    1610612749: "East",
    1610612750: "West",
    1610612752: "East",
    1610612753: "East",
    1610612755: "East",
    1610612761: "East",
    1610612764: "East",
    1610612742: "West",
    1610612743: "West",
    1610612744: "West",
    1610612745: "West",
    1610612746: "West",
    1610612747: "West",
    1610612763: "West",
    1610612740: "West",
    1610612760: "West",
    1610612756: "West",
    1610612757: "West",
    1610612758: "West",
    1610612759: "West",
    1610612762: "West",
}


NEXT_PLAYER_ID_START = 9000001
LOTTERY_PICK_COUNT = 14
PLAYOFF_TEAMS_PER_CONFERENCE = 8

# Approximate NBA lottery odds (per 1000) for the 14 non-playoff teams, worst record first.
LOTTERY_ODDS = [140, 140, 134, 122, 109, 94, 79, 67, 56, 46, 37, 29, 22, 16]

DEBUG_LOG_PATH = "/Users/harrisonhoggatt/Documents/GitHub/nba-manager-game/.cursor/debug-7efc9a.log"


def _debug_log(hypothesis_id, location, message, data=None, run_id="pre-fix"):
    # #region agent log
    try:
        payload = {
            "sessionId": "7efc9a",
            "runId": run_id,
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data or {},
            "timestamp": int(time.time() * 1000),
        }
        with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")
    except OSError:
        pass
    # #endregion


def _schedule_games_per_team(matchups, team_ids):
    counts = {team_id: 0 for team_id in team_ids}
    for game in matchups:
        counts[game["home_id"]] += 1
        counts[game["away_id"]] += 1
    return counts


def build_player_pool(cache_players, rng=None):
    rng = rng or random.Random()
    pool = {}
    for player in cache_players:
        player_id = player["id"]
        entry = dict(player)
        original_gp = player.get("gp") or 0
        entry["is_rookie"] = False
        entry["season_gp"] = 0
        entry["gp"] = 0
        ensure_positions(entry)
        init_career_profile(entry, rng)
        mark_nba_cache_stats(entry, source_gp=original_gp)
        pool[str(player_id)] = entry
    dedupe_all_player_names(pool.values())
    return pool


def refresh_all_roster_stats(season, lookup=None):
    lookup = lookup or league_lookup(season)
    for team_id_str in season.get("rosters", {}).keys():
        roster = roster_players(season, int(team_id_str), lookup)
        refresh_team_roster_stats(roster)


def _cap_team_rosters(season, max_size=15):
    from roster import MAX_ROSTER, release_player

    lookup = league_lookup(season)
    for team_id_str, roster_ids in list(season.get("rosters", {}).items()):
        team_id = int(team_id_str)
        if len(roster_ids) <= max_size:
            continue
        players = sorted(
            [lookup[pid] for pid in roster_ids if pid in lookup],
            key=lambda player: player.get("overall") or 0,
            reverse=True,
        )
        keep_ids = {player["id"] for player in players[:max_size]}
        for player_id in list(roster_ids):
            if player_id not in keep_ids:
                release_player(season, team_id, player_id)


def migrate_season(season, rng=None):
    rng = rng or random.Random()
    if "free_agents" not in season:
        season["free_agents"] = []
    if "future_draft_picks" not in season:
        team_ids = [int(team_id) for team_id in season.get("rosters", {}).keys()]
        draft_year = season.get("season_year", 2026) + 2
        season["future_draft_picks"] = init_draft_picks(team_ids, draft_year)
    from roster import repair_roster_sync

    repair_roster_sync(season)
    lookup = league_lookup(season)
    for player in season.get("players", {}).values():
        backfill_career_metadata(player, rng)
    refresh_all_roster_stats(season, lookup)
    from contracts import ensure_contract_fields

    ensure_contract_fields(season, rng)
    free_agents = []
    for key, player in season.get("players", {}).items():
        if not player.get("team_id"):
            free_agents.append(player.get("id", int(key)))
    season["free_agents"] = sorted(set(free_agents))
    return season


def league_lookup(season):
    lookup = {}
    for key, player in season.get("players", {}).items():
        player_id = player.get("id", int(key))
        lookup[player_id] = player
    return lookup


def init_draft_picks(team_ids, year):
    picks_by_team = {}
    pick_number = 1
    for team_id in sorted(team_ids):
        team_picks = []
        for round_num in (1, 2, 3):
            team_picks.append(
                {
                    "id": f"pick-{team_id}-{year}-r{round_num}",
                    "year": year,
                    "round": round_num,
                    "overall": pick_number,
                    "original_team_id": team_id,
                }
            )
            pick_number += 1
        picks_by_team[str(team_id)] = team_picks
    return picks_by_team


def can_trade(season):
    phase = season.get("phase", "regular")
    if phase in {"draft", "offseason"}:
        return True
    if phase == "regular":
        target = season.get("trade_deadline_games", TRADE_DEADLINE_GAMES)
        return not all_teams_at_gp(season, target)
    return False


def init_season(players, season_year=2026, rng=None):
    rng = rng or random.Random()

    if needs_attributes(players):
        apply_attributes(players)

    team_players = {}
    team_names = {}
    free_agent_ids = []
    for player in players:
        team_id = player.get("team_id")
        if not team_id:
            free_agent_ids.append(player["id"])
            continue
        team_players.setdefault(team_id, []).append(player["id"])
        team_names[team_id] = player.get("team", "Unknown")

    team_ids = sorted(team_players.keys())
    schedule = generate_schedule(team_ids, rng)
    standings = {
        str(team_id): {
            "w": 0,
            "l": 0,
            "gp": 0,
            "team_name": team_names[team_id],
        }
        for team_id in team_ids
    }
    draft_year = season_year + 1
    future_year = season_year + 2
    player_pool = build_player_pool(players, rng)
    season = {
        "season_year": season_year,
        "phase": "regular",
        "current_day": 1,
        "max_day": max(game["day"] for game in schedule) if schedule else 1,
        "trade_deadline_games": TRADE_DEADLINE_GAMES,
        "next_player_id": NEXT_PLAYER_ID_START,
        "players": player_pool,
        "free_agents": sorted(set(free_agent_ids)),
        "draft_picks": init_draft_picks(team_ids, draft_year),
        "future_draft_picks": init_draft_picks(team_ids, future_year),
        "draft_state": None,
        "trades": [],
        "rosters": {str(team_id): roster for team_id, roster in team_players.items()},
        "standings": standings,
        "schedule": schedule,
        "playoffs": None,
        "recent_results": [],
        "news_feed": [],
        "team_finances": {},
        "pending_fa_offers": {},
        "injury_log": [],
        "pending_notifications": [],
    }
    _cap_team_rosters(season)
    from roster import _sync_free_agents

    _sync_free_agents(season)
    season["free_agents"] = sorted(set(season.get("free_agents", []) + free_agent_ids))
    refresh_all_roster_stats(season, league_lookup(season))
    from contracts import assign_initial_contracts

    assign_initial_contracts(season, rng)
    return season


def generate_schedule(team_ids, rng=None):
    rng = rng or random.Random()
    matchups = []

    for index, home_id in enumerate(team_ids):
        for away_id in team_ids[index + 1 :]:
            matchups.append({"home_id": home_id, "away_id": away_id})
            matchups.append({"home_id": away_id, "away_id": home_id})

    matchups.extend(_generate_extra_games(team_ids, rng))

    rng.shuffle(matchups)
    scheduled = assign_days(matchups, rng)
    gp_counts = _schedule_games_per_team(scheduled, team_ids)
    min_gp = min(gp_counts.values())
    max_gp = max(gp_counts.values())
    # #region agent log
    _debug_log(
        "A",
        "season.py:generate_schedule",
        "schedule gp counts",
        {"min_gp": min_gp, "max_gp": max_gp, "total_games": len(scheduled), "target": GAMES_PER_TEAM},
    )
    # #endregion

    games = []
    for game_id, game in enumerate(scheduled, start=1):
        games.append(
            {
                "id": game_id,
                "day": game["day"],
                "home_id": game["home_id"],
                "away_id": game["away_id"],
                "home_score": None,
                "away_score": None,
                "played": False,
            }
        )
    return games


def _generate_extra_games(team_ids, rng):
    for _ in range(100):
        home_needed = {team_id: EXTRA_HOME_GAMES for team_id in team_ids}
        away_needed = {team_id: EXTRA_HOME_GAMES for team_id in team_ids}
        extra_games = []

        while sum(home_needed.values()) > 0:
            home_options = [team_id for team_id in team_ids if home_needed[team_id] > 0]
            away_options = [team_id for team_id in team_ids if away_needed[team_id] > 0]
            valid_pairs = [
                (home_id, away_id)
                for home_id in home_options
                for away_id in away_options
                if home_id != away_id
            ]
            if not valid_pairs:
                break
            home_id, away_id = rng.choice(valid_pairs)
            extra_games.append({"home_id": home_id, "away_id": away_id})
            home_needed[home_id] -= 1
            away_needed[away_id] -= 1

        if sum(home_needed.values()) == 0:
            return extra_games

    raise RuntimeError("Failed to generate balanced extra home games for schedule")


def assign_days(matchups, rng):
    rng.shuffle(matchups)
    games_per_day = 8
    for index, game in enumerate(matchups):
        game["day"] = (index // games_per_day) + 1
    return matchups


def players_by_id(players):
    return {player["id"]: player for player in players}


def roster_players(season, team_id, lookup=None):
    if lookup is None:
        lookup = league_lookup(season)
    roster_ids = season.get("rosters", {}).get(str(team_id), [])
    return [lookup[player_id] for player_id in roster_ids if player_id in lookup]


def allocate_player_id(season):
    player_id = season.get("next_player_id", NEXT_PLAYER_ID_START)
    season["next_player_id"] = player_id + 1
    return player_id


def _standings_row_sort_key(season, lookup):
    return lambda row: (
        row["win_pct"],
        row["w"],
        team_ovr_for_tiebreak(season, row["team_id"], lookup),
    )


def _standings_worst_first(season, lookup=None):
    lookup = lookup or league_lookup(season)
    rows = standings_table(season)
    rows.sort(key=_standings_row_sort_key(season, lookup))
    return list(reversed(rows))


def playoff_team_ids(season):
    playoff_ids = set()
    for conference in ("East", "West"):
        for row in standings_table(season, conference=conference)[:PLAYOFF_TEAMS_PER_CONFERENCE]:
            playoff_ids.add(row["team_id"])
    return playoff_ids


def lottery_team_rows(season, lookup=None):
    lookup = lookup or league_lookup(season)
    playoff_ids = playoff_team_ids(season)
    lottery_rows = [row for row in _standings_worst_first(season, lookup) if row["team_id"] not in playoff_ids]
    lottery_rows.sort(key=_standings_row_sort_key(season, lookup))
    return list(reversed(lottery_rows))


def _lottery_weights(team_count):
    if team_count <= len(LOTTERY_ODDS):
        return LOTTERY_ODDS[:team_count]
    extra = team_count - len(LOTTERY_ODDS)
    return LOTTERY_ODDS + [8] * extra


def _playoff_exit_tiers(season):
    playoffs = season.get("playoffs") or {}
    tiers = {}
    for round_index, round_data in enumerate(playoffs.get("rounds", [])):
        for series in round_data.get("series", []):
            if not series.get("complete"):
                continue
            if series["winner_id"] == series["high_seed_id"]:
                loser_id = series["low_seed_id"]
            else:
                loser_id = series["high_seed_id"]
            tiers[loser_id] = max(tiers.get(loser_id, 0), round_index + 1)

    champion_id = playoffs.get("champion_id")
    if champion_id:
        tiers[champion_id] = len(playoffs.get("rounds", [])) + 1
    return tiers


def playoff_finish_rows(season, lookup=None):
    lookup = lookup or league_lookup(season)
    playoff_ids = playoff_team_ids(season)
    if not playoff_ids:
        return []

    rows_by_id = {row["team_id"]: row for row in standings_table(season)}
    exit_tiers = _playoff_exit_tiers(season)
    playoff_rows = [rows_by_id[team_id] for team_id in playoff_ids if team_id in rows_by_id]
    playoff_rows.sort(
        key=lambda row: (
            exit_tiers.get(row["team_id"], 0),
            row["win_pct"],
            row["w"],
            team_ovr_for_tiebreak(season, row["team_id"], lookup),
        )
    )
    return playoff_rows


def run_draft_lottery(season, lookup=None, rng=None):
    lookup = lookup or league_lookup(season)
    rng = rng or random.Random()
    lottery_rows = lottery_team_rows(season, lookup)
    if not lottery_rows:
        lottery_rows = _standings_worst_first(season, lookup)[:LOTTERY_PICK_COUNT]

    base_weights = _lottery_weights(len(lottery_rows))
    weight_by_team = {
        row["team_id"]: base_weights[index]
        for index, row in enumerate(lottery_rows)
    }
    remaining = list(lottery_rows)
    lottery_winners = []

    for pick_number in range(1, min(LOTTERY_PICK_COUNT, len(remaining)) + 1):
        weights = [weight_by_team[row["team_id"]] for row in remaining]
        chosen = rng.choices(remaining, weights=weights, k=1)[0]
        lottery_winners.append(
            {
                "pick_number": pick_number,
                "team_id": chosen["team_id"],
                "team_name": chosen["team_name"],
            }
        )
        remaining.remove(chosen)

    playoff_rows = playoff_finish_rows(season, lookup)
    playoff_start = len(lottery_winners) + 1
    playoff_order = [
        {
            "pick_number": playoff_start + index,
            "team_id": row["team_id"],
            "team_name": row["team_name"],
        }
        for index, row in enumerate(playoff_rows)
    ]

    round1_rows = [
        {"team_id": entry["team_id"], "team_name": entry["team_name"]}
        for entry in lottery_winners
    ]
    round1_rows.extend(
        {"team_id": entry["team_id"], "team_name": entry["team_name"]}
        for entry in playoff_order
    )

    if len(round1_rows) < len(season.get("rosters", {})):
        seen_ids = {row["team_id"] for row in round1_rows}
        for row in _standings_worst_first(season, lookup):
            if row["team_id"] in seen_ids:
                continue
            round1_rows.append({"team_id": row["team_id"], "team_name": row["team_name"]})
            seen_ids.add(row["team_id"])
            if len(round1_rows) >= len(season.get("rosters", {})):
                break

    return {
        "lottery_order": lottery_winners,
        "playoff_order": playoff_order,
        "round1_team_order": round1_rows,
    }


def draft_order(season, lookup=None, rng=None):
    lookup = lookup or league_lookup(season)
    lottery_result = run_draft_lottery(season, lookup, rng=rng)
    round1_order = lottery_result["round1_team_order"]
    team_count = len(round1_order)
    order = []
    for round_num in (1, 2, 3):
        for index, row in enumerate(round1_order, start=1):
            order.append(
                {
                    "pick_number": (round_num - 1) * team_count + index,
                    "round": round_num,
                    "team_id": row["team_id"],
                    "team_name": row["team_name"],
                }
            )
    lottery_result["queue"] = order
    return lottery_result


def advance_season(season, rng=None):
    rng = rng or random.Random()
    from contracts import expire_contracts, sim_cpu_free_agency

    expire_contracts(season)
    if season.get("phase") in {"draft", "offseason", "complete"}:
        sim_cpu_free_agency(season, rng)
    retirements = apply_season_aging(season, rng)
    team_ids = [int(team_id) for team_id in season.get("rosters", {}).keys()]
    team_names = {
        int(team_id): record.get("team_name", str(team_id))
        for team_id, record in season.get("standings", {}).items()
    }

    season_year = season.get("season_year", 2026) + 1
    schedule = generate_schedule(team_ids, rng)
    standings = {
        str(team_id): {
            "w": 0,
            "l": 0,
            "gp": 0,
            "team_name": team_names.get(team_id, str(team_id)),
        }
        for team_id in team_ids
    }

    season.update(
        {
            "season_year": season_year,
            "phase": "regular",
            "current_day": 1,
            "max_day": max(game["day"] for game in schedule) if schedule else 1,
            "schedule": schedule,
            "standings": standings,
            "playoffs": None,
            "recent_results": [],
            "draft_state": None,
            "draft_picks": season.get("future_draft_picks") or init_draft_picks(team_ids, season_year + 1),
            "future_draft_picks": init_draft_picks(team_ids, season_year + 2),
            "last_retirements": retirements,
        }
    )
    try:
        from news import append_news

        for item in retirements:
            append_news(
                season,
                "retirement",
                player=item.get("name", "Unknown"),
                age=item.get("age"),
            )
    except ImportError:
        pass
    for player in season.get("players", {}).values():
        player["season_gp"] = 0
        player["gp"] = 0
    return season


def team_name(season, team_id):
    standing = season.get("standings", {}).get(str(team_id), {})
    return standing.get("team_name", str(team_id))


def standings_table(season, conference=None):
    rows = []
    for team_id_str, record in season.get("standings", {}).items():
        team_id = int(team_id_str)
        if conference and TEAM_CONFERENCES.get(team_id) != conference:
            continue
        wins = record.get("w", 0)
        losses = record.get("l", 0)
        games = record.get("gp", wins + losses)
        win_pct = wins / games if games else 0.0
        rows.append(
            {
                "team_id": team_id,
                "team_name": record.get("team_name", str(team_id)),
                "w": wins,
                "l": losses,
                "gp": games,
                "win_pct": win_pct,
            }
        )

    rows.sort(key=lambda row: (row["win_pct"], row["w"]), reverse=True)
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    return rows


def all_teams_at_gp(season, target_gp):
    standings = season.get("standings", {})
    if not standings:
        return True
    return all(record.get("gp", 0) >= target_gp for record in standings.values())


def regular_season_complete(season):
    return all_teams_at_gp(season, GAMES_PER_TEAM)


def all_schedule_games_played(season):
    schedule = season.get("schedule", [])
    return bool(schedule) and all(game["played"] for game in schedule)


def _record_result(season, game, result):
    home_id = game["home_id"]
    away_id = game["away_id"]
    home_score = result["home_score"]
    away_score = result["away_score"]
    game["home_score"] = home_score
    game["away_score"] = away_score
    game["home_box"] = result["home_box"]
    game["away_box"] = result["away_box"]
    game["played"] = True

    home_record = season["standings"][str(home_id)]
    away_record = season["standings"][str(away_id)]

    if home_score > away_score:
        home_record["w"] += 1
        away_record["l"] += 1
    else:
        home_record["l"] += 1
        away_record["w"] += 1

    home_record["gp"] += 1
    away_record["gp"] += 1

    players = season.get("players", {})
    for line in result["home_box"]:
        if line.get("min", 0) <= 0:
            continue
        player = players.get(str(line["player_id"]))
        if player is not None:
            player["season_gp"] = int(player.get("season_gp") or 0) + 1
            player["gp"] = int(player.get("gp") or 0) + 1
    for line in result["away_box"]:
        if line.get("min", 0) <= 0:
            continue
        player = players.get(str(line["player_id"]))
        if player is not None:
            player["season_gp"] = int(player.get("season_gp") or 0) + 1
            player["gp"] = int(player.get("gp") or 0) + 1

    all_lines = result["home_box"] + result["away_box"]
    top_scorer = max(all_lines, key=lambda line: line["pts"]) if all_lines else None

    season["recent_results"].insert(
        0,
        {
            "day": game["day"],
            "game_id": game["id"],
            "home_id": home_id,
            "away_id": away_id,
            "home_name": home_record["team_name"],
            "away_name": away_record["team_name"],
            "home_score": home_score,
            "away_score": away_score,
            "top_scorer_name": top_scorer["name"] if top_scorer else None,
            "top_scorer_pts": top_scorer["pts"] if top_scorer else None,
        },
    )
    season["recent_results"] = season["recent_results"][:20]

    try:
        from news import append_news

        if top_scorer and top_scorer.get("pts", 0) >= 35:
            opp_name = away_record["team_name"] if top_scorer in result["home_box"] else home_record["team_name"]
            append_news(
                season,
                "game",
                player=top_scorer.get("name", "Unknown"),
                pts=top_scorer["pts"],
                opp=opp_name,
            )
        margin = abs(home_score - away_score)
        if margin >= 20:
            winner = home_record if home_score > away_score else away_record
            loser = away_record if home_score > away_score else home_record
            w_score = max(home_score, away_score)
            l_score = min(home_score, away_score)
            if (loser.get("gp", 0) or 0) >= 10:
                append_news(
                    season,
                    "upset",
                    winner=winner["team_name"],
                    loser=loser["team_name"],
                    w_score=w_score,
                    l_score=l_score,
                )
    except ImportError:
        pass


def _play_game(season, game, lookup, rng, user_team_id=None):
    from injuries import injured_player_ids, roll_game_injuries, tick_injuries_after_game

    home_roster = roster_players(season, game["home_id"], lookup)
    away_roster = roster_players(season, game["away_id"], lookup)
    day = game.get("day", season.get("current_day", 1))

    user_team_id = user_team_id or season.get("user_team_id")
    if user_team_id and int(game["home_id"]) == int(user_team_id):
        roll_game_injuries(season, game["home_id"], home_roster, day, rng)
    elif user_team_id and int(game["away_id"]) == int(user_team_id):
        roll_game_injuries(season, game["away_id"], away_roster, day, rng)

    home_injured = injured_player_ids(home_roster)
    away_injured = injured_player_ids(away_roster)

    game["home_dnp"] = [
        {
            "player_id": player["id"],
            "name": player.get("name", str(player["id"])),
            "reason": (player.get("injury") or {}).get("type", "injury"),
        }
        for player in home_roster
        if player["id"] in home_injured
    ]
    game["away_dnp"] = [
        {
            "player_id": player["id"],
            "name": player.get("name", str(player["id"])),
            "reason": (player.get("injury") or {}).get("type", "injury"),
        }
        for player in away_roster
        if player["id"] in away_injured
    ]

    home_gp = season["standings"][str(game["home_id"])].get("gp", 0)
    away_gp = season["standings"][str(game["away_id"])].get("gp", 0)
    result = simulate_game_with_box_score(
        home_roster,
        away_roster,
        rng,
        home_team_gp=home_gp,
        away_team_gp=away_gp,
        home_exclude_ids=home_injured,
        away_exclude_ids=away_injured,
    )
    _record_result(season, game, result)

    tick_injuries_after_game(home_roster)
    tick_injuries_after_game(away_roster)
    return game


def simulate_games(season, lookup, rng=None, through_day=None, count_days=None, through_team_gp=None, user_team_id=None):
    rng = rng or random.Random()
    games_played = 0
    start_day = season.get("current_day", 1)
    user_team_id = user_team_id or season.get("user_team_id")

    if count_days is not None:
        end_day = start_day + count_days - 1
    elif through_day is not None:
        end_day = through_day
    else:
        end_day = season.get("max_day", start_day)

    for day in range(start_day, end_day + 1):
        if through_team_gp is not None and all_teams_at_gp(season, through_team_gp):
            break

        for game in season["schedule"]:
            if game["played"] or game["day"] != day:
                continue
            if through_team_gp is not None and all_teams_at_gp(season, through_team_gp):
                break
            _play_game(season, game, lookup, rng, user_team_id=user_team_id)
            games_played += 1

    return games_played


def sim_rest_of_season(season, lookup, rng=None, user_team_id=None):
    rng = rng or random.Random()
    user_team_id = user_team_id or season.get("user_team_id")
    games_played = 0
    for game in season["schedule"]:
        if game["played"]:
            continue
        _play_game(season, game, lookup, rng, user_team_id=user_team_id)
        games_played += 1

    gp_values = [record.get("gp", 0) for record in season.get("standings", {}).values()]
    all_played = all_schedule_games_played(season)
    complete = regular_season_complete(season)
    # #region agent log
    _debug_log(
        "ABC",
        "season.py:sim_rest_of_season",
        "post sim state",
        {
            "games_played": games_played,
            "all_schedule_played": all_played,
            "regular_complete": complete,
            "min_gp": min(gp_values) if gp_values else None,
            "max_gp": max(gp_values) if gp_values else None,
            "current_day_before": season.get("current_day"),
            "max_day": season.get("max_day"),
            "phase_before": season.get("phase"),
        },
    )
    # #endregion

    if complete or all_played:
        season["phase"] = "regular_complete"
        season["current_day"] = season.get("max_day", 1)
    else:
        season["current_day"] = season.get("max_day", 1) + 1

    # #region agent log
    _debug_log(
        "C",
        "season.py:sim_rest_of_season",
        "final season state",
        {
            "phase": season.get("phase"),
            "current_day": season.get("current_day"),
            "max_day": season.get("max_day"),
        },
    )
    # #endregion
    return games_played


def sim_day(season, lookup, rng=None, user_team_id=None):
    day = season.get("current_day", 1)
    count = simulate_games(season, lookup, rng=rng, through_day=day, user_team_id=user_team_id)
    season["current_day"] = day + 1
    if regular_season_complete(season):
        season["phase"] = "regular_complete"
    return count


def sim_week(season, lookup, rng=None, user_team_id=None):
    start_day = season.get("current_day", 1)
    count = simulate_games(season, lookup, rng=rng, count_days=7, user_team_id=user_team_id)
    season["current_day"] = start_day + 7
    if regular_season_complete(season):
        season["phase"] = "regular_complete"
    return count


def sim_to_trade_deadline(season, lookup, rng=None, user_team_id=None):
    rng = rng or random.Random()
    user_team_id = user_team_id or season.get("user_team_id")
    target = season.get("trade_deadline_games", TRADE_DEADLINE_GAMES)
    games_played = 0

    while not all_teams_at_gp(season, target):
        day = season.get("current_day", 1)
        day_games = [
            game
            for game in season["schedule"]
            if not game["played"] and game["day"] == day
        ]
        if not day_games:
            if day > season.get("max_day", day):
                break
            season["current_day"] = day + 1
            continue

        for game in day_games:
            if all_teams_at_gp(season, target):
                break
            _play_game(season, game, lookup, rng, user_team_id=user_team_id)
            games_played += 1

        season["current_day"] = day + 1

    return games_played


def team_ovr_for_tiebreak(season, team_id, lookup):
    roster = roster_players(season, team_id, lookup)
    team_gp = season.get("standings", {}).get(str(team_id), {}).get("gp")
    return compute_team_overall(roster, team_gp=team_gp) or 0


def seed_playoffs(season, lookup):
    if not regular_season_complete(season):
        sim_rest_of_season(season, lookup)

    rounds = []
    quarterfinal_series = []

    for conference in ("East", "West"):
        rows = standings_table(season, conference=conference)[:8]
        matchups = [(0, 7), (3, 4), (1, 6), (2, 5)]
        for high_index, low_index in matchups:
            high = rows[high_index]
            low = rows[low_index]
            quarterfinal_series.append(_new_series(conference, high, low))

    rounds.append({"name": "Conference Quarterfinals", "series": quarterfinal_series})
    rounds.append({"name": "Conference Semifinals", "series": []})
    rounds.append({"name": "Conference Finals", "series": []})
    rounds.append({"name": "NBA Finals", "series": []})

    season["phase"] = "playoffs"
    season["playoffs"] = {
        "round_index": 0,
        "rounds": rounds,
        "champion_id": None,
        "champion_name": None,
    }
    return season["playoffs"]


def _new_series(conference, high_seed, low_seed):
    return {
        "conference": conference,
        "high_seed_id": high_seed["team_id"],
        "high_seed_name": high_seed["team_name"],
        "low_seed_id": low_seed["team_id"],
        "low_seed_name": low_seed["team_name"],
        "high_wins": 0,
        "low_wins": 0,
        "winner_id": None,
        "winner_name": None,
        "complete": False,
    }


def _series_label(series):
    high = series["high_seed_name"]
    low = series["low_seed_name"]
    return f"{high} {series['high_wins']} – {series['low_wins']} {low}"


def _simulate_series(series, season, lookup, rng):
    while series["high_wins"] < PLAYOFF_WINS_NEEDED and series["low_wins"] < PLAYOFF_WINS_NEEDED:
        home_roster = roster_players(season, series["high_seed_id"], lookup)
        away_roster = roster_players(season, series["low_seed_id"], lookup)
        home_score, away_score = simulate_game(home_roster, away_roster, rng)
        if home_score > away_score:
            series["high_wins"] += 1
        else:
            series["low_wins"] += 1

    if series["high_wins"] > series["low_wins"]:
        series["winner_id"] = series["high_seed_id"]
        series["winner_name"] = series["high_seed_name"]
    else:
        series["winner_id"] = series["low_seed_id"]
        series["winner_name"] = series["low_seed_name"]
    series["complete"] = True


def _build_next_round_series(winners, conference=None):
    series_list = []
    if conference:
        conf_winners = [team for team in winners if TEAM_CONFERENCES.get(team["team_id"]) == conference]
        for index in range(0, len(conf_winners), 2):
            if index + 1 >= len(conf_winners):
                break
            high = conf_winners[index]
            low = conf_winners[index + 1]
            series_list.append(_new_series(conference, high, low))
        return series_list

    if len(winners) >= 2:
        east = winners[0]
        west = winners[1]
        return [
            {
                "conference": "Finals",
                "high_seed_id": east["team_id"],
                "high_seed_name": east["team_name"],
                "low_seed_id": west["team_id"],
                "low_seed_name": west["team_name"],
                "high_wins": 0,
                "low_wins": 0,
                "winner_id": None,
                "winner_name": None,
                "complete": False,
            }
        ]
    return []


def _winner_row(series):
    return {
        "team_id": series["winner_id"],
        "team_name": series["winner_name"],
    }


def advance_playoff_round(season, lookup, rng=None):
    rng = rng or random.Random()
    playoffs = season.get("playoffs")
    if not playoffs:
        return 0

    round_index = playoffs.get("round_index", 0)
    rounds = playoffs.get("rounds", [])
    if round_index >= len(rounds):
        return 0

    current_round = rounds[round_index]
    series_played = 0
    for series in current_round["series"]:
        if series["complete"]:
            continue
        _simulate_series(series, season, lookup, rng)
        series_played += 1

    if not all(series["complete"] for series in current_round["series"]):
        return series_played

    winners = [_winner_row(series) for series in current_round["series"]]
    next_index = round_index + 1
    if next_index >= len(rounds):
        if winners:
            playoffs["champion_id"] = winners[0]["team_id"]
            playoffs["champion_name"] = winners[0]["team_name"]
            season["phase"] = "complete"
        return series_played

    if next_index == 1:
        rounds[next_index]["series"] = _build_next_round_series(winners, "East") + _build_next_round_series(
            winners, "West"
        )
    elif next_index == 2:
        rounds[next_index]["series"] = _build_next_round_series(winners, "East") + _build_next_round_series(
            winners, "West"
        )
    elif next_index == 3:
        east_winner = next(
            winner for winner in winners if TEAM_CONFERENCES.get(winner["team_id"]) == "East"
        )
        west_winner = next(
            winner for winner in winners if TEAM_CONFERENCES.get(winner["team_id"]) == "West"
        )
        rounds[next_index]["series"] = _build_next_round_series([east_winner, west_winner])

    playoffs["round_index"] = next_index
    return series_played


def simulate_all_playoffs(season, lookup, rng=None):
    rng = rng or random.Random()
    total = 0
    while season.get("phase") == "playoffs":
        played = advance_playoff_round(season, lookup, rng)
        total += played
        if played == 0:
            break
    return total


def schedule_games(season, day=None, team_id=None, played=None):
    games = list(season.get("schedule", []))
    if day is not None:
        games = [game for game in games if game["day"] == day]
    if team_id is not None:
        games = [
            game
            for game in games
            if game["home_id"] == team_id or game["away_id"] == team_id
        ]
    if played is not None:
        games = [game for game in games if game["played"] == played]
    return games


def games_played_count(season):
    return sum(1 for game in season.get("schedule", []) if game["played"])

def enrich_game_for_display(game, season):
    return {
        **game,
        "home_name": team_name(season, game["home_id"]),
        "away_name": team_name(season, game["away_id"]),
    }


def find_schedule_game(season, game_id):
    for game in season.get("schedule", []):
        if game.get("id") == game_id:
            return game
    return None
