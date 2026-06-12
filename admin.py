"""Localhost-only admin panel for custom players and season editing."""

import os
import random

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from attributes import (
    ATTRIBUTE_KEYS,
    MAX_ATTR,
    MIN_ATTR,
    POTENTIAL_MAX,
    POTENTIAL_MIN,
    _assign_peak_attributes,
    ensure_positions,
    init_rookie_career_profile,
    refresh_player_from_attributes,
)
from contracts import (
    MIN_SALARY_M,
    apply_roster_salary_multiplier,
    assign_player_contract,
    clear_team_salary_cap,
    ensure_contract_fields,
    get_salary_cap,
    refresh_all_team_finances,
    set_team_salary_cap,
    team_finances,
)
from draft import generate_rookie_profile
from game import get_game, load_session_season, save_session_season
from names import ensure_unique_name
from ratings import compute_intrinsic_overall
from roster import (
    assign_player_to_team,
    free_agent_players,
    reconcile_team_roster,
    release_player,
    roster_size,
    two_way_players,
)
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


def _parse_int(raw, default=None):
    if raw is None:
        return default
    text = str(raw).strip()
    if text == "":
        return default
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


AGE_MIN = 18
AGE_MAX = 45
OVERALL_MIN = 25
OVERALL_MAX = 99


def _validate_player_form(form, *, is_create=False, existing_player=None, valid_team_ids=None):
    errors = []
    parsed = {}

    age_raw = form.get("age", "").strip()
    if is_create or age_raw:
        age = _parse_int(age_raw, default=20 if is_create else None)
        if age is None:
            errors.append("Age must be a whole number.")
        elif not AGE_MIN <= age <= AGE_MAX:
            errors.append(f"Age must be between {AGE_MIN} and {AGE_MAX}.")
        else:
            parsed["age"] = age

    if is_create:
        overall_raw = form.get("overall", "60").strip()
        overall = _parse_int(overall_raw)
        if overall is None:
            errors.append("Overall must be a whole number.")
        elif not OVERALL_MIN <= overall <= OVERALL_MAX:
            errors.append(f"Overall must be between {OVERALL_MIN} and {OVERALL_MAX}.")
        else:
            parsed["overall"] = overall

    potential_raw = form.get("potential", "").strip()
    if potential_raw:
        potential = _parse_int(potential_raw)
        if potential is None:
            errors.append("Potential must be a whole number.")
        elif not POTENTIAL_MIN <= potential <= POTENTIAL_MAX:
            errors.append(f"Potential must be between {POTENTIAL_MIN} and {POTENTIAL_MAX}.")
        else:
            parsed["potential"] = potential

    peak_raw = form.get("peak_age", "").strip()
    if peak_raw:
        peak_age = _parse_int(peak_raw)
        if peak_age is None:
            errors.append("Peak age must be a whole number.")
        else:
            parsed["peak_age"] = peak_age

    retirement_raw = form.get("retirement_age", "").strip()
    if retirement_raw:
        retirement_age = _parse_int(retirement_raw)
        if retirement_age is None:
            errors.append("Retirement age must be a whole number.")
        else:
            parsed["retirement_age"] = retirement_age

    age_for_check = parsed.get("age")
    if age_for_check is None and existing_player is not None:
        age_for_check = existing_player.get("age") or 25
    peak_for_check = parsed.get("peak_age")
    if peak_for_check is None and existing_player is not None:
        peak_for_check = existing_player.get("peak_age")
    if "retirement_age" in parsed:
        if parsed["retirement_age"] <= age_for_check:
            errors.append("Retirement age must be greater than current age.")
        elif peak_for_check and parsed["retirement_age"] <= peak_for_check:
            errors.append("Retirement age must be greater than peak age.")

    dev_raw = form.get("development_rate", "").strip()
    if dev_raw:
        dev_val = _parse_float(dev_raw)
        if dev_val is None:
            errors.append("Development rate must be a number.")
        elif not 0.5 <= dev_val <= 2.0:
            errors.append("Development rate must be between 0.5 and 2.0.")
        else:
            parsed["development_rate"] = round(dev_val, 3)

    ppg_raw = form.get("ppg", "").strip()
    if ppg_raw:
        ppg_val = _parse_float(ppg_raw)
        if ppg_val is None:
            errors.append("PPG must be a number.")
        else:
            parsed["ppg"] = round(ppg_val, 1)
            parsed["manual_ppg"] = True

    salary_raw = form.get("salary", "").strip()
    if salary_raw:
        salary_val = _parse_float(salary_raw)
        if salary_val is None:
            errors.append("Salary must be a number.")
        elif salary_val < MIN_SALARY_M:
            errors.append(f"Salary must be at least ${MIN_SALARY_M}M.")
        else:
            parsed["salary"] = round(salary_val, 1)

    contract_years_raw = form.get("contract_years", "").strip()
    if contract_years_raw:
        contract_years = _parse_int(contract_years_raw)
        if contract_years is None:
            errors.append("Contract years must be a whole number.")
        elif not 0 <= contract_years <= 6:
            errors.append("Contract years must be between 0 and 6.")
        else:
            parsed["contract_years"] = contract_years

    parsed["attributes"] = {}
    for key in ATTRIBUTE_KEYS:
        raw = form.get(f"attr_{key}", "").strip()
        if raw:
            attr_val = _parse_int(raw)
            if attr_val is None:
                errors.append(f"{key.title()} must be a whole number.")
            else:
                parsed["attributes"][key] = max(MIN_ATTR, min(MAX_ATTR, attr_val))

    if is_create:
        parsed["destination"] = form.get("destination", "draft")
        team_id_raw = form.get("team_id", "").strip()
        if parsed["destination"] == "team":
            team_id = _parse_int(team_id_raw)
            if team_id is None or (valid_team_ids is not None and team_id not in valid_team_ids):
                errors.append("Select a valid team when assigning to a roster.")
            else:
                parsed["team_id"] = team_id
    elif valid_team_ids is not None:
        team_id_raw = form.get("team_id", "").strip()
        if team_id_raw == "":
            parsed["team_id"] = None
        else:
            team_id = _parse_int(team_id_raw)
            if team_id is None or team_id not in valid_team_ids:
                errors.append("Select a valid team or Free Agent.")
            else:
                parsed["team_id"] = team_id

    parsed["name"] = form.get("name", "").strip() or "Custom Player"
    return errors, parsed


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


def _admin_teams(season_data):
    teams = [
        {"team_id": int(team_id), "team_name": record.get("team_name", team_id)}
        for team_id, record in season_data.get("standings", {}).items()
    ]
    teams.sort(key=lambda item: item["team_name"])
    return teams


@admin_bp.route("/players/<int:player_id>/edit", methods=["GET", "POST"])
def admin_edit_player(player_id):
    season_id, season_data, lookup, redirect_response = _season_or_redirect()
    if redirect_response is not None:
        return redirect_response
    player = lookup.get(player_id)
    if not player:
        flash("Player not found.", "error")
        return redirect(url_for("admin.admin_players"))

    teams = _admin_teams(season_data)
    valid_team_ids = {team["team_id"] for team in teams}

    if request.method == "POST":
        errors, parsed = _validate_player_form(
            request.form,
            is_create=False,
            existing_player=player,
            valid_team_ids=valid_team_ids,
        )
        if errors:
            for message in errors:
                flash(message, "error")
            years_to_peak = None
            peak_age = parsed.get("peak_age", player.get("peak_age"))
            age = parsed.get("age", player.get("age"))
            if peak_age is not None and age is not None:
                years_to_peak = max(0, peak_age - age)
            return render_template(
                "admin/edit_player.html",
                page_title=f"Edit {player.get('name', player_id)}",
                player=player,
                teams=teams,
                attribute_keys=ATTRIBUTE_KEYS,
                years_to_peak=years_to_peak,
                form_data=request.form,
            )

        raw_name = parsed["name"]
        player["name"] = ensure_unique_name(raw_name, _existing_names(season_data, exclude_player_id=player_id))

        if "age" in parsed:
            player["age"] = parsed["age"]

        positions_raw = request.form.get("positions", "")
        if positions_raw:
            player["positions"] = [pos.strip() for pos in positions_raw.split("/") if pos.strip()]
            ensure_positions(player)

        if "potential" in parsed:
            player["potential"] = parsed["potential"]
            player.pop("peak_attributes", None)
            _assign_peak_attributes(player, random.Random())

        if "peak_age" in parsed:
            player["peak_age"] = parsed["peak_age"]
        if "retirement_age" in parsed:
            player["retirement_age"] = parsed["retirement_age"]

        if "development_rate" in parsed:
            player["development_rate"] = parsed["development_rate"]

        manual_ppg = parsed.get("manual_ppg", False)

        base = player.setdefault("base_attributes", player.get("attributes", {}))
        for key, value in parsed.get("attributes", {}).items():
            base[key] = value

        if manual_ppg:
            player["stats_source"] = "manual"
            player["ppg"] = parsed["ppg"]
            refresh_player_from_attributes(player)
            player["ppg"] = parsed["ppg"]
        else:
            if player.get("stats_source") == "manual" and request.form.get("ppg", "").strip() == "":
                player["stats_source"] = "generated"
            refresh_player_from_attributes(player)

        player["overall"] = compute_intrinsic_overall(player)

        if "salary" in parsed:
            player["salary"] = parsed["salary"]
            player["previous_salary"] = parsed["salary"]
        if "contract_years" in parsed:
            player["contract_years"] = parsed["contract_years"]

        if "team_id" in parsed:
            current_team = _parse_int(player.get("team_id"))
            new_team = parsed["team_id"]
            if current_team != new_team:
                ok, team_message = assign_player_to_team(
                    season_data, player_id, new_team, force=True
                )
                if not ok:
                    flash(team_message, "error")
                    err_years_to_peak = None
                    peak_age = parsed.get("peak_age", player.get("peak_age"))
                    age = parsed.get("age", player.get("age"))
                    if peak_age is not None and age is not None:
                        err_years_to_peak = max(0, peak_age - age)
                    return render_template(
                        "admin/edit_player.html",
                        page_title=f"Edit {player.get('name', player_id)}",
                        player=player,
                        teams=teams,
                        attribute_keys=ATTRIBUTE_KEYS,
                        years_to_peak=err_years_to_peak,
                        form_data=request.form,
                    )
                flash(team_message)

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
        teams=teams,
        attribute_keys=ATTRIBUTE_KEYS,
        years_to_peak=years_to_peak,
    )


@admin_bp.route("/players/create", methods=["GET", "POST"])
def admin_create_player():
    season_id, season_data, lookup, redirect_response = _season_or_redirect()
    if redirect_response is not None:
        return redirect_response

    teams = _admin_teams(season_data)

    if request.method == "POST":
        valid_team_ids = {team["team_id"] for team in teams}
        errors, parsed = _validate_player_form(
            request.form,
            is_create=True,
            valid_team_ids=valid_team_ids,
        )
        if errors:
            for message in errors:
                flash(message, "error")
            return render_template(
                "admin/create_player.html",
                page_title="Create Player",
                teams=teams,
                attribute_keys=ATTRIBUTE_KEYS,
                form_data=request.form,
            )

        name = ensure_unique_name(parsed["name"], _existing_names(season_data))
        overall = parsed["overall"]
        destination = parsed.get("destination", "draft")

        profile = generate_rookie_profile(overall)
        player_id = allocate_player_id(season_data)
        player = {
            "id": player_id,
            "name": name,
            "team_id": None,
            "team": None,
            "overall": overall,
            "scout_grade": overall,
            "age": parsed["age"],
            "gp": 0,
            "is_rookie": True,
            "positions": profile["positions"],
            "stats_source": "generated",
        }
        for key, value in parsed.get("attributes", {}).items():
            profile["attributes"][key] = value
        init_rookie_career_profile(player, profile["attributes"], scout_grade=overall)

        if "potential" in parsed:
            player["potential"] = parsed["potential"]
            player.pop("peak_attributes", None)
            _assign_peak_attributes(player, random.Random())
        if "peak_age" in parsed:
            player["peak_age"] = parsed["peak_age"]
        if "retirement_age" in parsed:
            player["retirement_age"] = parsed["retirement_age"]
        if "development_rate" in parsed:
            player["development_rate"] = parsed["development_rate"]

        if parsed.get("manual_ppg"):
            player["stats_source"] = "manual"
            player["ppg"] = parsed["ppg"]

        refresh_player_from_attributes(player)
        if parsed.get("manual_ppg"):
            player["ppg"] = parsed["ppg"]
        player["overall"] = compute_intrinsic_overall(player)
        season_data["players"][str(player_id)] = player

        if destination == "team" and "team_id" in parsed:
            team_id = parsed["team_id"]
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


@admin_bp.route("/teams")
def admin_teams():
    season_id, season_data, lookup, redirect_response = _season_or_redirect()
    if redirect_response is not None:
        return redirect_response

    teams = []
    game = get_game()
    user_team_id = int(game["team_id"]) if game and game.get("team_id") else None
    for team in _admin_teams(season_data):
        tid = team["team_id"]
        record = season_data.get("standings", {}).get(str(tid), {})
        cap_override = (season_data.get("salary_cap_overrides") or {}).get(str(tid))
        teams.append(
            {
                **team,
                "roster_size": roster_size(season_data, tid),
                "record": f"{record.get('w', 0)}-{record.get('l', 0)}",
                "is_user_team": user_team_id == tid,
                "salary_cap": get_salary_cap(season_data, tid),
                "cap_override": cap_override,
            }
        )

    return render_template(
        "admin/teams.html",
        page_title="Admin Teams",
        season=season_data,
        teams=teams,
    )


@admin_bp.route("/teams/<int:team_id>", methods=["GET", "POST"])
def admin_team_roster(team_id):
    season_id, season_data, lookup, redirect_response = _season_or_redirect()
    if redirect_response is not None:
        return redirect_response

    teams = _admin_teams(season_data)
    valid_team_ids = {team["team_id"] for team in teams}
    if team_id not in valid_team_ids:
        flash("Team not found.", "error")
        return redirect(url_for("admin.admin_teams"))

    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "release":
            player_id = _parse_int(request.form.get("player_id"))
            if player_id:
                ok, message = release_player(season_data, team_id, player_id, force=True)
                flash(message, "success" if ok else "error")
        elif action == "add_fa":
            player_id = _parse_int(request.form.get("player_id"))
            if player_id:
                ok, message = assign_player_to_team(
                    season_data, player_id, team_id, force=True
                )
                flash(message, "success" if ok else "error")
        elif action == "set_cap":
            cap_raw = request.form.get("salary_cap", "").strip()
            cap_val = _parse_float(cap_raw)
            if cap_val is None:
                flash("Salary cap must be a number.", "error")
            else:
                try:
                    set_team_salary_cap(season_data, team_id, cap_val)
                    flash(f"Salary cap set to ${cap_val:.1f}M for {team_name(season_data, team_id)}.")
                except ValueError as exc:
                    flash(str(exc), "error")
        elif action == "reset_cap":
            clear_team_salary_cap(season_data, team_id)
            flash(f"Salary cap reset to league default (${get_salary_cap(season_data)}M).")
        elif action == "discount_salaries":
            pct_raw = request.form.get("salary_pct", "").strip()
            pct_val = _parse_float(pct_raw)
            if pct_val is None or not 5 <= pct_val <= 100:
                flash("Salary percentage must be between 5 and 100.", "error")
            else:
                updated = apply_roster_salary_multiplier(
                    season_data, team_id, pct_val / 100.0, lookup
                )
                flash(f"Scaled {updated} player salaries to {pct_val:.0f}% of previous pay.")
        elif action == "set_player_salary":
            player_id = _parse_int(request.form.get("player_id"))
            salary_val = _parse_float(request.form.get("salary", "").strip())
            if player_id is None or salary_val is None:
                flash("Player and salary are required.", "error")
            elif salary_val < MIN_SALARY_M:
                flash(f"Salary must be at least ${MIN_SALARY_M}M.", "error")
            else:
                player = lookup.get(player_id)
                if not player or int(player.get("team_id") or -1) != team_id:
                    flash("Player not found on this roster.", "error")
                else:
                    player["salary"] = round(salary_val, 1)
                    player["previous_salary"] = player["salary"]
                    flash(f"Updated {player.get('name', player_id)} salary to ${salary_val:.1f}M.")
        reconcile_team_roster(season_data, team_id)
        ensure_contract_fields(season_data)
        refresh_all_roster_stats(season_data, lookup)
        refresh_all_team_finances(season_data, lookup)
        save_session_season(season_id, season_data)
        return redirect(url_for("admin.admin_team_roster", team_id=team_id))

    ensure_contract_fields(season_data)
    roster = roster_players(season_data, team_id, lookup)
    roster.sort(key=lambda p: p.get("overall") or 0, reverse=True)
    g_league_roster = sorted(
        two_way_players(season_data, team_id, lookup),
        key=lambda p: p.get("overall") or 0,
        reverse=True,
    )
    free_agents = sorted(
        free_agent_players(season_data, lookup),
        key=lambda p: p.get("overall") or 0,
        reverse=True,
    )[:50]
    record = season_data.get("standings", {}).get(str(team_id), {})
    game = get_game()
    finances = team_finances(season_data, team_id, lookup)
    is_user_team = game and int(game.get("team_id") or -1) == team_id

    return render_template(
        "admin/team_roster.html",
        page_title=f"Roster — {team_name(season_data, team_id)}",
        season=season_data,
        team_id=team_id,
        team_name=team_name(season_data, team_id),
        roster=roster,
        g_league_roster=g_league_roster,
        free_agents=free_agents,
        record=f"{record.get('w', 0)}-{record.get('l', 0)}",
        roster_size=len(roster),
        finances=finances,
        is_user_team=is_user_team,
        league_cap=get_salary_cap(season_data),
    )
