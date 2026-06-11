"""Tests for admin panel access control and form validation."""

import os
import tempfile
import unittest

import season_store
from app import app
from game import clear_game


class AdminTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self._prev = os.environ.get("ADMIN_ENABLED")
        os.environ["ADMIN_ENABLED"] = "0"

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("ADMIN_ENABLED", None)
        else:
            os.environ["ADMIN_ENABLED"] = self._prev

    def test_admin_hidden_when_disabled(self):
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 404)

    def test_admin_available_when_enabled_on_localhost(self):
        os.environ["ADMIN_ENABLED"] = "1"
        response = self.client.get("/admin/", environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
        self.assertEqual(response.status_code, 200)


class AdminValidationTests(unittest.TestCase):
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
        self._prev_admin = os.environ.get("ADMIN_ENABLED")
        os.environ["ADMIN_ENABLED"] = "1"
        with self.client.session_transaction() as sess:
            clear_game(sess)

    def tearDown(self):
        if self._prev_admin is None:
            os.environ.pop("ADMIN_ENABLED", None)
        else:
            os.environ["ADMIN_ENABLED"] = self._prev_admin

    def _start_game_and_season(self):
        self.client.post("/start", environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
        self.client.post("/season/start", environ_overrides={"REMOTE_ADDR": "127.0.0.1"})

    def test_create_player_invalid_age(self):
        self._start_game_and_season()
        response = self.client.post(
            "/admin/players/create",
            data={"name": "Test Player", "age": "13.2", "overall": "60"},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Age must be a whole number.", response.data)

    def test_create_player_valid(self):
        self._start_game_and_season()
        with self.client.session_transaction() as sess:
            season_id = sess.get("season_id")
        season_data = season_store.load_season(season_id)
        player_count_before = len(season_data.get("players", {}))

        response = self.client.post(
            "/admin/players/create",
            data={"name": "Valid Player", "age": "20", "overall": "60"},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        season_data = season_store.load_season(season_id)
        self.assertEqual(len(season_data.get("players", {})), player_count_before + 1)
