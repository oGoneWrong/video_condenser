"""
tests/test_extract_insights.py
Unit tests for the retry/fallback helpers added to extract_insights.py
in response to a real 503 ("high demand") crash hit while testing
run_pipeline.py end to end - extract_insights.py previously had no
retry logic at all, unlike slide_planner.py's equivalent cascade.
These tests pin down the classification logic (_is_retryable) and
error-label formatting without making any real Gemini calls.

Run: python3 -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from extract_insights import (  # noqa: E402
    EXTRACTION_MODELS,
    _error_label,
    _is_retryable,
)


class FakeGeminiError(Exception):
    """Stands in for google.genai.errors.ServerError/ClientError without
    needing the real SDK installed - only the attributes _is_retryable
    and _error_label actually read (code, status) are faked."""

    def __init__(self, message, code=None, status=None):
        super().__init__(message)
        self.code = code
        self.status = status


class IsRetryableTests(unittest.TestCase):
    def test_503_unavailable_is_retryable(self):
        # The exact shape of the error that crashed run_pipeline.py's
        # test run: google.genai.errors.ServerError: 503 UNAVAILABLE.
        exc = FakeGeminiError("503 UNAVAILABLE", code=503, status="UNAVAILABLE")
        self.assertTrue(_is_retryable(exc))

    def test_429_rate_limited_is_retryable(self):
        exc = FakeGeminiError("429 rate limited", code=429, status="RESOURCE_EXHAUSTED")
        self.assertTrue(_is_retryable(exc))

    def test_high_demand_message_without_a_code_is_retryable(self):
        # Some SDK error paths don't set .code/.status at all - the
        # message text itself is the only signal available.
        exc = FakeGeminiError("This model is currently experiencing high demand.")
        self.assertTrue(_is_retryable(exc))

    def test_bad_api_key_is_not_retryable(self):
        exc = FakeGeminiError("400 API key not valid", code=400, status="INVALID_ARGUMENT")
        self.assertFalse(_is_retryable(exc))

    def test_plain_value_error_is_not_retryable(self):
        self.assertFalse(_is_retryable(ValueError("something else broke")))


class ErrorLabelTests(unittest.TestCase):
    def test_code_and_status_both_present(self):
        exc = FakeGeminiError("x", code=503, status="UNAVAILABLE")
        self.assertEqual(_error_label(exc), "Error 503 UNAVAILABLE")

    def test_code_only(self):
        exc = FakeGeminiError("x", code=503)
        self.assertEqual(_error_label(exc), "Error 503")

    def test_neither_falls_back_to_class_name(self):
        self.assertEqual(_error_label(ValueError("x")), "Error (ValueError)")


class ExtractionModelsTests(unittest.TestCase):
    def test_stops_at_flash_not_flash_lite(self):
        # Locks in the deliberate design choice (see the module
        # docstring): same-tier Flash models only, no fall-through to
        # the meaningfully weaker Flash-Lite tier for this deliverable
        # text-rewrite call.
        self.assertEqual(
            EXTRACTION_MODELS,
            ["models/gemini-3.8-flash", "models/gemini-3.7-flash", "models/gemini-3.6-flash"],
        )
        self.assertNotIn("models/gemini-3.5-flash-lite", EXTRACTION_MODELS)


if __name__ == "__main__":
    unittest.main()
