import os

from dotenv import load_dotenv
from flask import Flask, redirect, render_template, request, url_for

import cache
from fetcher import refresh_cache
from scheduler import start_scheduler

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev")

SORT_COLUMNS = {"name", "team", "ppg", "rpg", "apg", "spg", "bpg"}
STAT_COLUMNS = ("ppg", "rpg", "apg", "spg", "bpg")
STAT_LABELS = {
    "ppg": "PPG",
    "rpg": "RPG",
    "apg": "APG",
    "spg": "SPG",
    "bpg": "BPG",
}


def _compute_stat_ranks(players):
    ranks_by_id = {player["id"]: {} for player in players}

    for stat in STAT_COLUMNS:
        ranked = [player for player in players if player.get(stat) is not None]
        ranked.sort(key=lambda player: player[stat], reverse=True)

        rank = 0
        prev_value = object()
        for index, player in enumerate(ranked):
            value = player[stat]
            if value != prev_value:
                rank = index + 1
                prev_value = value
            ranks_by_id[player["id"]][stat] = rank

    return ranks_by_id


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


def _next_order(column, current_sort, current_order):
    if column == current_sort:
        return "desc" if current_order == "asc" else "asc"
    return "asc"


@app.route("/")
def index():
    return render_template(
        "index.html",
        page_title="Dashboard",
        content="Dashboard — coming soon",
    )


@app.route("/team")
def team():
    return render_template(
        "index.html",
        page_title="My Team",
        content="My Team — coming soon",
    )


@app.route("/trade")
def trade():
    return render_template(
        "index.html",
        page_title="Trade Engine",
        content="Trade Engine — coming soon",
    )


@app.route("/search")
def search():
    query = request.args.get("q", "").strip()
    sort_key = request.args.get("sort", "name")
    order = request.args.get("order", "asc")
    selected_raw = request.args.get("selected", "").strip()

    if sort_key not in SORT_COLUMNS:
        sort_key = "name"
    if order not in {"asc", "desc"}:
        order = "asc"

    cache_data = cache.load_cache()
    all_players = list(cache_data.get("players", []))
    stat_ranks = _compute_stat_ranks(all_players)
    players_by_id = {player["id"]: player for player in all_players}

    selected_id = None
    if selected_raw.isdigit():
        candidate_id = int(selected_raw)
        if candidate_id in players_by_id:
            selected_id = candidate_id

    selected_player = players_by_id.get(selected_id) if selected_id is not None else None
    selected_ranks = stat_ranks.get(selected_id, {}) if selected_id is not None else {}

    players = list(all_players)
    if query:
        needle = query.lower()
        players = [
            player
            for player in players
            if needle in player.get("name", "").lower()
        ]

    players = _sort_players(players, sort_key, order)
    for player in players:
        player["ranks"] = stat_ranks.get(player["id"], {})

    def make_search_url(**overrides):
        params = {"q": query, "sort": sort_key, "order": order}
        active_selected = selected_id
        if "selected" in overrides:
            active_selected = overrides.pop("selected")
        if active_selected is not None:
            params["selected"] = active_selected
        params.update(overrides)
        return url_for("search", **params)

    return render_template(
        "search.html",
        page_title="Search",
        players=players,
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
