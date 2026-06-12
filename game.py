import random

from flask import redirect, session, url_for

from errors import SeasonSaveError, get_logger
from fetcher import fetch_teams
import season_store

logger = get_logger(__name__)

SESSION_GAME_STARTED = "game_started"
SESSION_TEAM_ID = "team_id"
SESSION_TEAM_NAME = "team_name"
SESSION_SEASON_ID = "season_id"


def get_game(current_session=None):
    current_session = current_session if current_session is not None else session
    if not current_session.get(SESSION_GAME_STARTED):
        return None

    return {
        "started": True,
        "team_id": current_session.get(SESSION_TEAM_ID),
        "team_name": current_session.get(SESSION_TEAM_NAME),
    }


def get_season_id(current_session=None):
    current_session = current_session if current_session is not None else session
    return current_session.get(SESSION_SEASON_ID)


def set_season_id(season_id, current_session=None):
    current_session = current_session if current_session is not None else session
    current_session[SESSION_SEASON_ID] = season_id


def load_session_season(current_session=None):
    current_session = current_session if current_session is not None else session
    season_id = get_season_id(current_session)
    if not season_id:
        return None, None
    season_data = season_store.load_season(season_id)
    if season_data is None:
        logger.warning("Season unavailable or corrupt; clearing session season id %s", season_id)
        current_session.pop(SESSION_SEASON_ID, None)
        return None, None
    return season_id, season_data


def save_session_season(season_id, season_data, current_session=None):
    if not season_store.save_season(season_id, season_data):
        raise SeasonSaveError("Could not save game progress. Try again.")
    set_season_id(season_id, current_session)


def start_game(current_session=None):
    current_session = current_session if current_session is not None else session
    teams = fetch_teams()
    if not teams:
        raise RuntimeError("No teams available to start a game.")
    current_session.pop(SESSION_SEASON_ID, None)
    team = random.choice(teams)
    current_session[SESSION_GAME_STARTED] = True
    current_session[SESSION_TEAM_ID] = team["id"]
    current_session[SESSION_TEAM_NAME] = team["full_name"]
    return team


def clear_game(current_session=None):
    current_session = current_session if current_session is not None else session
    season_id = current_session.pop(SESSION_SEASON_ID, None)
    if season_id:
        season_store.delete_season(season_id)
    current_session.pop(SESSION_GAME_STARTED, None)
    current_session.pop(SESSION_TEAM_ID, None)
    current_session.pop(SESSION_TEAM_NAME, None)


def require_game():
    if get_game() is None:
        return redirect(url_for("index"))
    return None
