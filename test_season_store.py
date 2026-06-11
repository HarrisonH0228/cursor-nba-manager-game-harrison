import json
import os
import shutil
import tempfile
import unittest

import season_store


class SeasonStoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig_seasons_dir = season_store.SEASONS_DIR
        cls._temp_dir = tempfile.mkdtemp()
        season_store.SEASONS_DIR = cls._temp_dir

    @classmethod
    def tearDownClass(cls):
        season_store.SEASONS_DIR = cls._orig_seasons_dir
        shutil.rmtree(cls._temp_dir, ignore_errors=True)

    def setUp(self):
        for name in os.listdir(season_store.SEASONS_DIR):
            path = os.path.join(season_store.SEASONS_DIR, name)
            if os.path.isfile(path):
                os.remove(path)

    def _sample_season(self, **overrides):
        payload = dict(season_store.DEFAULT_SEASON)
        payload["season_year"] = 2026
        payload.update(overrides)
        return payload

    def test_save_load_round_trip(self):
        season_id = season_store.create_season_id()
        payload = self._sample_season(current_day=5)

        season_store.save_season(season_id, payload)
        loaded, status = season_store.load_season(season_id)

        self.assertIsNone(status)
        self.assertEqual(loaded["current_day"], 5)

    def test_save_writes_valid_json(self):
        season_id = season_store.create_season_id()
        season_store.save_season(season_id, self._sample_season())
        path = season_store._season_path(season_id)
        with open(path, encoding="utf-8") as handle:
            json.load(handle)

    def test_load_recovers_from_bak(self):
        season_id = season_store.create_season_id()
        season_store.save_season(season_id, self._sample_season(current_day=8))
        season_store.save_season(season_id, self._sample_season(current_day=9))

        path = season_store._season_path(season_id)
        backup = season_store._backup_path(season_id)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{not valid json")

        loaded, status = season_store.load_season(season_id)
        self.assertEqual(status, "restored")
        self.assertEqual(loaded["current_day"], 9)
        self.assertTrue(os.path.exists(backup))

    def test_load_returns_none_when_both_corrupt(self):
        season_id = season_store.create_season_id()
        path = season_store._season_path(season_id)
        backup = season_store._backup_path(season_id)
        corrupt = season_store._corrupt_path(season_id)

        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{bad")
        with open(backup, "w", encoding="utf-8") as handle:
            handle.write("{also bad")

        loaded, status = season_store.load_season(season_id)
        self.assertIsNone(loaded)
        self.assertEqual(status, "corrupt")
        self.assertTrue(os.path.exists(corrupt))
        self.assertFalse(os.path.exists(path))
