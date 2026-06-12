"""Tests for offseason draft, trades, and season rollover."""

import os
import random
import tempfile
import unittest

import season_store
from attributes import apply_attributes
from draft import (
    draft_board_context,
    generate_prospect,
    make_pick,
    resolve_pick_owner,
    sim_rest_of_draft,
    skip_pick,
    start_draft,
)
from game import clear_game, set_season_id
from ratings import apply_ratings
import cache
from season import (
    advance_playoff_round,
    advance_season,
    can_trade,
    init_season,
    league_lookup,
    playoff_bracket_context,
    record_championship,
    regular_season_complete,
    roster_players,
    seed_playoffs,
    sim_day,
    sim_rest_of_season,
    sim_to_trade_deadline,
    sim_week,
    simulate_all_playoffs,
)
from trade import TRADE_TOLERANCE, cpu_accepts_trade, evaluate_trade, execute_trade, validate_trade
from roster import (
    MAX_ROSTER,
    MAX_TWO_WAY,
    MIN_ROSTER,
    assign_to_g_league,
    recall_from_g_league,
    release_player,
    roster_size,
    sign_free_agent,
    two_way_count,
)


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
            self.assertEqual(len(picks), 3)
            rounds = {pick["round"] for pick in picks}
            self.assertEqual(rounds, {1, 2, 3})

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
        user_player["salary"] = 10.0
        partner_player["salary"] = 10.0
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
        self.assertGreaterEqual(preview["partner_net"], -TRADE_TOLERANCE)
        self.assertLessEqual(abs(preview["meter"] - 50), 30)

        class _FixedRng:
            def __init__(self, value):
                self._value = value

            def random(self):
                return self._value

        self.assertEqual(
            preview["would_accept"],
            cpu_accepts_trade(
                self.season,
                user_team,
                partner_team,
                even_out,
                [],
                even_in,
                [],
                rng=_FixedRng(1.0),
            ),
        )

        lopsided_out = [user_players[-1]["id"]]
        lopsided_in = [partner_players[0]["id"]]
        lopsided = evaluate_trade(
            self.season, user_team, partner_team, lopsided_out, [], lopsided_in, []
        )
        self.assertFalse(lopsided["would_accept"])
        self.assertLess(lopsided["partner_net"], -TRADE_TOLERANCE)
        self.assertEqual(
            lopsided["would_accept"],
            cpu_accepts_trade(
                self.season, user_team, partner_team, lopsided_out, [], lopsided_in, []
            ),
        )

    def test_very_appealing_trade_acceptance(self):
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

        appealing_out = [user_players[0]["id"]]
        appealing_in = [partner_players[-1]["id"]]
        preview = evaluate_trade(
            self.season, user_team, partner_team, appealing_out, [], appealing_in, []
        )
        self.assertTrue(preview["would_accept"])
        self.assertEqual(preview["label"], "Very appealing")
        self.assertGreater(preview["partner_net"], preview["tolerance"])

        class _FixedRng:
            def __init__(self, value):
                self._value = value

            def random(self):
                return self._value

        self.assertTrue(
            cpu_accepts_trade(
                self.season,
                user_team,
                partner_team,
                appealing_out,
                [],
                appealing_in,
                [],
                rng=_FixedRng(1.0),
            )
        )
        self.assertFalse(
            cpu_accepts_trade(
                self.season,
                user_team,
                partner_team,
                appealing_out,
                [],
                appealing_in,
                [],
                rng=_FixedRng(0.0),
            )
        )

    def test_draft_talent_curve(self):
        team_count = len(self.season["rosters"])
        early_ovrs = []
        late_ovrs = []
        for slot in (1, 3, 5):
            prospect = generate_prospect(self.season, 1, slot, team_count, self.rng)
            early_ovrs.append(prospect["overall"])
        for slot in (25, 28, 30):
            prospect = generate_prospect(self.season, 1, slot, team_count, self.rng)
            late_ovrs.append(prospect["overall"])

        round_avgs = {}
        for round_num in (1, 2, 3):
            ovrs = []
            for slot in (1, 5, 15, 25):
                prospect = generate_prospect(self.season, round_num, slot, team_count, self.rng)
                ovrs.append(prospect["overall"])
            round_avgs[round_num] = sum(ovrs) / len(ovrs)

        self.assertGreater(sum(early_ovrs) / len(early_ovrs), sum(late_ovrs) / len(late_ovrs) + 3)
        self.assertGreater(round_avgs[1], round_avgs[2] + 8)
        self.assertGreater(round_avgs[2], round_avgs[3] + 5)

    def test_generational_talent_is_rare(self):
        team_count = len(self.season["rosters"])
        generational_count = 0
        trials = 500
        for trial in range(trials):
            prospect = generate_prospect(
                self.season, 1, 1, team_count, rng=random.Random(trial)
            )
            if prospect.get("career_arc") == "generational":
                generational_count += 1
        self.assertLess(generational_count / trials, 0.05)

    def test_shared_pool_early_picks_better_than_late(self):
        from draft import generate_draft_class, generate_prospect_options, start_draft

        lookup = league_lookup(self.season)
        start_draft(self.season, lookup, rng=random.Random(99))
        state = self.season["draft_state"]
        team_count = state["team_count"]

        early_options = generate_prospect_options(self.season, 1, team_count, self.rng)
        late_options = generate_prospect_options(self.season, 20, team_count, self.rng)
        early_avg = sum(p["overall"] for p in early_options) / len(early_options)
        late_avg = sum(p["overall"] for p in late_options) / len(late_options)
        self.assertGreater(early_avg, late_avg)

        pool = generate_draft_class(self.season, team_count, random.Random(100))
        top_rank = pool[0]["draft_rank"]
        bottom_rank = pool[-1]["draft_rank"]
        self.assertLess(top_rank, bottom_rank)
        self.assertGreater(pool[0]["overall"], pool[-1]["overall"])

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

    def test_playoff_games_persist_box_scores(self):
        lookup = league_lookup(self.season)
        sim_rest_of_season(self.season, lookup, rng=self.rng)
        seed_playoffs(self.season, lookup)
        advance_playoff_round(self.season, lookup, rng=self.rng)

        quarterfinals = self.season["playoffs"]["rounds"][0]
        completed = [series for series in quarterfinals["series"] if series.get("complete")]
        self.assertTrue(completed)
        series = completed[0]
        self.assertIn("games", series)
        self.assertGreater(len(series["games"]), 0)
        game = series["games"][0]
        self.assertIn("home_box", game)
        self.assertIn("away_box", game)
        self.assertEqual(
            sum(line["pts"] for line in game["home_box"]),
            game["home_score"],
        )
        self.assertEqual(
            sum(line["pts"] for line in game["away_box"]),
            game["away_score"],
        )

    def test_playoff_bracket_context_splits_conferences(self):
        lookup = league_lookup(self.season)
        sim_rest_of_season(self.season, lookup, rng=self.rng)
        seed_playoffs(self.season, lookup)
        bracket = playoff_bracket_context(self.season)

        self.assertEqual(len(bracket["east_rounds"]), 3)
        self.assertEqual(len(bracket["west_rounds"]), 3)
        self.assertEqual(len(bracket["east_rounds"][0]["series"]), 4)
        self.assertEqual(len(bracket["west_rounds"][0]["series"]), 4)
        self.assertEqual(len(bracket["east_rounds"][1]["series"]), 2)
        self.assertEqual(len(bracket["west_rounds"][1]["series"]), 2)
        self.assertEqual(len(bracket["east_rounds"][2]["series"]), 1)
        self.assertIsNotNone(bracket["finals"])
        self.assertTrue(
            bracket["east_rounds"][1]["series"][0]["series"].get("placeholder")
        )
        east_qf0 = bracket["east_rounds"][0]["series"][0]
        west_qf0 = bracket["west_rounds"][0]["series"][0]
        self.assertEqual(east_qf0["global_series_idx"], 0)
        self.assertEqual(west_qf0["global_series_idx"], 4)
        playoffs = self.season["playoffs"]["rounds"][0]["series"]
        self.assertIs(
            west_qf0["series"],
            playoffs[west_qf0["global_series_idx"]],
        )

    def test_playoff_bracket_global_series_idx_semifinals(self):
        lookup = league_lookup(self.season)
        sim_rest_of_season(self.season, lookup, rng=self.rng)
        seed_playoffs(self.season, lookup)
        while self.season["playoffs"]["round_index"] == 0:
            played = advance_playoff_round(self.season, lookup, rng=self.rng)
            if played == 0:
                break

        bracket = playoff_bracket_context(self.season)
        east_sf0 = bracket["east_rounds"][1]["series"][0]
        west_sf0 = bracket["west_rounds"][1]["series"][0]
        self.assertEqual(east_sf0["global_series_idx"], 0)
        self.assertEqual(west_sf0["global_series_idx"], 2)
        semifinals = self.season["playoffs"]["rounds"][1]["series"]
        self.assertIs(east_sf0["series"], semifinals[0])
        self.assertIs(west_sf0["series"], semifinals[2])

    def test_cpu_signs_star_free_agents_on_legend(self):
        from contracts import sim_cpu_free_agency

        lookup = league_lookup(self.season)
        self.season["difficulty"] = "legend"
        self.season["phase"] = "offseason"
        for player in self.season["players"].values():
            if player.get("team_id"):
                player["salary"] = 3.0
        star_id = self.season["next_player_id"]
        self.season["next_player_id"] += 1
        star = {
            "id": star_id,
            "name": "Test Star FA",
            "overall": 88,
            "age": 29,
            "team_id": None,
            "asking_salary": 20.0,
            "previous_salary": 18.0,
            "position": "SF",
            "gp": 0,
            "season_gp": 0,
        }
        self.season["players"][str(star_id)] = star
        self.season["free_agents"].append(star_id)

        signed = sim_cpu_free_agency(self.season, rng=random.Random(99))
        signed_ids = {player["id"] for player, _team in signed}
        self.assertIn(star_id, signed_ids)
        lookup = league_lookup(self.season)
        self.assertIsNotNone(lookup[star_id].get("team_id"))

    def test_trade_with_string_team_id(self):
        lookup = league_lookup(self.season)
        user_team = int(next(iter(self.season["rosters"])))
        partner_team = int(next(tid for tid in self.season["rosters"] if int(tid) != user_team))

        user_player = lookup[self.season["rosters"][str(user_team)][0]]
        partner_player = lookup[self.season["rosters"][str(partner_team)][0]]
        user_player["team_id"] = str(user_team)
        user_player["salary"] = 10.0
        partner_player["salary"] = 10.0

        valid, message = validate_trade(
            self.season,
            user_team,
            partner_team,
            [user_player["id"]],
            [],
            [partner_player["id"]],
            [],
        )
        self.assertTrue(valid, message)

        ok, exec_message = execute_trade(
            self.season,
            user_team,
            partner_team,
            [user_player["id"]],
            [],
            [partner_player["id"]],
            [],
        )
        self.assertTrue(ok, exec_message)
        self.assertEqual(int(self.season["players"][str(user_player["id"])]["team_id"]), partner_team)

    def test_roster_players_resolves_string_roster_ids(self):
        from simulation import simulate_game_with_box_score

        lookup = league_lookup(self.season)
        user_team = int(next(iter(self.season["rosters"])))
        partner_team = int(next(tid for tid in self.season["rosters"] if int(tid) != user_team))
        self.season["rosters"][str(user_team)] = [
            str(pid) for pid in self.season["rosters"][str(user_team)]
        ]
        home_roster = roster_players(self.season, user_team, lookup)
        away_roster = roster_players(self.season, partner_team, lookup)
        self.assertGreaterEqual(len(home_roster), MIN_ROSTER)

        result = simulate_game_with_box_score(
            home_roster,
            away_roster,
            rng=self.rng,
        )
        self.assertGreaterEqual(len(result["home_box"]), 5)
        self.assertGreaterEqual(len(result["away_box"]), 5)

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

    def test_sim_day_stops_at_max_day(self):
        lookup = league_lookup(self.season)
        max_day = self.season["max_day"]
        self.season["current_day"] = max_day
        count = sim_day(self.season, lookup, rng=self.rng)
        self.assertGreaterEqual(count, 0)
        self.assertEqual(self.season["current_day"], max_day)
        self.assertEqual(self.season["phase"], "regular_complete")

    def test_sim_day_no_op_past_max_day(self):
        lookup = league_lookup(self.season)
        self.season["current_day"] = self.season["max_day"] + 5
        count = sim_day(self.season, lookup, rng=self.rng)
        self.assertEqual(count, 0)

    def test_sim_week_clamps_to_max_day(self):
        lookup = league_lookup(self.season)
        max_day = self.season["max_day"]
        self.season["current_day"] = max(1, max_day - 2)
        sim_week(self.season, lookup, rng=self.rng)
        self.assertLessEqual(self.season["current_day"], max_day)

    def test_record_championship_sets_pending_bonus_for_user(self):
        lookup = league_lookup(self.season)
        team_id = int(next(iter(self.season["rosters"])))
        self.season["user_team_id"] = team_id
        record_championship(self.season, team_id)
        self.assertIn("pending_championship_bonus", self.season)
        self.assertGreater(self.season["pending_championship_bonus"], 0)

    def test_advance_season_rerolls_gm_profiles(self):
        lookup = league_lookup(self.season)
        self.season["phase"] = "offseason"
        advance_season(self.season, rng=self.rng)
        self.assertTrue(self.season.get("gm_personalities_enabled"))
        self.assertGreater(len(self.season.get("gm_profiles") or {}), 0)

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

    def test_traded_pick_changes_draft_owner(self):
        lookup = league_lookup(self.season)
        user_team = int(next(iter(self.season["rosters"])))
        partner_team = int(next(tid for tid in self.season["rosters"] if int(tid) != user_team))

        user_r1 = next(
            pick for pick in self.season["draft_picks"][str(user_team)] if pick["round"] == 1
        )
        partner_r1 = next(
            pick for pick in self.season["draft_picks"][str(partner_team)] if pick["round"] == 1
        )
        execute_trade(
            self.season,
            user_team,
            partner_team,
            [],
            [user_r1["id"]],
            [],
            [partner_r1["id"]],
        )

        self.season["phase"] = "complete"
        start_draft(self.season, lookup, rng=self.rng)
        queue = self.season["draft_state"]["queue"]
        user_slot_r1 = next(
            slot for slot in queue if slot["team_id"] == user_team and slot["round"] == 1
        )
        self.assertEqual(user_slot_r1["owner_team_id"], partner_team)
        self.assertEqual(resolve_pick_owner(self.season, user_team, 1), partner_team)

    def test_traded_away_pick_not_user_turn(self):
        lookup = league_lookup(self.season)
        user_team = int(next(iter(self.season["rosters"])))
        partner_team = int(next(tid for tid in self.season["rosters"] if int(tid) != user_team))

        user_r2 = next(
            pick for pick in self.season["draft_picks"][str(user_team)] if pick["round"] == 2
        )
        partner_r2 = next(
            pick for pick in self.season["draft_picks"][str(partner_team)] if pick["round"] == 2
        )
        execute_trade(
            self.season,
            user_team,
            partner_team,
            [],
            [user_r2["id"]],
            [],
            [partner_r2["id"]],
        )

        self.season["phase"] = "complete"
        start_draft(self.season, lookup, rng=self.rng)
        queue = self.season["draft_state"]["queue"]
        user_r2_slot = next(
            slot for slot in queue if slot["team_id"] == user_team and slot["round"] == 2
        )
        self.season["draft_state"]["current_index"] = queue.index(user_r2_slot)
        board = draft_board_context(self.season, user_team, lookup)
        self.assertFalse(board["is_user_turn"])

    def test_skip_pick_consumes_asset_without_player(self):
        lookup = league_lookup(self.season)
        user_team = int(next(iter(self.season["rosters"])))
        self.season["phase"] = "complete"
        start_draft(self.season, lookup, rng=self.rng)
        queue = self.season["draft_state"]["queue"]
        first_owner_slot = next(
            slot for slot in queue if slot["owner_team_id"] == user_team
        )
        self.season["draft_state"]["current_index"] = queue.index(first_owner_slot)
        roster_before = list(self.season["rosters"][str(user_team)])
        picks_before = len(self.season["draft_picks"][str(user_team)])

        ok, message = skip_pick(self.season, user_team)
        self.assertTrue(ok)
        self.assertIn("Skipped", message)
        self.assertEqual(len(self.season["draft_picks"][str(user_team)]), picks_before - 1)
        self.assertEqual(self.season["rosters"][str(user_team)], roster_before)

    def test_release_removes_player_from_roster_everywhere(self):
        user_team = int(next(iter(self.season["rosters"])))
        lookup = league_lookup(self.season)
        player_id = self.season["rosters"][str(user_team)][0]

        ok, _ = release_player(self.season, user_team, player_id)
        self.assertTrue(ok)
        self.assertNotIn(player_id, self.season["rosters"][str(user_team)])
        self.assertIsNone(self.season["players"][str(player_id)]["team_id"])
        self.assertEqual(self.season["players"][str(player_id)]["team"], "Free Agent")

        roster = roster_players(self.season, user_team, lookup)
        roster_ids = [player["id"] for player in roster]
        self.assertNotIn(player_id, roster_ids)

    def test_release_and_sign_free_agent(self):
        user_team = int(next(iter(self.season["rosters"])))
        player_id = self.season["rosters"][str(user_team)][0]

        ok, _ = release_player(self.season, user_team, player_id)
        self.assertTrue(ok)
        self.assertIn(player_id, self.season.get("free_agents", []))
        self.assertIsNone(self.season["players"][str(player_id)]["team_id"])

        from contracts import compute_asking_salary

        fa = self.season["players"][str(player_id)]
        ask = compute_asking_salary(fa)
        ok, msg = sign_free_agent(self.season, user_team, player_id, salary=ask * 1.05, years=2)
        self.assertTrue(ok, msg)
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

    def test_release_works_when_team_id_desynced(self):
        user_team = int(next(iter(self.season["rosters"])))
        player_id = self.season["rosters"][str(user_team)][0]
        self.season["players"][str(player_id)]["team_id"] = 999999
        ok, _ = release_player(self.season, user_team, player_id)
        self.assertTrue(ok)
        self.assertNotIn(player_id, self.season["rosters"][str(user_team)])

    def test_partner_trade_auto_releases_when_over_cap(self):
        user_team = int(next(iter(self.season["rosters"])))
        partner_team = int(next(iter(self.season["rosters"].keys())))
        if partner_team == user_team:
            partner_team = int(list(self.season["rosters"].keys())[1])

        partner_roster = self.season["rosters"][str(partner_team)]
        while len(partner_roster) < MAX_ROSTER:
            clone = dict(self.season["players"][str(partner_roster[0])])
            clone["id"] = 9900000 + len(partner_roster)
            clone["name"] = f"Filler {clone['id']}"
            clone["salary"] = 1.0
            clone["contract_years"] = 1
            self.season["players"][str(clone["id"])] = clone
            partner_roster.append(clone["id"])

        user_player = self.season["players"][str(self.season["rosters"][str(user_team)][0])]
        partner_player = self.season["players"][str(partner_roster[0])]
        user_player["salary"] = 5.0
        partner_player["salary"] = 5.0

        ok, message = execute_trade(
            self.season,
            user_team,
            partner_team,
            [user_player["id"]],
            [],
            [partner_player["id"]],
            [],
        )
        self.assertTrue(ok, message)
        self.assertLessEqual(roster_size(self.season, partner_team), MAX_ROSTER)

    def test_g_league_assign_and_recall(self):
        lookup = league_lookup(self.season)
        user_team = int(next(iter(self.season["rosters"])))
        player_id = self.season["rosters"][str(user_team)][0]
        player = lookup[player_id]
        player["age"] = 22
        nba_size_before = roster_size(self.season, user_team)

        ok, message = assign_to_g_league(self.season, user_team, player_id)
        self.assertTrue(ok, message)
        self.assertEqual(roster_size(self.season, user_team), nba_size_before - 1)
        self.assertEqual(two_way_count(self.season, user_team), 1)
        self.assertTrue(player.get("two_way"))

        ok, message = recall_from_g_league(self.season, user_team, player_id)
        self.assertTrue(ok, message)
        self.assertEqual(roster_size(self.season, user_team), nba_size_before)
        self.assertEqual(two_way_count(self.season, user_team), 0)

    def test_g_league_two_way_limit(self):
        lookup = league_lookup(self.season)
        user_team = int(next(iter(self.season["rosters"])))
        roster = self.season["rosters"][str(user_team)]
        for index in range(MAX_TWO_WAY):
            player = lookup[roster[index]]
            player["age"] = 21
            ok, _ = assign_to_g_league(self.season, user_team, player["id"])
            self.assertTrue(ok)
        ok, message = assign_to_g_league(self.season, user_team, roster[MAX_TWO_WAY])
        self.assertFalse(ok)
        self.assertIn(str(MAX_TWO_WAY), message)

    def test_signing_resets_unsigned_seasons(self):
        from contracts import propose_offer

        lookup = league_lookup(self.season)
        user_team = int(next(iter(self.season["rosters"])))
        while roster_size(self.season, user_team) >= MAX_ROSTER:
            release_player(self.season, user_team, self.season["rosters"][str(user_team)][-1], force=True)
        fa_id = self.season["free_agents"][0]
        fa = lookup[fa_id]
        fa["unsigned_seasons"] = 2
        ask = float(fa.get("asking_salary") or 5)
        ok, _, accepted = propose_offer(self.season, user_team, fa_id, ask * 1.2, 2)
        self.assertTrue(ok and accepted)
        self.assertNotIn("unsigned_seasons", fa)


if __name__ == "__main__":
    unittest.main()
