"""Tests for team OVR and participation penalties."""

import unittest

from ratings import (
    PARTICIPATION_GP_RATIO,
    TEAM_GP_PENALTY_START,
    _player_meets_participation,
    _team_overall_weight,
    compute_team_overall,
)


def _player(player_id, overall, season_gp=40, gp=40):
    return {
        "id": player_id,
        "overall": overall,
        "season_gp": season_gp,
        "gp": gp,
    }


class TeamOverallTests(unittest.TestCase):
    def test_no_penalty_before_team_game_20(self):
        star = _player(1, 95, season_gp=0)
        self.assertTrue(_player_meets_participation(star, 10))
        weight = _team_overall_weight(0, star, team_gp=10)
        self.assertAlmostEqual(weight, 2.5)

    def test_penalty_after_game_20_under_half_participation(self):
        part_timer = _player(2, 90, season_gp=10)
        self.assertFalse(_player_meets_participation(part_timer, 30))
        weight = _team_overall_weight(0, part_timer, team_gp=30)
        self.assertAlmostEqual(weight, 2.5 / 3)

    def test_no_penalty_at_half_participation(self):
        regular = _player(3, 88, season_gp=15)
        self.assertTrue(_player_meets_participation(regular, 30))

    def test_injured_star_lowers_team_ovr_after_game_20(self):
        roster = [
            _player(10, 95, season_gp=30),
            _player(11, 88, season_gp=28),
            _player(12, 85, season_gp=27),
            _player(13, 82, season_gp=26),
            _player(14, 80, season_gp=25),
            _player(15, 78, season_gp=5),
            _player(16, 76, season_gp=24),
            _player(17, 74, season_gp=23),
            _player(18, 72, season_gp=22),
        ]
        healthy = [dict(player, season_gp=30) for player in roster]
        full = compute_team_overall(healthy, team_gp=30)
        hurt = compute_team_overall(roster, team_gp=30)
        self.assertLess(hurt, full)


class SeasonGpTests(unittest.TestCase):
    def test_record_result_increments_season_gp(self):
        from season import _record_result, init_season
        import cache
        import random
        from ratings import apply_ratings
        from attributes import apply_attributes

        players = list(cache.load_cache().get("players", []))
        apply_ratings(players)
        apply_attributes(players)
        season = init_season(players, season_year=2026, rng=random.Random(1))
        game = season["schedule"][0]
        player_id = season["rosters"][str(game["home_id"])][0]
        player = season["players"][str(player_id)]
        before = player.get("season_gp", 0)

        _record_result(
            season,
            game,
            {
                "home_score": 110,
                "away_score": 100,
                "home_box": [{"player_id": player_id, "name": "Test", "min": 24, "pts": 20, "reb": 5, "ast": 4, "stl": 1, "blk": 0}],
                "away_box": [],
            },
        )
        self.assertEqual(player["season_gp"], before + 1)
        self.assertEqual(player["gp"], before + 1)

    def test_init_season_starts_gp_at_zero(self):
        from season import init_season
        import cache
        import random
        from ratings import apply_ratings
        from attributes import apply_attributes

        players = list(cache.load_cache().get("players", []))
        apply_ratings(players)
        apply_attributes(players)
        season = init_season(players, season_year=2026, rng=random.Random(2))
        for player in season["players"].values():
            self.assertEqual(player.get("gp"), 0)
            self.assertEqual(player.get("season_gp"), 0)

    def test_advance_season_resets_gp(self):
        from season import advance_season, init_season
        import cache
        import random
        from ratings import apply_ratings
        from attributes import apply_attributes

        players = list(cache.load_cache().get("players", []))
        apply_ratings(players)
        apply_attributes(players)
        season = init_season(players, season_year=2026, rng=random.Random(3))
        for player in season["players"].values():
            player["gp"] = 55
            player["season_gp"] = 55
            player["retirement_age"] = 99

        advance_season(season, rng=random.Random(4))

        for player in season["players"].values():
            self.assertEqual(player.get("gp"), 0)
            self.assertEqual(player.get("season_gp"), 0)


if __name__ == "__main__":
    unittest.main()
