"""Tests for admin custom draft players."""

import random
import unittest

import cache
from attributes import apply_attributes
from custom_players import add_custom_player, delete_custom_player, list_custom_players
from draft import generate_prospect_options, make_pick, start_draft
from ratings import apply_ratings
from season import init_season, league_lookup, sim_rest_of_season, seed_playoffs, simulate_all_playoffs


class CustomPlayerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        players = list(cache.load_cache().get("players", []))
        apply_ratings(players)
        apply_attributes(players)
        cls.players = players

    def setUp(self):
        for player in list_custom_players():
            delete_custom_player(player["custom_id"])

    def tearDown(self):
        for player in list_custom_players():
            delete_custom_player(player["custom_id"])

    def test_add_custom_player_accepts_string_potential(self):
        entry = add_custom_player(
            name="String Potential",
            age="20",
            positions=["PG"],
            attributes={key: "80" for key in ("scoring", "playmaking", "rebounding", "defense", "efficiency", "stamina")},
            potential="91",
        )
        self.assertEqual(entry["potential"], 91)
        delete_custom_player(entry["custom_id"])

    def test_overclocked_custom_player_keeps_high_attributes(self):
        entry = add_custom_player(
            name="Super Prospect",
            age=19,
            positions=["SG"],
            attributes={
                "scoring": 130,
                "playmaking": 120,
                "rebounding": 110,
                "defense": 115,
                "efficiency": 125,
                "stamina": 118,
            },
            potential=145,
            overclock=True,
        )
        self.assertTrue(entry["is_overclocked"])
        self.assertGreater(entry["overall"], 99)
        self.assertGreater(entry["ppg"], 32)

        season = init_season(self.players, season_year=2026, rng=random.Random(10))
        from custom_players import build_prospect_from_template

        prospect = build_prospect_from_template(season, entry, rng=random.Random(11))
        self.assertTrue(prospect.get("is_overclocked"))
        self.assertGreater(prospect["overall"], 99)
        attrs = prospect.get("attributes") or {}
        self.assertGreater(attrs.get("scoring", 0), 99)
        delete_custom_player(entry["custom_id"])

    def test_custom_player_appears_in_draft_options(self):
        add_custom_player(
            name="Test Prospect",
            age=19,
            positions=["SG"],
            attributes={key: 85 for key in ("scoring", "playmaking", "rebounding", "defense", "efficiency", "stamina")},
            potential=92,
        )

        season = init_season(self.players, season_year=2026, rng=random.Random(1))
        lookup = league_lookup(season)
        sim_rest_of_season(season, lookup, rng=random.Random(2))
        seed_playoffs(season, lookup)
        simulate_all_playoffs(season, lookup, rng=random.Random(3))
        season["phase"] = "complete"
        start_draft(season, lookup, rng=random.Random(4))

        found = False
        for trial in range(20):
            options = generate_prospect_options(season, 1, 1, 30, rng=random.Random(100 + trial))
            if any(prospect.get("is_custom") for prospect in options):
                found = True
                break

        self.assertTrue(found)

    def test_custom_player_removed_after_drafted(self):
        entry = add_custom_player(
            name="One And Done",
            age=20,
            positions=["PF"],
            attributes={key: 80 for key in ("scoring", "playmaking", "rebounding", "defense", "efficiency", "stamina")},
        )

        season = init_season(self.players, season_year=2026, rng=random.Random(5))
        lookup = league_lookup(season)
        sim_rest_of_season(season, lookup, rng=random.Random(6))
        seed_playoffs(season, lookup)
        simulate_all_playoffs(season, lookup, rng=random.Random(7))
        season["phase"] = "complete"
        start_draft(season, lookup, rng=random.Random(8))

        custom_prospect = None
        for trial in range(30):
            options = generate_prospect_options(season, 1, 1, 30, rng=random.Random(200 + trial))
            for prospect in options:
                if prospect.get("custom_id") == entry["custom_id"]:
                    custom_prospect = prospect
                    break
            if custom_prospect:
                break

        self.assertIsNotNone(custom_prospect)
        from draft import current_pick
        slot = current_pick(season)
        self.assertIsNotNone(slot)
        ok, message = make_pick(
            season,
            slot["team_id"],
            prospect=custom_prospect,
            rng=random.Random(9),
            auto_trim=True,
        )
        self.assertTrue(ok, message)

        for trial in range(10):
            options = generate_prospect_options(season, 1, 2, 30, rng=random.Random(300 + trial))
            self.assertFalse(
                any(prospect.get("custom_id") == entry["custom_id"] for prospect in options)
            )


if __name__ == "__main__":
    unittest.main()
