import os

from dotenv import load_dotenv
from flask import Flask, flash, g, jsonify, redirect, render_template, request, session, url_for
from flask_wtf.csrf import CSRFProtect

import cache
from errors import (
    CustomPlayersWriteError,
    SeasonSaveError,
    configure_logging,
    format_cache_timestamp,
    get_logger,
)
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
    advance_season,
    can_trade,
    enrich_game_for_display,
    find_schedule_game,
    games_played_count,
    init_season,
    league_lookup,
    regular_season_complete,
    roster_players,
    schedule_games,
    seed_playoffs,
    sim_day,
    sim_rest_of_season,
    sim_to_trade_deadline,
    sim_week,
    simulate_all_playoffs,
    playoff_bracket_view,
    standings_table,
    team_name,
)
from draft import (
    draft_board_context,
    make_pick,
    sim_draft_to_user_pick,
    sim_rest_of_draft,
    start_draft,
)
from roster import (
    MAX_ROSTER,
    can_remove_player,
    free_agent_players,
    release_player,
    roster_size,
    sign_free_agent,
)
from trade import (
    cpu_accepts_trade,
    evaluate_trade,
    execute_trade,
    other_teams,
    picks_grouped_by_year,
    team_picks,
    trade_window_message,
    validate_trade,
)
from attributes import (
    ATTRIBUTE_KEYS,
    VALID_POSITIONS,
    apply_attributes,
    ensure_positions,
    init_career_profile,
    init_career_profiles,
    effective_attributes,
    needs_attributes,
    positions_label,
    scouting_upside_tier,
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
from custom_players import (
    add_custom_player,
    delete_custom_player,
    get_custom_player,
    list_custom_players,
    parse_career_from_form,
    parse_attributes_from_form,
    update_custom_player,
)
from admin_roster import (
    admin_move_player,
    admin_place_custom_on_team,
    admin_release_player,
    admin_sign_free_agent,
    admin_update_league_player,
    list_season_teams,
)

load_dotenv()
configure_logging()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev")
ADMIN_ENABLED = os.getenv("ADMIN_ENABLED", "true").lower() == "true"
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "1234")
CSRFProtect(app)
logger = get_logger(__name__)

SORT_COLUMNS = {"name", "team", "overall", "ppg", "rpg", "apg", "spg", "bpg"}
ROSTER_SORT_COLUMNS = {"name", "overall", "age", "gp", "position", "ppg", "rpg", "apg", "spg", "bpg"}
TEAM_SORT_COLUMNS = {"team", "overall", "roster_size"}
VIEW_MODES = {"players", "teams", "roster"}


def _build_cache_status(flash_result, cache_data):
    players = cache_data.get("players") or []
    last_updated = cache_data.get("last_updated")
    formatted_ts = format_cache_timestamp(last_updated)

    if flash_result:
        if flash_result.get("ok"):
            return {
                "alert_class": "success",
                "message": "Player data refreshed successfully.",
            }
        if flash_result.get("used_cache"):
            ts = format_cache_timestamp(flash_result.get("last_updated")) or formatted_ts or "unknown time"
            return {
                "alert_class": "warning",
                "message": f"Using cached data from {ts}",
            }
        return {
            "alert_class": "danger",
            "message": "Player data unavailable. Check your connection and click Refresh Data.",
        }

    if not players and not last_updated:
        return {"alert_class": "secondary", "message": "No cached data yet."}
    if not players:
        return {
            "alert_class": "danger",
            "message": "Player data unavailable. Check your connection and click Refresh Data.",
        }
    return None


def _require_int(raw, field_name, minimum=None, maximum=None):
    value_raw = str(raw).strip()
    if not value_raw.lstrip("-").isdigit():
        return None, f"Invalid {field_name}."
    value = int(value_raw)
    if minimum is not None and value < minimum:
        return None, f"{field_name} must be at least {minimum}."
    if maximum is not None and value > maximum:
        return None, f"{field_name} must be at most {maximum}."
    return value, None


def _coerce_str_list(values):
    if values is None:
        return []
    if not isinstance(values, list):
        return None
    return [str(value) for value in values]


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
    cache_data, all_players = cache.get_cached_players_payload()

    if needs_ratings(all_players):
        apply_ratings(all_players)

    if needs_attributes(all_players):
        apply_attributes(all_players)

    init_career_profiles(all_players)
    for player in all_players:
        ensure_positions(player)

    return cache_data, all_players


def _request_cache_data():
    if "cache_data" not in g:
        g.cache_data = cache.load_cache()
    return g.cache_data


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


@app.context_processor
def inject_game():
    cache_data = _request_cache_data()
    flash_result = session.pop("cache_flash", None)
    _, season_data = load_session_season()
    return {
        "game": get_game(),
        "active_season": season_data,
        "positions_label": positions_label,
        "max_roster": MAX_ROSTER,
        "admin_enabled": ADMIN_ENABLED,
        "admin_authenticated": session.get("admin_authenticated"),
        "cache_status": _build_cache_status(flash_result, cache_data),
    }


@app.route("/")
def index():
    game = get_game()
    if game is None:
        return render_template("landing.html", page_title="NBA Manager")

    cache_data, all_players = _active_players()
    _, season_data = load_session_season()
    team_info = _team_context(all_players, game["team_id"], season_data)
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
    try:
        team = start_game()
    except RuntimeError as exc:
        flash(str(exc), "error")
        return redirect(url_for("index"))
    flash(f"You are the GM of the {team['full_name']}!", "success")
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
    team_info = _team_context(all_players, game["team_id"], season_data)
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
        roster_size=len(roster),
        max_roster=MAX_ROSTER,
        can_release=season_data is not None and can_trade(season_data) and can_remove_player(season_data, game["team_id"]),
        sort=sort_key,
        order=order,
        next_order=_next_order,
        make_team_url=make_team_url,
        stat_columns=STAT_COLUMNS,
        stat_labels=STAT_LABELS,
        positions_label=positions_label,
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
        flash("Start a season first.", "error")
        return redirect(url_for("team"))

    ok, message = release_player(season_data, game["team_id"], player_id)
    if ok and not _save_season(season_id, season_data):
        return redirect(url_for("team"))
    flash(message, "success")
    return redirect(url_for("team"))


@app.route("/free-agency")
def free_agency():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    game = get_game()
    season_id, season_data = load_session_season()
    if season_data is None:
        flash("Start a season first.", "error")
        return redirect(url_for("season_hub"))

    sort_key, order = _parse_sort_order("overall", "desc", ROSTER_SORT_COLUMNS)
    lookup = league_lookup(season_data)
    agents = _sort_players(free_agent_players(season_data, lookup), sort_key, order)
    user_roster_count = roster_size(season_data, game["team_id"])

    def make_fa_url(**overrides):
        params = {"sort": sort_key, "order": order}
        params.update(overrides)
        return url_for("free_agency", **params)

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
    )


@app.route("/free-agency/sign/<int:player_id>", methods=["POST"])
def free_agency_sign(player_id):
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    game = get_game()
    season_id, season_data = load_session_season()
    if season_data is None:
        flash("Start a season first.", "error")
        return redirect(url_for("free_agency"))

    ok, message = sign_free_agent(season_data, game["team_id"], player_id)
    if ok and not _save_season(season_id, season_data):
        return redirect(url_for("free_agency"))
    flash(message, "success")
    return redirect(url_for("free_agency"))


@app.route("/trade")
def trade():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    game = get_game()
    _, season_data = load_session_season()
    if season_data is None:
        flash("Start a season first to trade.", "error")
        return redirect(url_for("season_hub"))

    partner_raw = request.args.get("partner", "").strip()
    partner_id = None
    if partner_raw.isdigit():
        partner_id = int(partner_raw)

    user_team_id = game["team_id"]
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

    return render_template(
        "trade.html",
        page_title="Trade Engine",
        season=season_data,
        can_trade=can_trade(season_data),
        trade_message=trade_window_message(season_data),
        user_roster=user_roster,
        user_picks=user_picks,
        user_picks_by_year=picks_grouped_by_year(user_picks),
        teams=teams,
        partner_id=partner_id,
        partner_name=partner_name,
        partner_roster=partner_roster,
        partner_picks=partner_picks,
        partner_picks_by_year=picks_grouped_by_year(partner_picks) if partner_id else [],
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
        flash("Start a season first.", "error")
        return redirect(url_for("season_hub"))

    partner_raw = request.form.get("partner_id", "").strip()
    if not partner_raw.isdigit():
        flash("Select a trade partner.", "error")
        return redirect(url_for("trade"))

    partner_id = int(partner_raw)
    outgoing_players = request.form.getlist("outgoing_players")
    outgoing_picks = request.form.getlist("outgoing_picks")
    incoming_players = request.form.getlist("incoming_players")
    incoming_picks = request.form.getlist("incoming_picks")

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
        flash(message, "success")
        return redirect(url_for("trade", partner=partner_id))

    if not cpu_accepts_trade(
        season_data,
        game["team_id"],
        partner_id,
        outgoing_players,
        outgoing_picks,
        incoming_players,
        incoming_picks,
    ):
        flash("Trade rejected — partner isn't getting enough value.", "error")
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
    if ok and not _save_season(season_id, season_data):
        return redirect(url_for("trade", partner=partner_id))
    flash(message, "success")
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
    outgoing_players = _coerce_str_list(payload.get("outgoing_players"))
    outgoing_picks = _coerce_str_list(payload.get("outgoing_picks"))
    incoming_players = _coerce_str_list(payload.get("incoming_players"))
    incoming_picks = _coerce_str_list(payload.get("incoming_picks"))
    if (
        outgoing_players is None
        or outgoing_picks is None
        or incoming_players is None
        or incoming_picks is None
    ):
        return jsonify({"error": "Invalid trade payload."}), 400

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
    try:
        save_session_season(season_id, season_data)
        return True
    except SeasonSaveError as exc:
        logger.exception("Season save failed")
        flash(str(exc), "error")
        return False


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
        flash("Season already in progress.", "error")
        return redirect(url_for("season_hub"))

    season_id = season_store.create_season_id()
    season_data = init_season(all_players, season_year=cache_data.get("season") or 2026)
    set_season_id(season_id)
    if not _save_season(season_id, season_data):
        return redirect(url_for("season_hub"))
    flash("Season started.", "success")
    return redirect(url_for("season_hub"))


@app.route("/season/sim/season", methods=["POST"])
def season_sim_full():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    _, all_players, lookup, season_id, season_data = _season_context()
    if season_data is None:
        flash("Start a season first.", "error")
        return redirect(url_for("season_hub"))

    count = sim_rest_of_season(season_data, lookup)
    if not _save_season(season_id, season_data):
        return redirect(url_for("season_hub"))
    flash(f"Simulated {count} games. Regular season complete.", "success")
    return redirect(url_for("season_hub"))


@app.route("/season/schedule")
def season_schedule():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    game = get_game()
    _, _, lookup, season_id, season_data = _season_context()
    if season_data is None:
        flash("Start a season first.", "error")
        return redirect(url_for("season_hub"))

    day_raw = request.args.get("day", "").strip()
    schedule_day = season_data.get("current_day", 1)
    max_day = season_data.get("max_day", schedule_day)
    if day_raw:
        day_value, err = _require_int(day_raw, "Day", minimum=1, maximum=max_day)
        if err:
            flash(err, "error")
        else:
            schedule_day = day_value

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
        flash("Start a season first.", "error")
        return redirect(url_for("season_hub"))

    schedule_game = find_schedule_game(season_data, game_id)
    if schedule_game is None or not schedule_game.get("played"):
        flash("Box score not available for that game.", "error")
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

    _, _, lookup, season_id, season_data = _season_context()
    if season_data is None:
        flash("Start a season first.", "error")
        return redirect(url_for("season_hub"))

    count = sim_day(season_data, lookup)
    if not _save_season(season_id, season_data):
        return redirect(url_for("season_hub"))
    flash(f"Simulated day {season_data.get('current_day', 1) - 1}: {count} games.", "success")
    return redirect(url_for("season_hub"))


@app.route("/season/sim/week", methods=["POST"])
def season_sim_week():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    _, _, lookup, season_id, season_data = _season_context()
    if season_data is None:
        flash("Start a season first.", "error")
        return redirect(url_for("season_hub"))

    count = sim_week(season_data, lookup)
    if not _save_season(season_id, season_data):
        return redirect(url_for("season_hub"))
    flash(f"Simulated one week: {count} games.", "success")
    return redirect(url_for("season_hub"))


@app.route("/season/sim/trade-deadline", methods=["POST"])
def season_sim_trade_deadline():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    _, _, lookup, season_id, season_data = _season_context()
    if season_data is None:
        flash("Start a season first.", "error")
        return redirect(url_for("season_hub"))

    count = sim_to_trade_deadline(season_data, lookup)
    if not _save_season(season_id, season_data):
        return redirect(url_for("season_hub"))
    flash(f"Simulated to trade deadline (~55 GP): {count} games.", "success")
    return redirect(url_for("season_hub"))


@app.route("/season/playoffs", methods=["GET", "POST"])
def season_playoffs():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    game = get_game()
    _, _, lookup, season_id, season_data = _season_context()
    if season_data is None:
        flash("Start a season first.", "error")
        return redirect(url_for("season_hub"))

    if request.method == "POST" and season_data.get("playoffs") is None:
        if not regular_season_complete(season_data):
            sim_rest_of_season(season_data, lookup)
        seed_playoffs(season_data, lookup)
        if not _save_season(season_id, season_data):
            return redirect(url_for("season_playoffs"))
        flash("Playoffs seeded.", "success")
        return redirect(url_for("season_playoffs"))

    east_standings = standings_table(season_data, conference="East")
    west_standings = standings_table(season_data, conference="West")
    bracket = playoff_bracket_view(season_data, user_team_id=game["team_id"]) if season_data.get("playoffs") else None
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


@app.route("/season/sim/playoffs", methods=["POST"])
def season_sim_playoffs():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    sim_mode = request.form.get("mode", "round")
    _, _, lookup, season_id, season_data = _season_context()
    if season_data is None or season_data.get("playoffs") is None:
        flash("Start playoffs first.", "error")
        return redirect(url_for("season_playoffs"))

    if sim_mode == "all":
        count = simulate_all_playoffs(season_data, lookup)
        message = "Playoffs complete."
        if season_data.get("playoffs", {}).get("champion_name"):
            message = f"Champion: {season_data['playoffs']['champion_name']}"
        flash(message, "success")
    else:
        count = advance_playoff_round(season_data, lookup)
        flash(f"Simulated playoff round: {count} series finished.", "success")

    if not _save_season(season_id, season_data):
        return redirect(url_for("season_playoffs"))
    return redirect(url_for("season_playoffs"))


@app.route("/season/draft", methods=["GET"])
def season_draft():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    game = get_game()
    _, _, lookup, season_id, season_data = _season_context()
    if season_data is None:
        flash("Start a season first.", "error")
        return redirect(url_for("season_hub"))

    phase = season_data.get("phase")
    if phase == "complete":
        return render_template(
            "draft.html",
            page_title="Draft",
            season=season_data,
            phase=phase,
            board=None,
            user_team_id=game["team_id"],
            positions_label=positions_label,
        )

    if phase not in {"draft", "offseason"}:
        flash("Draft is not available yet.", "error")
        return redirect(url_for("season_hub"))

    board = draft_board_context(season_data, game["team_id"], lookup)
    for prospect in board.get("prospect_options", []):
        prospect["upside_tier"] = scouting_upside_tier(prospect)
    return render_template(
        "draft.html",
        page_title="Draft",
        season=season_data,
        phase=phase,
        board=board,
        user_team_id=game["team_id"],
        positions_label=positions_label,
    )


@app.route("/season/draft/start", methods=["POST"])
def season_draft_start():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    _, _, lookup, season_id, season_data = _season_context()
    if season_data is None:
        flash("Start a season first.", "error")
        return redirect(url_for("season_hub"))

    if season_data.get("phase") != "complete":
        flash("Draft can only start after playoffs.", "error")
        return redirect(url_for("season_draft"))

    start_draft(season_data, lookup)
    if not _save_season(season_id, season_data):
        return redirect(url_for("season_draft"))
    flash("Draft started.", "success")
    return redirect(url_for("season_draft"))


@app.route("/season/draft/pick", methods=["POST"])
def season_draft_pick():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    game = get_game()
    _, _, lookup, season_id, season_data = _season_context()
    if season_data is None or season_data.get("phase") != "draft":
        flash("No draft in progress.", "error")
        return redirect(url_for("season_draft"))

    option_raw = request.form.get("prospect_index", "0").strip()
    option_index, err = _require_int(option_raw, "prospect selection", minimum=0)
    state = season_data.get("draft_state") or {}
    options = state.get("prospect_options", [])
    if err or option_index is None or option_index >= len(options) or not options:
        flash("Select a valid prospect.", "error")
        return redirect(url_for("season_draft"))
    prospect = options[option_index]

    ok, message = make_pick(season_data, game["team_id"], prospect=prospect)
    if not _save_season(season_id, season_data):
        return redirect(url_for("season_draft"))
    flash(message, "success")
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
        flash("No draft in progress.", "error")
        return redirect(url_for("season_draft"))

    if sim_mode == "rest":
        count = sim_rest_of_draft(season_data, auto_user_picks=True)
        message = f"Simulated {count} picks. Draft complete."
    else:
        count = sim_draft_to_user_pick(season_data, game["team_id"])
        message = f"Simulated {count} CPU picks to your turn."

    if not _save_season(season_id, season_data):
        return redirect(url_for("season_draft"))
    flash(message, "success")
    return redirect(url_for("season_draft"))


@app.route("/season/advance", methods=["POST"])
def season_advance():
    redirect_response = require_game()
    if redirect_response is not None:
        return redirect_response

    _, _, lookup, season_id, season_data = _season_context()
    if season_data is None:
        flash("Start a season first.", "error")
        return redirect(url_for("season_hub"))

    if season_data.get("phase") != "offseason":
        flash("Complete the draft before advancing.", "error")
        return redirect(url_for("season_draft"))

    advance_season(season_data)
    if not _save_season(season_id, season_data):
        return redirect(url_for("season_draft"))
    message = f"Welcome to the {season_data['season_year']} season!"
    retirements = season_data.get("last_retirements") or []
    if retirements:
        names = ", ".join(f"{item['name']} ({item['age']})" for item in retirements[:8])
        if len(retirements) > 8:
            names += f", +{len(retirements) - 8} more"
        message = f"{message} Retired: {names}."
    flash(message, "success")
    return redirect(url_for("season_hub"))


def _admin_guard(*, require_auth=True):
    if not ADMIN_ENABLED:
        flash("Admin panel is disabled.", "error")
        return redirect(url_for("index"))
    if require_auth and not session.get("admin_authenticated"):
        flash("Admin login required.", "error")
        return redirect(url_for("admin_login"))
    return None


def _admin_player_form_data(form):
    overclock = form.get("overclock") == "on"
    try:
        career = parse_career_from_form(form, overclocked=overclock)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    return {
        "name": form.get("name", ""),
        "age": form.get("age", 19),
        "positions": form.getlist("positions"),
        "attributes": {key: form.get(key) for key in ATTRIBUTE_KEYS},
        "potential": form.get("potential") or None,
        "overclock": overclock,
        "career": career,
    }


def _admin_season_context():
    _, _, lookup, season_id, season_data = _season_context()
    teams = list_season_teams(season_data) if season_data else []
    return season_id, season_data, lookup, teams


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if not ADMIN_ENABLED:
        flash("Admin panel is disabled.", "error")
        return redirect(url_for("index"))
    if session.get("admin_authenticated"):
        return redirect(url_for("admin_panel"))
    if request.method == "POST":
        password = request.form.get("password", "")
        if password == ADMIN_PASSWORD:
            session["admin_authenticated"] = True
            flash("Admin access granted.", "success")
            return redirect(url_for("admin_panel"))
        flash("Incorrect password.", "error")
    return render_template("admin_login.html", page_title="Admin Login")


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("admin_authenticated", None)
    flash("Logged out of admin.", "success")
    return redirect(url_for("index"))


@app.route("/admin")
def admin_panel():
    blocked = _admin_guard()
    if blocked is not None:
        return blocked

    season_id, season_data, _, teams = _admin_season_context()
    return render_template(
        "admin.html",
        page_title="Admin",
        custom_players=list_custom_players(),
        attribute_keys=ATTRIBUTE_KEYS,
        valid_positions=VALID_POSITIONS,
        season_id=season_id,
        season_data=season_data,
        teams=teams,
    )


@app.route("/admin/players", methods=["POST"])
def admin_add_player():
    blocked = _admin_guard()
    if blocked is not None:
        return blocked

    try:
        form_data = _admin_player_form_data(request.form)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin_panel"))

    assign_team_id = request.form.get("assign_team_id", "").strip()

    try:
        entry = add_custom_player(**form_data)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin_panel"))
    except CustomPlayersWriteError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin_panel"))

    message = "Custom player added to the draft pool."
    if assign_team_id.isdigit():
        season_id, season_data, _, _ = _admin_season_context()
        if season_data:
            ok, _, assign_message = admin_place_custom_on_team(
                season_data,
                entry["custom_id"],
                int(assign_team_id),
            )
            if ok:
                if not _save_season(season_id, season_data):
                    return redirect(url_for("admin_panel"))
                message = assign_message
            else:
                message = f"{message} {assign_message}"
        else:
            message = f"{message} Start a season to assign players to teams."

    flash(message, "success")
    return redirect(url_for("admin_panel"))


@app.route("/admin/players/<custom_id>/edit", methods=["GET", "POST"])
def admin_edit_custom_player(custom_id):
    blocked = _admin_guard()
    if blocked is not None:
        return blocked

    player = get_custom_player(custom_id)
    if not player:
        flash("Custom player not found.", "error")
        return redirect(url_for("admin_panel"))

    if request.method == "POST":
        try:
            form_data = _admin_player_form_data(request.form)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("admin_edit_custom_player", custom_id=custom_id))
        try:
            updated = update_custom_player(custom_id, **form_data)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("admin_edit_custom_player", custom_id=custom_id))
        except CustomPlayersWriteError as exc:
            flash(str(exc), "error")
            return redirect(url_for("admin_edit_custom_player", custom_id=custom_id))
        if updated:
            flash(f"Updated {updated['name']}.", "success")
        else:
            flash("Custom player not found.", "error")
        return redirect(url_for("admin_panel"))

    return render_template(
        "admin_edit_custom.html",
        page_title=f"Edit {player['name']}",
        player=player,
        attribute_keys=ATTRIBUTE_KEYS,
        valid_positions=VALID_POSITIONS,
    )


@app.route("/admin/players/<custom_id>/delete", methods=["POST"])
def admin_delete_player(custom_id):
    blocked = _admin_guard()
    if blocked is not None:
        return blocked

    try:
        if delete_custom_player(custom_id):
            flash("Custom player removed.", "success")
        else:
            flash("Custom player not found.", "error")
    except CustomPlayersWriteError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin_panel"))


@app.route("/admin/rosters")
def admin_rosters():
    blocked = _admin_guard()
    if blocked is not None:
        return blocked

    season_id, season_data, lookup, teams = _admin_season_context()
    team_id_raw = request.args.get("team_id", "").strip()
    selected_team_id = int(team_id_raw) if team_id_raw.isdigit() else None
    if selected_team_id is None and teams:
        selected_team_id = teams[0]["team_id"]

    roster = []
    selected_team = None
    free_agents = []
    if season_data and selected_team_id is not None:
        roster = roster_players(season_data, selected_team_id, lookup)
        selected_team = next((team for team in teams if team["team_id"] == selected_team_id), None)
        free_agents = sorted(
            free_agent_players(season_data, lookup),
            key=lambda player: player.get("name", "").lower(),
        )

    return render_template(
        "admin_rosters.html",
        page_title="Admin Rosters",
        season_data=season_data,
        teams=teams,
        selected_team_id=selected_team_id,
        selected_team=selected_team,
        roster=roster,
        custom_players=list_custom_players(),
        free_agents=free_agents,
    )


@app.route("/admin/rosters/assign-custom", methods=["POST"])
def admin_roster_assign_custom():
    blocked = _admin_guard()
    if blocked is not None:
        return blocked

    season_id, season_data, _, _ = _admin_season_context()
    if not season_data:
        flash("No active season.", "error")
        return redirect(url_for("admin_rosters"))

    team_id = request.form.get("team_id", "").strip()
    custom_id = request.form.get("custom_id", "").strip()
    if not team_id.isdigit() or not custom_id:
        flash("Team and custom player are required.", "error")
        return redirect(url_for("admin_rosters", team_id=team_id or None))

    ok, _, message = admin_place_custom_on_team(season_data, custom_id, int(team_id))
    if ok and not _save_season(season_id, season_data):
        return redirect(url_for("admin_rosters", team_id=team_id))
    flash(message, "success")
    return redirect(url_for("admin_rosters", team_id=team_id))


@app.route("/admin/rosters/release", methods=["POST"])
def admin_roster_release():
    blocked = _admin_guard()
    if blocked is not None:
        return blocked

    season_id, season_data, _, _ = _admin_season_context()
    if not season_data:
        flash("No active season.", "error")
        return redirect(url_for("admin_rosters"))

    team_id = request.form.get("team_id", "").strip()
    player_id = request.form.get("player_id", "").strip()
    if not team_id.isdigit() or not player_id.isdigit():
        flash("Invalid release request.", "error")
        return redirect(url_for("admin_rosters", team_id=team_id or None))

    ok, message = admin_release_player(season_data, int(team_id), int(player_id))
    if ok and not _save_season(season_id, season_data):
        return redirect(url_for("admin_rosters", team_id=team_id))
    flash(message, "success")
    return redirect(url_for("admin_rosters", team_id=team_id))


@app.route("/admin/rosters/move", methods=["POST"])
def admin_roster_move():
    blocked = _admin_guard()
    if blocked is not None:
        return blocked

    season_id, season_data, _, _ = _admin_season_context()
    if not season_data:
        flash("No active season.", "error")
        return redirect(url_for("admin_rosters"))

    player_id = request.form.get("player_id", "").strip()
    dest_team_id = request.form.get("dest_team_id", "").strip()
    source_team_id = request.form.get("source_team_id", "").strip()
    if not player_id.isdigit() or not dest_team_id.isdigit():
        flash("Invalid move request.", "error")
        return redirect(url_for("admin_rosters", team_id=source_team_id or None))

    ok, message = admin_move_player(season_data, int(player_id), int(dest_team_id))
    if ok:
        if not _save_season(season_id, season_data):
            return redirect(url_for("admin_rosters", team_id=source_team_id or dest_team_id))
        source_team_id = dest_team_id
    flash(message, "success")
    return redirect(url_for("admin_rosters", team_id=source_team_id or dest_team_id))


@app.route("/admin/rosters/sign-fa", methods=["POST"])
def admin_roster_sign_fa():
    blocked = _admin_guard()
    if blocked is not None:
        return blocked

    season_id, season_data, _, _ = _admin_season_context()
    if not season_data:
        flash("No active season.", "error")
        return redirect(url_for("admin_rosters"))

    team_id = request.form.get("team_id", "").strip()
    player_id = request.form.get("player_id", "").strip()
    if not team_id.isdigit() or not player_id.isdigit():
        flash("Invalid signing request.", "error")
        return redirect(url_for("admin_rosters", team_id=team_id or None))

    ok, message = admin_sign_free_agent(season_data, int(team_id), int(player_id))
    if ok and not _save_season(season_id, season_data):
        return redirect(url_for("admin_rosters", team_id=team_id))
    flash(message, "success")
    return redirect(url_for("admin_rosters", team_id=team_id))


@app.route("/admin/league-players/<int:player_id>/edit", methods=["GET", "POST"])
def admin_edit_league_player(player_id):
    blocked = _admin_guard()
    if blocked is not None:
        return blocked

    season_id, season_data, lookup, _ = _admin_season_context()
    if not season_data:
        flash("No active season.", "error")
        return redirect(url_for("admin_rosters"))

    player = lookup.get(player_id)
    if not player:
        flash("Player not found.", "error")
        return redirect(url_for("admin_rosters"))

    init_career_profile(player)

    if request.method == "POST":
        overclock = player.get("is_overclocked", False)
        try:
            career = parse_career_from_form(request.form, overclocked=overclock)
            attributes = parse_attributes_from_form(request.form, overclocked=overclock)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("admin_edit_league_player", player_id=player_id))
        ok, message = admin_update_league_player(
            season_data,
            player_id,
            career=career,
            attributes=attributes,
        )
        if ok:
            if not _save_season(season_id, season_data):
                return redirect(url_for("admin_edit_league_player", player_id=player_id))
        flash(message, "success")
        return redirect(url_for("admin_rosters", team_id=player.get("team_id")))

    edit_player = dict(player)
    edit_player["attributes"] = player.get("base_attributes") or effective_attributes(player)

    return render_template(
        "admin_edit_league.html",
        page_title=f"Edit {player.get('name', player_id)}",
        player=player,
        edit_player=edit_player,
        attribute_keys=ATTRIBUTE_KEYS,
    )


@app.route("/refresh", methods=["POST"])
def refresh():
    result = refresh_cache()
    session["cache_flash"] = result
    return redirect(url_for("search"))


@app.errorhandler(500)
def server_error(exc):
    logger.exception("Unhandled server error")
    return (
        render_template(
            "error.html",
            page_title="Something went wrong",
            message="Something went wrong. Please try again.",
        ),
        500,
    )


if not app.debug:

    @app.errorhandler(Exception)
    def uncaught_error(exc):
        logger.exception("Unhandled exception")
        return (
            render_template(
                "error.html",
                page_title="Something went wrong",
                message="Something went wrong. Please try again.",
            ),
            500,
        )


if os.getenv("ENABLE_SCHEDULER", "true").lower() == "true":
    start_scheduler(app)


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1")
