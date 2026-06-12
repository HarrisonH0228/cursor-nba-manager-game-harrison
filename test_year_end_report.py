"""Tests for end-of-season awards report."""

import random
import unittest

import cache
from attributes import apply_attributes
from ratings import apply_ratings
from season import (
    advance_playoff_round,
    init_season,
    league_lookup,
    seed_playoffs,
    sim_rest_of_season,
    simulate_all_playoffs,
)
from year_end_report import build_year_end_report, get_year_end_report


class YearEndReportTests(unittest.TestCase):
    def setUp(self):
        cache_data = cache.load_cache()
        players = list(cache_data.get("players", []))
        apply_ratings(players)
        apply_attributes(players)
        self.rng = random.Random(42)
        self.season = init_season(players, season_year=2026, rng=self.rng)
        self.lookup = league_lookup(self.season)

    def _complete_season(self):
        season = self.season
        lookup = self.lookup
        sim_rest_of_season(season, lookup, rng=self.rng)
        seed_playoffs(season, lookup)
        simulate_all_playoffs(season, lookup, rng=self.rng)
        self.assertEqual(season.get("phase"), "complete")

    def test_report_generated_when_playoffs_complete(self):
        self._complete_season()
        report = self.season.get("year_end_report")
        self.assertIsNotNone(report)
        self.assertIn("awards", report)
        self.assertGreater(len(report["awards"]), 0)
        mvp = next(a for a in report["awards"] if a["key"] == "mvp")
        self.assertIn("name", mvp["winner"])

    def test_build_year_end_report_includes_stat_leaders(self):
        self._complete_season()
        report = build_year_end_report(self.season, self.lookup)
        self.assertIn("ppg", report["stat_leaders"])
        self.assertGreater(len(report["stat_leaders"]["ppg"]["leaders"]), 0)

    def test_get_year_end_report_returns_cached(self):
        self._complete_season()
        first = get_year_end_report(self.season, self.lookup)
        second = get_year_end_report(self.season, self.lookup)
        self.assertEqual(first, second)

    def test_champion_in_report(self):
        self._complete_season()
        report = self.season["year_end_report"]
        self.assertEqual(report["champion"]["team_id"], self.season["playoffs"]["champion_id"])


if __name__ == "__main__":
    unittest.main()
