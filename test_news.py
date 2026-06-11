"""Tests for news ticker."""

import unittest

from news import MAX_NEWS_ITEMS, append_news, news_headlines
from news_templates import template_count


class NewsTests(unittest.TestCase):
    def test_template_count_at_least_100(self):
        self.assertGreaterEqual(template_count(), 100)

    def test_append_news_adds_headline(self):
        season = {"news_feed": []}
        headline = append_news(season, "signing", player="Test Player", team="Lakers", salary=10)
        self.assertIn(headline, season["news_feed"])
        self.assertTrue(len(headline) > 0)

    def test_feed_capped(self):
        season = {"news_feed": []}
        for index in range(40):
            append_news(
                season,
                "game",
                player=f"Player {index}",
                pts=30 + index,
                opp="Celtics",
            )
        self.assertLessEqual(len(season["news_feed"]), MAX_NEWS_ITEMS)

    def test_news_headlines_limit(self):
        season = {"news_feed": [f"H{i}" for i in range(20)]}
        self.assertEqual(len(news_headlines(season, limit=5)), 5)

    def test_duplicate_headline_not_added(self):
        duplicate = "Test Player signs with Lakers for $10M/yr, reportedly for the cafeteria fries"
        season = {"news_feed": [duplicate], "news_template_index": {"signing": 0}}
        result = append_news(season, "signing", player="Test Player", team="Lakers", salary=10)
        self.assertNotEqual(result, duplicate)
        self.assertEqual(season["news_feed"].count(duplicate), 1)

    def test_news_headlines_are_unique(self):
        season = {"news_feed": ["A", "B", "A", "C", "B"]}
        headlines = news_headlines(season, limit=12)
        self.assertEqual(headlines, ["A", "B", "C"])

    def test_news_headlines_pads_with_ambient_when_lookup_provided(self):
        import random

        import cache
        from attributes import apply_attributes
        from ratings import apply_ratings
        from season import init_season, league_lookup

        cache_data = cache.load_cache()
        players = list(cache_data.get("players", []))
        apply_ratings(players)
        apply_attributes(players)
        season = init_season(players, season_year=2026, rng=random.Random(1))
        lookup = league_lookup(season)
        headlines = news_headlines(season, limit=12, lookup=lookup, rng=random.Random(2))
        self.assertGreaterEqual(len(headlines), 12)


if __name__ == "__main__":
    unittest.main()
