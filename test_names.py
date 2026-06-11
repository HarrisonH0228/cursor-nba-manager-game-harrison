"""Tests for unique player name deduplication."""

import unittest

from names import ensure_unique_name


class NameTests(unittest.TestCase):
    def test_no_collision_unchanged(self):
        self.assertEqual(ensure_unique_name("John Smith", {"Jane Doe"}), "John Smith")

    def test_collision_gets_jr(self):
        result = ensure_unique_name("John Smith", {"John Smith"})
        self.assertEqual(result, "John Smith Jr.")

    def test_suffix_progression(self):
        existing = {"John Smith", "John Smith Jr.", "John Smith Sr."}
        result = ensure_unique_name("John Smith", existing)
        self.assertEqual(result, "John Smith II")

    def test_case_insensitive(self):
        result = ensure_unique_name("john smith", {"John Smith"})
        self.assertEqual(result, "john smith Jr.")


if __name__ == "__main__":
    unittest.main()
