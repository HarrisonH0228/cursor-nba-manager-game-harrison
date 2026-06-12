"""Tests for offseason draft, trades, and season rollover."""

import os
import random
import tempfile
import unittest

import season_store
from attributes import apply_attributes
from draft import generate_prospect, make_pick, sim_rest_of_draft, start_draft
from game import clear_game, set_season_id
from ratings import apply_ratings
import cache
from season import (
    advance_season,
    can_trade,
    draft_order,
    init_season,
    league_lookup,
    pick_owner,
    regular_season_complete,
    seed_playoffs,
    sim_rest_of_season,
    sim_to_trade_deadline,
    simulate_all_playoffs,
)
from trade import (
    cpu_accepts_trade,
    evaluate_trade,
    execute_trade,
    player_value,
    players_package_value,
    validate_trade,
)
from roster import MAX_ROSTER, MIN_ROSTER, release_player, roster_size, sign_free_agent


class OffseasonTests(unittest.TestCase):
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
        self.players = players
        self.rng = random.Random(42)
        self.season = init_season(self.players, season_year=2026, rng=self.rng)

    def test_init_has_player_pool_and_picks(self):
        self.assertIn("players", self.season)
        self.assertGreater(len(self.season["players"]), 100)
        self.assertEqual(self.season["next_player_id"], 9000001)
        self.assertIn("draft_picks", self.season)
        team_ids = self.season["rosters"].keys()
        for team_id in team_ids:
            picks = self.season["draft_picks"][team_id]
            self.assertEqual(len(picks), 6)
            rounds = {pick["round"] for pick in picks}
            self.assertEqual(rounds, {1, 2, 3})
            years = {pick["year"] for pick in picks}
            self.assertEqual(years, {2027, 2028})
            for pick in picks:
                self.assertIn("pick_number", pick)

    def test_league_lookup_and_rosters(self):
        lookup = league_lookup(self.season)
        team_id = int(next(iter(self.season["rosters"])))
        roster_ids = self.season["rosters"][str(team_id)]
        for player_id in roster_ids:
            self.assertIn(player_id, lookup)

    def test_trade_window_before_and_after_deadline(self):
        self.assertTrue(can_trade(self.season))
        lookup = league_lookup(self.season)
        sim_to_trade_deadline(self.season, lookup, rng=self.rng)
        self.assertFalse(can_trade(self.season))

    def test_trade_window_reopens_in_draft_offseason(self):
        lookup = league_lookup(self.season)
        sim_to_trade_deadline(self.season, lookup, rng=self.rng)
        self.season["phase"] = "draft"
        self.assertTrue(can_trade(self.season))
        self.season["phase"] = "offseason"
        self.assertTrue(can_trade(self.season))

    def test_trade_execution_moves_player_and_pick(self):
        lookup = league_lookup(self.season)
        user_team = int(next(iter(self.season["rosters"])))
        partner_team = int(next(tid for tid in self.season["rosters"] if int(tid) != user_team))

        user_player = lookup[self.season["rosters"][str(user_team)][0]]
        partner_player = lookup[self.season["rosters"][str(partner_team)][0]]
        user_pick = self.season["draft_picks"][str(user_team)][0]["id"]
        partner_pick = self.season["draft_picks"][str(partner_team)][0]["id"]

        valid, _ = validate_trade(
            self.season,
            user_team,
            partner_team,
            [user_player["id"]],
            [user_pick],
            [partner_player["id"]],
            [partner_pick],
        )
        self.assertTrue(valid)

        ok, message = execute_trade(
            self.season,
            user_team,
            partner_team,
            [user_player["id"]],
            [user_pick],
            [partner_player["id"]],
            [partner_pick],
        )
        self.assertTrue(ok, message)
        self.assertEqual(
            self.season["players"][str(user_player["id"])]["team_id"], partner_team
        )
        self.assertEqual(
            self.season["players"][str(partner_player["id"])]["team_id"], user_team
        )
        self.assertEqual(len(self.season["trades"]), 1)

    def test_cpu_accepts_near_even_trades(self):
        user_team = int(next(iter(self.season["rosters"])))
        partner_team = int(next(tid for tid in self.season["rosters"] if int(tid) != user_team))
        lookup = league_lookup(self.season)
        user_players = sorted(
            [lookup[pid] for pid in self.season["rosters"][str(user_team)]],
            key=lambda player: player.get("overall") or 0,
            reverse=True,
        )
        partner_players = sorted(
            [lookup[pid] for pid in self.season["rosters"][str(partner_team)]],
            key=lambda player: player.get("overall") or 0,
            reverse=True,
        )
        matched = False
        for user_player in user_players[:5]:
            for partner_player in partner_players[:5]:
                if cpu_accepts_trade(
                    self.season,
                    user_team,
                    partner_team,
                    [user_player["id"]],
                    [],
                    [partner_player["id"]],
                    [],
                ):
                    matched = True
                    break
            if matched:
                break
        self.assertTrue(matched, "Expected CPU to accept a similar-value 1-for-1 trade")

    def test_trade_meter_matches_cpu_acceptance(self):
        user_team = int(next(iter(self.season["rosters"])))
        partner_team = int(next(tid for tid in self.season["rosters"] if int(tid) != user_team))
        lookup = league_lookup(self.season)
        user_players = sorted(
            [lookup[pid] for pid in self.season["rosters"][str(user_team)]],
            key=lambda player: player.get("overall") or 0,
            reverse=True,
        )
        partner_players = sorted(
            [lookup[pid] for pid in self.season["rosters"][str(partner_team)]],
            key=lambda player: player.get("overall") or 0,
            reverse=True,
        )

        even_out = [user_players[2]["id"]]
        even_in = [partner_players[2]["id"]]
        for user_player, partner_player in zip(user_players[:5], partner_players[:5]):
            even_out = [user_player["id"]]
            even_in = [partner_player["id"]]
            preview = evaluate_trade(
                self.season, user_team, partner_team, even_out, [], even_in, []
            )
            if preview["would_accept"]:
                break

        self.assertTrue(preview["would_accept"], "Expected a near-even trade to be accepted")
        self.assertGreaterEqual(preview["partner_net"], -15)
        self.assertLessEqual(abs(preview["meter"] - 50), 30)
        self.assertEqual(
            preview["would_accept"],
            cpu_accepts_trade(
                self.season, user_team, partner_team, even_out, [], even_in, []
            ),
        )

        lopsided_out = [user_players[-1]["id"]]
        lopsided_in = [partner_players[0]["id"]]
        lopsided = evaluate_trade(
            self.season, user_team, partner_team, lopsided_out, [], lopsided_in, []
        )
        self.assertFalse(lopsided["would_accept"])
        self.assertLess(lopsided["partner_net"], -15)
        self.assertEqual(
            lopsided["would_accept"],
            cpu_accepts_trade(
                self.season, user_team, partner_team, lopsided_out, [], lopsided_in, []
            ),
        )

    def test_cpu_accepts_overpay_trades(self):
        user_team = int(next(iter(self.season["rosters"])))
        partner_team = int(next(tid for tid in self.season["rosters"] if int(tid) != user_team))
        lookup = league_lookup(self.season)
        user_players = sorted(
            [lookup[pid] for pid in self.season["rosters"][str(user_team)]],
            key=lambda player: player.get("overall") or 0,
            reverse=True,
        )
        partner_players = sorted(
            [lookup[pid] for pid in self.season["rosters"][str(partner_team)]],
            key=lambda player: player.get("overall") or 0,
            reverse=True,
        )
        overpay_out = [user_players[0]["id"]]
        overpay_in = [partner_players[-1]["id"]]
        preview = evaluate_trade(
            self.season, user_team, partner_team, overpay_out, [], overpay_in, []
        )
        self.assertTrue(preview["would_accept"])
        self.assertGreater(preview["partner_net"], 15)
        self.assertTrue(
            cpu_accepts_trade(
                self.season, user_team, partner_team, overpay_out, [], overpay_in, []
            )
        )

    def test_traded_pick_changes_draft_queue_owner(self):
        lookup = league_lookup(self.season)
        user_team = int(next(iter(self.season["rosters"])))
        partner_team = int(next(tid for tid in self.season["rosters"] if int(tid) != user_team))
        traded_pick = next(
            pick
            for pick in self.season["draft_picks"][str(user_team)]
            if pick.get("year") == 2027 and pick.get("round") == 1
        )
        ok, _ = execute_trade(
            self.season,
            user_team,
            partner_team,
            [],
            [traded_pick["id"]],
            [],
            [],
        )
        self.assertTrue(ok)

        sim_rest_of_season(self.season, lookup, rng=self.rng)
        seed_playoffs(self.season, lookup)
        simulate_all_playoffs(self.season, lookup, rng=self.rng)
        self.season["phase"] = "complete"
        lottery = draft_order(self.season, lookup, rng=self.rng)
        slot = next(
            item
            for item in lottery["queue"]
            if item.get("pick_id") == traded_pick["id"]
        )
        self.assertEqual(slot["team_id"], partner_team)
        self.assertEqual(
            pick_owner(
                self.season,
                traded_pick["year"],
                traded_pick["round"],
                traded_pick["pick_number"],
            ),
            partner_team,
        )

    def test_superstar_beats_role_player_package(self):
        superstar = {"overall": 95, "age": 27, "peak_age": 28}
        role_a = {"overall": 80, "age": 28, "peak_age": 28}
        role_b = {"overall": 80, "age": 29, "peak_age": 29}
        star_value = player_value(superstar)
        package_value = players_package_value([role_a, role_b])
        self.assertGreater(star_value, package_value)

    def test_young_star_premium(self):
        young = {"overall": 88, "age": 21, "peak_age": 27}
        older = {"overall": 88, "age": 30, "peak_age": 30}
        self.assertGreater(player_value(young), player_value(older))

    def test_advance_season_preserves_traded_future_pick(self):
        user_team = int(next(iter(self.season["rosters"])))
        partner_team = int(next(tid for tid in self.season["rosters"] if int(tid) != user_team))
        future_pick = next(
            pick for pick in self.season["draft_picks"][str(user_team)] if pick.get("year") == 2028
        )
        ok, _ = execute_trade(
            self.season,
            user_team,
            partner_team,
            [],
            [future_pick["id"]],
            [],
            [],
        )
        self.assertTrue(ok)

        lookup = league_lookup(self.season)
        sim_rest_of_season(self.season, lookup, rng=self.rng)
        seed_playoffs(self.season, lookup)
        simulate_all_playoffs(self.season, lookup, rng=self.rng)
        self.season["phase"] = "complete"
        start_draft(self.season, lookup, rng=self.rng)
        sim_rest_of_draft(self.season, auto_user_picks=True, rng=self.rng)

        advance_season(self.season, rng=self.rng)
        partner_picks = self.season["draft_picks"][str(partner_team)]
        self.assertTrue(any(pick["id"] == future_pick["id"] for pick in partner_picks))
        partner_years = {pick["year"] for pick in partner_picks}
        self.assertIn(2028, partner_years)
        self.assertIn(2029, partner_years)

    def test_draft_talent_curve(self):
        team_count = len(self.season["rosters"])
        round_avgs = {}
        for round_num in (1, 2, 3):
            ovrs = []
            for slot in (1, 5, 15, 25):
                prospect = generate_prospect(self.season, round_num, slot, team_count, self.rng)
                ovrs.append(prospect["overall"])
            round_avgs[round_num] = sum(ovrs) / len(ovrs)

        self.assertGreater(round_avgs[1], round_avgs[2] + 10)
        self.assertGreater(round_avgs[2], round_avgs[3] + 5)

    def test_lottery_favors_worst_teams(self):
        lookup = league_lookup(self.season)
        self.season["phase"] = "complete"
        sim_rest_of_season(self.season, lookup, rng=self.rng)
        seed_playoffs(self.season, lookup)
        simulate_all_playoffs(self.season, lookup, rng=self.rng)

        from season import lottery_team_rows, run_draft_lottery

        lottery_rows = lottery_team_rows(self.season, lookup)
        self.assertEqual(len(lottery_rows), 14)
        worst_team_id = lottery_rows[0]["team_id"]
        top_pick_counts = {row["team_id"]: 0 for row in lottery_rows}
        trials = 500
        for trial in range(trials):
            result = run_draft_lottery(self.season, lookup, rng=random.Random(trial))
            top_pick_counts[result["lottery_order"][0]["team_id"]] += 1

        self.assertGreater(
            top_pick_counts[worst_team_id],
            max(count for team_id, count in top_pick_counts.items() if team_id != worst_team_id),
        )

    def test_playoff_teams_follow_playoff_finish(self):
        lookup = league_lookup(self.season)
        sim_rest_of_season(self.season, lookup, rng=self.rng)
        seed_playoffs(self.season, lookup)
        simulate_all_playoffs(self.season, lookup, rng=self.rng)
        self.season["phase"] = "complete"

        start_draft(self.season, lookup, rng=self.rng)
        playoff_order = self.season["draft_state"]["playoff_order"]
        champion_id = self.season["playoffs"]["champion_id"]
        self.assertEqual(playoff_order[-1]["team_id"], champion_id)
        self.assertEqual(playoff_order[-1]["pick_number"], 30)
        self.assertEqual(len(self.season["draft_state"]["lottery_order"]), 14)

    def test_full_draft_cycle_and_advance(self):
        lookup = league_lookup(self.season)
        sim_rest_of_season(self.season, lookup, rng=self.rng)
        seed_playoffs(self.season, lookup)
        simulate_all_playoffs(self.season, lookup, rng=self.rng)
        self.season["phase"] = "complete"
        start_draft(self.season, lookup, rng=self.rng)
        sim_rest_of_draft(self.season, auto_user_picks=True, rng=self.rng)
        self.assertEqual(self.season["phase"], "offseason")
        self.assertIsNone(self.season["draft_state"])

        old_year = self.season["season_year"]
        old_player = next(iter(self.season["players"].values()))
        old_age = old_player.get("age") or 25
        advance_season(self.season, rng=self.rng)
        self.assertEqual(self.season["season_year"], old_year + 1)
        self.assertEqual(self.season["phase"], "regular")
        self.assertEqual(self.season["players"][str(old_player["id"])]["age"], old_age + 1)
        self.assertTrue(can_trade(self.season))
        self.assertGreater(len(self.season["schedule"]), 0)

    def test_full_season_sim_reaches_playoffs(self):
        lookup = league_lookup(self.season)
        sim_rest_of_season(self.season, lookup, rng=self.rng)
        self.assertEqual(self.season["phase"], "regular_complete")
        self.assertLessEqual(self.season["current_day"], self.season["max_day"])
        self.assertTrue(regular_season_complete(self.season))

    def test_schedule_has_82_games_per_team(self):
        from season import _schedule_games_per_team, generate_schedule

        team_ids = sorted(int(team_id) for team_id in self.season["rosters"].keys())
        for seed in range(50):
            schedule = generate_schedule(team_ids, rng=random.Random(seed))
            gp_counts = _schedule_games_per_team(schedule, team_ids)
            self.assertTrue(all(count == 82 for count in gp_counts.values()))

    def test_new_game_deletes_season_file(self):
        season_id = season_store.create_season_id()
        season_store.save_season(season_id, self.season)
        session = {}
        set_season_id(season_id, session)
        clear_game(session)
        self.assertNotIn("season_id", session)
        self.assertFalse(os.path.exists(os.path.join(season_store.SEASONS_DIR, f"{season_id}.json")))

    def test_roster_cap_blocks_overfull_trade(self):
        user_team = int(next(iter(self.season["rosters"])))
        partner_team = int(next(tid for tid in self.season["rosters"] if int(tid) != user_team))
        lookup = league_lookup(self.season)
        user_roster = list(self.season["rosters"][str(user_team)])
        while len(user_roster) < MAX_ROSTER:
            extra = lookup[user_roster[0]]
            clone_id = 9900000 + len(user_roster)
            clone = dict(extra)
            clone["id"] = clone_id
            self.season["players"][str(clone_id)] = clone
            user_roster.append(clone_id)
            clone["team_id"] = user_team
        self.season["rosters"][str(user_team)] = user_roster

        partner_player = lookup[self.season["rosters"][str(partner_team)][0]]
        valid, message = validate_trade(
            self.season,
            user_team,
            partner_team,
            [],
            [],
            [partner_player["id"]],
            [],
        )
        self.assertFalse(valid)
        self.assertIn("roster limit", message.lower())

    def test_release_and_sign_free_agent(self):
        user_team = int(next(iter(self.season["rosters"])))
        player_id = self.season["rosters"][str(user_team)][0]

        ok, _ = release_player(self.season, user_team, player_id)
        self.assertTrue(ok)
        self.assertIn(player_id, self.season.get("free_agents", []))
        self.assertIsNone(self.season["players"][str(player_id)]["team_id"])

        ok, _ = sign_free_agent(self.season, user_team, player_id)
        self.assertTrue(ok)
        self.assertEqual(self.season["players"][str(player_id)]["team_id"], user_team)
        self.assertNotIn(player_id, self.season.get("free_agents", []))

    def test_cannot_release_below_min_roster(self):
        user_team = int(next(iter(self.season["rosters"])))
        roster = self.season["rosters"][str(user_team)]
        while roster_size(self.season, user_team) > MIN_ROSTER:
            roster.pop()
        player_id = roster[0]
        ok, message = release_player(self.season, user_team, player_id)
        self.assertFalse(ok)
        self.assertIn(str(MIN_ROSTER), message)


if __name__ == "__main__":
    unittest.main()
