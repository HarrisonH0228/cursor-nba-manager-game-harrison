"""Tests for game start: roll and team pick flows."""

import unittest

from app import app
from fetcher import fetch_teams
from game import clear_game, get_game


class GameStartTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            clear_game(sess)

    def test_choose_team_page(self):
        response = self.client.get("/choose-team")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Choose Your Team", response.data)

    def test_roll_start(self):
        response = self.client.post("/start", follow_redirects=False)
        self.assertEqual(response.status_code, 302)

        with self.client.session_transaction() as sess:
            game = get_game(current_session=sess)
            self.assertIsNotNone(game)
            valid_ids = {team["id"] for team in fetch_teams()}
            self.assertIn(game["team_id"], valid_ids)

    def test_pick_valid_team(self):
        team_id = fetch_teams()[0]["id"]
        response = self.client.post(
            "/start/pick",
            data={"team_id": str(team_id)},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        with self.client.session_transaction() as sess:
            game = get_game(current_session=sess)
            self.assertIsNotNone(game)
            self.assertEqual(game["team_id"], team_id)

    def test_pick_invalid_team(self):
        response = self.client.post(
            "/start/pick",
            data={"team_id": "999"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        with self.client.session_transaction() as sess:
            game = get_game(current_session=sess)
            self.assertIsNone(game)

    def test_pick_missing_team(self):
        response = self.client.post("/start/pick", data={}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)

        with self.client.session_transaction() as sess:
            game = get_game(current_session=sess)
            self.assertIsNone(game)

    def test_choose_team_redirects_when_game_started(self):
        self.client.post("/start")
        response = self.client.get("/choose-team", follow_redirects=False)
        self.assertEqual(response.status_code, 302)

    def test_not_found_page(self):
        response = self.client.get("/this-route-does-not-exist")
        self.assertEqual(response.status_code, 404)
        self.assertIn(b"Page not found", response.data)


if __name__ == "__main__":
    unittest.main()
