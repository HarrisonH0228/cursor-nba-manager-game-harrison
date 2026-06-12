"""Tests for roster count reconciliation."""

import random
import unittest

import cache
from attributes import apply_attributes
from contracts import propose_offer
from ratings import apply_ratings
from roster import (
    MAX_ROSTER,
    MIN_ROSTER,
    release_player,
    reconcile_all_rosters,
    reconcile_team_roster,
    release_player,
    roster_size,
)
from season import init_season, league_lookup
from trade import execute_trade


class RosterSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cache_data = cache.load_cache()
        players = list(cache_data.get("players", []))
        apply_ratings(players)
        apply_attributes(players)
        cls.rng = random.Random(42)
        cls.season = init_season(players, season_year=2026, rng=cls.rng)
        cls.lookup = league_lookup(cls.season)

    def test_reconcile_fixes_orphan_team_id(self):
        team_id = int(next(iter(self.season["rosters"])))
        player_id = self.season["rosters"][str(team_id)][0]
        player = self.lookup[player_id]
        player["team_id"] = None
        reconcile_team_roster(self.season, team_id)
        self.assertEqual(self.lookup[player_id]["team_id"], team_id)
        self.assertIn(player_id, self.season["rosters"][str(team_id)])

    def test_reconcile_adds_missing_roster_entry(self):
        team_id = int(next(iter(self.season["rosters"])))
        player_id = self.season["rosters"][str(team_id)][0]
        self.season["rosters"][str(team_id)].remove(player_id)
        self.lookup[player_id]["team_id"] = team_id
        reconcile_team_roster(self.season, team_id)
        self.assertIn(player_id, self.season["rosters"][str(team_id)])

    def test_reconcile_all_teams(self):
        team_id = int(next(iter(self.season["rosters"])))
        player_id = self.season["rosters"][str(team_id)][0]
        self.lookup[player_id]["team_id"] = None
        reconcile_all_rosters(self.season)
        self.assertEqual(self.lookup[player_id]["team_id"], team_id)

    def test_trade_keeps_rosters_in_sync(self):
        user_team = int(next(iter(self.season["rosters"])))
        partner_team = int(next(tid for tid in self.season["rosters"] if int(tid) != user_team))
        user_player = self.lookup[self.season["rosters"][str(user_team)][0]]
        partner_player = self.lookup[self.season["rosters"][str(partner_team)][0]]
        user_player["salary"] = 8.0
        partner_player["salary"] = 8.0
        user_size_before = roster_size(self.season, user_team)
        partner_size_before = roster_size(self.season, partner_team)
        execute_trade(
            self.season,
            user_team,
            partner_team,
            [user_player["id"]],
            [],
            [partner_player["id"]],
            [],
        )
        self.assertIn(partner_player["id"], self.season["rosters"][str(user_team)])
        self.assertIn(user_player["id"], self.season["rosters"][str(partner_team)])
        self.assertEqual(self.lookup[partner_player["id"]]["team_id"], user_team)
        self.assertEqual(self.lookup[user_player["id"]]["team_id"], partner_team)
        self.assertEqual(roster_size(self.season, user_team), user_size_before)
        self.assertEqual(roster_size(self.season, partner_team), partner_size_before)

    def test_trade_allows_partner_below_min(self):
        user_team = int(next(iter(self.season["rosters"])))
        partner_team = int(next(tid for tid in self.season["rosters"] if int(tid) != user_team))
        while roster_size(self.season, partner_team) > MIN_ROSTER:
            pid = self.season["rosters"][str(partner_team)][-1]
            release_player(self.season, partner_team, pid, force=True)
        self.assertEqual(roster_size(self.season, partner_team), MIN_ROSTER)
        partner_roster = self.season["rosters"][str(partner_team)]

        incoming = [
            self.lookup[partner_roster[0]]["id"],
            self.lookup[partner_roster[1]]["id"],
        ]
        outgoing = [self.lookup[self.season["rosters"][str(user_team)][0]]["id"]]
        for pid in incoming + outgoing:
            self.lookup[pid]["salary"] = 5.0

        ok, message = execute_trade(
            self.season,
            user_team,
            partner_team,
            outgoing,
            [],
            incoming,
            [],
        )
        self.assertTrue(ok, message)
        self.assertEqual(roster_size(self.season, partner_team), MIN_ROSTER - 1)

    def test_signing_reconciles_roster(self):
        team_id = int(next(iter(self.season["rosters"])))
        while roster_size(self.season, team_id) >= MAX_ROSTER:
            pid = self.season["rosters"][str(team_id)][-1]
            release_player(self.season, team_id, pid, force=True)
        fa_id = self.season["free_agents"][0]
        fa = self.lookup[fa_id]
        ask = float(fa.get("asking_salary") or 5)
        ok, _, accepted = propose_offer(self.season, team_id, fa_id, ask * 1.2, 2)
        self.assertTrue(ok and accepted)
        self.assertIn(fa_id, self.season["rosters"][str(team_id)])
        self.assertEqual(self.lookup[fa_id]["team_id"], team_id)


if __name__ == "__main__":
    unittest.main()
