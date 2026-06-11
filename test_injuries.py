"""Tests for in-season injury system."""

import random
import tempfile
import unittest
from unittest.mock import patch

import season_store
from attributes import apply_attributes
from injuries import (
    drain_pending_notifications,
    injured_player_ids,
    player_is_injured,
    roll_game_injuries,
)
from ratings import apply_ratings
import cache
from season import init_season, league_lookup, roster_players, sim_day
from simulation import simulate_game_with_box_score


class InjuryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig_seasons_dir = season_store.SEASONS_DIR
        cls._temp_dir = tempfile.mkdtemp()
        season_store.SEASONS_DIR = cls._temp_dir

    @classmethod
    def tearDownClass(cls):
        season_store.SEASONS_DIR = cls._orig_seasons_dir

    def setUp(self):
        cache_data = cache.load_cache()
        players = list(cache_data.get("players", []))
        apply_ratings(players)
        apply_attributes(players)
        self.rng = random.Random(7)
        self.season = init_season(players, season_year=2026, rng=self.rng)

    def test_roll_injury_sets_player_status(self):
        user_team = int(next(iter(self.season["rosters"])))
        lookup = league_lookup(self.season)
        roster = roster_players(self.season, user_team, lookup)
        for player in roster:
            player.pop("injury", None)

        with patch("injuries.INJURY_CHANCE_PER_GAME", 1.0):
            events = roll_game_injuries(
                self.season, user_team, roster, day=1, rng=random.Random(1)
            )

        self.assertTrue(events)
        self.assertTrue(any(player_is_injured(player) for player in roster))
        injured = next(player for player in roster if player_is_injured(player))
        self.assertGreater(injured["injury"]["games_remaining"], 0)
        self.assertTrue(self.season["pending_notifications"])

    def test_injured_player_excluded_from_box_score(self):
        user_team = int(next(iter(self.season["rosters"])))
        partner_team = int(next(tid for tid in self.season["rosters"] if int(tid) != user_team))
        lookup = league_lookup(self.season)
        home_roster = roster_players(self.season, user_team, lookup)
        away_roster = roster_players(self.season, partner_team, lookup)
        injured = home_roster[0]
        injured["injury"] = {"type": "ankle", "games_remaining": 3, "day_reported": 1}

        injured_ids = injured_player_ids(home_roster)
        result = simulate_game_with_box_score(
            home_roster,
            away_roster,
            rng=self.rng,
            home_exclude_ids=injured_ids,
        )
        box_ids = {line["player_id"] for line in result["home_box"]}
        self.assertNotIn(injured["id"], box_ids)

    def test_sim_day_queues_injury_notifications(self):
        lookup = league_lookup(self.season)
        self.season["pending_notifications"] = []
        sim_day(self.season, lookup, rng=random.Random(99))
        pending = drain_pending_notifications(self.season)
        self.assertIsInstance(pending, list)


if __name__ == "__main__":
    unittest.main()
