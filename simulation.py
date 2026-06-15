import math
import random

from attributes import build_team_box_score

HOME_COURT_ADVANTAGE = 2.5
LOGISTIC_K = 0.12
PACE_STDEV = 0.06
MIN_TEAM_SCORE = 80


def win_prob(home_ovr, away_ovr):
    if home_ovr is None or away_ovr is None:
        return 0.5
    diff = (home_ovr + HOME_COURT_ADVANTAGE) - away_ovr
    return 1 / (1 + math.exp(-LOGISTIC_K * diff))


def _team_score(box):
    return sum(line["pts"] for line in box)


def _apply_score_floor(box, min_score):
    total = _team_score(box)
    if total >= min_score or total <= 0:
        return total

    factor = min_score / total
    for line in box:
        line["pts"] = max(0, round(line["pts"] * factor))
    diff = min_score - _team_score(box)
    if diff > 0:
        box[0]["pts"] += diff
    return _team_score(box)


def _break_tie(home_box, away_box, rng):
    home_score = _team_score(home_box)
    away_score = _team_score(away_box)
    if home_score != away_score or not home_box or not away_box:
        return home_score, away_score

    if rng.random() < 0.5:
        home_box[0]["pts"] += 1
    else:
        away_box[0]["pts"] += 1
    return _team_score(home_box), _team_score(away_box)


def simulate_game_with_box_score(home_roster, away_roster, rng=None):
    rng = rng or random.Random()

    away_pace = rng.gauss(1.0, PACE_STDEV)
    home_pace = rng.gauss(1.0, PACE_STDEV)

    away_box = build_team_box_score(away_roster, rng, pace_factor=away_pace)
    home_box = build_team_box_score(
        home_roster,
        rng,
        pace_factor=home_pace,
        home_boost=HOME_COURT_ADVANTAGE,
    )

    home_score = _team_score(home_box)
    away_score = _team_score(away_box)
    if home_score < MIN_TEAM_SCORE and away_score < MIN_TEAM_SCORE:
        home_score = _apply_score_floor(home_box, MIN_TEAM_SCORE)
        away_score = _apply_score_floor(away_box, MIN_TEAM_SCORE)

    home_score, away_score = _break_tie(home_box, away_box, rng)

    return {
        "home_score": home_score,
        "away_score": away_score,
        "home_box": home_box,
        "away_box": away_box,
    }


def simulate_game(home_roster, away_roster, rng=None):
    result = simulate_game_with_box_score(home_roster, away_roster, rng=rng)
    return result["home_score"], result["away_score"]
