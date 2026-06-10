import os

from dotenv import load_dotenv
from flask import Flask, redirect, render_template, request, url_for

import cache
from fetcher import refresh_cache
from scheduler import start_scheduler

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev")

SORT_COLUMNS = {"name", "team", "ppg", "rpg", "apg"}


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

    if sort_key not in SORT_COLUMNS:
        sort_key = "name"
    if order not in {"asc", "desc"}:
        order = "asc"

    cache_data = cache.load_cache()
    players = list(cache_data.get("players", []))

    if query:
        needle = query.lower()
        players = [
            player
            for player in players
            if needle in player.get("name", "").lower()
        ]

    players = _sort_players(players, sort_key, order)

    return render_template(
        "search.html",
        page_title="Search",
        players=players,
        q=query,
        sort=sort_key,
        order=order,
        last_updated=cache_data.get("last_updated"),
        refreshed=request.args.get("refreshed") == "1",
        next_order=_next_order,
    )


@app.route("/refresh")
def refresh():
    refresh_cache()
    return redirect(url_for("search", refreshed=1))


if os.getenv("ENABLE_SCHEDULER", "true").lower() == "true":
    start_scheduler(app)


if __name__ == "__main__":
    app.run(debug=True)
