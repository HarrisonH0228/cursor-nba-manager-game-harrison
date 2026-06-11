"""Tests for admin panel access control."""

import os
import unittest

from app import app


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
