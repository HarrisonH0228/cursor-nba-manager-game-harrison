"""Tests for salary cap and contract system."""

import random
import unittest

import cache
from attributes import apply_attributes
from contracts import (
    SALARY_CAP_M,
    compute_asking_salary,
    ensure_contract_fields,
    evaluate_offer,
    expire_contracts,
    propose_offer,
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
        ask = compute_asking_salary(fa)
        ok, message, accepted = propose_offer(self.season, team_id, fa_id, ask * 1.1, 2)
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


if __name__ == "__main__":
    unittest.main()
