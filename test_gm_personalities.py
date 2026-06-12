"""Tests for GM personality archetypes and integrations."""

import random
import unittest

import cache
from attributes import apply_attributes
from gm_personalities import (
    ARCHETYPES,
    cpu_fa_offer_multiplier,
    cpu_fa_team_priority,
    get_gm_profile,
    partner_trade_tolerance,
    personalities_enabled,
    pick_for_team,
    reroll_gm_personalities,
    trade_values_for_partner,
)
from ratings import apply_ratings
from season import advance_season, init_season, league_lookup
from trade import TRADE_TOLERANCE


class GmPersonalityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cache_data = cache.load_cache()
        players = list(cache_data.get("players", []))
        apply_ratings(players)
        apply_attributes(players)
        cls.rng = random.Random(42)
        cls.season = init_season(players, season_year=2026, rng=cls.rng)
        cls.lookup = league_lookup(cls.season)

    def test_first_season_personalities_disabled(self):
        self.assertFalse(self.season.get("gm_personalities_enabled"))
        self.assertEqual(get_gm_profile(self.season, 1)["archetype"], "balanced")

    def test_advance_season_enables_personalities(self):
        cache_data = cache.load_cache()
        players = list(cache_data.get("players", []))
        apply_ratings(players)
        apply_attributes(players)
        season = init_season(players, season_year=2026, rng=random.Random(7))
        season["phase"] = "offseason"
        advance_season(season, rng=random.Random(7))
        self.assertTrue(season.get("gm_personalities_enabled"))
        profiles = season.get("gm_profiles") or {}
        self.assertGreater(len(profiles), 0)
        for profile in profiles.values():
            self.assertIn(profile["archetype"], ARCHETYPES)

    def test_reroll_skips_user_team(self):
        season = dict(self.season)
        season["user_team_id"] = int(next(iter(season["rosters"])))
        reroll_gm_personalities(season, rng=random.Random(99))
        self.assertNotIn(str(season["user_team_id"]), season["gm_profiles"])

    def test_partner_tolerance_varies_by_archetype(self):
        season = dict(self.season)
        season["gm_personalities_enabled"] = True
        season["gm_profiles"] = {
            "2": {"archetype": "cheap", "trade_tolerance": 8},
            "3": {"archetype": "super_team_builder", "trade_tolerance": 20},
        }
        self.assertLess(partner_trade_tolerance(season, 2), TRADE_TOLERANCE)
        self.assertGreater(partner_trade_tolerance(season, 3), TRADE_TOLERANCE)

    def test_young_blood_prefers_younger_prospects(self):
        season = dict(self.season)
        season["gm_personalities_enabled"] = True
        team_id = int(next(iter(season["rosters"])))
        season["gm_profiles"] = {str(team_id): {"archetype": "young_blood", "trade_tolerance": 14}}
        prospects = [
            {"draft_rank": 5, "age": 19, "overall": 72},
            {"draft_rank": 6, "age": 24, "overall": 78},
        ]
        picked = pick_for_team(season, team_id, prospects)
        self.assertEqual(picked["age"], 19)

    def test_super_team_builder_prefers_highest_overall(self):
        season = dict(self.season)
        season["gm_personalities_enabled"] = True
        team_id = int(next(iter(season["rosters"])))
        season["gm_profiles"] = {
            str(team_id): {"archetype": "super_team_builder", "trade_tolerance": 20}
        }
        prospects = [
            {"draft_rank": 1, "overall": 68, "age": 20},
            {"draft_rank": 2, "overall": 81, "age": 22},
        ]
        picked = pick_for_team(season, team_id, prospects)
        self.assertEqual(picked["overall"], 81)

    def test_cheap_gm_lower_fa_multiplier(self):
        season = dict(self.season)
        season["gm_personalities_enabled"] = True
        team_id = int(next(iter(season["rosters"])))
        season["gm_profiles"] = {str(team_id): {"archetype": "cheap", "trade_tolerance": 8}}
        player = {"overall": 80, "age": 27}
        cheap_mult = cpu_fa_offer_multiplier(season, team_id, player)
        season["gm_profiles"][str(team_id)]["archetype"] = "balanced"
        balanced_mult = cpu_fa_offer_multiplier(season, team_id, player)
        self.assertLess(cheap_mult, balanced_mult)

    def test_trade_values_weighted_when_enabled(self):
        season = dict(self.season)
        season["gm_personalities_enabled"] = True
        user_team = int(next(iter(season["rosters"])))
        partner_team = int(next(tid for tid in season["rosters"] if int(tid) != user_team))
        season["gm_profiles"] = {
            str(partner_team): {"archetype": "super_team_builder", "trade_tolerance": 20}
        }
        star_id = season["rosters"][str(user_team)][0]
        star = self.lookup[star_id]
        star["overall"] = 88
        partner_in, partner_out = trade_values_for_partner(
            season, user_team, partner_team, [star_id], [], [], []
        )
        self.assertGreater(partner_in, 0)
        season["gm_personalities_enabled"] = False
        neutral_in, _ = trade_values_for_partner(
            season, user_team, partner_team, [star_id], [], [], []
        )
        self.assertGreaterEqual(partner_in, neutral_in)

    def test_personalities_enabled_flag(self):
        season = {"gm_personalities_enabled": False}
        self.assertFalse(personalities_enabled(season))
        season["gm_personalities_enabled"] = True
        self.assertTrue(personalities_enabled(season))

    def test_super_team_builder_fa_priority_for_stars(self):
        season = dict(self.season)
        season["gm_personalities_enabled"] = True
        team_id = int(next(iter(season["rosters"])))
        season["gm_profiles"] = {
            str(team_id): {"archetype": "super_team_builder", "trade_tolerance": 20}
        }
        star = {"overall": 90, "age": 28}
        role = {"overall": 65, "age": 28}
        self.assertGreater(
            cpu_fa_team_priority(season, team_id, star),
            cpu_fa_team_priority(season, team_id, role),
        )


if __name__ == "__main__":
    unittest.main()
