"""Tests for admin panel access control and form validation."""

import os
import tempfile
import unittest

import season_store
from app import app
from game import clear_game
from roster import assign_player_to_team
from season import league_lookup


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
        season_data, _ = season_store.load_season(season_id)
        player_count_before = len(season_data.get("players", {}))

        response = self.client.post(
            "/admin/players/create",
            data={"name": "Valid Player", "age": "20", "overall": "60"},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        season_data, _ = season_store.load_season(season_id)
        self.assertEqual(len(season_data.get("players", {})), player_count_before + 1)


class AdminTeamAssignmentTests(unittest.TestCase):
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

    def test_assign_player_to_team_moves_roster(self):
        self._start_game_and_season()
        with self.client.session_transaction() as sess:
            season_id = sess.get("season_id")
        season_data, _ = season_store.load_season(season_id)
        lookup = league_lookup(season_data)
        player = next(p for p in season_data["players"].values() if p.get("team_id"))
        player_id = int(player["id"])
        old_team_id = int(player["team_id"])
        new_team_id = next(
            int(team_id)
            for team_id in season_data["standings"]
            if int(team_id) != old_team_id
        )

        ok, _message = assign_player_to_team(season_data, player_id, new_team_id, force=True)
        self.assertTrue(ok)
        updated = lookup[player_id]
        self.assertEqual(int(updated["team_id"]), new_team_id)
        self.assertNotIn(player_id, season_data["rosters"][str(old_team_id)])
        self.assertIn(player_id, season_data["rosters"][str(new_team_id)])

    def test_assign_player_to_free_agency(self):
        self._start_game_and_season()
        with self.client.session_transaction() as sess:
            season_id = sess.get("season_id")
        season_data, _ = season_store.load_season(season_id)
        lookup = league_lookup(season_data)
        player = next(p for p in season_data["players"].values() if p.get("team_id"))
        player_id = int(player["id"])
        old_team_id = int(player["team_id"])

        ok, _message = assign_player_to_team(season_data, player_id, None, force=True)
        self.assertTrue(ok)
        updated = lookup[player_id]
        self.assertIsNone(updated.get("team_id"))
        self.assertNotIn(player_id, season_data["rosters"][str(old_team_id)])
        self.assertIn(player_id, season_data.get("free_agents", []))

    def test_admin_edit_moves_player_via_form(self):
        self._start_game_and_season()
        with self.client.session_transaction() as sess:
            season_id = sess.get("season_id")
        season_data, _ = season_store.load_season(season_id)
        player = next(p for p in season_data["players"].values() if p.get("team_id"))
        player_id = int(player["id"])
        old_team_id = int(player["team_id"])
        new_team_id = next(
            int(team_id)
            for team_id in season_data["standings"]
            if int(team_id) != old_team_id
        )

        response = self.client.post(
            f"/admin/players/{player_id}/edit",
            data={
                "name": player["name"],
                "age": str(int(player.get("age") or 25)),
                "team_id": str(new_team_id),
            },
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        season_data, _ = season_store.load_season(season_id)
        lookup = league_lookup(season_data)
        updated = lookup[player_id]
        self.assertEqual(int(updated["team_id"]), new_team_id)
        self.assertNotIn(player_id, season_data["rosters"][str(old_team_id)])
        self.assertIn(player_id, season_data["rosters"][str(new_team_id)])

    def test_admin_teams_page(self):
        self._start_game_and_season()
        response = self.client.get(
            "/admin/teams",
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Team Rosters", response.data)
        self.assertIn(b"Edit Roster", response.data)

    def test_admin_team_roster_release(self):
        self._start_game_and_season()
        with self.client.session_transaction() as sess:
            season_id = sess.get("season_id")
        season_data, _ = season_store.load_season(season_id)
        team_id = int(next(iter(season_data["rosters"])))
        player_id = season_data["rosters"][str(team_id)][0]

        response = self.client.post(
            f"/admin/teams/{team_id}",
            data={"action": "release", "player_id": str(player_id)},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        season_data, _ = season_store.load_season(season_id)
        lookup = league_lookup(season_data)
        self.assertNotIn(player_id, season_data["rosters"][str(team_id)])
        self.assertIsNone(lookup[player_id].get("team_id"))


class TeamPageRenderTests(unittest.TestCase):
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

    def test_team_page_renders_without_contract_years(self):
        self.client.post("/start", environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
        self.client.post("/season/start", environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
        with self.client.session_transaction() as sess:
            season_id = sess.get("season_id")
            team_id = sess.get("team_id")
        season_data, _ = season_store.load_season(season_id)
        player_id = season_data["rosters"][str(team_id)][0]
        player = season_data["players"][str(player_id)]
        player.pop("contract_years", None)
        player.pop("salary", None)
        season_store.save_season(season_id, season_data)

        response = self.client.get("/team", environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
        self.assertEqual(response.status_code, 200)
        self.assertIn(player["name"].encode(), response.data)
