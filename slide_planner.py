"""
slide_planner.py
The "reasoning" layer between Step 3's raw insights text and Step 4's
slide/chart rendering: decides (a) which FACTS bullets belong on the
same slide together, and (b) which NUMBERS & CONTEXT lines are clean
enough to become a chart bar (label + numeric value + unit) versus
plain context bullets.

Uses the same Google Gemini free tier already wired up in
extract_insights.py (Step 3) - same API key, same .env, same "no
billing required" reasoning - so this adds one more cheap call per
video, not a new provider or a new signup for anyone running the repo.

Deliberately narrow scope: this module never invents content. It only
regroups and re-labels lines that already survived Step 3's own
verification filter (anything "[NOT IN VIDEO - verify externally]" is
dropped in Python, before Gemini ever sees the text - the model is
never in a position to promote an unverified claim into a chart).

Index-based, not verbatim-text-based: the first version asked Gemini to
echo each bullet back word-for-word so Python could check nothing was
dropped. In practice the model doesn't reproduce text with byte-for-byte
fidelity (a re-typed dash, a trimmed space) even when told to, so an
exact-string-equality check against real output raised
"planner dropped, altered, or duplicated a NUMBERS & CONTEXT line" on a
line that was actually just fine. Now Gemini only ever returns which
INDEX a line belongs to; the actual text always comes back from our own
`facts`/`number_lines` lists, never from anything the model typed - so
there is nothing left for it to get slightly wrong.

Fails soft: if GEMINI_API_KEY is missing or the call/parse fails for
any reason, callers fall back to the old deterministic regex/pagination
logic (see build_video.py's build_slide_deck). A public repo shouldn't
hard-fail just because someone hasn't set up an API key yet.

Retries + same-provider model fallback: the free tier's Flash models
occasionally return a 503 ("this model is currently experiencing high
demand") - a real, if temporary, availability problem, and Google's own
error message says to just retry. _call_gemini retries a 503/429 on
the current model a few times with exponential backoff, then moves on
to the next, older model in PLANNER_MODELS (still the same API key -
no second provider, no extra signup for anyone running the repo).
Anything that ISN'T a 503/429 - a bad key, a malformed response, one of
this module's own validation errors below - is a content problem, not
an availability one, so it's raised immediately instead of burning
through every model on something none of them would fix; the caller's
existing regex fallback handles that case same as before.
"""

import json
import os
import random
import sys
import time

from dotenv import load_dotenv

load_dotenv()

# Ordered newest -> oldest. A 503 tends to hit whichever model is
# newest/most in-demand hardest, so falling back to an older-generation
# Flash model is a real fix, not just extra retries against the same
# saturated model. All of these are the same GEMINI_API_KEY / free
# tier - no new provider, no new signup for anyone running the repo.
PLANNER_MODELS = [
    "models/gemini-3.8-flash",
    "models/gemini-3.7-flash",
    "models/gemini-3.6-flash",
    "models/gemini-3.5-flash-lite",
]

# Retries per model, with exponential backoff, before moving on to the
# next (older) model in PLANNER_MODELS. Applies only to infrastructure
# -level failures (503 overloaded, 429 rate-limited) - see _is_retryable.
MAX_RETRIES_PER_MODEL = 3
BASE_BACKOFF_SECONDS = 1.0

PLANNER_PROMPT = """You are laying out a short vertical (9:16) insight video's slides from \
already-verified bullet points. You classify and group by INDEX only - you never retype the \
lines themselves.

FACTS (index. text):
{facts_block}

NUMBERS & CONTEXT (index. text):
{numbers_block}

Return ONLY a JSON object with this exact shape:
{{
  "fact_groups": [[<int index>, ...], ...],
  "chart_items": [{{"index": <int index into NUMBERS & CONTEXT>, \
"label": "<short label, <=6 words>", "value": <plain number, no units or commas>, \
"unit": "<short unit/caption, e.g. 'NT$/month' or '% increase'>"}}, ...],
  "context_indices": [<int index into NUMBERS & CONTEXT>, ...]
}}

FACTS grouping rules - read this carefully, it's the part that's easy to get wrong:
1. First, find "linked pairs": a line that introduces a named person or entity (e.g. \
"Interviewee (Mr. Su): ...") and a LATER line that reports specifically what that same person \
said or did (e.g. "Mr. Su's response: ..."). These two lines are a linked pair.
2. A linked pair must never be split across two different groups. If you would otherwise cut \
a group at 3 and that cut falls between a linked pair, move the boundary so the pair stays \
together - even if that makes a group of 2 or 4 instead of 3.
3. Where there's no linked pair to keep together, default to groups of 3, in original index \
order, every index used exactly once.

Worked example of rule 2 (indices only, ignore the topic - it's just to show the shape):
  Input order: 0=intro, 1=context, 2="Interviewee (X): ...", 3="X's response: ...", \
4="Interviewee (Y): ...", 5="Y's response: ..."
  WRONG (default-3 pagination, ignores the pairs): [[0,1,2],[3,4,5]] - this splits X's pair \
(2 and 3 end up in different groups).
  RIGHT: [[0,1],[2,3],[4,5]] - X's pair (2,3) and Y's pair (4,5) each stay whole, even though \
no group has exactly 3.

NUMBERS & CONTEXT rules:
- chart_items: pick lines that state ONE clear numeric quantity - a figure a bar chart could \
show. Parse out just the number (e.g. "nearly NT$36,000" -> 36000). A range ("3% to 5%") or a \
vague comparison ("more than doubled") is NOT a clean number - leave it as a context index \
instead.
- context_indices: every NUMBERS & CONTEXT index not picked for chart_items.
- Every FACTS index must appear in exactly one fact_groups group. Every NUMBERS & CONTEXT index \
must appear in exactly one of chart_items or context_indices. Never drop one, never use one twice.

Output ONLY the JSON object. No markdown fences, no commentary.
"""


def _client_and_key():
    from google import genai

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")
    return genai.Client(api_key=key)


def _numbered_block(lines: list) -> str:
    return "\n".join(f"{i}. {line}" for i, line in enumerate(lines)) or "(none)"


def _is_retryable(exc: Exception) -> bool:
    """
    True only for infrastructure-level failures worth retrying or
    escalating to an older model - the model is temporarily overloaded
    (503) or the free tier's rate limit was hit (429). False for
    everything else (a bad API key, a malformed response, one of this
    module's own validation errors) - those aren't fixed by waiting or
    trying a different model, so they should surface immediately and
    let the caller fall back to the deterministic regex path instead of
    retrying something that will never succeed.
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


# 1-indexed attempt number -> the word someone reading the console
# output would actually use ("second attempt", not "attempt 2/3").
# Only the words up to MAX_RETRIES_PER_MODEL are ever needed; the
# fallback (f"attempt {n}") covers it if that constant is ever raised.
_ATTEMPT_WORDS = {2: "second", 3: "third", 4: "fourth", 5: "fifth"}


def _attempt_word(n: int) -> str:
    return _ATTEMPT_WORDS.get(n, f"attempt {n}")


def _error_label(exc: Exception) -> str:
    """'Error 503 UNAVAILABLE' when the SDK exposes a code/status, else
    the exception's class name - either way, short enough for a
    one-line progress message."""
    code = getattr(exc, "code", None)
    status = getattr(exc, "status", None)
    if code and status:
        return f"Error {code} {status}"
    if code:
        return f"Error {code}"
    return f"Error ({type(exc).__name__})"


def _call_gemini(client, prompt: str):
    """
    Try each model in PLANNER_MODELS in order (newest first). A 503/429
    on the current model is retried a few times with exponential
    backoff; once that model's retries are exhausted, move on to the
    next, older model. Any other exception (bad key, malformed output)
    is raised immediately - see _is_retryable and the module docstring.

    Prints one line before each attempt starts (so a silent multi-
    second API call doesn't look like the script hung) and one line
    per failure, so someone watching the terminal can actually follow
    along - which model it's talking to right now, which attempt just
    failed, and whether it's retrying the same model or falling back
    to the next one - instead of a silent pause followed by an
    unexplained drop to regex grouping.
    """
    from google.genai import types

    config = types.GenerateContentConfig(
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        response_mime_type="application/json",
    )

    last_exc = None
    for model_index, model in enumerate(PLANNER_MODELS):
        for attempt in range(MAX_RETRIES_PER_MODEL):
            print(f"Connected to {model} - crafting the slide layout...", file=sys.stderr)
            try:
                response = client.models.generate_content(model=model, contents=prompt, config=config)
                print(f"{model} responded - slide layout ready.", file=sys.stderr)
                return response
            except Exception as exc:
                if not _is_retryable(exc):
                    raise
                last_exc = exc

                is_last_attempt = attempt == MAX_RETRIES_PER_MODEL - 1
                is_last_model = model_index == len(PLANNER_MODELS) - 1
                label = _error_label(exc)

                if is_last_attempt and is_last_model:
                    print(f"{label} on {model} - out of fallback models, "
                          "handing off to the regex-based layout instead.",
                          file=sys.stderr)
                elif is_last_attempt:
                    next_model = PLANNER_MODELS[model_index + 1]
                    print(f"{label} on {model} - fallback attempt, "
                          f"switching to {next_model}...", file=sys.stderr)
                else:
                    sleep_for = BASE_BACKOFF_SECONDS * (2 ** attempt) + random.uniform(0, 0.5)
                    print(f"{label} on {model} - {_attempt_word(attempt + 2)} attempt, "
                          f"retrying in {sleep_for:.1f}s...", file=sys.stderr)
                    time.sleep(sleep_for)
    raise last_exc


def plan_slides(facts: list, number_lines: list) -> dict:
    """
    Ask Gemini to group FACTS into slide-sized chunks (keeping linked
    pairs like an interviewee's intro + their response together) and
    split NUMBERS & CONTEXT into clean chart data vs. plain context.

    Returns {"fact_groups": [[...text...], ...], "chart_items": [...],
    "context_bullets": [...]} - the same text-based shape build_video.py
    already expects; the index resolution below is entirely internal to
    this function. Raises on any failure - callers should catch and
    fall back to the deterministic regex/pagination path (see
    build_video.py) rather than let one bad LLM response break the
    whole build.
    """
    client = _client_and_key()

    prompt = PLANNER_PROMPT.format(
        facts_block=_numbered_block(facts),
        numbers_block=_numbered_block(number_lines),
    )

    response = _call_gemini(client, prompt)

    raw = json.loads(response.text)

    # Defensive validation - never trust the model for a hard layout
    # constraint, only for the judgment call of how to group things.
    # Every check here is against INDICES the model returned, resolved
    # against our own `facts`/`number_lines` lists - the model's JSON
    # never supplies the actual text, so there's nothing for it to
    # subtly corrupt in transit.
    fact_groups_idx = raw["fact_groups"]
    all_fact_idx = [i for group in fact_groups_idx for i in group]
    if sorted(all_fact_idx) != list(range(len(facts))):
        raise ValueError("planner's fact_groups didn't cover every FACTS index exactly once")
    if any(len(group) > 4 or len(group) == 0 for group in fact_groups_idx):
        raise ValueError("planner produced an out-of-bounds fact group")

    chart_items_idx = raw["chart_items"]
    context_idx = raw["context_indices"]
    chart_indices = [item["index"] for item in chart_items_idx]
    all_number_idx = chart_indices + context_idx
    if sorted(all_number_idx) != list(range(len(number_lines))):
        raise ValueError("planner's chart_items/context_indices didn't cover every "
                          "NUMBERS & CONTEXT index exactly once")

    return {
        "fact_groups": [[facts[i] for i in group] for group in fact_groups_idx],
        "chart_items": [
            {
                "label": item["label"],
                "value": item["value"],
                "unit": item.get("unit", ""),
                "source_line": number_lines[item["index"]],
            }
            for item in chart_items_idx
        ],
        "context_bullets": [number_lines[i] for i in context_idx],
    }
