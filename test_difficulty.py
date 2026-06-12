import random
import unittest

import cache
from attributes import apply_attributes
from difficulty import (
    DIFFICULTY_LEVELS,
    get_difficulty_settings,
    normalize_difficulty,
)
from ratings import apply_ratings
from season import init_season


class DifficultyTests(unittest.TestCase):
    def test_normalize_difficulty_defaults_unknown(self):
        self.assertEqual(normalize_difficulty("invalid"), "normal")
        self.assertEqual(normalize_difficulty(None), "normal")

    def test_all_levels_have_presets(self):
        for level in DIFFICULTY_LEVELS:
            settings = get_difficulty_settings({"difficulty": level})
            self.assertGreater(settings["max_cpu_fa_signings"], 0)
            self.assertIn("trade_tolerance", settings)

    def test_legend_is_harder_than_easy(self):
        easy = get_difficulty_settings({"difficulty": "easy"})
        legend = get_difficulty_settings({"difficulty": "legend"})
        self.assertLess(easy["max_cpu_fa_signings"], legend["max_cpu_fa_signings"])
        self.assertGreater(easy["trade_tolerance"], legend["trade_tolerance"])
        self.assertGreater(easy["outcome_nudge_blend"], legend["outcome_nudge_blend"])

    def test_init_season_stores_difficulty(self):
        cache_data = cache.load_cache()
        players = list(cache_data.get("players", []))
        apply_ratings(players)
        apply_attributes(players)
        season = init_season(players, season_year=2026, rng=random.Random(1), difficulty="hard")
        self.assertEqual(season["difficulty"], "hard")
        self.assertTrue(season["gm_personalities_enabled"])


if __name__ == "__main__":
    unittest.main()
