"""Localhost-only admin panel for custom players and season editing."""

import os
import random

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from attributes import (
    ATTRIBUTE_KEYS,
    POTENTIAL_MAX,
    POTENTIAL_MIN,
    _assign_peak_attributes,
    ensure_positions,
    init_rookie_career_profile,
    refresh_player_from_attributes,
)
from contracts import assign_player_contract, refresh_all_team_finances
from draft import generate_rookie_profile
from game import get_game, load_session_season, save_session_season
from names import ensure_unique_name
from ratings import compute_intrinsic_overall
from season import allocate_player_id, league_lookup, refresh_all_roster_stats, roster_players, team_name

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

LOCAL_HOSTS = {"127.0.0.1", "::1"}


def admin_enabled():
    return os.getenv("ADMIN_ENABLED", "").lower() in {"1", "true", "yes"}


def _admin_allowed():
    if not admin_enabled():
        return False
    if request.remote_addr not in LOCAL_HOSTS:
        return False
    token = os.getenv("ADMIN_TOKEN", "")
    if token and request.args.get("token") != token and request.form.get("token") != token:
        if request.cookies.get("admin_token") != token:
            return False
    return True


@admin_bp.before_request
def guard_admin():
    if not _admin_allowed():
        abort(404)


def _season_or_redirect():
    season_id, season_data = load_session_season()
    if season_data is None:
        return None, None, None, redirect(url_for("season_hub"))
    lookup = league_lookup(season_data)
    return season_id, season_data, lookup, None


def _existing_names(season_data, exclude_player_id=None):
    names = set()
    for key, other in season_data.get("players", {}).items():
        if exclude_player_id is not None and int(other.get("id", key)) == int(exclude_player_id):
            continue
        if other.get("name"):
            names.add(other["name"])
    return names


def _parse_float(raw):
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


@admin_bp.route("/")
def admin_index():
    game = get_game()
    season_id, season_data = load_session_season()
    return render_template(
        "admin/index.html",
        page_title="Admin",
        game=game,
        season=season_data,
        season_id=season_id,
    )


@admin_bp.route("/players")
def admin_players():
    season_id, season_data, lookup, redirect_response = _season_or_redirect()
    if redirect_response is not None:
        return redirect_response
    query = request.args.get("q", "").strip().lower()
    players = list(season_data.get("players", {}).values())
    if query:
        players = [player for player in players if query in (player.get("name") or "").lower()]
    players.sort(key=lambda player: player.get("overall") or 0, reverse=True)
    return render_template(
        "admin/players.html",
        page_title="Admin Players",
        season=season_data,
        players=players[:100],
        query=query,
    )


@admin_bp.route("/players/<int:player_id>/edit", methods=["GET", "POST"])
def admin_edit_player(player_id):
    season_id, season_data, lookup, redirect_response = _season_or_redirect()
    if redirect_response is not None:
        return redirect_response
    player = lookup.get(player_id)
    if not player:
        flash("Player not found.")
        return redirect(url_for("admin.admin_players"))

    if request.method == "POST":
        raw_name = request.form.get("name", player.get("name", "")).strip()
        player["name"] = ensure_unique_name(raw_name, _existing_names(season_data, exclude_player_id=player_id))

        if request.form.get("age", "").isdigit():
            player["age"] = int(request.form["age"])

        positions_raw = request.form.get("positions", "")
        if positions_raw:
            player["positions"] = [pos.strip() for pos in positions_raw.split("/") if pos.strip()]
            ensure_positions(player)

        potential_raw = request.form.get("potential", "").strip()
        if potential_raw.isdigit():
            player["potential"] = max(POTENTIAL_MIN, min(POTENTIAL_MAX, int(potential_raw)))
            player.pop("peak_attributes", None)
            _assign_peak_attributes(player, random.Random())

        if request.form.get("peak_age", "").isdigit():
            player["peak_age"] = int(request.form["peak_age"])
        if request.form.get("retirement_age", "").isdigit():
            retirement_age = int(request.form["retirement_age"])
            age = player.get("age") or 25
            if retirement_age <= age:
                flash("Retirement age must be greater than current age.")
                return redirect(url_for("admin.admin_edit_player", player_id=player_id))
            if player.get("peak_age") and retirement_age <= player["peak_age"]:
                flash("Retirement age must be greater than peak age.")
                return redirect(url_for("admin.admin_edit_player", player_id=player_id))
            player["retirement_age"] = retirement_age

        dev_raw = request.form.get("development_rate", "").strip()
        dev_val = _parse_float(dev_raw)
        if dev_val is not None:
            player["development_rate"] = round(max(0.5, min(2.0, dev_val)), 3)

        ppg_raw = request.form.get("ppg", "").strip()
        ppg_val = _parse_float(ppg_raw)
        manual_ppg = ppg_val is not None and ppg_raw != ""

        base = player.setdefault("base_attributes", player.get("attributes", {}))
        for key in ATTRIBUTE_KEYS:
            raw = request.form.get(f"attr_{key}", "").strip()
            if raw.isdigit():
                base[key] = int(raw)

        if manual_ppg:
            player["stats_source"] = "manual"
            player["ppg"] = round(ppg_val, 1)
            refresh_player_from_attributes(player)
            player["ppg"] = round(ppg_val, 1)
        else:
            if player.get("stats_source") == "manual":
                player["stats_source"] = "generated"
            refresh_player_from_attributes(player)

        player["overall"] = compute_intrinsic_overall(player)
        if player.get("team_id"):
            refresh_all_roster_stats(season_data, lookup)
        refresh_all_team_finances(season_data, lookup)
        save_session_season(season_id, season_data)
        flash(f"Updated {player['name']}.")
        return redirect(url_for("admin.admin_edit_player", player_id=player_id))

    years_to_peak = None
    if player.get("peak_age") is not None and player.get("age") is not None:
        years_to_peak = max(0, player["peak_age"] - player["age"])

    return render_template(
        "admin/edit_player.html",
        page_title=f"Edit {player.get('name', player_id)}",
        player=player,
        attribute_keys=ATTRIBUTE_KEYS,
        years_to_peak=years_to_peak,
    )


@admin_bp.route("/players/create", methods=["GET", "POST"])
def admin_create_player():
    season_id, season_data, lookup, redirect_response = _season_or_redirect()
    if redirect_response is not None:
        return redirect_response

    teams = [
        {"team_id": int(team_id), "team_name": record.get("team_name", team_id)}
        for team_id, record in season_data.get("standings", {}).items()
    ]
    teams.sort(key=lambda item: item["team_name"])

    if request.method == "POST":
        name = request.form.get("name", "").strip() or "Custom Player"
        name = ensure_unique_name(name, _existing_names(season_data))
        overall_raw = request.form.get("overall", "60").strip()
        overall = int(overall_raw) if overall_raw.isdigit() else 60
        destination = request.form.get("destination", "draft")
        team_id_raw = request.form.get("team_id", "").strip()

        profile = generate_rookie_profile(overall)
        player_id = allocate_player_id(season_data)
        player = {
            "id": player_id,
            "name": name,
            "team_id": None,
            "team": None,
            "overall": overall,
            "scout_grade": overall,
            "age": int(request.form.get("age", "20") or 20),
            "gp": 0,
            "is_rookie": True,
            "positions": profile["positions"],
            "stats_source": "generated",
        }
        for key in ATTRIBUTE_KEYS:
            raw = request.form.get(f"attr_{key}", "").strip()
            if raw.isdigit():
                profile["attributes"][key] = int(raw)
        init_rookie_career_profile(player, profile["attributes"], scout_grade=overall)

        potential_raw = request.form.get("potential", "").strip()
        if potential_raw.isdigit():
            player["potential"] = max(POTENTIAL_MIN, min(POTENTIAL_MAX, int(potential_raw)))
            player.pop("peak_attributes", None)
            _assign_peak_attributes(player, random.Random())
        if request.form.get("peak_age", "").isdigit():
            player["peak_age"] = int(request.form["peak_age"])
        if request.form.get("retirement_age", "").isdigit():
            player["retirement_age"] = int(request.form["retirement_age"])
        dev_val = _parse_float(request.form.get("development_rate", "").strip())
        if dev_val is not None:
            player["development_rate"] = round(max(0.5, min(2.0, dev_val)), 3)

        ppg_val = _parse_float(request.form.get("ppg", "").strip())
        if ppg_val is not None and request.form.get("ppg", "").strip():
            player["stats_source"] = "manual"
            player["ppg"] = round(ppg_val, 1)

        refresh_player_from_attributes(player)
        if player.get("stats_source") == "manual" and ppg_val is not None:
            player["ppg"] = round(ppg_val, 1)
        player["overall"] = compute_intrinsic_overall(player)
        season_data["players"][str(player_id)] = player

        if destination == "team" and team_id_raw.isdigit():
            team_id = int(team_id_raw)
            player["team_id"] = team_id
            player["team"] = team_name(season_data, team_id)
            roster = season_data["rosters"].setdefault(str(team_id), [])
            if player_id not in roster:
                roster.append(player_id)
            assign_player_contract(player)
            refresh_all_roster_stats(season_data, lookup)
            flash(f"Added {name} to {player['team']}.")
        else:
            state = season_data.get("draft_state")
            if state:
                state.setdefault("prospect_pool", []).append(player)
                flash(f"Added {name} to draft prospect pool.")
            else:
                player["asking_salary"] = player.get("asking_salary")
                flash(f"Created {name} as free agent (no draft active).")

        refresh_all_team_finances(season_data, lookup)
        save_session_season(season_id, season_data)
        return redirect(url_for("admin.admin_players"))

    return render_template(
        "admin/create_player.html",
        page_title="Create Player",
        teams=teams,
        attribute_keys=ATTRIBUTE_KEYS,
    )
