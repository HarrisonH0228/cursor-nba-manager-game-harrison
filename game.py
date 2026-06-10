import random

from flask import redirect, session, url_for

from fetcher import fetch_teams

SESSION_GAME_STARTED = "game_started"
SESSION_TEAM_ID = "team_id"
SESSION_TEAM_NAME = "team_name"


def get_game(current_session=None):
    current_session = current_session if current_session is not None else session
    if not current_session.get(SESSION_GAME_STARTED):
        return None

    return {
        "started": True,
        "team_id": current_session.get(SESSION_TEAM_ID),
        "team_name": current_session.get(SESSION_TEAM_NAME),
    }


def start_game(current_session=None):
    current_session = current_session if current_session is not None else session
    team = random.choice(fetch_teams())
    current_session[SESSION_GAME_STARTED] = True
    current_session[SESSION_TEAM_ID] = team["id"]
    current_session[SESSION_TEAM_NAME] = team["full_name"]
    return team


def clear_game(current_session=None):
    current_session = current_session if current_session is not None else session
    current_session.pop(SESSION_GAME_STARTED, None)
    current_session.pop(SESSION_TEAM_ID, None)
    current_session.pop(SESSION_TEAM_NAME, None)


def require_game():
    if get_game() is None:
        return redirect(url_for("index"))
    return None
