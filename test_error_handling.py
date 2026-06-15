"""Tests for error handling at external boundaries."""

import os
import tempfile
import unittest
from unittest.mock import patch

import cache
import custom_players
import fetcher
import season_store
from errors import format_cache_timestamp, read_json


class ErrorHandlingTests(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.mkdtemp()
        self._orig_cache_path = cache.CACHE_PATH
        self._orig_seasons_dir = season_store.SEASONS_DIR
        self._orig_custom_path = custom_players.CUSTOM_PLAYERS_PATH
        cache.CACHE_PATH = os.path.join(self._temp_dir, "cache.json")
        season_store.SEASONS_DIR = os.path.join(self._temp_dir, "seasons")
        custom_players.CUSTOM_PLAYERS_PATH = os.path.join(self._temp_dir, "custom_players.json")

    def tearDown(self):
        cache.CACHE_PATH = self._orig_cache_path
        season_store.SEASONS_DIR = self._orig_seasons_dir
        custom_players.CUSTOM_PLAYERS_PATH = self._orig_custom_path

    def test_corrupt_cache_returns_default(self):
        os.makedirs(os.path.dirname(cache.CACHE_PATH), exist_ok=True)
        with open(cache.CACHE_PATH, "w", encoding="utf-8") as handle:
            handle.write("{not json")

        data = cache.load_cache()
        self.assertEqual(data["players"], [])
        self.assertIsNone(data["last_updated"])

    def test_corrupt_custom_players_returns_default(self):
        os.makedirs(os.path.dirname(custom_players.CUSTOM_PLAYERS_PATH), exist_ok=True)
        with open(custom_players.CUSTOM_PLAYERS_PATH, "w", encoding="utf-8") as handle:
            handle.write("{bad")

        data = custom_players.load_custom_players()
        self.assertEqual(data["players"], [])

    def test_refresh_cache_uses_existing_cache_on_api_failure(self):
        cache.save_cache(
            {
                "last_updated": "2026-06-01T12:00:00Z",
                "season": 2026,
                "players": [{"id": 1, "name": "Test Player"}],
            }
        )

        with patch.object(fetcher, "_fetch_league_player_stats", side_effect=RuntimeError("network down")):
            result = fetcher.refresh_cache()

        self.assertFalse(result["ok"])
        self.assertTrue(result["used_cache"])
        self.assertEqual(result["last_updated"], "2026-06-01T12:00:00Z")
        self.assertEqual(len(cache.get_players()), 1)

    def test_refresh_cache_empty_cache_does_not_raise(self):
        cache.ensure_cache_file()

        with patch.object(fetcher, "_fetch_league_player_stats", side_effect=RuntimeError("network down")):
            result = fetcher.refresh_cache()

        self.assertFalse(result["ok"])
        self.assertFalse(result["used_cache"])
        self.assertIsNone(result["last_updated"])
        self.assertIn("network down", result["error"])

    def test_save_season_write_failure_returns_false(self):
        season_id = season_store.create_season_id()
        with patch("season_store.write_json", return_value=False):
            ok = season_store.save_season(season_id, {"season_year": 2026, "players": {}})
        self.assertFalse(ok)

    def test_player_record_skips_malformed_row(self):
        record = fetcher._player_record({"GP": 10}, {}, {})
        self.assertIsNone(record)

    def test_format_cache_timestamp(self):
        formatted = format_cache_timestamp("2026-06-01T12:00:00Z")
        self.assertIn("2026", formatted)
        self.assertIn("UTC", formatted)

    def test_invalid_season_id_rejected(self):
        self.assertIsNone(season_store.load_season("not-a-uuid"))
        self.assertIsNone(season_store.load_season("../etc/passwd"))
        self.assertFalse(season_store.save_season("bad-id", {"season_year": 2026}))
        self.assertFalse(season_store.delete_season("bad-id"))

    def test_read_json_default_not_mutated(self):
        default = {"players": []}
        path = os.path.join(self._temp_dir, "missing.json")
        data = read_json(path, default, "test default")
        data["players"].append({"id": 1})
        self.assertEqual(default["players"], [])
        again = read_json(path, default, "test default")
        self.assertEqual(again["players"], [])


class AdminAuthTests(unittest.TestCase):
    def setUp(self):
        import app as app_module

        self.app = app_module.app
        self.app.config["WTF_CSRF_ENABLED"] = False
        self.client = self.app.test_client()

    def test_admin_panel_requires_login(self):
        with self.client.session_transaction() as sess:
            sess.pop("admin_authenticated", None)
        response = self.client.get("/admin", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login", response.headers.get("Location", ""))

    def test_admin_login_grants_access(self):
        response = self.client.post(
            "/admin/login",
            data={"password": "1234"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertTrue(sess.get("admin_authenticated"))


if __name__ == "__main__":
    unittest.main()
