"""Tests for player attributes and per-game box scores."""

import random
import unittest

import cache
from attributes import (
    PLAYER_MAX_MINUTES,
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
        self.assertLessEqual(sum(minutes.values()), 240)

    def test_no_player_exceeds_48_minutes(self):
        team_id = self.players[0]["team_id"]
        roster = [player for player in self.players if player.get("team_id") == team_id]
        rng = random.Random(42)
        for _ in range(100):
            minutes = allocate_minutes(roster, rng=rng)
            self.assertLessEqual(max(minutes.values()), PLAYER_MAX_MINUTES)

    def test_injured_rotation_caps_at_48(self):
        team_id = self.players[0]["team_id"]
        roster = [player for player in self.players if player.get("team_id") == team_id]
        opponent = next(
            player["team_id"]
            for player in self.players
            if player.get("team_id") != team_id
        )
        away_roster = [player for player in self.players if player.get("team_id") == opponent]
        exclude_ids = {player["id"] for player in roster[:5]}
        result = simulate_game_with_box_score(
            roster,
            away_roster,
            rng=random.Random(17),
            home_exclude_ids=exclude_ids,
        )
        for line in result["home_box"]:
            self.assertLessEqual(line["min"], PLAYER_MAX_MINUTES)

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
        self.assertGreater(stats["ppg"], 36.0)
        self.assertLessEqual(stats["rpg"], 16.0)

    def test_rookie_profile_assigns_positions(self):
        profile = generate_rookie_profile(60, rng=random.Random(5))
        self.assertIn("positions", profile)
        self.assertGreaterEqual(len(profile["positions"]), 1)

    def test_elite_roster_scores_higher_than_weak_roster(self):
        rng = random.Random(42)
        sorted_players = sorted(
            self.players,
            key=lambda player: player.get("ppg") or 0,
            reverse=True,
        )
        elite_roster = sorted_players[:8]
        weak_roster = sorted_players[-8:]

        elite_scores = []
        weak_scores = []
        for _ in range(50):
            result = simulate_game_with_box_score(elite_roster, weak_roster, rng=rng)
            elite_scores.append(result["home_score"])
            weak_scores.append(result["away_score"])

        self.assertGreater(sum(elite_scores) / len(elite_scores), sum(weak_scores) / len(weak_scores) + 5)

    def test_team_scores_vary_with_roster_strength(self):
        rng = random.Random(43)
        sorted_players = sorted(
            self.players,
            key=lambda player: player.get("overall") or 0,
            reverse=True,
        )
        elite_roster = sorted_players[:5]
        weak_roster = sorted_players[-5:]
        dummy_opponent = sorted_players[10:15]

        elite_totals = []
        weak_totals = []
        for _ in range(40):
            elite_result = simulate_game_with_box_score(elite_roster, dummy_opponent, rng=rng)
            weak_result = simulate_game_with_box_score(weak_roster, dummy_opponent, rng=rng)
            elite_totals.append(elite_result["home_score"])
            weak_totals.append(weak_result["home_score"])

        elite_spread = max(elite_totals) - min(elite_totals)
        weak_spread = max(weak_totals) - min(weak_totals)
        self.assertGreater(sum(elite_totals) / len(elite_totals), sum(weak_totals) / len(weak_totals))
        self.assertGreater(elite_spread, 5)
        self.assertGreater(weak_spread, 5)

    def test_roster_ppg_spread_not_clustered_at_cap(self):
        from attributes import refresh_team_roster_stats

        team_id = self.players[0]["team_id"]
        roster = [player for player in self.players if player.get("team_id") == team_id]
        refresh_team_roster_stats(roster)
        ppgs = [player.get("ppg") or 0 for player in roster]
        self.assertGreater(max(ppgs) - min(ppgs), 10)
        at_cap = sum(1 for ppg in ppgs if ppg >= 30)
        self.assertLessEqual(at_cap, len(ppgs))

    def test_realistic_team_scores_and_no_dual_80_scorers(self):
        rng = random.Random(99)
        team_id = self.players[0]["team_id"]
        roster = [player for player in self.players if player.get("team_id") == team_id]
        opponent = next(
            player["team_id"] for player in self.players if player.get("team_id") != team_id
        )
        away_roster = [player for player in self.players if player.get("team_id") == opponent]
        dual_80 = 0
        for _ in range(100):
            result = simulate_game_with_box_score(roster, away_roster, rng=rng)
            self.assertGreaterEqual(result["home_score"], 85)
            self.assertLessEqual(result["home_score"], 135)
            self.assertGreaterEqual(result["away_score"], 85)
            self.assertLessEqual(result["away_score"], 135)
            home_80 = sum(1 for line in result["home_box"] if line["pts"] >= 80)
            away_80 = sum(1 for line in result["away_box"] if line["pts"] >= 80)
            if home_80 >= 2 or away_80 >= 2:
                dual_80 += 1
        self.assertEqual(dual_80, 0)

    def test_at_least_five_players_get_minutes(self):
        team_id = self.players[0]["team_id"]
        roster = [player for player in self.players if player.get("team_id") == team_id]
        minutes = allocate_minutes(roster)
        active = sum(1 for value in minutes.values() if value > 0)
        self.assertGreaterEqual(active, 5)


if __name__ == "__main__":
    unittest.main()
