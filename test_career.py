"""Tests for player aging, attribute curves, and retirement."""

import random
import unittest

import cache
from attributes import (
    age_multiplier,
    apply_attributes,
    apply_season_aging,
    effective_attributes,
    init_career_profile,
    refresh_player_from_attributes,
    season_averages_from_attributes_deterministic,
)
from ratings import apply_ratings
from season import advance_season, init_season


class CareerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        players = list(cache.load_cache().get("players", []))
        apply_ratings(players)
        apply_attributes(players)
        cls.players = players

    def test_retirement_age_range(self):
        rng = random.Random(1)
        for _ in range(50):
            player = dict(self.players[_ % len(self.players)])
            player.pop("retirement_age", None)
            player.pop("peak_age", None)
            player.pop("base_attributes", None)
            init_career_profile(player, rng)
            self.assertGreaterEqual(player["retirement_age"], 38)
            self.assertLessEqual(player["retirement_age"], 43)
            self.assertGreaterEqual(player["peak_age"], 28)
            self.assertLessEqual(player["peak_age"], 30)

    def test_attributes_grow_then_decline(self):
        player = dict(self.players[0])
        player["age"] = 22
        player["peak_age"] = 29
        player.pop("base_attributes", None)
        init_career_profile(player, random.Random(2))
        young_scoring = effective_attributes(player)["scoring"]

        player["age"] = 29
        peak_scoring = effective_attributes(player)["scoring"]

        player["age"] = 36
        old_scoring = effective_attributes(player)["scoring"]

        self.assertLess(young_scoring, peak_scoring)
        self.assertGreater(peak_scoring, old_scoring)

    def test_age_multiplier_peak_and_decline(self):
        self.assertAlmostEqual(age_multiplier(29, 29), 1.0)
        self.assertLess(age_multiplier(22, 29), age_multiplier(28, 29))
        self.assertLess(age_multiplier(36, 29), age_multiplier(29, 29))

    def test_player_retires_and_is_removed(self):
        season = init_season(self.players, season_year=2026, rng=random.Random(3))
        player = min(season["players"].values(), key=lambda item: item.get("age") or 99)
        player_id = player["id"]
        team_id = player["team_id"]
        player["age"] = 25
        player["retirement_age"] = 26
        for other in season["players"].values():
            if other["id"] != player_id:
                other["retirement_age"] = 99

        retirements = apply_season_aging(season, rng=random.Random(4))

        self.assertEqual(len(retirements), 1)
        self.assertEqual(retirements[0]["player_id"], player_id)
        self.assertNotIn(str(player_id), season["players"])
        self.assertNotIn(player_id, season["rosters"][str(team_id)])

    def test_advance_season_drops_retired_players(self):
        season = init_season(self.players, season_year=2026, rng=random.Random(5))
        target = min(season["players"].values(), key=lambda item: item.get("age") or 99)
        target["age"] = 25
        target["retirement_age"] = 26
        for other in season["players"].values():
            if other["id"] != target["id"]:
                other["retirement_age"] = 99
        before_count = len(season["players"])

        advance_season(season, rng=random.Random(6))

        self.assertEqual(len(season["players"]), before_count - 1)
        self.assertNotIn(str(target["id"]), season["players"])
        self.assertTrue(season.get("last_retirements"))

    def test_deterministic_stat_refresh(self):
        attrs = {
            "scoring": 80,
            "playmaking": 70,
            "rebounding": 60,
            "defense": 65,
            "efficiency": 75,
            "stamina": 72,
        }
        first = season_averages_from_attributes_deterministic(attrs)
        second = season_averages_from_attributes_deterministic(attrs)
        self.assertEqual(first, second)

    def test_refresh_player_updates_display_stats(self):
        player = dict(self.players[1])
        init_career_profile(player, random.Random(7))
        refresh_player_from_attributes(player)
        expected = season_averages_from_attributes_deterministic(player["attributes"], player)
        self.assertEqual(player["ppg"], expected["ppg"])

    def test_potential_caps_development(self):
        player = dict(self.players[2])
        player["age"] = 22
        player["peak_age"] = 29
        player["overall"] = 55
        player["potential"] = 62
        player["development_rate"] = 1.0
        player.pop("base_attributes", None)
        init_career_profile(player, random.Random(8))
        season = {"players": {str(player["id"]): player}, "rosters": {}}
        for _ in range(5):
            apply_season_aging(season, rng=random.Random(9))
            if player["age"] >= player["retirement_age"]:
                break
        peak_attrs = effective_attributes(player)
        self.assertLessEqual(max(peak_attrs.values()), 75)

    def test_careers_do_not_all_converge_to_elite(self):
        season = init_season(self.players, season_year=2026, rng=random.Random(10))
        for _ in range(6):
            apply_season_aging(season, rng=random.Random(11 + _))
        overalls = [player.get("overall") or 0 for player in season["players"].values()]
        self.assertGreater(max(overalls) - min(overalls), 15)
        self.assertLess(sum(1 for ovr in overalls if ovr >= 95), len(overalls) * 0.2)

    def test_multi_season_ppg_stays_realistic(self):
        season = init_season(self.players, season_year=2026, rng=random.Random(12))
        for year in range(6):
            apply_season_aging(season, rng=random.Random(20 + year))
        ppgs = [player.get("ppg") or 0 for player in season["players"].values()]
        self.assertLessEqual(max(ppgs), 32.0)
        elite_count = sum(1 for ppg in ppgs if ppg >= 28)
        self.assertLess(elite_count, len(ppgs) * 0.05)

    def test_same_potential_players_have_different_stat_lines(self):
        base = dict(self.players[0])
        player_a = dict(base)
        player_a["id"] = 8800001
        player_b = dict(base)
        player_b["id"] = 8800002
        for player in (player_a, player_b):
            player["age"] = 22
            player["overall"] = 70
            player["potential"] = 82
            player.pop("peak_attributes", None)
            player.pop("stat_modifiers", None)
            player.pop("base_attributes", None)
            init_career_profile(player, random.Random(player["id"]))
        self.assertNotEqual(player_a["stat_modifiers"], player_b["stat_modifiers"])
        refresh_player_from_attributes(player_a)
        refresh_player_from_attributes(player_b)
        self.assertNotEqual(player_a["ppg"], player_b["ppg"])


if __name__ == "__main__":
    unittest.main()
