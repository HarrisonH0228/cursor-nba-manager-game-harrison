import random

from ratings import compute_team_overall
from simulation import simulate_game

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
    1610612750: "East",
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


def init_season(players, season_year=2026, rng=None):
    rng = rng or random.Random()

    team_players = {}
    team_names = {}
    for player in players:
        team_id = player.get("team_id")
        if not team_id:
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

    return {
        "season_year": season_year,
        "phase": "regular",
        "current_day": 1,
        "max_day": max(game["day"] for game in schedule) if schedule else 1,
        "trade_deadline_games": TRADE_DEADLINE_GAMES,
        "rosters": {str(team_id): roster for team_id, roster in team_players.items()},
        "standings": standings,
        "schedule": schedule,
        "playoffs": None,
        "recent_results": [],
    }


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
    home_needed = {team_id: EXTRA_HOME_GAMES for team_id in team_ids}
    away_needed = {team_id: EXTRA_HOME_GAMES for team_id in team_ids}
    extra_games = []

    for _ in range(len(team_ids) * EXTRA_HOME_GAMES):
        home_options = [team_id for team_id in team_ids if home_needed[team_id] > 0]
        if not home_options:
            break
        home_id = rng.choice(home_options)
        away_options = [
            team_id
            for team_id in team_ids
            if team_id != home_id and away_needed[team_id] > 0
        ]
        if not away_options:
            break
        away_id = rng.choice(away_options)
        extra_games.append({"home_id": home_id, "away_id": away_id})
        home_needed[home_id] -= 1
        away_needed[away_id] -= 1

    return extra_games


def assign_days(matchups, rng):
    rng.shuffle(matchups)
    games_per_day = 8
    for index, game in enumerate(matchups):
        game["day"] = (index // games_per_day) + 1
    return matchups


def players_by_id(players):
    return {player["id"]: player for player in players}


def roster_players(season, team_id, lookup):
    roster_ids = season.get("rosters", {}).get(str(team_id), [])
    return [lookup[player_id] for player_id in roster_ids if player_id in lookup]


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


def _record_result(season, game, home_score, away_score):
    home_id = game["home_id"]
    away_id = game["away_id"]
    game["home_score"] = home_score
    game["away_score"] = away_score
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

    season["recent_results"].insert(
        0,
        {
            "day": game["day"],
            "home_id": home_id,
            "away_id": away_id,
            "home_name": home_record["team_name"],
            "away_name": away_record["team_name"],
            "home_score": home_score,
            "away_score": away_score,
        },
    )
    season["recent_results"] = season["recent_results"][:20]


def _play_game(season, game, lookup, rng):
    home_roster = roster_players(season, game["home_id"], lookup)
    away_roster = roster_players(season, game["away_id"], lookup)
    home_score, away_score = simulate_game(home_roster, away_roster, rng)
    _record_result(season, game, home_score, away_score)
    return game


def simulate_games(season, lookup, rng=None, through_day=None, count_days=None, through_team_gp=None):
    rng = rng or random.Random()
    games_played = 0
    start_day = season.get("current_day", 1)

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
            _play_game(season, game, lookup, rng)
            games_played += 1

    return games_played


def sim_rest_of_season(season, lookup, rng=None):
    rng = rng or random.Random()
    games_played = 0
    for game in season["schedule"]:
        if game["played"]:
            continue
        _play_game(season, game, lookup, rng)
        games_played += 1
    season["current_day"] = season.get("max_day", 1) + 1
    if regular_season_complete(season):
        season["phase"] = "regular_complete"
    return games_played


def sim_day(season, lookup, rng=None):
    day = season.get("current_day", 1)
    count = simulate_games(season, lookup, rng=rng, through_day=day)
    season["current_day"] = day + 1
    if regular_season_complete(season):
        season["phase"] = "regular_complete"
    return count


def sim_week(season, lookup, rng=None):
    start_day = season.get("current_day", 1)
    count = simulate_games(season, lookup, rng=rng, count_days=7)
    season["current_day"] = start_day + 7
    if regular_season_complete(season):
        season["phase"] = "regular_complete"
    return count


def sim_to_trade_deadline(season, lookup, rng=None):
    rng = rng or random.Random()
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
            _play_game(season, game, lookup, rng)
            games_played += 1

        season["current_day"] = day + 1

    return games_played


def team_ovr_for_tiebreak(season, team_id, lookup):
    roster = roster_players(season, team_id, lookup)
    return compute_team_overall(roster) or 0


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
