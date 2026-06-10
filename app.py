import os

from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, url_for

import cache
from fetcher import refresh_cache
from game import clear_game, get_game, require_game, start_game
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
