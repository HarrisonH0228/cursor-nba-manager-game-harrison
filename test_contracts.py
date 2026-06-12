"""Tests for salary cap and contract system."""

import random
import unittest

import cache
from attributes import apply_attributes
from contracts import (
    CONTRACT_WARNING_YEARS,
    SALARY_CAP_M,
    apply_championship_bonuses,
    championship_bonus_amount,
    clear_championship_bonuses,
    compute_asking_salary,
    compute_extension_ask,
    ensure_contract_fields,
    evaluate_offer,
    expiring_contract_report,
    expire_contracts,
    max_player_salary,
    propose_extension,
    propose_offer,
    roll_initial_contract_years,
    team_finances,
    validate_offer_terms,
)
from ratings import apply_ratings
from roster import sign_free_agent
from season import init_season, league_lookup
from trade import pick_trade_preview, TRADE_TOLERANCE


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cache_data = cache.load_cache()
        players = list(cache_data.get("players", []))
        apply_ratings(players)
        apply_attributes(players)
        cls.rng = random.Random(42)
        cls.season = init_season(players, season_year=2026, rng=cls.rng)
        cls.lookup = league_lookup(cls.season)

    def test_players_have_contracts_after_init(self):
        rostered = [p for p in self.lookup.values() if p.get("team_id")]
        self.assertTrue(all(p.get("salary") for p in rostered[:20]))

    def test_team_finances_cap_space(self):
        team_id = int(next(iter(self.season["rosters"])))
        fin = team_finances(self.season, team_id, self.lookup)
        self.assertLessEqual(fin["payroll"], SALARY_CAP_M)
        self.assertAlmostEqual(fin["cap_space"], SALARY_CAP_M - fin["payroll"], places=1)

    def test_high_offer_accepted_low_offer_rejected(self):
        fa_id = self.season["free_agents"][0]
        fa = self.lookup[fa_id]
        fa["asking_salary"] = 8.0
        fa["overall"] = 65
        team_id = int(next(iter(self.season["rosters"])))
        accepted, _ = evaluate_offer(fa, 10.0, 3, self.season, team_id)
        self.assertTrue(accepted)
        rejected, _ = evaluate_offer(fa, 1.5, 1, self.season, team_id)
        self.assertFalse(rejected)

    def test_validate_offer_terms_rejects_over_cap(self):
        team_id = int(next(iter(self.season["rosters"])))
        fa_id = self.season["free_agents"][0]
        fa = self.lookup[fa_id]
        fin = team_finances(self.season, team_id, self.lookup)
        ok, message = validate_offer_terms(fa, fin["cap_space"] + 50, 2, team_id, self.season, self.lookup)
        self.assertFalse(ok)
        self.assertIn("cap", message.lower())

    def test_expire_contracts_releases_player(self):
        team_id = int(next(iter(self.season["rosters"])))
        player_id = self.season["rosters"][str(team_id)][0]
        player = self.lookup[player_id]
        player["contract_years"] = 1
        expired = expire_contracts(self.season, self.lookup)
        self.assertTrue(any(p["id"] == player_id for p in expired))
        self.assertIsNone(self.lookup[player_id].get("team_id"))

    def test_propose_offer_signs_with_good_offer(self):
        team_id = int(next(iter(self.season["rosters"])))
        player_id = self.season["rosters"][str(team_id)][0]
        from roster import release_player

        release_player(self.season, team_id, player_id, force=True)
        fa_id = player_id
        fa = self.lookup[fa_id]
        fa["overall"] = 65
        fa["asking_salary"] = 8.0
        fa["previous_salary"] = 8.0
        ask = compute_asking_salary(fa)
        fin = team_finances(self.season, team_id, self.lookup)
        offer = min(
            ask * 1.1,
            max_player_salary(fa.get("overall") or 50),
            fin["cap_space"],
        )
        ok, message, accepted = propose_offer(self.season, team_id, fa_id, offer, 2)
        self.assertTrue(ok, message)
        self.assertTrue(accepted)
        self.assertEqual(self.lookup[fa_id].get("team_id"), team_id)

    def test_pick_trade_preview(self):
        outgoing = {"round": 2, "overall": 45, "year": 2027}
        incoming = {"round": 1, "overall": 1, "year": 2029}
        preview = pick_trade_preview(self.season, outgoing, incoming)
        self.assertIn("would_accept", preview)
        self.assertLessEqual(preview["diff"], TRADE_TOLERANCE + 50)

    def test_ensure_contract_fields_backfills(self):
        bare = {"players": {"1": {"id": 1, "overall": 70, "age": 25, "team_id": 2}}, "rosters": {"2": [1]}}
        ensure_contract_fields(bare, self.rng)
        self.assertIn("salary", bare["players"]["1"])
        self.assertIn("team_finances", bare)

    def test_roll_initial_contract_years_range(self):
        years_seen = set()
        for _ in range(50):
            player = {"overall": 82, "age": 26}
            years_seen.add(roll_initial_contract_years(player, self.rng))
        self.assertTrue(all(2 <= y <= 4 for y in years_seen))

    def test_expiring_contract_report(self):
        team_id = int(next(iter(self.season["rosters"])))
        player_id = self.season["rosters"][str(team_id)][0]
        player = self.lookup[player_id]
        player["contract_years"] = CONTRACT_WARNING_YEARS
        report = expiring_contract_report(self.season, team_id, self.lookup)
        ids = {item["player_id"] for item in report}
        self.assertIn(player_id, ids)

    def test_propose_extension_accepts_fair_offer(self):
        team_id = int(next(iter(self.season["rosters"])))
        player_id = 999001
        player = {
            "id": player_id,
            "name": "Bench Test",
            "team_id": team_id,
            "team": "Test",
            "overall": 35,
            "age": 28,
            "salary": 2.0,
            "previous_salary": 2.0,
            "contract_years": 1,
        }
        self.season["players"][str(player_id)] = player
        self.lookup[player_id] = player
        self.season["rosters"][str(team_id)].append(player_id)
        ask = compute_extension_ask(player)
        ok, message, accepted = propose_extension(
            self.season, team_id, player_id, salary=ask * 1.05, years=2
        )
        self.assertTrue(ok, message)
        self.assertTrue(accepted)
        self.assertEqual(player["contract_years"], 2)

    def test_championship_bonus_amount_tiers(self):
        self.assertGreater(championship_bonus_amount({"overall": 90}), 1.0)
        self.assertLess(championship_bonus_amount({"overall": 60}), 1.0)

    def test_apply_and_clear_championship_bonuses(self):
        team_id = int(next(iter(self.season["rosters"])))
        total = apply_championship_bonuses(self.season, team_id, self.lookup)
        self.assertGreater(total, 0)
        rostered = [
            self.lookup[pid]
            for pid in self.season["rosters"][str(team_id)]
        ]
        self.assertTrue(all(p.get("championship_bonus") for p in rostered))
        fin = team_finances(self.season, team_id, self.lookup)
        self.assertGreater(fin["bonus_paid"], 0)
        clear_championship_bonuses(self.season)
        self.assertFalse(any(p.get("championship_bonus") for p in rostered))


if __name__ == "__main__":
    unittest.main()
