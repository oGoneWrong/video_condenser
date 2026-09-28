"""
tests/test_heygen_avatar.py
Unit tests for unescape_json_url() in tools/heygen_avatar/generate_avatar_clip.py.
This function was added after run_6's download failed with a plain 403 that
was actually caused by a literal `\\u0026` (JSON-escaped `&`) surviving into
a download URL extracted from raw, non-JSON-decoded HeyGen CLI stdout - see
docs/ARCHITECTURE.md's Step 4b section for the full root cause. These tests
lock in the fix against the exact bug pattern that was hit, plus generalize
it to other escape codes so the fix isn't narrowly hardcoded to just `\\u0026`.

Run: python3 -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools" / "heygen_avatar"))

from generate_avatar_clip import unescape_json_url  # noqa: E402


class UnescapeJsonUrlTests(unittest.TestCase):
    def test_unescapes_the_actual_bug_pattern_that_broke_run_6(self):
        broken = (
            "https://resource2.heygen.ai/video/abc123.mp4"
            "?Expires=1234567890\\u0026Signature=xyz\\u0026Key-Pair-Id=abc"
        )
        fixed = unescape_json_url(broken)
        self.assertEqual(
            fixed,
            "https://resource2.heygen.ai/video/abc123.mp4"
            "?Expires=1234567890&Signature=xyz&Key-Pair-Id=abc",
        )
        # The whole point of the bug: without unescaping, only the first
        # query param survives a real HTTP request.
        self.assertNotIn("\\u0026", fixed)

    def test_clean_url_passes_through_unchanged(self):
        clean = "https://resource2.heygen.ai/video/abc123.mp4?Expires=1&Signature=2"
        self.assertEqual(unescape_json_url(clean), clean)

    def test_generalizes_to_other_escape_codes_not_just_ampersand(self):
        # < / > are "<" / ">" - confirms the fix is a general
        # \uXXXX unescaper, not a special case for "&" alone.
        escaped = "https://example.com/x\\u003cy\\u003ez"
        self.assertEqual(unescape_json_url(escaped), "https://example.com/x<y>z")


if __name__ == "__main__":
    unittest.main()
