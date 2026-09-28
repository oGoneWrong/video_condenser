"""
tests/test_build_video.py
Unit tests for build_video.py's pure, side-effect-free packing logic
(pack_by_height). Everything else in build_video.py either shells out
(Kokoro TTS via `npx hyperframes tts`) or touches the filesystem, so this
file is deliberately narrow - it locks in the one function whose behavior
is worth pinning down without a real render.

Run: python3 -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_video import pack_by_height, count_slides, AVAILABLE_HEIGHT  # noqa: E402


class PackByHeightTests(unittest.TestCase):
    def test_items_that_fit_share_one_page(self):
        items = ["a", "b", "c"]
        pages = pack_by_height(items, lambda item: AVAILABLE_HEIGHT / 4)
        self.assertEqual(pages, [["a", "b", "c"]])

    def test_overflow_starts_a_new_page(self):
        # Two items fit together (1000 < AVAILABLE_HEIGHT), a third would
        # push the running total over budget and starts a new page instead.
        items = ["a", "b", "c"]
        pages = pack_by_height(items, lambda item: 500)
        self.assertEqual(pages, [["a", "b"], ["c"]])

    def test_oversized_single_item_still_gets_its_own_page(self):
        # The docstring's explicit guarantee: an item bigger than the
        # whole budget on its own must not be silently dropped.
        pages = pack_by_height(["huge"], lambda item: AVAILABLE_HEIGHT * 5)
        self.assertEqual(pages, [["huge"]])

    def test_oversized_item_does_not_merge_onto_an_already_full_page(self):
        heights = {"a": 10, "huge": AVAILABLE_HEIGHT * 5}
        pages = pack_by_height(["a", "huge"], lambda item: heights[item])
        self.assertEqual(pages, [["a"], ["huge"]])

    def test_empty_input_returns_no_pages(self):
        self.assertEqual(pack_by_height([], lambda item: 1), [])


class CountSlidesTests(unittest.TestCase):
    def test_counts_each_slide_variant_once(self):
        html = (
            '<div class="slide facts-slide">a</div>'
            '<div class="slide map-slide">b</div>'
            '<div class="slide numbers-slide">c</div>'
        )
        self.assertEqual(count_slides(html), 3)

    def test_ignores_non_slide_classes(self):
        html = '<div class="slide-deck-wrapper"><div class="header">x</div></div>'
        # "slide-deck-wrapper" doesn't contain the whole word "slide" on its
        # own token boundary the way count_slides expects real slide divs
        # to - this pins down that a wrapper class isn't miscounted as a slide.
        self.assertEqual(count_slides(html), 0)

    def test_empty_html_counts_zero(self):
        self.assertEqual(count_slides(""), 0)


if __name__ == "__main__":
    unittest.main()
