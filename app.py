import os

from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, url_for

import cache
from fetcher import refresh_cache
from game import (
    clear_game,
    get_game,
    load_session_season,
    require_game,
    save_session_season,
    set_season_id,
    start_game,
)
import season_store
from season import (
    advance_playoff_round,
    enrich_game_for_display,
    games_played_count,
    init_season,
    regular_season_complete,
    schedule_games,
    seed_playoffs,
    sim_day,
    sim_rest_of_season,
    sim_to_trade_deadline,
    sim_week,
    simulate_all_playoffs,
    standings_table,
)
from ratings import (
    STAT_COLUMNS,
    STAT_LABELS,
    apply_ratings,
    build_team_summaries,
    compute_stat_ranks,
    compute_team_overall,
    compute_team_ranks,
    needs_ratings,
)
from scheduler import start_scheduler

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev")

SORT_COLUMNS = {"name", "team", "overall", "ppg", "rpg", "apg", "spg", "bpg"}
ROSTER_SORT_COLUMNS = {"name", "overall", "age", "gp", "ppg", "rpg", "apg", "spg", "bpg"}
TEAM_SORT_COLUMNS = {"team", "overall", "roster_size"}
VIEW_MODES = {"players", "teams", "roster"}


def _sort_players(players, sort_key, order):
    reverse = order == "desc"

    if sort_key == "name":
        return sorted(
            players,
            key=lambda player: player.get("name", "").lower(),
            reverse=reverse,
        )

    if sort_key == "team":
        return sorted(
            players,
            key=lambda player: player.get("team", "").lower(),
            reverse=reverse,
        )

    return sorted(
        players,
        key=lambda player: player.get(sort_key) or 0,
        reverse=reverse,
    )


def _sort_teams(teams, sort_key, order):
    reverse = order == "desc"

    if sort_key == "team":
        return sorted(
            teams,
            key=lambda team: team.get("team", "").lower(),
            reverse=reverse,
        )

    return sorted(
        teams,
        key=lambda team: team.get(sort_key) or 0,
        reverse=reverse,
    )


def _next_order(column, current_sort, current_order):
    if column == current_sort:
        return "desc" if current_order == "asc" else "asc"
    return "asc"


def _parse_sort_order(default_sort, default_order, allowed_columns):
    sort_key = request.args.get("sort", default_sort)
    order = request.args.get("order", default_order)

    if sort_key not in allowed_columns:
        sort_key = default_sort
    if order not in {"asc", "desc"}:
        order = default_order

    return sort_key, order


def _load_players():
    cache_data = cache.load_cache()
    all_players = list(cache_data.get("players", []))

    if needs_ratings(all_players):
        apply_ratings(all_players)

    return cache_data, all_players


def _team_context(all_players, team_id):
    roster = [player for player in all_players if player.get("team_id") == team_id]
    team_summaries = build_team_summaries(all_players)
    team_ranks = compute_team_ranks(team_summaries)
    team_name = roster[0].get("team") if roster else "Unknown Team"

    return {
        "roster": roster,
        "team_name": team_name,
        "team_overall": compute_team_overall(roster),
        "team_rank": team_ranks.get(team_id, {}).get("overall"),
    }


def _attach_roster_ranks(roster, stat_ranks):
    for player in roster:
        player["ranks"] = stat_ranks.get(player["id"], {})
    return roster


def _known_team_ids(all_players):
    return {
        player["team_id"]
        for player in all_players
        if player.get("team_id")
    }


@app.context_processor
def inject_game():
    return {"game": get_game()}


@app.route("/")
def index():
    game = get_game()
    if game is None:
        return render_template("landing.html", page_title="NBA Manager")

    cache_data, all_players = _load_players()
    team_info = _team_context(all_players, game["team_id"])
    roster = _sort_players(team_info["roster"], "overall", "desc")
    top_players = roster[:3]

    return render_template(
        "dashboard.html",
        page_title="Dashboard",
        team_name=game["team_name"],
        team_overall=team_info["team_overall"],
        team_rank=team_info["team_rank"],
        roster_size=len(roster),
        top_players=top_players,
        last_updated=cache_data.get("last_updated"),
    )


@app.route("/start", methods=["POST"])
def start():
    team = start_game()
    flash(f"You are the GM of the {team['full_name']}!")
    return redirect(url_for("team"))


@app.route("/new-game", methods=["POST"])
def new_game():
    clear_game()
    return redirect(url_for("index"))


@app.route("/team")
def team():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    game = get_game()
    sort_key, order = _parse_sort_order("overall", "desc", ROSTER_SORT_COLUMNS)
    cache_data, all_players = _load_players()
    team_info = _team_context(all_players, game["team_id"])
    stat_ranks = compute_stat_ranks(all_players)
    roster = _sort_players(team_info["roster"], sort_key, order)
    _attach_roster_ranks(roster, stat_ranks)

    def make_team_url(**overrides):
        params = {"sort": sort_key, "order": order}
        params.update(overrides)
        return url_for("team", **params)

    return render_template(
        "team.html",
        page_title="My Team",
        team_name=game["team_name"],
        team_overall=team_info["team_overall"],
        team_rank=team_info["team_rank"],
        roster=roster,
        sort=sort_key,
        order=order,
        next_order=_next_order,
        make_team_url=make_team_url,
        stat_columns=STAT_COLUMNS,
        stat_labels=STAT_LABELS,
        last_updated=cache_data.get("last_updated"),
    )


@app.route("/trade")
def trade():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    return render_template(
        "index.html",
        page_title="Trade Engine",
        content="Trade Engine — coming soon",
    )


@app.route("/search")
def search():
    query = request.args.get("q", "").strip()
    view = request.args.get("view", "players")
    selected_raw = request.args.get("selected", "").strip()
    team_id_raw = request.args.get("team_id", "").strip()

    if view not in VIEW_MODES:
        view = "players"

    cache_data, all_players = _load_players()
    game = get_game()
    known_team_ids = _known_team_ids(all_players)

    roster_team_id = None
    if team_id_raw.isdigit():
        candidate_team_id = int(team_id_raw)
        if candidate_team_id in known_team_ids:
            roster_team_id = candidate_team_id

    if view == "roster":
        if roster_team_id is None:
            return redirect(url_for("search", view="teams", q=query))
        sort_key, order = _parse_sort_order("overall", "desc", ROSTER_SORT_COLUMNS)
    elif view == "teams":
        sort_key, order = _parse_sort_order("team", "asc", TEAM_SORT_COLUMNS)
    else:
        sort_key, order = _parse_sort_order("name", "asc", SORT_COLUMNS)

    stat_ranks = compute_stat_ranks(all_players)
    players_by_id = {player["id"]: player for player in all_players}

    selected_id = None
    if selected_raw.isdigit():
        candidate_id = int(selected_raw)
        if candidate_id in players_by_id:
            selected_id = candidate_id

    selected_player = players_by_id.get(selected_id) if selected_id is not None else None
    selected_ranks = stat_ranks.get(selected_id, {}) if selected_id is not None else {}

    def make_search_url(**overrides):
        params = {
            "q": query,
            "sort": sort_key,
            "order": order,
            "view": view,
        }
        active_view = overrides.get("view", view)
        active_team_id = overrides.get("team_id", roster_team_id)
        active_selected = selected_id

        if "selected" in overrides:
            active_selected = overrides.pop("selected")

        if active_team_id is not None and active_view == "roster":
            params["team_id"] = active_team_id
        if active_selected is not None and active_view == "players":
            params["selected"] = active_selected

        params.update(overrides)
        return url_for("search", **params)

    if view == "roster":
        team_info = _team_context(all_players, roster_team_id)
        roster = _sort_players(team_info["roster"], sort_key, order)
        _attach_roster_ranks(roster, stat_ranks)

        return render_template(
            "search.html",
            page_title="Search",
            view=view,
            teams=[],
            players=[],
            roster=roster,
            roster_team_id=roster_team_id,
            roster_team_name=team_info["team_name"],
            roster_team_overall=team_info["team_overall"],
            roster_team_rank=team_info["team_rank"],
            is_user_team=game is not None and roster_team_id == game["team_id"],
            q=query,
            sort=sort_key,
            order=order,
            selected_id=None,
            selected_player=None,
            selected_ranks={},
            stat_columns=STAT_COLUMNS,
            stat_labels=STAT_LABELS,
            last_updated=cache_data.get("last_updated"),
            refreshed=request.args.get("refreshed") == "1",
            stale=request.args.get("stale") == "1",
            next_order=_next_order,
            make_search_url=make_search_url,
            user_team_id=game["team_id"] if game else None,
        )

    if view == "teams":
        teams = build_team_summaries(all_players)
        team_ranks = compute_team_ranks(teams)

        if query:
            needle = query.lower()
            teams = [
                team_summary
                for team_summary in teams
                if needle in team_summary.get("team", "").lower()
            ]

        teams = _sort_teams(teams, sort_key, order)
        for team_summary in teams:
            team_summary["ranks"] = team_ranks.get(team_summary["team_id"], {})

        return render_template(
            "search.html",
            page_title="Search",
            view=view,
            teams=teams,
            players=[],
            roster=[],
            roster_team_id=None,
            roster_team_name=None,
            roster_team_overall=None,
            roster_team_rank=None,
            is_user_team=False,
            q=query,
            sort=sort_key,
            order=order,
            selected_id=None,
            selected_player=None,
            selected_ranks={},
            stat_columns=STAT_COLUMNS,
            stat_labels=STAT_LABELS,
            last_updated=cache_data.get("last_updated"),
            refreshed=request.args.get("refreshed") == "1",
            stale=request.args.get("stale") == "1",
            next_order=_next_order,
            make_search_url=make_search_url,
            user_team_id=game["team_id"] if game else None,
        )

    players = list(all_players)
    if query:
        needle = query.lower()
        players = [
            player
            for player in players
            if needle in player.get("name", "").lower()
        ]

    players = _sort_players(players, sort_key, order)
    _attach_roster_ranks(players, stat_ranks)

    return render_template(
        "search.html",
        page_title="Search",
        view=view,
        teams=[],
        players=players,
        roster=[],
        roster_team_id=None,
        roster_team_name=None,
        roster_team_overall=None,
        roster_team_rank=None,
        is_user_team=False,
        q=query,
        sort=sort_key,
        order=order,
        selected_id=selected_id,
        selected_player=selected_player,
        selected_ranks=selected_ranks,
        stat_columns=STAT_COLUMNS,
        stat_labels=STAT_LABELS,
        last_updated=cache_data.get("last_updated"),
        refreshed=request.args.get("refreshed") == "1",
        stale=request.args.get("stale") == "1",
        next_order=_next_order,
        make_search_url=make_search_url,
        user_team_id=game["team_id"] if game else None,
    )


def _season_context():
    cache_data, all_players = _load_players()
    lookup = {player["id"]: player for player in all_players}
    season_id, season_data = load_session_season()
    return cache_data, all_players, lookup, season_id, season_data


def _save_season(season_id, season_data):
    save_session_season(season_id, season_data)


def _render_season(season_id, season_data, lookup, game, page="hub", schedule_day=None):
    east_standings = standings_table(season_data, conference="East") if season_data else []
    west_standings = standings_table(season_data, conference="West") if season_data else []
    schedule = []
    if season_data and page == "schedule":
        day_filter = schedule_day
        if day_filter is None:
            day_filter = season_data.get("current_day", 1)
        schedule = [
            enrich_game_for_display(game, season_data)
            for game in schedule_games(season_data, day=day_filter)
        ]

    return render_template(
        "season.html",
        page_title="Season",
        page=page,
        season=season_data,
        season_id=season_id,
        east_standings=east_standings,
        west_standings=west_standings,
        user_team_id=game["team_id"],
        schedule=schedule,
        schedule_day=schedule_day or (season_data.get("current_day", 1) if season_data else 1),
        games_played=games_played_count(season_data) if season_data else 0,
        regular_complete=regular_season_complete(season_data) if season_data else False,
    )


@app.route("/season")
def season_hub():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    game = get_game()
    _, _, lookup, season_id, season_data = _season_context()
    return _render_season(season_id, season_data, lookup, game, page="hub")


@app.route("/season/start", methods=["POST"])
def season_start():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    cache_data, all_players, lookup, season_id, season_data = _season_context()
    if season_data is not None:
        flash("Season already in progress.")
        return redirect(url_for("season_hub"))

    season_id = season_store.create_season_id()
    season_data = init_season(all_players, season_year=cache_data.get("season") or 2026)
    set_season_id(season_id)
    _save_season(season_id, season_data)
    flash("Season started.")
    return redirect(url_for("season_hub"))


@app.route("/season/sim/season", methods=["POST"])
def season_sim_full():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    _, all_players, lookup, season_id, season_data = _season_context()
    if season_data is None:
        flash("Start a season first.")
        return redirect(url_for("season_hub"))

    count = sim_rest_of_season(season_data, lookup)
    _save_season(season_id, season_data)
    flash(f"Simulated {count} games. Regular season complete.")
    return redirect(url_for("season_hub"))


@app.route("/season/schedule")
def season_schedule():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    game = get_game()
    _, _, lookup, season_id, season_data = _season_context()
    if season_data is None:
        flash("Start a season first.")
        return redirect(url_for("season_hub"))

    day_raw = request.args.get("day", "").strip()
    schedule_day = season_data.get("current_day", 1)
    if day_raw.isdigit():
        schedule_day = int(day_raw)

    return _render_season(
        season_id,
        season_data,
        lookup,
        game,
        page="schedule",
        schedule_day=schedule_day,
    )


@app.route("/season/sim/day", methods=["POST"])
def season_sim_day():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    _, _, lookup, season_id, season_data = _season_context()
    if season_data is None:
        flash("Start a season first.")
        return redirect(url_for("season_hub"))

    count = sim_day(season_data, lookup)
    _save_season(season_id, season_data)
    flash(f"Simulated day {season_data.get('current_day', 1) - 1}: {count} games.")
    return redirect(url_for("season_hub"))


@app.route("/season/sim/week", methods=["POST"])
def season_sim_week():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    _, _, lookup, season_id, season_data = _season_context()
    if season_data is None:
        flash("Start a season first.")
        return redirect(url_for("season_hub"))

    count = sim_week(season_data, lookup)
    _save_season(season_id, season_data)
    flash(f"Simulated one week: {count} games.")
    return redirect(url_for("season_hub"))


@app.route("/season/sim/trade-deadline", methods=["POST"])
def season_sim_trade_deadline():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    _, _, lookup, season_id, season_data = _season_context()
    if season_data is None:
        flash("Start a season first.")
        return redirect(url_for("season_hub"))

    count = sim_to_trade_deadline(season_data, lookup)
    _save_season(season_id, season_data)
    flash(f"Simulated to trade deadline (~55 GP): {count} games.")
    return redirect(url_for("season_hub"))


@app.route("/season/playoffs", methods=["GET", "POST"])
def season_playoffs():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    game = get_game()
    _, _, lookup, season_id, season_data = _season_context()
    if season_data is None:
        flash("Start a season first.")
        return redirect(url_for("season_hub"))

    if request.method == "POST" and season_data.get("playoffs") is None:
        if not regular_season_complete(season_data):
            sim_rest_of_season(season_data, lookup)
        seed_playoffs(season_data, lookup)
        _save_season(season_id, season_data)
        flash("Playoffs seeded.")
        return redirect(url_for("season_playoffs"))

    east_standings = standings_table(season_data, conference="East")
    west_standings = standings_table(season_data, conference="West")
    return render_template(
        "season.html",
        page_title="Playoffs",
        page="playoffs",
        season=season_data,
        season_id=season_id,
        east_standings=east_standings,
        west_standings=west_standings,
        user_team_id=game["team_id"],
        schedule=[],
        schedule_day=season_data.get("current_day", 1),
        games_played=games_played_count(season_data),
        regular_complete=regular_season_complete(season_data),
    )


@app.route("/season/sim/playoffs", methods=["POST"])
def season_sim_playoffs():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    sim_mode = request.form.get("mode", "round")
    _, _, lookup, season_id, season_data = _season_context()
    if season_data is None or season_data.get("playoffs") is None:
        flash("Start playoffs first.")
        return redirect(url_for("season_playoffs"))

    if sim_mode == "all":
        count = simulate_all_playoffs(season_data, lookup)
        message = "Playoffs complete."
        if season_data.get("playoffs", {}).get("champion_name"):
            message = f"Champion: {season_data['playoffs']['champion_name']}"
        flash(message)
    else:
        count = advance_playoff_round(season_data, lookup)
        flash(f"Simulated playoff round: {count} series finished.")

    _save_season(season_id, season_data)
    return redirect(url_for("season_playoffs"))


@app.route("/refresh")
def refresh():
    try:
        success = refresh_cache()
    except Exception:
        return redirect(url_for("search", stale=1))

    if success:
        return redirect(url_for("search", refreshed=1))
    return redirect(url_for("search", stale=1))


if os.getenv("ENABLE_SCHEDULER", "true").lower() == "true":
    start_scheduler(app)


if __name__ == "__main__":
    app.run(debug=True)
