import random

from flask import redirect, session, url_for

from difficulty import normalize_difficulty
from fetcher import fetch_team, fetch_teams
import season_store

SESSION_GAME_STARTED = "game_started"
SESSION_TEAM_ID = "team_id"
SESSION_TEAM_NAME = "team_name"
SESSION_SEASON_ID = "season_id"
SESSION_SEASON_RECOVERY = "season_recovery"
SESSION_DIFFICULTY = "difficulty"


def get_game(current_session=None):
    current_session = current_session if current_session is not None else session
    if not current_session.get(SESSION_GAME_STARTED):
        return None

    return {
        "started": True,
        "team_id": current_session.get(SESSION_TEAM_ID),
        "team_name": current_session.get(SESSION_TEAM_NAME),
        "difficulty": normalize_difficulty(current_session.get(SESSION_DIFFICULTY)),
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

    season_data, recovery_status = season_store.load_season(season_id)
    if recovery_status == "restored":
        current_session[SESSION_SEASON_RECOVERY] = "restored"
    elif season_data is None:
        current_session.pop(SESSION_SEASON_ID, None)
        current_session[SESSION_SEASON_RECOVERY] = "corrupt"
        return None, None

    return season_id, season_data


def consume_season_recovery_notice(current_session=None):
    current_session = current_session if current_session is not None else session
    return current_session.pop(SESSION_SEASON_RECOVERY, None)


def save_session_season(season_id, season_data, current_session=None):
    season_store.save_season(season_id, season_data)
    set_season_id(season_id, current_session)


def start_game(current_session=None, team_id=None, difficulty=None):
    current_session = current_session if current_session is not None else session
    if team_id is not None:
        team = fetch_team(team_id)
        if not team:
            return None
    else:
        team = random.choice(fetch_teams())
    current_session[SESSION_GAME_STARTED] = True
    current_session[SESSION_TEAM_ID] = team["id"]
    current_session[SESSION_TEAM_NAME] = team["full_name"]
    current_session[SESSION_DIFFICULTY] = normalize_difficulty(difficulty)
    return team


def clear_game(current_session=None):
    current_session = current_session if current_session is not None else session
    season_id = current_session.pop(SESSION_SEASON_ID, None)
    if season_id:
        season_store.delete_season(season_id)
    current_session.pop(SESSION_GAME_STARTED, None)
    current_session.pop(SESSION_TEAM_ID, None)
    current_session.pop(SESSION_TEAM_NAME, None)
    current_session.pop(SESSION_DIFFICULTY, None)


def require_game():
    if get_game() is None:
        return redirect(url_for("index"))
    return None
