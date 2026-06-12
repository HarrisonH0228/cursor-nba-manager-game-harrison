import math
import random

from attributes import (
    _adjust_box_score_points,
    _target_team_score,
    simulate_team_box_score_from_roster,
)
from ratings import compute_team_defense_rating, compute_team_overall

HOME_COURT_ADVANTAGE = 2.5
LOGISTIC_K = 0.12
OUTCOME_NUDGE_BLEND = 0.12
OUTCOME_NUDGE_MIN_OVR_GAP = 8
DEFENSE_SCORE_FACTOR = 0.004
DEFENSE_WIN_BLEND = 0.20


def win_prob(home_ovr, away_ovr, home_def=None, away_def=None):
    if home_ovr is None or away_ovr is None:
        return 0.5
    diff = (home_ovr + HOME_COURT_ADVANTAGE) - away_ovr
    if home_def is not None and away_def is not None:
        def_diff = (home_def - away_def) * DEFENSE_WIN_BLEND
        diff += def_diff
    return 1 / (1 + math.exp(-LOGISTIC_K * diff))


def _defense_target_adjustment(offense_ovr, defense_rating):
    """Shift target score based on opponent defense before box score build."""
    league_avg_def = 50
    def_diff = defense_rating - league_avg_def
    return -def_diff * DEFENSE_SCORE_FACTOR * 10


def _apply_score_adjustment(home_box, away_box, home_delta, away_delta):
    _adjust_box_score_points(home_box, home_delta)
    _adjust_box_score_points(away_box, away_delta)
    home_score = sum(line["pts"] for line in home_box)
    away_score = sum(line["pts"] for line in away_box)
    return home_score, away_score


def simulate_game_with_box_score(
    home_roster,
    away_roster,
    rng=None,
    home_team_gp=None,
    away_team_gp=None,
    home_exclude_ids=None,
    away_exclude_ids=None,
    difficulty_settings=None,
):
    rng = rng or random.Random()
    home_exclude_ids = home_exclude_ids or set()
    away_exclude_ids = away_exclude_ids or set()
    settings = difficulty_settings or {}
    nudge_blend = settings.get("outcome_nudge_blend", OUTCOME_NUDGE_BLEND)
    nudge_min_gap = settings.get("outcome_nudge_min_gap", OUTCOME_NUDGE_MIN_OVR_GAP)

    home_ovr = compute_team_overall(home_roster, team_gp=home_team_gp)
    away_ovr = compute_team_overall(away_roster, team_gp=away_team_gp)
    home_def = compute_team_defense_rating(home_roster, team_gp=home_team_gp)
    away_def = compute_team_defense_rating(away_roster, team_gp=away_team_gp)

    home_target = _target_team_score(home_roster, rng, team_gp=home_team_gp)
    away_target = _target_team_score(away_roster, rng, team_gp=away_team_gp)

    home_target = max(
        92,
        min(128, round(home_target + _defense_target_adjustment(home_ovr, away_def))),
    )
    away_target = max(
        92,
        min(128, round(away_target + _defense_target_adjustment(away_ovr, home_def))),
    )

    home_box, home_score = simulate_team_box_score_from_roster(
        home_roster,
        rng,
        pace_factor=1.0,
        exclude_player_ids=home_exclude_ids,
        team_gp=home_team_gp,
        target_score=home_target,
    )
    away_box, away_score = simulate_team_box_score_from_roster(
        away_roster,
        rng,
        pace_factor=1.0,
        exclude_player_ids=away_exclude_ids,
        team_gp=away_team_gp,
        target_score=away_target,
    )

    home_bonus = rng.randint(2, 3)
    home_score, away_score = _apply_score_adjustment(home_box, away_box, home_bonus, 0)

    expected_home_win = win_prob(home_ovr, away_ovr, home_def, away_def) >= 0.5
    actual_home_win = home_score > away_score
    ovr_gap = abs((home_ovr or 50) - (away_ovr or 50))

    if expected_home_win != actual_home_win and ovr_gap >= nudge_min_gap:
        combined = home_score + away_score
        shift = max(1, round(combined * nudge_blend * 0.5))
        if expected_home_win:
            home_score, away_score = _apply_score_adjustment(home_box, away_box, shift, -shift)
        else:
            home_score, away_score = _apply_score_adjustment(home_box, away_box, -shift, shift)

    if home_score == away_score:
        if (home_ovr or 0) >= (away_ovr or 0):
            home_score, away_score = _apply_score_adjustment(home_box, away_box, 1, 0)
        else:
            home_score, away_score = _apply_score_adjustment(home_box, away_box, 0, 1)

    return {
        "home_score": home_score,
        "away_score": away_score,
        "home_box": home_box,
        "away_box": away_box,
    }


def simulate_game(home_roster, away_roster, rng=None):
    result = simulate_game_with_box_score(home_roster, away_roster, rng=rng)
    return result["home_score"], result["away_score"]
