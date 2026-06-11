import math
import random

from attributes import _build_team_box_score
from ratings import compute_team_overall

HOME_COURT_ADVANTAGE = 2.5
LOGISTIC_K = 0.12
DEFAULT_BASE_SCORE = 112.0
SCORE_STDEV = 8.0
MARGIN_STDEV = 5.0


def win_prob(home_ovr, away_ovr):
    if home_ovr is None or away_ovr is None:
        return 0.5
    diff = (home_ovr + HOME_COURT_ADVANTAGE) - away_ovr
    return 1 / (1 + math.exp(-LOGISTIC_K * diff))


def _generate_team_scores(home_ovr, away_ovr, rng):
    home_chance = win_prob(home_ovr, away_ovr)
    home_wins = rng.random() < home_chance

    base = rng.gauss(DEFAULT_BASE_SCORE, SCORE_STDEV)
    margin = abs(rng.gauss(8, MARGIN_STDEV))
    if home_wins:
        home_score = round(base + margin / 2)
        away_score = round(base - margin / 2)
    else:
        home_score = round(base - margin / 2)
        away_score = round(base + margin / 2)

    home_score = max(home_score, 80)
    away_score = max(away_score, 80)
    if home_score == away_score:
        if home_wins:
            home_score += 1
        else:
            away_score += 1

    return home_score, away_score


def simulate_game_with_box_score(home_roster, away_roster, rng=None, home_team_gp=None, away_team_gp=None):
    rng = rng or random.Random()

    home_ovr = compute_team_overall(home_roster, team_gp=home_team_gp)
    away_ovr = compute_team_overall(away_roster, team_gp=away_team_gp)
    home_score, away_score = _generate_team_scores(home_ovr, away_ovr, rng)

    home_box = _build_team_box_score(home_roster, home_score, rng)
    away_box = _build_team_box_score(away_roster, away_score, rng)

    return {
        "home_score": home_score,
        "away_score": away_score,
        "home_box": home_box,
        "away_box": away_box,
    }


def simulate_game(home_roster, away_roster, rng=None):
    result = simulate_game_with_box_score(home_roster, away_roster, rng=rng)
    return result["home_score"], result["away_score"]
