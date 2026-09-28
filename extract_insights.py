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
"""

import os
import sys

from google import genai
from google.genai import types
from dotenv import load_dotenv

from storage import load_transcript, save_text

load_dotenv()

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


def extract_insights(transcript_text: str, api_key: str = None, model: str = "models/gemini-3.8-flash") -> str:
    """
    Send transcript text to Gemini and return journalistic bullet-point
    insights extracted from it.
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
    response = client.models.generate_content(
        model=model,
        contents=EXTRACTION_PROMPT.format(transcript=transcript_text),
        config=types.GenerateContentConfig(
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
    )

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
