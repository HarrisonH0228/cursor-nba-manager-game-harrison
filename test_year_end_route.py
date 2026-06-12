"""Route smoke tests for year-end report page."""

import os
import tempfile
import unittest

import season_store
from app import app
from game import clear_game


class YearEndRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig_seasons_dir = season_store.SEASONS_DIR
        cls._temp_dir = tempfile.mkdtemp()
        season_store.SEASONS_DIR = cls._temp_dir

    @classmethod
    def tearDownClass(cls):
        season_store.SEASONS_DIR = cls._orig_seasons_dir

    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            clear_game(sess)

    def test_year_end_redirects_without_complete_season(self):
        self.client.post("/start")
        self.client.post("/season/start")
        response = self.client.get("/season/year-end", follow_redirects=False)
        self.assertEqual(response.status_code, 302)


if __name__ == "__main__":
    unittest.main()
