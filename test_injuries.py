"""Tests for in-season injury system."""

import random
import tempfile
import unittest
from unittest.mock import patch

import season_store
from attributes import apply_attributes
from injuries import (
    build_dnp_list,
    drain_pending_notifications,
    game_exclude_ids,
    injured_player_ids,
    player_is_injured,
    roll_game_injuries,
    tick_injuries_after_game,
)
from ratings import apply_ratings
import cache
from season import (
    championship_count,
    init_season,
    league_lookup,
    record_championship,
    roster_players,
    sim_day,
)
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

        exclude_ids = game_exclude_ids(home_roster)
        result = simulate_game_with_box_score(
            home_roster,
            away_roster,
            rng=self.rng,
            home_exclude_ids=exclude_ids,
        )
        box_ids = {line["player_id"] for line in result["home_box"]}
        self.assertNotIn(injured["id"], box_ids)

    def test_sim_day_queues_injury_notifications(self):
        lookup = league_lookup(self.season)
        self.season["pending_notifications"] = []
        sim_day(self.season, lookup, rng=random.Random(99))
        pending = drain_pending_notifications(self.season)
        self.assertIsInstance(pending, list)

    def test_tick_injuries_clears_after_games(self):
        lookup = league_lookup(self.season)
        user_team = int(next(iter(self.season["rosters"])))
        roster = roster_players(self.season, user_team, lookup)
        player = roster[0]
        player["injury"] = {"type": "ankle", "games_remaining": 2, "day_reported": 1}

        tick_injuries_after_game(roster)
        self.assertEqual(player["injury"]["games_remaining"], 1)
        tick_injuries_after_game(roster)
        self.assertFalse(player_is_injured(player))

    def test_game_exclude_ids_activates_players_for_minimum(self):
        lookup = league_lookup(self.season)
        user_team = int(next(iter(self.season["rosters"])))
        roster = roster_players(self.season, user_team, lookup)
        for index, player in enumerate(roster):
            if index < 12:
                player["injury"] = {
                    "type": "ankle",
                    "games_remaining": index + 1,
                    "day_reported": 1,
                }

        exclude_ids = game_exclude_ids(roster)
        active_count = len(roster) - len(exclude_ids)
        self.assertEqual(active_count, 5)
        self.assertEqual(len(injured_player_ids(roster)), 12)

    def test_box_score_has_at_least_five_players(self):
        lookup = league_lookup(self.season)
        user_team = int(next(iter(self.season["rosters"])))
        partner_team = int(next(tid for tid in self.season["rosters"] if int(tid) != user_team))
        home_roster = roster_players(self.season, user_team, lookup)
        away_roster = roster_players(self.season, partner_team, lookup)
        for index, player in enumerate(home_roster):
            if index < 12:
                player["injury"] = {
                    "type": "knee",
                    "games_remaining": index + 1,
                    "day_reported": 1,
                }

        exclude_ids = game_exclude_ids(home_roster)
        result = simulate_game_with_box_score(
            home_roster,
            away_roster,
            rng=self.rng,
            home_exclude_ids=exclude_ids,
        )
        self.assertGreaterEqual(len(result["home_box"]), 5)

    def test_build_dnp_list_only_includes_excluded_injured(self):
        roster = [
            {"id": index, "name": f"P{index}", "injury": {"type": "ankle", "games_remaining": index + 1}}
            for index in range(10)
        ]
        exclude_ids = game_exclude_ids(roster)
        dnp = build_dnp_list(roster, exclude_ids)
        dnp_ids = {entry["player_id"] for entry in dnp}
        self.assertEqual(len(dnp_ids), 5)
        self.assertTrue(all(player_id >= 5 for player_id in dnp_ids))


class ChampionshipTests(unittest.TestCase):
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

    def test_record_championship_increments_and_persists(self):
        team_id = int(next(iter(self.season["rosters"])))
        self.assertEqual(championship_count(self.season, team_id), 0)

        record_championship(self.season, team_id)
        self.assertEqual(championship_count(self.season, team_id), 1)

        from season import advance_season

        advance_season(self.season, rng=self.rng)
        self.assertEqual(championship_count(self.season, team_id), 1)

        record_championship(self.season, team_id)
        self.assertEqual(championship_count(self.season, team_id), 2)


if __name__ == "__main__":
    unittest.main()
