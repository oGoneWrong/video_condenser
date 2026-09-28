"""
extract_insights.py
Step 3 of the pipeline: transcript -> structured journalistic insights,
via the Google Gemini API (free tier - no billing required, unlike the
Anthropic Console API which is prepaid-credits-only).

Why bullet-point extraction avoids plagiarism (and a full paragraph
rewrite risks it): a paraphrase that follows the transcript's own
sentence order and structure is still derivative, even with every word
swapped for a synonym - that's the shallow "paraphraser" pattern
plagiarism detectors are built to catch. Extraction is different: the
model reads for FACTS, drops the original phrasing and structure
entirely, and re-expresses each fact as an independent, self-contained
statement. What survives is the information, not the source's words or
shape - which is also structurally closer to what Step 4 (short-video
scenes) actually needs: discrete, ranked, one-idea-per-line points, not
flowing prose.

Output has two sections:
  FACTS         - who/what/when, directly from the transcript (names,
                  dates, attributed interviewee responses).
  NUMBERS & CONTEXT - quantitative claims. Anything actually stated in
                  the transcript is extracted normally. Anything a
                  reader would want but the transcript DOESN'T provide
                  (adoption rates, spending figures, companies
                  involved, etc.) is explicitly flagged as
                  "[NOT IN VIDEO - verify externally]" rather than
                  guessed at. This matters: an LLM asked to "supplement
                  with other reliable sources" without an actual search
                  tool will produce a plausible-sounding number that
                  may simply be invented. Flagging the gap instead of
                  filling it keeps every number in this file
                  traceable back to the source - you do the external
                  verification yourself, deliberately, rather than
                  inheriting a hallucinated stat without knowing it.

Setup:
    1. Get a free API key at https://aistudio.google.com/apikey
       (no credit card required for the free tier)
    2. pip install google-genai python-dotenv
    3. Add GEMINI_API_KEY=your_key_here to your .env file
       (same .env as Step 2's ASSEMBLYAI_API_KEY - one file, all keys)

Usage:
    python extract_insights.py <video_id_or_identifier>
    (reads transcripts/<identifier>.txt, writes insights/<identifier>.txt)

Retries + same-tier model fallback: the free tier's Flash models
occasionally return a 503 ("this model is currently experiencing high
demand") or a 429 (rate limit) - real, if temporary, availability
problems. This call retries the current model a few times with
exponential backoff, then falls back to the next model in
EXTRACTION_MODELS. Unlike slide_planner.py's equivalent cascade
(4 models deep, down to gemini-3.5-flash-lite), this one is
deliberately shorter - 3.8 -> 3.7 -> 3.6 Flash only - and does NOT
fall through to Flash-Lite. Reasoning, checked against Google's own
published GDPVal-AA v2 benchmark (a professional-knowledge/reasoning
Elo score): 3.8 -> 3.7 -> 3.6 step down gradually and consistently
(~4% each, 1545 -> 1482 -> 1421 Elo) - they're the same "Flash" tier,
just successive generations. 3.6 -> 3.5 Flash-Lite isn't a step, it's
a cliff (Flash-Lite's general Intelligence Index is roughly half of
3.8 Flash's) - a genuinely smaller/cheaper model class, not just an
older one. That distinction matters more here than in slide_planner.py:
slide_planner's own fallback, if every model fails, is deterministic
regex grouping - a non-LLM safety net. This function's output IS the
deliverable text (the journalistic rewrite itself), and has no
equivalent non-LLM fallback, so a quiet fall-through to a meaningfully
weaker model would mean nothing catches a resulting drop in write
quality. Running out of same-tier Flash models is instead treated as a
real, reportable failure (raised to the caller) rather than silently
degrading what gets narrated in the video.

Any exception that ISN'T a 503/429 (a bad key, a malformed response)
is raised immediately instead of burning through every model on
something none of them would fix.
"""

import os
import random
import sys
import time

from google import genai
from google.genai import types
from dotenv import load_dotenv

from storage import load_transcript, save_text

load_dotenv()

# Ordered newest -> oldest, same-tier Flash models only - see the
# module docstring's "Retries + same-tier model fallback" section for
# why this stops at 3.6 Flash rather than also falling through to
# 3.5 Flash-Lite the way slide_planner.py's cascade does.
EXTRACTION_MODELS = [
    "models/gemini-3.8-flash",
    "models/gemini-3.7-flash",
    "models/gemini-3.6-flash",
]

# Retries per model, with exponential backoff, before moving on to the
# next (older) model in EXTRACTION_MODELS. Applies only to
# infrastructure-level failures (503 overloaded, 429 rate-limited) -
# see _is_retryable. Mirrors slide_planner.py's identical constants;
# kept as a separate copy rather than a shared import so each pipeline
# stage script still runs standalone (see README.md's repo layout).
MAX_RETRIES_PER_MODEL = 3
BASE_BACKOFF_SECONDS = 1.0


def _is_retryable(exc: Exception) -> bool:
    """
    True only for infrastructure-level failures worth retrying or
    escalating to an older model - the model is temporarily overloaded
    (503) or the free tier's rate limit was hit (429). False for
    everything else (a bad API key, a malformed response) - those
    aren't fixed by waiting or trying a different model, so they
    should surface immediately.
    """
    code = getattr(exc, "code", None)
    status = str(getattr(exc, "status", "") or "").upper()
    message = str(exc)
    return (
        code in (503, 429)
        or status in ("UNAVAILABLE", "RESOURCE_EXHAUSTED")
        or "UNAVAILABLE" in message
        or "RESOURCE_EXHAUSTED" in message
        or "high demand" in message.lower()
    )


_ATTEMPT_WORDS = {2: "second", 3: "third", 4: "fourth", 5: "fifth"}


def _attempt_word(n: int) -> str:
    return _ATTEMPT_WORDS.get(n, f"attempt {n}")


def _error_label(exc: Exception) -> str:
    """'Error 503 UNAVAILABLE' when the SDK exposes a code/status, else
    the exception's class name."""
    code = getattr(exc, "code", None)
    status = getattr(exc, "status", None)
    if code and status:
        return f"Error {code} {status}"
    if code:
        return f"Error {code}"
    return f"Error ({type(exc).__name__})"


def _call_gemini(client, prompt: str, models: list):
    """
    Try each model in `models` in order (newest first). A 503/429 on
    the current model is retried a few times with exponential backoff;
    once that model's retries are exhausted, move on to the next,
    older model. Any other exception is raised immediately - see
    _is_retryable and the module docstring.

    Prints one line before each attempt and one line per failure, so
    someone watching the terminal can follow along instead of a silent
    pause followed by an unexplained crash.
    """
    config = types.GenerateContentConfig(
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    last_exc = None
    for model_index, model in enumerate(models):
        for attempt in range(MAX_RETRIES_PER_MODEL):
            print(f"Connected to {model} - extracting insights...", file=sys.stderr)
            try:
                response = client.models.generate_content(model=model, contents=prompt, config=config)
                print(f"{model} responded - insights ready.", file=sys.stderr)
                return response
            except Exception as exc:
                if not _is_retryable(exc):
                    raise
                last_exc = exc

                is_last_attempt = attempt == MAX_RETRIES_PER_MODEL - 1
                is_last_model = model_index == len(models) - 1
                label = _error_label(exc)

                if is_last_attempt and is_last_model:
                    print(f"{label} on {model} - out of fallback models "
                          f"(stopped at {model}, not falling through to "
                          "Flash-Lite - see module docstring).", file=sys.stderr)
                elif is_last_attempt:
                    next_model = models[model_index + 1]
                    print(f"{label} on {model} - fallback attempt, "
                          f"switching to {next_model}...", file=sys.stderr)
                else:
                    sleep_for = BASE_BACKOFF_SECONDS * (2 ** attempt) + random.uniform(0, 0.5)
                    print(f"{label} on {model} - {_attempt_word(attempt + 2)} attempt, "
                          f"retrying in {sleep_for:.1f}s...", file=sys.stderr)
                    time.sleep(sleep_for)
    raise last_exc

EXTRACTION_PROMPT = """You are a journalist extracting structured insights from a video transcript, \
to be used later as the basis for a short insight video.

Produce exactly two sections, in this exact format:

## FACTS
The concrete, named facts stated in the transcript: what the subject/project is \
called, when it started or happened, who is involved (names, roles), and how \
interviewees responded. One fact per line, formatted as "Label: value". \
Attributed responses should be short and in your own words, not verbatim quotes \
copied word-for-word from the transcript.

## NUMBERS & CONTEXT
Two kinds of lines, both one per line:
1. Any numbers, statistics, or figures ACTUALLY STATED in the transcript, in your \
own words, formatted as "Label: value".
2. Up to 5 additional numbers or contextual facts a reader would reasonably want \
to know about this topic (e.g. adoption rate, spending, companies involved, \
comparable programs) that are NOT stated in the transcript. For each of these, \
write: "[NOT IN VIDEO - verify externally]: <what to look up and why it matters>".

Hard rules:
- Every fact or number pulled FROM the transcript must be phrased in your own \
words - never copy transcript sentences verbatim.
- Never fabricate or estimate a statistic that isn't in the transcript. If you \
don't know a number, use the "[NOT IN VIDEO - verify externally]" placeholder \
instead of guessing at a value.
- Keep each line to one sentence or less.
- Output ONLY the two sections above. No preamble, no closing remarks.

Transcript:
{transcript}
"""


def extract_insights(transcript_text: str, api_key: str = None, model: str = None) -> str:
    """
    Send transcript text to Gemini and return journalistic bullet-point
    insights extracted from it.

    By default, cascades through EXTRACTION_MODELS (3.8 -> 3.7 -> 3.6
    Flash) with retries on transient 503/429 errors - see the module
    docstring's "Retries + same-tier model fallback" section. Pass
    `model=` to pin a single specific model instead (no cascade,
    no fallback) - useful for testing or if you want deterministic
    model selection.
    """
    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError(
            "No API key found. Set the GEMINI_API_KEY environment "
            "variable (in .env), or pass api_key= directly."
        )

    client = genai.Client(api_key=key)

    # We never pass `tools=` here - no function calling is happening in
    # this call at all. Automatic function calling (AFC) is on by
    # default in the SDK regardless, which is what triggers its "not
    # recommended" warning. Disabling it explicitly is the documented
    # fix: it matches what we are actually doing (no tools) and silences
    # the warning since the behavior is now stated, not implicit.
    models = [model] if model else EXTRACTION_MODELS
    response = _call_gemini(client, EXTRACTION_PROMPT.format(transcript=transcript_text), models)

    return response.text


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python extract_insights.py <identifier>")

    identifier = sys.argv[1]
    transcript_text = load_transcript(identifier)

    bullets = extract_insights(transcript_text)

    saved_path = save_text(bullets, identifier, "insights")
    print(f"Saved to {saved_path}\n")
    print(bullets)
