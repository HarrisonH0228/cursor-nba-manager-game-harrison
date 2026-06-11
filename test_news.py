"""Tests for news ticker."""

import unittest

from news import MAX_NEWS_ITEMS, append_news, news_headlines


class NewsTests(unittest.TestCase):
    def test_append_news_adds_headline(self):
        season = {"news_feed": []}
        headline = append_news(season, "signing", player="Test Player", team="Lakers", salary=10)
        self.assertIn(headline, season["news_feed"])
        self.assertTrue(len(headline) > 0)

    def test_feed_capped(self):
        season = {"news_feed": []}
        for index in range(40):
            append_news(season, "game", player=f"P{index}", pts=30, opp="Celtics")
        self.assertLessEqual(len(season["news_feed"]), MAX_NEWS_ITEMS)

    def test_news_headlines_limit(self):
        season = {"news_feed": [f"H{i}" for i in range(20)]}
        self.assertEqual(len(news_headlines(season, limit=5)), 5)


if __name__ == "__main__":
    unittest.main()
