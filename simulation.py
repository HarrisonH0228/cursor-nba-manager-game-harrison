import math
import random

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


def simulate_game(home_roster, away_roster, rng=None):
    rng = rng or random

    home_ovr = compute_team_overall(home_roster)
    away_ovr = compute_team_overall(away_roster)
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
