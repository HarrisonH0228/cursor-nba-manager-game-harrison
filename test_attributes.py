"""Tests for player attributes and per-game box scores."""

import random
import unittest

import cache
from attributes import (
    allocate_minutes,
    apply_attributes,
    derive_attributes,
    ensure_positions,
    generate_rookie_attributes,
    generate_rookie_profile,
    position_stat_multipliers,
    season_averages_from_attributes,
    season_averages_from_attributes_deterministic,
)
from draft import generate_prospect
from ratings import apply_ratings
from season import init_season, league_lookup, sim_day
from simulation import simulate_game_with_box_score


class AttributeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cache_data = cache.load_cache()
        cls.players = list(cache_data.get("players", []))
        apply_ratings(cls.players)
        apply_attributes(cls.players)

    def test_derived_scoring_tracks_ppg(self):
        sorted_players = sorted(
            self.players,
            key=lambda player: player.get("ppg") or 0,
            reverse=True,
        )
        top = sorted_players[0]
        bottom = sorted_players[-1]
        self.assertGreater(
            top["attributes"]["scoring"],
            bottom["attributes"]["scoring"],
        )

    def test_apply_attributes_populates_all_keys(self):
        player = dict(self.players[0])
        player.pop("attributes", None)
        attrs = derive_attributes(player)
        for key in ("scoring", "playmaking", "rebounding", "defense", "efficiency", "stamina"):
            self.assertIn(key, attrs)
            self.assertGreaterEqual(attrs[key], 25)
            self.assertLessEqual(attrs[key], 99)

    def test_box_score_points_sum_to_team_score(self):
        rng = random.Random(7)
        team_id = self.players[0]["team_id"]
        roster = [player for player in self.players if player.get("team_id") == team_id]
        opponent = next(
            player["team_id"]
            for player in self.players
            if player.get("team_id") != team_id
        )
        away_roster = [player for player in self.players if player.get("team_id") == opponent]

        for _ in range(100):
            result = simulate_game_with_box_score(roster, away_roster, rng=rng)
            home_pts = sum(line["pts"] for line in result["home_box"])
            away_pts = sum(line["pts"] for line in result["away_box"])
            self.assertEqual(home_pts, result["home_score"])
            self.assertEqual(away_pts, result["away_score"])

    def test_minutes_sum_to_240(self):
        team_id = self.players[0]["team_id"]
        roster = [player for player in self.players if player.get("team_id") == team_id]
        minutes = allocate_minutes(roster)
        self.assertEqual(sum(minutes.values()), 240)

    def test_rookie_attributes_lower_than_stars(self):
        rng = random.Random(11)
        rookie_attrs = generate_rookie_attributes(55, rng)
        star = max(self.players, key=lambda player: player.get("overall") or 0)
        self.assertLess(rookie_attrs["scoring"], star["attributes"]["scoring"])

    def test_rookie_season_averages_from_attributes(self):
        rng = random.Random(3)
        attrs = generate_rookie_attributes(60, rng)
        stats = season_averages_from_attributes(attrs, rng)
        self.assertLess(stats["ppg"], 25)
        self.assertGreater(stats["ppg"], 0)

    def test_draft_prospect_has_attributes(self):
        season = init_season(self.players, season_year=2026, rng=random.Random(1))
        prospect = generate_prospect(season, 1, 1, 30, rng=random.Random(2))
        self.assertIn("attributes", prospect)
        self.assertIn("ppg", prospect)

    def test_regular_season_persists_box_scores(self):
        season = init_season(self.players, season_year=2026, rng=random.Random(4))
        lookup = league_lookup(season)
        sim_day(season, lookup, rng=random.Random(5))
        played_games = [game for game in season["schedule"] if game.get("played")]
        self.assertTrue(played_games)
        sample = played_games[0]
        self.assertIn("home_box", sample)
        self.assertIn("away_box", sample)
        self.assertEqual(
            sum(line["pts"] for line in sample["home_box"]),
            sample["home_score"],
        )

    def test_playoff_sim_produces_box_scores(self):
        team_id = self.players[0]["team_id"]
        roster = [player for player in self.players if player.get("team_id") == team_id]
        opponent_id = next(player["team_id"] for player in self.players if player["team_id"] != team_id)
        away_roster = [player for player in self.players if player.get("team_id") == opponent_id]
        result = simulate_game_with_box_score(roster, away_roster, rng=random.Random(9))
        self.assertTrue(result["home_box"])
        self.assertTrue(result["away_box"])

    def test_position_stat_profiles(self):
        attrs = {"scoring": 70, "playmaking": 70, "rebounding": 70, "defense": 70, "efficiency": 70, "stamina": 80}
        pg_stats = season_averages_from_attributes_deterministic(attrs, {"positions": ["PG"]})
        center_stats = season_averages_from_attributes_deterministic(attrs, {"positions": ["C"]})
        self.assertGreater(pg_stats["apg"], center_stats["apg"])
        self.assertGreater(center_stats["rpg"], pg_stats["rpg"])

    def test_multi_position_averages_multipliers(self):
        single = position_stat_multipliers(["PG"])
        dual = position_stat_multipliers(["PG", "SG"])
        self.assertAlmostEqual(dual["apg"], (single["apg"] + position_stat_multipliers(["SG"])["apg"]) / 2)

    def test_stat_display_caps(self):
        attrs = {"scoring": 99, "playmaking": 99, "rebounding": 99, "defense": 99, "efficiency": 99, "stamina": 99}
        player = {"positions": ["SG"], "stat_modifiers": {"ppg": 1.06, "rpg": 1.0, "apg": 1.0, "spg": 1.0, "bpg": 1.0}}
        stats = season_averages_from_attributes_deterministic(attrs, player)
        self.assertLessEqual(stats["ppg"], 32.0)

    def test_rookie_profile_assigns_positions(self):
        profile = generate_rookie_profile(60, rng=random.Random(5))
        self.assertIn("positions", profile)
        self.assertGreaterEqual(len(profile["positions"]), 1)


if __name__ == "__main__":
    unittest.main()
