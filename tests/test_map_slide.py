"""
tests/test_map_slide.py
Unit tests for map_slide.py's _find_cities(), the regex-based city lookup
that the "honest map decision" entry in docs/DECISIONS.md documents as
pattern-matching (a fixed CITIES list), not general geo-entity recognition.
These tests lock in exactly that documented behavior - including its
sharp edges - rather than pretending it's smarter than it is.

Run: python3 -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from map_slide import _find_cities  # noqa: E402


class FindCitiesTests(unittest.TestCase):
    def test_returns_cities_in_order_of_first_appearance(self):
        text = "Kaohsiung reported higher costs than Taipei this year."
        found = _find_cities(text)
        self.assertLess(found.index("Kaohsiung"), found.index("Taipei"))

    def test_new_taipei_masks_out_separate_taipei_match(self):
        # _find_cities masks longer names first specifically so "New Taipei"
        # isn't also double-counted as a bare "Taipei" hit.
        text = "New Taipei City announced a new policy."
        found = _find_cities(text)
        self.assertIn("New Taipei", found)
        self.assertNotIn("Taipei", found)

    def test_duplicate_mentions_collapse_to_one_entry(self):
        text = "Taipei is expensive. Taipei is also crowded. Taipei, Taipei."
        found = _find_cities(text)
        self.assertEqual(found.count("Taipei"), 1)

    def test_word_boundary_rejects_partial_match(self):
        # "Taipeiwan" should not register as a "Taipei" hit - the lookup is
        # word-bounded, not a bare substring search.
        text = "Taipeiwan is not a real place name."
        found = _find_cities(text)
        self.assertNotIn("Taipei", found)

    def test_no_known_city_returns_empty_list(self):
        text = "This sentence mentions no Taiwanese city at all."
        self.assertEqual(_find_cities(text), [])


if __name__ == "__main__":
    unittest.main()
