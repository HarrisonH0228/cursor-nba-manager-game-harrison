import os
import random

from dotenv import load_dotenv
from flask import Flask, flash, jsonify, redirect, render_template, request, url_for
from werkzeug.exceptions import HTTPException

import cache
from fetcher import fetch_teams, refresh_cache
from game import (
    clear_game,
    consume_season_recovery_notice,
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
    advance_season,
    can_trade,
    championship_count,
    enrich_game_for_display,
    find_schedule_game,
    games_played_count,
    init_season,
    league_lookup,
    playoff_bracket_context,
    regular_season_complete,
    roster_players,
    schedule_games,
    seed_playoffs,
    sim_day,
    sim_rest_of_season,
    sim_to_trade_deadline,
    sim_week,
    simulate_all_playoffs,
    standings_table,
    team_name,
)
from draft import (
    draft_board_context,
    draft_pick_trade_context,
    make_pick,
    sim_draft_to_user_pick,
    sim_rest_of_draft,
    skip_pick,
    start_draft,
    trade_pick_for_future,
)
from injuries import drain_pending_notifications, user_team_injury_report
from gm_personalities import archetype_label, get_gm_profile
from roster import (
    MAX_G_LEAGUE_AGE,
    MAX_ROSTER,
    MAX_TWO_WAY,
    MIN_ROSTER,
    assign_to_g_league,
    can_assign_two_way,
    can_remove_player,
    free_agent_players,
    recall_from_g_league,
    reconcile_all_rosters,
    reconcile_team_roster,
    release_player,
    repair_roster_sync,
    roster_size,
    two_way_players,
)
from trade import (
    cpu_accepts_trade,
    evaluate_trade,
    execute_trade,
    future_team_picks,
    other_teams,
    pick_trade_preview,
    pick_value,
    team_picks,
    trade_window_message,
    validate_trade,
    TRADE_TOLERANCE,
)
from attributes import apply_attributes, ensure_positions, init_career_profiles, needs_attributes, positions_label, scouting_upside_tier
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
from admin import admin_bp
from attributes import refresh_team_roster_stats
from contracts import (
    MAX_FA_YEARS,
    compute_asking_salary,
    ensure_contract_fields,
    expiring_contract_report,
    min_acceptable_salary,
    propose_extension,
    propose_offer,
    team_finances,
)
from news import news_headlines
from scheduler import start_scheduler
from year_end_report import get_year_end_report

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev")
app.register_blueprint(admin_bp)


@app.template_filter("stat1")
def stat1(value):
    if value is None:
        return "—"
    try:
        return f"{float(value):.1f}"
    except (TypeError, ValueError):
        return "—"


SORT_COLUMNS = {"name", "team", "overall", "ppg", "rpg", "apg", "spg", "bpg"}
ROSTER_SORT_COLUMNS = {"name", "overall", "age", "gp", "position", "ppg", "rpg", "apg", "spg", "bpg"}
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

    if sort_key == "position":
        return sorted(
            players,
            key=lambda player: (player.get("positions") or ["ZZ"])[0],
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

    if needs_attributes(all_players):
        apply_attributes(all_players)

    init_career_profiles(all_players)
    for player in all_players:
        ensure_positions(player)

    return cache_data, all_players


def _season_player_lookup(season_data=None):
    if season_data is None:
        _, season_data = load_session_season()
    if season_data and season_data.get("players"):
        return league_lookup(season_data)
    _, all_players = _load_players()
    return {player["id"]: player for player in all_players}


def _active_players(season_data=None):
    cache_data, all_players = _load_players()
    if season_data is None:
        _, season_data = load_session_season()
    if season_data and season_data.get("players"):
        lookup = league_lookup(season_data)
        return cache_data, list(lookup.values())
    return cache_data, all_players


def _team_context(all_players, team_id, season_data=None):
    if season_data and season_data.get("rosters"):
        roster = roster_players(season_data, team_id)
        team_name_value = roster[0].get("team") if roster else None
        if not team_name_value:
            standing = season_data.get("standings", {}).get(str(team_id), {})
            team_name_value = standing.get("team_name", "Unknown Team")
    else:
        roster = [player for player in all_players if player.get("team_id") == team_id]
        team_name_value = roster[0].get("team") if roster else "Unknown Team"

    team_summaries = build_team_summaries(all_players)

    team_gp = None
    if season_data and season_data.get("standings"):
        team_gp = season_data["standings"].get(str(team_id), {}).get("gp")

    return {
        "roster": roster,
        "team_name": team_name_value,
        "team_overall": compute_team_overall(roster, team_gp=team_gp),
        "team_rank": compute_team_ranks(team_summaries).get(team_id, {}).get("overall"),
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


def _build_season_team_summaries(season_data, lookup):
    reconcile_all_rosters(season_data)
    summaries = []
    for team_id_str in season_data.get("rosters", {}).keys():
        team_id = int(team_id_str)
        roster = roster_players(season_data, team_id, lookup)
        top_player = max(
            roster,
            key=lambda player: player.get("overall") or 0,
            default=None,
        )
        team_name_value = (
            season_data.get("standings", {}).get(team_id_str, {}).get("team_name")
            or (roster[0].get("team") if roster else str(team_id))
        )
        summaries.append(
            {
                "team_id": team_id,
                "team": team_name_value,
                "overall": compute_team_overall(roster),
                "roster_size": roster_size(season_data, team_id),
                "top_player_name": top_player.get("name") if top_player else None,
                "top_player_overall": top_player.get("overall") if top_player else None,
            }
        )
    return summaries


def _can_sim_regular_season(season_data):
    if not season_data or season_data.get("phase") != "regular":
        return False
    return season_data.get("current_day", 1) <= season_data.get("max_day", 1)


@app.context_processor
def inject_game():
    _, season_data = load_session_season()
    recovery = consume_season_recovery_notice()
    if recovery == "restored":
        flash("Season save was corrupted; restored from backup.", "warning")
    elif recovery == "corrupt":
        flash("Season save was corrupted; please start a new season.", "error")
    game = get_game()
    lookup = league_lookup(season_data) if season_data else None
    headlines = (
        news_headlines(season_data, lookup=lookup, limit=12) if season_data else []
    )
    user_championships = (
        championship_count(season_data, game["team_id"]) if game and season_data else 0
    )
    user_roster_size = None
    if game and season_data:
        reconcile_team_roster(season_data, game["team_id"])
        user_roster_size = roster_size(season_data, game["team_id"])
    return {
        "game": game,
        "active_season": season_data,
        "positions_label": positions_label,
        "max_roster": MAX_ROSTER,
        "min_roster": MIN_ROSTER,
        "max_two_way": MAX_TWO_WAY,
        "max_g_league_age": MAX_G_LEAGUE_AGE,
        "news_headlines": headlines,
        "user_championships": user_championships,
        "user_roster_size": user_roster_size,
    }


@app.route("/")
def index():
    game = get_game()
    if game is None:
        return render_template("landing.html", page_title="NBA Manager")

    cache_data, all_players = _active_players()
    _, season_data = load_session_season()
    if season_data:
        reconcile_team_roster(season_data, game["team_id"])
    team_info = _team_context(all_players, game["team_id"], season_data)
    roster = _sort_players(team_info["roster"], "overall", "desc")
    top_players = roster[:3]
    user_count = roster_size(season_data, game["team_id"]) if season_data else len(roster)

    return render_template(
        "dashboard.html",
        page_title="Dashboard",
        team_name=game["team_name"],
        team_overall=team_info["team_overall"],
        team_rank=team_info["team_rank"],
        roster_size=user_count,
        top_players=top_players,
        team_finances=team_finances(season_data, game["team_id"]) if season_data else None,
        last_updated=cache_data.get("last_updated"),
    )


@app.route("/choose-team")
def choose_team():
    game = get_game()
    if game is not None:
        return redirect(url_for("index"))
    teams = sorted(fetch_teams(), key=lambda team: team["full_name"])
    return render_template(
        "choose_team.html",
        page_title="Choose Your Team",
        teams=teams,
    )


@app.route("/start", methods=["POST"])
def start():
    team = start_game()
    flash(f"You rolled the {team['full_name']}!")
    return redirect(url_for("team"))


@app.route("/start/pick", methods=["POST"])
def start_pick():
    team_id_raw = request.form.get("team_id", "").strip()
    if not team_id_raw.isdigit():
        flash("Select a valid team.", "error")
        return redirect(url_for("choose_team"))

    team_id = int(team_id_raw)
    valid_ids = {team["id"] for team in fetch_teams()}
    if team_id not in valid_ids:
        flash("Select a valid team.", "error")
        return redirect(url_for("choose_team"))

    team = start_game(team_id=team_id)
    if team is None:
        flash("Could not start with that team. Try again.", "error")
        return redirect(url_for("choose_team"))

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
    cache_data, all_players = _active_players()
    _, season_data = load_session_season()
    lookup = league_lookup(season_data) if season_data else None
    if season_data:
        reconcile_team_roster(season_data, game["team_id"])
        ensure_contract_fields(season_data)
        refresh_team_roster_stats(roster_players(season_data, game["team_id"]))
    team_info = _team_context(all_players, game["team_id"], season_data)
    stat_ranks = compute_stat_ranks(all_players)
    roster = _sort_players(team_info["roster"], sort_key, order)
    _attach_roster_ranks(roster, stat_ranks)
    g_league_roster = []
    if season_data:
        g_league_roster = _sort_players(
            two_way_players(season_data, game["team_id"], lookup), sort_key, order
        )
    expiring_contracts = (
        expiring_contract_report(season_data, game["team_id"], lookup) if season_data else []
    )

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
        g_league_roster=g_league_roster,
        roster_size=roster_size(season_data, game["team_id"]) if season_data else len(roster),
        max_roster=MAX_ROSTER,
        max_two_way=MAX_TWO_WAY,
        can_assign_g_league=season_data is not None
        and can_trade(season_data)
        and can_assign_two_way(season_data, game["team_id"]),
        can_release=season_data is not None and can_trade(season_data) and can_remove_player(season_data, game["team_id"]),
        can_extend=season_data is not None and can_trade(season_data),
        can_g_league_moves=season_data is not None and can_trade(season_data),
        expiring_contracts=expiring_contracts,
        max_fa_years=MAX_FA_YEARS,
        sort=sort_key,
        order=order,
        next_order=_next_order,
        make_team_url=make_team_url,
        stat_columns=STAT_COLUMNS,
        stat_labels=STAT_LABELS,
        positions_label=positions_label,
        team_finances=team_finances(season_data, game["team_id"]) if season_data else None,
        last_updated=cache_data.get("last_updated"),
    )


@app.route("/team/release/<int:player_id>", methods=["POST"])
def team_release(player_id):
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    game = get_game()
    season_id, season_data = load_session_season()
    if season_data is None:
        flash("Start a season first.")
        return redirect(url_for("team"))

    ok, message = release_player(season_data, game["team_id"], player_id)
    if ok:
        save_session_season(season_id, season_data)
    flash(message)
    return redirect(url_for("team"))


@app.route("/team/extend/<int:player_id>", methods=["POST"])
def team_extend(player_id):
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    game = get_game()
    season_id, season_data = load_session_season()
    if season_data is None:
        flash("Start a season first.")
        return redirect(url_for("team"))

    salary_raw = request.form.get("salary", "").strip()
    years_raw = request.form.get("years", "2").strip()
    try:
        salary = float(salary_raw)
    except ValueError:
        flash("Enter a valid salary.")
        return redirect(url_for("team"))
    years = int(years_raw) if years_raw.isdigit() else 2

    ok, message, _accepted = propose_extension(
        season_data, game["team_id"], player_id, salary, years
    )
    save_session_season(season_id, season_data)
    flash(message)
    return redirect(url_for("team"))


@app.route("/team/g-league/<int:player_id>", methods=["POST"])
def team_g_league_send(player_id):
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    game = get_game()
    season_id, season_data = load_session_season()
    if season_data is None:
        flash("Start a season first.")
        return redirect(url_for("team"))

    ok, message = assign_to_g_league(season_data, game["team_id"], player_id)
    if ok:
        save_session_season(season_id, season_data)
    flash(message)
    return redirect(url_for("team"))


@app.route("/team/g-league/recall/<int:player_id>", methods=["POST"])
def team_g_league_recall(player_id):
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    game = get_game()
    season_id, season_data = load_session_season()
    if season_data is None:
        flash("Start a season first.")
        return redirect(url_for("team"))

    ok, message = recall_from_g_league(season_data, game["team_id"], player_id)
    if ok:
        save_session_season(season_id, season_data)
    flash(message)
    return redirect(url_for("team"))


def _filter_free_agents(players, query="", position="", min_ovr=None, max_ovr=None, max_age=None):
    filtered = players
    if query:
        needle = query.casefold()
        filtered = [p for p in filtered if needle in (p.get("name") or "").casefold()]
    if position:
        filtered = [
            p
            for p in filtered
            if position in (p.get("positions") or [])
        ]
    if min_ovr is not None:
        filtered = [p for p in filtered if int(p.get("overall") or 0) >= min_ovr]
    if max_ovr is not None:
        filtered = [p for p in filtered if int(p.get("overall") or 99) <= max_ovr]
    if max_age is not None:
        filtered = [p for p in filtered if int(p.get("age") or 99) <= max_age]
    return filtered


@app.route("/free-agency")
def free_agency():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    game = get_game()
    season_id, season_data = load_session_season()
    if season_data is None:
        flash("Start a season first.")
        return redirect(url_for("season_hub"))

    sort_key, order = _parse_sort_order("overall", "desc", ROSTER_SORT_COLUMNS)
    reconcile_team_roster(season_data, game["team_id"])
    lookup = league_lookup(season_data)
    fa_query = request.args.get("q", "").strip()
    fa_pos = request.args.get("pos", "").strip().upper()
    min_ovr_raw = request.args.get("min_ovr", "").strip()
    max_ovr_raw = request.args.get("max_ovr", "").strip()
    max_age_raw = request.args.get("max_age", "").strip()
    min_ovr = int(min_ovr_raw) if min_ovr_raw.isdigit() else None
    max_ovr = int(max_ovr_raw) if max_ovr_raw.isdigit() else None
    max_age = int(max_age_raw) if max_age_raw.isdigit() else None
    agents = _filter_free_agents(
        free_agent_players(season_data, lookup),
        query=fa_query,
        position=fa_pos if fa_pos in {"PG", "SG", "SF", "PF", "C"} else "",
        min_ovr=min_ovr,
        max_ovr=max_ovr,
        max_age=max_age,
    )
    agents = _sort_players(agents, sort_key, order)
    user_roster_count = roster_size(season_data, game["team_id"])

    def make_fa_url(**overrides):
        params = {
            "sort": sort_key,
            "order": order,
            "q": fa_query,
            "pos": fa_pos,
            "min_ovr": min_ovr_raw,
            "max_ovr": max_ovr_raw,
            "max_age": max_age_raw,
        }
        params.update(overrides)
        return url_for("free_agency", **{k: v for k, v in params.items() if v not in (None, "")})

    finances = team_finances(season_data, game["team_id"], lookup)
    for player in agents:
        player["asking_salary"] = player.get("asking_salary") or compute_asking_salary(player)
        player["min_salary"] = min_acceptable_salary(player)

    return render_template(
        "free_agency.html",
        page_title="Free Agency",
        free_agents=agents,
        can_sign=can_trade(season_data) and user_roster_count < MAX_ROSTER,
        roster_size=user_roster_count,
        max_roster=MAX_ROSTER,
        sort=sort_key,
        order=order,
        next_order=_next_order,
        make_fa_url=make_fa_url,
        positions_label=positions_label,
        team_finances=finances,
        max_fa_years=MAX_FA_YEARS,
        fa_query=fa_query,
        fa_pos=fa_pos,
        fa_min_ovr=min_ovr_raw,
        fa_max_ovr=max_ovr_raw,
        fa_max_age=max_age_raw,
    )


@app.route("/free-agency/offer/<int:player_id>", methods=["POST"])
def free_agency_offer(player_id):
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    game = get_game()
    season_id, season_data = load_session_season()
    if season_data is None:
        flash("Start a season first.")
        return redirect(url_for("free_agency"))

    salary_raw = request.form.get("salary", "").strip()
    years_raw = request.form.get("years", "2").strip()
    try:
        salary = float(salary_raw)
    except ValueError:
        flash("Enter a valid salary.")
        return redirect(url_for("free_agency"))
    years = int(years_raw) if years_raw.isdigit() else 2

    ok, message, _accepted = propose_offer(season_data, game["team_id"], player_id, salary, years)
    save_session_season(season_id, season_data)
    flash(message)
    return redirect(url_for("free_agency"))


@app.route("/free-agency/sign/<int:player_id>", methods=["POST"])
def free_agency_sign(player_id):
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    game = get_game()
    season_id, season_data = load_session_season()
    if season_data is None:
        flash("Start a season first.")
        return redirect(url_for("free_agency"))

    lookup = league_lookup(season_data)
    player = lookup.get(player_id)
    salary = None
    if player:
        salary = player.get("asking_salary") or compute_asking_salary(player)
    ok, message, _accepted = propose_offer(
        season_data, game["team_id"], player_id, salary or 5.0, 2
    )
    save_session_season(season_id, season_data)
    flash(message)
    return redirect(url_for("free_agency"))


@app.route("/trade")
def trade():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    game = get_game()
    _, season_data = load_session_season()
    if season_data is None:
        flash("Start a season first to trade.")
        return redirect(url_for("season_hub"))

    partner_raw = request.args.get("partner", "").strip()
    partner_id = None
    if partner_raw.isdigit():
        partner_id = int(partner_raw)

    user_team_id = game["team_id"]
    repair_roster_sync(season_data, user_team_id)
    if partner_id is not None:
        repair_roster_sync(season_data, partner_id)
    lookup = league_lookup(season_data)
    user_roster = sorted(
        roster_players(season_data, user_team_id, lookup),
        key=lambda player: player.get("overall") or 0,
        reverse=True,
    )
    user_picks = team_picks(season_data, user_team_id)
    teams = other_teams(season_data, user_team_id)

    partner_roster = []
    partner_picks = []
    partner_name = None
    if partner_id is not None:
        partner_roster = sorted(
            roster_players(season_data, partner_id, lookup),
            key=lambda player: player.get("overall") or 0,
            reverse=True,
        )
        partner_picks = team_picks(season_data, partner_id)
        partner_name = season_data.get("standings", {}).get(str(partner_id), {}).get(
            "team_name", str(partner_id)
        )

    partner_gm = None
    if partner_id is not None:
        profile = get_gm_profile(season_data, partner_id)
        partner_gm = archetype_label(profile.get("archetype", "balanced"))

    return render_template(
        "trade.html",
        page_title="Trade Engine",
        season=season_data,
        can_trade=can_trade(season_data),
        trade_message=trade_window_message(season_data),
        user_roster=user_roster,
        user_picks=user_picks,
        teams=teams,
        partner_id=partner_id,
        partner_name=partner_name,
        partner_roster=partner_roster,
        partner_picks=partner_picks,
        partner_gm=partner_gm,
        trades=season_data.get("trades", [])[-10:],
        user_roster_size=roster_size(season_data, user_team_id),
        max_roster=MAX_ROSTER,
    )


@app.route("/trade/propose", methods=["POST"])
def trade_propose():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    game = get_game()
    season_id, season_data = load_session_season()
    if season_data is None:
        flash("Start a season first.")
        return redirect(url_for("season_hub"))

    partner_raw = request.form.get("partner_id", "").strip()
    if not partner_raw.isdigit():
        flash("Select a trade partner.")
        return redirect(url_for("trade"))

    partner_id = int(partner_raw)
    outgoing_players = request.form.getlist("outgoing_players")
    outgoing_picks = request.form.getlist("outgoing_picks")
    incoming_players = request.form.getlist("incoming_players")
    incoming_picks = request.form.getlist("incoming_picks")

    repair_roster_sync(season_data, game["team_id"])
    repair_roster_sync(season_data, partner_id)

    valid, message = validate_trade(
        season_data,
        game["team_id"],
        partner_id,
        outgoing_players,
        outgoing_picks,
        incoming_players,
        incoming_picks,
    )
    if not valid:
        flash(message)
        return redirect(url_for("trade", partner=partner_id))

    preview = evaluate_trade(
        season_data,
        game["team_id"],
        partner_id,
        outgoing_players,
        outgoing_picks,
        incoming_players,
        incoming_picks,
    )
    if not cpu_accepts_trade(
        season_data,
        game["team_id"],
        partner_id,
        outgoing_players,
        outgoing_picks,
        incoming_players,
        incoming_picks,
    ):
        tolerance = preview.get("tolerance", TRADE_TOLERANCE)
        if preview["partner_net"] > tolerance:
            flash("Trade rejected — partner had second thoughts.")
        else:
            flash("Trade rejected — value too far apart.")
        return redirect(url_for("trade", partner=partner_id))

    ok, message = execute_trade(
        season_data,
        game["team_id"],
        partner_id,
        outgoing_players,
        outgoing_picks,
        incoming_players,
        incoming_picks,
    )
    _save_season(season_id, season_data)
    flash(message)
    return redirect(url_for("trade", partner=partner_id))


@app.route("/trade/evaluate", methods=["POST"])
def trade_evaluate():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    game = get_game()
    _, season_data = load_session_season()
    if season_data is None:
        return jsonify({"error": "Start a season first."}), 400

    payload = request.get_json(silent=True) or {}
    partner_raw = str(payload.get("partner_id", "")).strip()
    if not partner_raw.isdigit():
        return jsonify({"error": "Select a trade partner."}), 400

    partner_id = int(partner_raw)
    outgoing_players = payload.get("outgoing_players") or []
    outgoing_picks = payload.get("outgoing_picks") or []
    incoming_players = payload.get("incoming_players") or []
    incoming_picks = payload.get("incoming_picks") or []

    result = evaluate_trade(
        season_data,
        game["team_id"],
        partner_id,
        outgoing_players,
        outgoing_picks,
        incoming_players,
        incoming_picks,
    )
    return jsonify(result)


@app.route("/search")
def search():
    query = request.args.get("q", "").strip()
    view = request.args.get("view", "players")
    selected_raw = request.args.get("selected", "").strip()
    team_id_raw = request.args.get("team_id", "").strip()

    if view not in VIEW_MODES:
        view = "players"

    cache_data, all_players = _active_players()
    _, season_data = load_session_season()
    if season_data:
        reconcile_all_rosters(season_data)
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
        team_info = _team_context(all_players, roster_team_id, season_data)
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
        if season_data and season_data.get("rosters"):
            teams = _build_season_team_summaries(season_data, league_lookup(season_data))
        else:
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
    season_id, season_data = load_session_season()
    if season_data and season_data.get("players"):
        lookup = league_lookup(season_data)
    else:
        lookup = {player["id"]: player for player in all_players}
    return cache_data, all_players, lookup, season_id, season_data


def _save_season(season_id, season_data):
    game = get_game()
    if game and season_data is not None:
        season_data["user_team_id"] = game["team_id"]
    save_session_season(season_id, season_data)


def _flash_injury_notifications(season_data, user_team_id=None):
    if not season_data:
        return
    for message in drain_pending_notifications(season_data, user_team_id=user_team_id):
        flash(message, "warning")


def _flash_championship_bonus(season_data):
    """Flash pending championship bonus and clear it from season state."""
    if not season_data:
        return False
    bonus = season_data.pop("pending_championship_bonus", None)
    if bonus is not None:
        flash(f"Championship bonus: ${bonus}M distributed to your roster!", "success")
        return True
    return False


def _render_season(season_id, season_data, lookup, game, page="hub", schedule_day=None):
    if _flash_championship_bonus(season_data):
        _save_season(season_id, season_data)
    east_standings = standings_table(season_data, conference="East") if season_data else []
    west_standings = standings_table(season_data, conference="West") if season_data else []
    expiring_contracts = (
        expiring_contract_report(season_data, game["team_id"], lookup)
        if season_data
        else []
    )
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
        user_injury_report=user_team_injury_report(season_data, game["team_id"], lookup)
        if season_data
        else [],
        schedule=schedule,
        schedule_day=schedule_day or (season_data.get("current_day", 1) if season_data else 1),
        games_played=games_played_count(season_data) if season_data else 0,
        regular_complete=regular_season_complete(season_data) if season_data else False,
        can_sim_regular=_can_sim_regular_season(season_data),
        expiring_contracts=expiring_contracts,
        max_fa_years=MAX_FA_YEARS,
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

    game = get_game()
    season_id = season_store.create_season_id()
    season_year = cache_data.get("season") or 2026
    season_rng = random.Random(season_year)
    season_data = init_season(all_players, season_year=season_year, rng=season_rng)
    season_data["user_team_id"] = game["team_id"]
    set_season_id(season_id)
    _save_season(season_id, season_data)
    flash("Season started.")
    return redirect(url_for("season_hub"))


@app.route("/season/sim/season", methods=["POST"])
def season_sim_full():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    game = get_game()
    _, _, lookup, season_id, season_data = _season_context()
    if season_data is None:
        flash("Start a season first.")
        return redirect(url_for("season_hub"))

    count = sim_rest_of_season(season_data, lookup, user_team_id=game["team_id"])
    _save_season(season_id, season_data)
    _flash_injury_notifications(season_data, user_team_id=game["team_id"])
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
    max_day = season_data.get("max_day", schedule_day)
    if day_raw.isdigit():
        schedule_day = max(1, min(int(day_raw), max_day))

    return _render_season(
        season_id,
        season_data,
        lookup,
        game,
        page="schedule",
        schedule_day=schedule_day,
    )


@app.route("/season/game/<int:game_id>")
def season_game_box_score(game_id):
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    game_state = get_game()
    _, _, lookup, season_id, season_data = _season_context()
    if season_data is None:
        flash("Start a season first.")
        return redirect(url_for("season_hub"))

    schedule_game = find_schedule_game(season_data, game_id)
    if schedule_game is None or not schedule_game.get("played"):
        flash("Box score not available for that game.")
        return redirect(url_for("season_schedule"))

    return render_template(
        "box_score.html",
        page_title="Box Score",
        game=schedule_game,
        home_name=team_name(season_data, schedule_game["home_id"]),
        away_name=team_name(season_data, schedule_game["away_id"]),
        user_team_id=game_state["team_id"],
    )


@app.route("/season/sim/day", methods=["POST"])
def season_sim_day():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    game = get_game()
    _, _, lookup, season_id, season_data = _season_context()
    if season_data is None:
        flash("Start a season first.")
        return redirect(url_for("season_hub"))
    if not _can_sim_regular_season(season_data):
        flash("Regular season simulation is complete.")
        return redirect(url_for("season_hub"))

    count = sim_day(season_data, lookup, user_team_id=game["team_id"])
    _save_season(season_id, season_data)
    _flash_injury_notifications(season_data, user_team_id=game["team_id"])
    flash(f"Simulated day {season_data.get('current_day', 1) - 1}: {count} games.")
    return redirect(url_for("season_hub"))


@app.route("/season/sim/week", methods=["POST"])
def season_sim_week():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    game = get_game()
    _, _, lookup, season_id, season_data = _season_context()
    if season_data is None:
        flash("Start a season first.")
        return redirect(url_for("season_hub"))
    if not _can_sim_regular_season(season_data):
        flash("Regular season simulation is complete.")
        return redirect(url_for("season_hub"))

    count = sim_week(season_data, lookup, user_team_id=game["team_id"])
    _save_season(season_id, season_data)
    _flash_injury_notifications(season_data, user_team_id=game["team_id"])
    flash(f"Simulated one week: {count} games.")
    return redirect(url_for("season_hub"))


@app.route("/season/sim/trade-deadline", methods=["POST"])
def season_sim_trade_deadline():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    game = get_game()
    _, _, lookup, season_id, season_data = _season_context()
    if season_data is None:
        flash("Start a season first.")
        return redirect(url_for("season_hub"))
    if not _can_sim_regular_season(season_data):
        flash("Regular season simulation is complete.")
        return redirect(url_for("season_hub"))

    count = sim_to_trade_deadline(season_data, lookup, user_team_id=game["team_id"])
    _save_season(season_id, season_data)
    _flash_injury_notifications(season_data, user_team_id=game["team_id"])
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
    bracket = playoff_bracket_context(season_data)
    return render_template(
        "season.html",
        page_title="Playoffs",
        page="playoffs",
        season=season_data,
        season_id=season_id,
        east_standings=east_standings,
        west_standings=west_standings,
        user_team_id=game["team_id"],
        bracket=bracket,
        schedule=[],
        schedule_day=season_data.get("current_day", 1),
        games_played=games_played_count(season_data),
        regular_complete=regular_season_complete(season_data),
    )


@app.route("/season/playoffs/series/<int:round_idx>/<int:series_idx>/game/<int:game_idx>")
def season_playoff_box_score(round_idx, series_idx, game_idx):
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    game_state = get_game()
    _, _, _lookup, _season_id, season_data = _season_context()
    if season_data is None:
        flash("Start a season first.")
        return redirect(url_for("season_hub"))

    playoffs = season_data.get("playoffs") or {}
    rounds = playoffs.get("rounds", [])
    if round_idx < 0 or round_idx >= len(rounds):
        flash("Playoff series not found.")
        return redirect(url_for("season_playoffs"))

    series_list = rounds[round_idx].get("series", [])
    if series_idx < 0 or series_idx >= len(series_list):
        flash("Playoff series not found.")
        return redirect(url_for("season_playoffs"))

    games = series_list[series_idx].get("games", [])
    if game_idx < 0 or game_idx >= len(games):
        flash("Box score not available for that game.")
        return redirect(url_for("season_playoffs"))

    playoff_game = games[game_idx]
    return render_template(
        "box_score.html",
        page_title="Playoff Box Score",
        game=playoff_game,
        home_name=team_name(season_data, playoff_game["home_id"]),
        away_name=team_name(season_data, playoff_game["away_id"]),
        user_team_id=game_state["team_id"],
        back_url=url_for("season_playoffs"),
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

    _flash_championship_bonus(season_data)
    _save_season(season_id, season_data)
    return redirect(url_for("season_playoffs"))


@app.route("/season/year-end")
def season_year_end():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    game = get_game()
    _, _, lookup, season_id, season_data = _season_context()
    if season_data is None:
        flash("Start a season first.")
        return redirect(url_for("season_hub"))

    phase = season_data.get("phase")
    if phase not in {"complete", "draft", "offseason"}:
        flash("Year-end report is available after the playoffs conclude.")
        return redirect(url_for("season_hub"))

    had_report = bool(season_data.get("year_end_report"))
    report = get_year_end_report(season_data, lookup)
    if report and not had_report:
        _save_season(season_id, season_data)

    return render_template(
        "year_end.html",
        page_title="Year in Review",
        season=season_data,
        report=report,
        user_team_id=game["team_id"],
    )


@app.route("/season/draft", methods=["GET"])
def season_draft():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    game = get_game()
    _, _, lookup, season_id, season_data = _season_context()
    if season_data is None:
        flash("Start a season first.")
        return redirect(url_for("season_hub"))

    phase = season_data.get("phase")
    reconcile_team_roster(season_data, game["team_id"])
    user_roster_count = roster_size(season_data, game["team_id"])
    if phase == "complete":
        return render_template(
            "draft.html",
            page_title="Draft",
            season=season_data,
            phase=phase,
            board=None,
            user_team_id=game["team_id"],
            user_roster_size=user_roster_count,
            max_roster=MAX_ROSTER,
            positions_label=positions_label,
        )

    if phase not in {"draft", "offseason"}:
        flash("Draft is not available yet.")
        return redirect(url_for("season_hub"))

    board = draft_board_context(season_data, game["team_id"], lookup)
    for prospect in board.get("prospect_options", []):
        prospect["upside_tier"] = scouting_upside_tier(prospect)
    pick_trade_ctx = draft_pick_trade_context(season_data, game["team_id"])
    trade_teams = []
    for team in other_teams(season_data, game["team_id"]):
        future_picks = future_team_picks(season_data, team["team_id"])
        if not future_picks:
            continue
        enriched_picks = []
        for pick in future_picks:
            entry = dict(pick)
            if pick_trade_ctx and pick_trade_ctx.get("outgoing_pick"):
                preview = pick_trade_preview(
                    season_data, pick_trade_ctx["outgoing_pick"], pick
                )
                entry["trade_val"] = preview["incoming_val"]
                entry["would_accept"] = preview["would_accept"]
                entry["val_diff"] = preview["diff"]
            enriched_picks.append(entry)
        trade_teams.append({**team, "future_picks": enriched_picks})
    return render_template(
        "draft.html",
        page_title="Draft",
        season=season_data,
        phase=phase,
        board=board,
        user_team_id=game["team_id"],
        trade_teams=trade_teams,
        pick_trade_ctx=pick_trade_ctx,
        trade_tolerance=TRADE_TOLERANCE,
        positions_label=positions_label,
        user_roster_size=user_roster_count,
        max_roster=MAX_ROSTER,
    )


@app.route("/terms")
def terms():
    return render_template("terms.html", page_title="Terms of Service")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html", page_title="Privacy Policy")


@app.route("/disclaimer")
def disclaimer():
    return render_template("disclaimer.html", page_title="Disclaimer")


@app.route("/season/draft/start", methods=["POST"])
def season_draft_start():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    _, _, lookup, season_id, season_data = _season_context()
    if season_data is None:
        flash("Start a season first.")
        return redirect(url_for("season_hub"))

    if season_data.get("phase") != "complete":
        flash("Draft can only start after playoffs.")
        return redirect(url_for("season_draft"))

    start_draft(season_data, lookup)
    _save_season(season_id, season_data)
    flash("Draft started.")
    return redirect(url_for("season_draft"))


@app.route("/season/draft/pick", methods=["POST"])
def season_draft_pick():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    game = get_game()
    _, _, lookup, season_id, season_data = _season_context()
    if season_data is None or season_data.get("phase") != "draft":
        flash("No draft in progress.")
        return redirect(url_for("season_draft"))

    option_raw = request.form.get("prospect_index", "0").strip()
    try:
        option_index = int(option_raw)
    except ValueError:
        option_index = 0

    state = season_data.get("draft_state") or {}
    options = state.get("prospect_options", [])
    prospect = options[option_index] if 0 <= option_index < len(options) else None

    ok, message = make_pick(season_data, game["team_id"], prospect=prospect)
    _save_season(season_id, season_data)
    flash(message if ok else message)
    return redirect(url_for("season_draft"))


@app.route("/season/draft/skip", methods=["POST"])
def season_draft_skip():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    game = get_game()
    _, _, lookup, season_id, season_data = _season_context()
    if season_data is None or season_data.get("phase") != "draft":
        flash("No draft in progress.")
        return redirect(url_for("season_draft"))

    ok, message = skip_pick(season_data, game["team_id"])
    _save_season(season_id, season_data)
    flash(message)
    return redirect(url_for("season_draft"))


@app.route("/season/draft/trade-pick", methods=["POST"])
def season_draft_trade_pick():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    game = get_game()
    _, _, lookup, season_id, season_data = _season_context()
    if season_data is None or season_data.get("phase") != "draft":
        flash("No draft in progress.")
        return redirect(url_for("season_draft"))

    partner_raw = request.form.get("partner_id", "").strip()
    incoming_pick = request.form.get("incoming_future_pick", "").strip()
    if not partner_raw.isdigit() or not incoming_pick:
        flash("Select a partner and future pick.")
        return redirect(url_for("season_draft"))

    ok, message = trade_pick_for_future(
        season_data,
        game["team_id"],
        int(partner_raw),
        incoming_pick,
    )
    _save_season(season_id, season_data)
    flash(message if ok else message)
    return redirect(url_for("season_draft"))


@app.route("/season/draft/sim", methods=["POST"])
def season_draft_sim():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    game = get_game()
    sim_mode = request.form.get("mode", "to_user")
    _, _, lookup, season_id, season_data = _season_context()
    if season_data is None or season_data.get("phase") != "draft":
        flash("No draft in progress.")
        return redirect(url_for("season_draft"))

    if sim_mode == "rest":
        count = sim_rest_of_draft(season_data, auto_user_picks=True)
        message = f"Simulated {count} picks. Draft complete."
    else:
        count = sim_draft_to_user_pick(season_data, game["team_id"])
        message = f"Simulated {count} CPU picks to your turn."

    _save_season(season_id, season_data)
    flash(message)
    return redirect(url_for("season_draft"))


@app.route("/season/advance", methods=["POST"])
def season_advance():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    _, _, lookup, season_id, season_data = _season_context()
    if season_data is None:
        flash("Start a season first.")
        return redirect(url_for("season_hub"))

    if season_data.get("phase") != "offseason":
        flash("Complete the draft before advancing.")
        return redirect(url_for("season_draft"))

    advance_season(season_data)
    _save_season(season_id, season_data)
    message = f"Welcome to the {season_data['season_year']} season!"
    retirements = season_data.get("last_retirements") or []
    if retirements:
        names = ", ".join(f"{item['name']} ({item['age']})" for item in retirements[:8])
        if len(retirements) > 8:
            names += f", +{len(retirements) - 8} more"
        message = f"{message} Retired: {names}."
    departures = season_data.get("last_departures") or []
    if departures:
        names = ", ".join(f"{item['name']}" for item in departures[:8])
        if len(departures) > 8:
            names += f", +{len(departures) - 8} more"
        message = f"{message} Left FA pool: {names}."
    flash(message)
    return redirect(url_for("season_hub"))


@app.route("/refresh")
def refresh():
    try:
        success = refresh_cache()
    except Exception:
        return redirect(url_for("search", stale=1))

    if success:
        return redirect(url_for("search", refreshed=1))
    return redirect(url_for("search", stale=1))


@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(405)
def http_error(error):
    code = error.code if isinstance(error, HTTPException) else 500
    message = error.description if isinstance(error, HTTPException) and error.description else "Request failed."
    return (
        render_template(
            "error.html",
            page_title="Error",
            error_code=code,
            error_message=message,
        ),
        code,
    )


@app.errorhandler(404)
def not_found(error):
    return (
        render_template(
            "error.html",
            page_title="Not Found",
            error_code=404,
            error_message="Page not found.",
        ),
        404,
    )


@app.errorhandler(500)
def server_error(error):
    app.logger.exception("Internal server error: %s", error)
    return (
        render_template(
            "error.html",
            page_title="Error",
            error_code=500,
            error_message="Something went wrong. Please try again.",
        ),
        500,
    )


@app.errorhandler(Exception)
def unhandled_exception(error):
    if isinstance(error, HTTPException):
        return error
    app.logger.exception("Unhandled exception: %s", error)
    return (
        render_template(
            "error.html",
            page_title="Error",
            error_code=500,
            error_message="Something went wrong. Please try again.",
        ),
        500,
    )


if os.getenv("ENABLE_SCHEDULER", "true").lower() == "true":
    start_scheduler(app)


if __name__ == "__main__":
    app.run(debug=True)
