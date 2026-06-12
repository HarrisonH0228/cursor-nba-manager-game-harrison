"""Smoke tests for legal footer pages."""

import unittest

from app import app
from game import clear_game


class LegalPageTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            clear_game(sess)

    def test_terms_page(self):
        response = self.client.get("/terms")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Terms of Service", response.data)
        self.assertIn(b"unofficial", response.data.lower())

    def test_privacy_page(self):
        response = self.client.get("/privacy")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Privacy Policy", response.data)

    def test_disclaimer_page(self):
        response = self.client.get("/disclaimer")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Disclaimer", response.data)
        self.assertIn(b"affiliated", response.data.lower())

    def test_footer_links_on_home(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"/terms", response.data)
        self.assertIn(b"/privacy", response.data)
        self.assertIn(b"/disclaimer", response.data)


if __name__ == "__main__":
    unittest.main()
