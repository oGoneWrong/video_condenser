"""
build_video.py
Step 4 (final) of the pipeline: structured insights -> a short,
narrated, vertical (9:16) insight video - assembled by HyperFrames
(HTML -> MP4, https://github.com/heygen-com/hyperframes) instead of
Pillow + MoviePy.

Why the switch: a PNG handed to ffmpeg is a black box between "here's
the text" and "here's the pixels" - nothing left to read back or
reason about once it's rendered. An HTML composition stays text the
whole way through: content and layout both stay inspectable and
editable, which is exactly what the slide-review checkpoint is for.

Pipeline shape (v6, runs end-to-end in one place - no laptop hop):
  1. build_slide_deck(identifier)     - unchanged from v3: turns Step 3's
     insights into a paginated deck (facts pages, numbers pages), each
     capped so a slide's content always fits without clipping.
  2. render_slides(identifier)        - CHECKPOINT. Renders every slide
     as a standalone, browser-openable .html file under
     slides/<identifier>/ and stops. No audio, no composition, no video.
  3. build_composition(identifier)    - narrates each slide (local
     Kokoro-82M TTS via `npx hyperframes tts` - no network call, unlike
     edge-tts - concatenated per slide via ffmpeg's concat demuxer),
     probes each merged clip's real duration (ffprobe), and writes a
     STANDALONE HyperFrames composition to render/compositions/<identifier>.html
     with every slide + its audio as sibling timed clips.
  4. npx hyperframes render (from render/) - Chrome + ffmpeg are already
     on this machine, and GSAP is now vendored locally (render/vendor/),
     so the whole pipeline - narration, composition, render - runs
     wherever this script runs, without needing edge-tts's network
     endpoint or a jsdelivr CDN fetch at render time.

v5 -> v6 change, and why: v5 used edge-tts (network TTS) and a
jsdelivr CDN <script> for GSAP. Both are fine on a machine with open
internet (e.g. your own laptop) but get silently blocked by a locked-down
sandbox's network allowlist. Kokoro-82M is a small local model (one-time
download, then fully offline) and a vendored gsap.min.js needs no
network at render time either, so the same script produces the same
MP4 anywhere - which turned out to matter for a different reason than
the one that motivated it: edge-tts is an unofficial, reverse-engineered
hook into a Microsoft endpoint, not something a public repo should
depend on indefinitely. Kokoro's local-model approach is the more
durable choice for that reason alone, sandbox or not.

v6 -> v7 change: this project is being published to GitHub for other
people to run themselves, so "renders correctly in whatever environment
Claude happens to run in" stopped being the goal - the goal is a plain,
reusable Python entry point, matching the style of Steps 1-3.
  - Visual identity switched from an ad hoc dark palette to HyperFrames'
    published "Blue Professional" design spec (hyperframes.dev/design):
    corporate parchment #fdfae7 background, cobalt #1e2bfa as the one
    accent color, Space Grotesk display / Inter body - vendored locally
    (render/vendor/fonts/) rather than a Google Fonts CDN link, same
    determinism reasoning as the GSAP fix.
  - A new reasoning step (slide_planner.py) replaces the old
    regex-only grouping/chart-detection with one Gemini call - the same
    free-tier Gemini already used by extract_insights.py (Step 3), so
    this adds no new provider, no new signup, and a negligible per-video
    cost. It decides which FACTS bullets belong together (still capped
    at 3, up to 4 only when tightly linked) and which NUMBERS & CONTEXT
    lines are clean enough to chart. It fails soft: if the call or its
    output doesn't check out, build_slide_deck falls back to the old
    deterministic regex/pagination path rather than breaking the build.
  - NUMBERS & CONTEXT figures that share a unit (so they're actually
    comparable) become a hand-coded inline SVG bar chart - no chart
    library, no CDN, nothing to vendor beyond what's already local.
    A figure that's the only one in its unit becomes a single large
    stat number instead of a one-bar "chart", which would compare
    against nothing.

The composition format below follows the real rules read from the
installed project's own AGENTS.md/CLAUDE.md and .agents/skills/ docs
(hyperframes-core: minimal-composition.md, composition-patterns.md,
tracks-and-clips.md), not the approximate examples found via web
search earlier - those omitted the GSAP timeline registration, the
root's positioning requirements, and the monolithic-vs-sub-composition
distinction entirely. Key rules actually enforced by the tool:
  - Root needs data-composition-id, data-width, data-height, and a
    duration source (we set root data-duration explicitly).
  - Every timed element needs data-start (+ a duration for non-media
    clips); class="clip" is what the shared CSS keys the full-frame
    box off, and `lint` warns without it.
  - One paused root GSAP timeline must be registered on
    window.__timelines[composition-id], even with nothing to animate
    yet (animations are still deferred, per the original request).
  - This is the "monolithic" architecture (one file, sibling `.clip`
    scenes) - no <template> wrapping needed, since we're not using
    sub-compositions (data-composition-src) for anything.

Render it (from inside the render/ project directory):
    npm run check   # lint - always run after regenerating a composition
    time npx hyperframes render . -c compositions/<identifier>.html \\
        -o ../videos/<identifier>.mp4 -q draft
    # `time` reports how long the render took once it's done - no
    # stopwatch needed, same idea as the elapsed-time line this script
    # itself prints after narrating + writing the composition.

Colors and typography follow the dataviz skill's validated dark-mode
palette (references/palette.md), as CSS custom properties - the
palette file is already written that way, so this ports over close to
verbatim:
  chart surface #1a1a19, primary ink #ffffff, secondary ink #c3c2b7,
  accent (categorical slot 1, blue) #3987e5 for stat-tile numbers and
  bullet markers. Text never carries the accent color itself - only
  the bullet dot / stat number does; body text stays in ink tokens.

Anything flagged "[NOT IN VIDEO - verify externally]" by Step 3 is
still dropped before rendering or narration - unverified content never
reaches a slide or the finished video.

Setup:
    pip install kokoro-onnx soundfile google-genai python-dotenv
    (first run of `npx hyperframes tts` downloads the ~/.hyperframes-cached
     Kokoro-82M model once; every run after that is fully offline.
     ffmpeg is already required by Step 1 - this reuses that same binary
     for audio concatenation and duration probing, no new package.
     GEMINI_API_KEY is the same free-tier key Step 3 already needs - see
     extract_insights.py's own Setup section - reused here by
     slide_planner.py; if it's missing, this script still works, just
     with the older regex-based grouping instead of Gemini's.)

    One-time, after `npx hyperframes init render`:
        cd render
        npm install gsap @fontsource/space-grotesk @fontsource/inter
        mkdir -p vendor/fonts
        cp node_modules/gsap/dist/gsap.min.js vendor/
        cp node_modules/@fontsource/inter/files/inter-latin-400-normal.woff2 vendor/fonts/
        cp node_modules/@fontsource/space-grotesk/files/space-grotesk-latin-{400,600,700}-normal.woff2 vendor/fonts/
        rm -rf node_modules   # only vendor/ is needed from here on

Usage:
    python build_video.py <identifier> --slides-only
        (writes slides/<identifier>/*.html for review, stops there)
    python build_video.py <identifier>
        (also narrates + writes render/compositions/<identifier>.html
         plus its audio files - stops short of the render/CLI step,
         which needs the Node project and is run separately, see above)
"""

import html
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from storage import load_text
from map_slide import (
    MAP_SLIDE_CSS,
    build_map_highlight_tweens,
    build_map_slide,
    render_avatar_clip_html,
    render_map_slide_html,
)

VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
# Kokoro-82M voice id (local, offline TTS via `npx hyperframes tts`).
# af_heart is the tool's own default - a warm, clear US-female voice.
# Full list: run `npx hyperframes tts --list`.
VOICE = "af_heart"

OUTPUT_DIR = Path("videos")
SLIDES_DIR = Path("slides")
TEMP_DIR = Path(".video_build_tmp")

# Generous on purpose - the very first `npx hyperframes tts` call ever
# made on a machine downloads the Kokoro-82M model first, which can
# legitimately take a couple of minutes on a slow connection. Every
# call after that finishes in single-digit seconds once the model's
# cached, so a call still running past this is genuinely stuck, not
# just slow - see generate_narration.
TTS_TIMEOUT_SECONDS = 600

# A dropped connection (most often mid-download of that same Kokoro
# model) fails FAST with an error in the JSON payload rather than
# hanging - a different failure mode from TTS_TIMEOUT_SECONDS above,
# and one a plain retry often just fixes, so it gets its own small
# retry loop instead of being treated as a hard failure on the first hit.
TTS_MAX_RETRIES = 3
TTS_RETRY_BACKOFF_SECONDS = 2.0
_TTS_RETRYABLE_ERROR_SNIPPETS = (
    "ECONNRESET", "ETIMEDOUT", "ECONNREFUSED", "EAI_AGAIN", "SOCKET HANG UP",
)

# The HyperFrames project scaffolded by `npx hyperframes init render` -
# a sibling Node project. Compositions and their audio live here so
# `npx hyperframes render` (run from inside render/) can find them.
RENDER_DIR = Path("render")
COMPOSITIONS_DIR = RENDER_DIR / "compositions"
# GSAP vendored locally (npm install gsap; dist copied here) instead of
# the jsdelivr CDN <script src> v5 used - a locked-down sandbox's network
# allowlist can reach npm's registry but not arbitrary CDNs, so the
# composition must not depend on a CDN fetch at render time.
GSAP_VENDOR_PATH = RENDER_DIR / "vendor" / "gsap.min.js"
# Space Grotesk / Inter (Blue Professional's two typefaces), vendored the
# same way via `npm install @fontsource/space-grotesk @fontsource/inter`
# and copying just the latin woff2 files - not a Google Fonts CDN link,
# for the same offline/deterministic-render reason as GSAP above.
FONT_VENDOR_DIR = RENDER_DIR / "vendor" / "fonts"

# --- Height-based slide packing ---------------------------------------
# v7 used a fixed per-slide item COUNT (3 facts, 2 chart blocks, 2
# context bullets) to keep a slide's content inside the canvas. That
# guarantees no overflow, but it's blind to how much of the canvas a
# given count actually fills - a slide with two short bullets and a
# slide with two near-max-length bullets get the same cap, so the
# short case renders with a lot of visibly empty canvas below the
# content ("dead space"), and the pipeline was already producing more,
# thinner slides than the content needed.
#
# v8 replaces the count cap with an estimate of each candidate's real
# rendered HEIGHT, and packs greedily: keep adding whole items to the
# current slide while the running estimate stays under budget, cut to
# a new slide only when the next item would overflow. Two things this
# deliberately does NOT do: it never splits an item that's already
# atomic (a Gemini fact_group whose linked pair must stay together, or
# one chart_block), and the character-width estimate below is tuned
# wide on purpose (see CHAR_WIDTH_FACTOR) so a slightly-off estimate
# pushes content to an earlier slide rather than risking a clipped one.
# This is an estimate, not a browser layout engine - verify visually
# after regenerating slides, the same way the old fixed caps were
# themselves tuned from an actual rendering test (see the git history
# for the comment this replaced).

# Canvas budget, from SLIDE_CSS: .slide is 1920px tall with 90px
# padding top/bottom -> 1740px content box. The title (72px, ~1.2x
# line-height, 80px margin-bottom) is fixed overhead on every slide,
# regardless of content, so it's subtracted once up front.
#
# Budgeted for TWO title lines, not one: a screenshot test of the
# first real packed deck caught "BY THE NUMBERS (3/3)" wrapping to two
# lines at this font size (~72px Space Grotesk, bold, ~900px content
# width) - a title in the low/mid teens of characters fits one line,
# but "BY THE NUMBERS" alone is already 14 characters before the page
# count even gets appended, so a second line is the realistic case to
# budget for, not the edge case. That render still passed (71px of
# real margin to spare), but only because HEIGHT_SAFETY_MARGIN below
# happened to absorb the ~87px gap - fixed at the source here instead
# of relying on a margin meant for a different kind of error.
SLIDE_CONTENT_HEIGHT = 1740
TITLE_HEIGHT = 2 * 72 * 1.2 + 80  # ~253px, two lines

# Subtracted again on top of the above - a fixed insurance margin
# against the character-width estimate being wrong in the risky
# direction (undercounting wrapped lines). Cheap to be conservative
# here; the cost of guessing too high is one slightly-earlier page
# break, not a clipped bullet off the bottom of the canvas.
HEIGHT_SAFETY_MARGIN = 120
AVAILABLE_HEIGHT = SLIDE_CONTENT_HEIGHT - TITLE_HEIGHT - HEIGHT_SAFETY_MARGIN

BULLET_FONT_SIZE = 44
BULLET_LINE_HEIGHT = 1.6
BULLET_MARGIN_BOTTOM = 28
BULLET_TEXT_WIDTH = 900 - 34  # slide content width minus the li's left padding

# Average glyph width for Inter at this size, as a fraction of the
# font size. A real proportional-font average sits closer to
# 0.50-0.52x; this is deliberately higher (fewer estimated characters
# per line -> more estimated wrapped lines -> a taller, more
# conservative height guess) for the same reason as
# HEIGHT_SAFETY_MARGIN above.
CHAR_WIDTH_FACTOR = 0.58

CHART_CARD_PADDING_V = 36 * 2
CHART_CARD_MARGIN_BOTTOM = 32


def estimate_bullet_height(text: str) -> float:
    """Estimated rendered height (px) of one <li> bullet, wrapping included."""
    chars_per_line = max(1, int(BULLET_TEXT_WIDTH / (BULLET_FONT_SIZE * CHAR_WIDTH_FACTOR)))
    lines = -(-len(text) // chars_per_line)  # ceil division, min 1 line
    return max(1, lines) * BULLET_FONT_SIZE * BULLET_LINE_HEIGHT + BULLET_MARGIN_BOTTOM


def estimate_chart_block_height(block: dict) -> float:
    """Estimated rendered height (px) of one .chart-block card (bars or a single stat)."""
    if block["kind"] == "bars":
        inner = len(block["items"]) * CHART_ROW_HEIGHT
    else:
        # .metric-value (104px, ~1.2x line-height) + 10px gap + .metric-caption (32px, ~1.2x)
        inner = 104 * 1.2 + 10 + 32 * 1.2
    return inner + CHART_CARD_PADDING_V + CHART_CARD_MARGIN_BOTTOM


def pack_by_height(items: list, height_fn) -> list:
    """
    Greedily pack atomic `items` onto pages: keep adding items to the
    current page while its running estimated height stays under
    AVAILABLE_HEIGHT, cutting to a new page only when the next item
    would overflow. An item larger than the whole budget on its own
    still gets a page to itself (the check only applies once a page
    already holds something), rather than being silently dropped.
    """
    pages, current, current_height = [], [], 0.0
    for item in items:
        h = height_fn(item)
        if current and current_height + h > AVAILABLE_HEIGHT:
            pages.append(current)
            current, current_height = [], 0.0
        current.append(item)
        current_height += h
    if current:
        pages.append(current)
    return pages


def pack_numbers_pages(blocks: list, context_bullets: list) -> list:
    """
    Lay out chart blocks and context bullets across as few numbers
    pages as their real rendered height allows. Blocks are placed
    first on each page (matching the template's chart-blocks-then-
    bullets layout), then context bullets fill whatever height remains
    - both streams share ONE running budget per page, so a page is cut
    when the next item of EITHER kind would overflow. Packing the two
    streams independently (each against its own full budget) would let
    a "full" block page and a "full" context page combine into an
    overflowing slide - precisely the failure mode the old fixed caps
    of 2 blocks + 2 context bullets were manually tuned to avoid.

    Returns a list of (page_blocks, page_context) tuples.
    """
    pages = []
    block_queue = list(blocks)
    context_queue = list(context_bullets)

    while block_queue or context_queue:
        page_blocks, page_context = [], []
        remaining = AVAILABLE_HEIGHT

        while block_queue:
            h = estimate_chart_block_height(block_queue[0])
            if page_blocks and h > remaining:
                break
            page_blocks.append(block_queue.pop(0))
            remaining -= h

        while context_queue:
            h = estimate_bullet_height(context_queue[0])
            if page_context and h > remaining:
                break
            page_context.append(context_queue.pop(0))
            remaining -= h

        pages.append((page_blocks, page_context))

    return pages

# A leading number, optionally with $/~ prefix, commas/decimal, and a
# trailing %/K/M/B unit letter - loose on purpose since Step 3's output
# is free-text from an LLM, not a strict schema. Used only by the
# deterministic fallback path when slide_planner isn't available.
NUMBER_PATTERN = re.compile(r'^[~$]?\s*([\d][\d,\.]*\s*[%KkMmBb]?)\b\s*(.*)$')

# HyperFrames' "Blue Professional" design spec (hyperframes.dev/design):
# corporate parchment canvas + a single cobalt accent carrying every
# emphasis - "quiet is the most expensive thing on the page." As CSS
# custom properties, shared between the checkpoint preview and the real
# composition (the composition additionally gets FONT_FACE_CSS - see
# build_composition - since the checkpoint's standalone files live
# outside render/ and can't reach render/vendor/fonts/ by a relative path).
SLIDE_CSS = """
:root {
  --canvas: #fdfae7;
  --ink: #111111;
  --muted: #6b6b6b;
  --cobalt: #1e2bfa;
  --cobalt-tint: rgba(30, 43, 250, 0.04);
  --cobalt-border: rgba(30, 43, 250, 0.20);
}
body { margin: 0; background: #000; }
.slide {
  width: 1080px;
  height: 1920px;
  background: var(--canvas);
  color: var(--ink);
  font-family: "Inter", system-ui, -apple-system, "Segoe UI", sans-serif;
  box-sizing: border-box;
  padding: 90px;
}
.slide .title {
  font-family: "Space Grotesk", system-ui, sans-serif;
  font-size: 72px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--ink);
  margin: 0 0 80px 0;
}
.bullets { list-style: none; padding: 0; margin: 0; }
.bullets li {
  position: relative;
  padding-left: 34px;
  margin-bottom: 28px;
  font-size: 44px;
  line-height: 1.6;
  color: var(--muted);
}
.bullets li::before {
  content: "";
  position: absolute;
  left: 0; top: 0.5em;
  width: 16px; height: 16px;
  border-radius: 50%;
  background: var(--cobalt);
}
.chart-blocks { margin-bottom: 40px; }
.chart-block {
  background: var(--cobalt-tint);
  border: 1px solid var(--cobalt-border);
  border-radius: 14px;
  padding: 36px 40px;
  margin-bottom: 32px;
}
.chart-row-label {
  font-family: "Space Grotesk", system-ui, sans-serif;
  font-weight: 600;
  font-size: 30px;
  fill: var(--ink);
}
.chart-row-value {
  font-family: "Space Grotesk", system-ui, sans-serif;
  font-weight: 700;
  font-size: 32px;
  fill: var(--cobalt);
}
.metric-value {
  font-family: "Space Grotesk", system-ui, sans-serif;
  font-size: 104px;
  font-weight: 700;
  color: var(--cobalt);
  letter-spacing: -0.01em;
}
.metric-caption {
  font-family: "Inter", system-ui, sans-serif;
  font-size: 32px;
  color: var(--muted);
  margin-top: 10px;
}
""" + MAP_SLIDE_CSS

# The @font-face declarations, kept separate from SLIDE_CSS: the
# checkpoint's standalone files (slides/<id>/NN_type.html) live outside
# render/ and would need a longer relative path to reach
# render/vendor/fonts/ - not worth it for a preview, which falls back to
# a system sans-serif instead. Only the real composition (inside
# render/compositions/, which IS a render/ subpath) includes this.
def font_face_css(fonts_dir: str = "vendor/fonts") -> str:
    """
    @font-face block pointing at the vendored woff2 files. Takes a path
    prefix because the two callers see the files from different places:
    the real composition (render/compositions/<id>.html) reaches them
    at "vendor/fonts/..." (root-relative to the render/ project, per
    the lint rule that caught our first ../vendor/ attempt); the
    checkpoint preview (slides/<identifier>/NN_type.html) gets its own
    copy alongside it instead (see render_slides), at "fonts/...".
    """
    return f"""
@font-face {{
  font-family: "Space Grotesk";
  font-weight: 400;
  src: url("{fonts_dir}/space-grotesk-latin-400-normal.woff2") format("woff2");
}}
@font-face {{
  font-family: "Space Grotesk";
  font-weight: 600;
  src: url("{fonts_dir}/space-grotesk-latin-600-normal.woff2") format("woff2");
}}
@font-face {{
  font-family: "Space Grotesk";
  font-weight: 700;
  src: url("{fonts_dir}/space-grotesk-latin-700-normal.woff2") format("woff2");
}}
@font-face {{
  font-family: "Inter";
  font-weight: 400;
  src: url("{fonts_dir}/inter-latin-400-normal.woff2") format("woff2");
}}
"""

# HyperFrames-specific chrome added around SLIDE_CSS for the real
# composition (not needed for the standalone checkpoint preview):
# the root's positioning contract and the full-frame .clip box every
# timed element is keyed off. See tracks-and-clips.md / minimal-composition.md.
STAGE_CSS = """
#stage { position: relative; width: 1080px; height: 1920px; overflow: hidden; }
.clip { position: absolute; inset: 0; }
"""


def parse_sections(insights_text: str) -> dict:
    """
    Split the Step 3 insights file into {"facts": [...], "numbers": [...]}
    raw bullet lines, dropping section headers and any unverified line.
    """
    sections = {"facts": [], "numbers": []}
    current = None
    for raw_line in insights_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line == "## FACTS":
            current = "facts"
            continue
        if line == "## NUMBERS & CONTEXT":
            current = "numbers"
            continue
        if "[NOT IN VIDEO" in line:
            continue
        if current:
            sections[current].append(line.lstrip("-").strip())
    return sections


def split_label_value(line: str) -> tuple:
    if ":" in line:
        label, value = line.split(":", 1)
        return label.strip(), value.strip()
    return "", line.strip()


def sentence_case(text: str) -> str:
    return text[0].upper() + text[1:] if text else text


def try_parse_stat(line: str):
    """
    If a line's value starts with a number, return (number_str, caption)
    for a stat tile. Otherwise return None, so the caller falls back to
    a plain bullet line instead of forcing a bad fit.
    """
    label, value = split_label_value(line)
    match = NUMBER_PATTERN.match(value)
    if not match:
        return None
    number = match.group(1).strip()
    caption = sentence_case(label) if label else sentence_case(match.group(2).strip())
    return number, caption or "Reported figure"


def format_elapsed(seconds: float) -> str:
    """'12.3s' under a minute, '2m 05s' at or past one - so a longer
    narration/render step reads as a clock time, not a pile of digits."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(round(seconds)), 60)
    return f"{minutes}m {secs:02d}s"


def page_title(base: str, index: int, total: int) -> str:
    """'THE FACTS' alone, or 'THE FACTS (2/3)' when a section spans pages."""
    return f"{base} ({index + 1}/{total})" if total > 1 else base


def split_numbers(number_lines: list) -> tuple:
    """
    Split NUMBERS & CONTEXT lines into stat-tile candidates and plain
    context bullets. Each item keeps its original raw line (for
    narration, unchanged from Step 3's wording) alongside its parsed
    (number, caption) when it has one.
    Returns (stat_items, context_items), each a list of
    (raw_line, parsed_or_None).
    """
    stat_items, context_items = [], []
    for line in number_lines:
        parsed = try_parse_stat(line)
        (stat_items if parsed else context_items).append((line, parsed))
    return stat_items, context_items


def format_metric(value: float, unit: str) -> str:
    """'36,000' + 'NT$/month' -> '36,000 NT$/month'; '12.5' + '%' -> '12.5%'."""
    text = f"{value:,.0f}" if float(value).is_integer() else f"{value:,.1f}"
    unit = (unit or "").strip()
    if not unit:
        return text
    return f"{text}{unit}" if unit[0] in "%x×" else f"{text} {unit}"


def group_chart_items(chart_items: list) -> list:
    """
    Group chart_items (each {"label","value","unit","source_line"}) by
    their unit string, in first-seen order. Two or more items sharing a
    unit are actually comparable, so they become one bar-chart block;
    a unit with only one item becomes a single stat block instead of a
    one-bar "chart" that has nothing to compare against. Never mixes
    different units into one chart - that would compare unlike things
    on one axis, which is a real chart-correctness bug, not a style choice.
    """
    order, by_unit = [], {}
    for item in chart_items:
        unit = (item.get("unit") or "").strip()
        if unit not in by_unit:
            by_unit[unit] = []
            order.append(unit)
        by_unit[unit].append(item)

    blocks = []
    for unit in order:
        items = by_unit[unit]
        if len(items) >= 2:
            blocks.append({"kind": "bars", "unit": unit, "items": items})
        else:
            blocks.append({"kind": "stat", "item": items[0]})
    return blocks


# Bar chart geometry, in the slide's own content coordinate space
# (900px wide - the 1080px canvas minus its 90px side padding).
# 900 (the slide's content width) minus the .chart-block card's own
# 40px*2 padding - the first render caught this: with CHART_WIDTH left
# at 900, the SVG didn't fit inside its own padded card and overflowed
# past the slide edge for any wide bar + long value label.
CHART_WIDTH = 820
CHART_MAX_BAR_WIDTH = 420   # leaves >=380px for the value label after the bar
CHART_ROW_HEIGHT = 110
CHART_BAR_HEIGHT = 36

# --- Sentence-level highlight (bullets only, not chart blocks - see
# build_composition) -----------------------------------------------
# Sentence, not word: word-level timing needs real per-word timestamps
# (ASR on each generated clip, or an estimate splitting a clip's
# duration by word length) and reads as distracting at this content
# density (a data/insight video, not a lyric video) - a deliberate
# scope call, not a placeholder for "not implemented yet". Per-BULLET
# timing, by contrast, already falls out of build_slide_narration's
# per-line durations for free (each bullet is exactly one narrated
# line), so this needed no new data collection.
#
# Colors reuse the composition's own ink/muted tokens (SLIDE_CSS) -
# the house style note above ("text never carries the accent color
# itself") rules out a cobalt-tinted active state, so "active" vs
# "resting" is carried by ink-vs-muted + opacity instead, not a new color.
BULLET_ACTIVE_COLOR = "#111111"   # var(--ink)
BULLET_DIM_COLOR = "#6b6b6b"      # var(--muted) - the bullets' own resting color
BULLET_DIM_OPACITY = 0.45
BULLET_HIGHLIGHT_TRANSITION_SECONDS = 0.3


def render_bar_chart_svg(items: list) -> str:
    """
    A plain, hand-coded horizontal bar chart - one hue (cobalt), thin
    bars, rounded data-ends, direct value labels, no legend (a single
    series needs none - the block's own numbers are the labels). Every
    item here already shares one unit (see group_chart_items), so the
    comparison the chart draws is a real one.
    """
    max_value = max(item["value"] for item in items) or 1
    height = len(items) * CHART_ROW_HEIGHT
    rows = []
    for i, item in enumerate(items):
        y = i * CHART_ROW_HEIGHT
        bar_width = max(8, (item["value"] / max_value) * CHART_MAX_BAR_WIDTH)
        label = html.escape(item["label"])
        value_text = html.escape(format_metric(item["value"], item.get("unit", "")))
        rows.append(
            f'<text x="0" y="{y + 26}" class="chart-row-label">{label}</text>'
            f'<rect x="0" y="{y + 44}" width="{bar_width:.1f}" height="{CHART_BAR_HEIGHT}" '
            f'rx="10" fill="var(--cobalt)"/>'
            f'<text x="{bar_width + 20:.1f}" y="{y + 44 + CHART_BAR_HEIGHT - 8}" '
            f'class="chart-row-value">{value_text}</text>'
        )
    return (
        f'<svg viewBox="0 0 {CHART_WIDTH} {height}" width="{CHART_WIDTH}" height="{height}">'
        + "".join(rows) +
        "</svg>"
    )


def render_metric_html(item: dict) -> str:
    """
    A single figure with nothing to compare against - a big number, not
    a one-bar chart. Takes either a real (value, unit) pair (the
    slide_planner path) or a pre-formatted "display" string (the
    regex-fallback path, which only ever extracts an already-formatted
    number like "$36,000", not a clean float it could recompute from).
    """
    value_text = html.escape(item["display"] if "display" in item
                              else format_metric(item["value"], item.get("unit", "")))
    caption = html.escape(item["label"])
    return (
        f'<div class="metric-value">{value_text}</div>'
        f'<div class="metric-caption">{caption}</div>'
    )


def render_chart_block_html(block: dict) -> str:
    inner = render_bar_chart_svg(block["items"]) if block["kind"] == "bars" else render_metric_html(block["item"])
    return f'<div class="chart-block">{inner}</div>'


def build_slide_deck(identifier: str) -> list:
    """
    The single source of truth for what slides exist, in order. Both
    the review checkpoint and the final composition are built from this
    same deck, so what you approve is exactly what gets rendered later.

    Each deck entry is a dict:
      {"type": "facts", "title": str, "bullets": [...], "narration_lines": [...]}
      {"type": "numbers", "title": str, "chart_blocks": [...],
       "bullets": [...], "narration_lines": [...]}
      {"type": "map", "title": str, "subtitle": str, "callouts": [...],
       "narration_lines": [...]}   (see map_slide.py)

    Tries slide_planner's Gemini call first (smarter fact grouping +
    real chart data); falls back to the old deterministic regex/
    pagination path if the API key is missing or the call/its output
    doesn't check out. Either path fills the same deck shape, so
    everything downstream (checkpoint, composition, narration) doesn't
    need to know which one ran.
    """
    insights_text = load_text(identifier, "insights")
    sections = parse_sections(insights_text)
    facts, number_lines = sections["facts"], sections["numbers"]

    # Regional map slide (map_slide.py): pulls the per-city figures it
    # uses OUT of number_lines before anything else sees them, so the
    # planner and packer below never turn those same figures into
    # bullets or charts too - each number is shown and narrated once.
    # Returns (None, number_lines unchanged) when the insights don't
    # support a map, so a video without regional data builds as before.
    map_slide, number_lines = build_map_slide(facts, number_lines, identifier)

    try:
        from slide_planner import plan_slides
        plan = plan_slides(facts, number_lines)
        fact_groups = plan["fact_groups"]
        chart_items = plan["chart_items"]
        context_bullets = plan["context_bullets"]
        used_planner = True
    except Exception as exc:
        print(f"slide_planner unavailable or failed ({exc}) - "
              "falling back to regex-based grouping.", file=sys.stderr)
        # No linked-pair signal without the planner, so each fact is its
        # own atomic unit for packing purposes - see the pack_by_height
        # docstring for why "atomic unit" still means "may share a
        # slide with others", not "gets its own slide".
        fact_groups = [[f] for f in facts]
        stat_items, context_items = split_numbers(number_lines)
        chart_items = [
            {"label": caption, "display": number, "source_line": raw}
            for raw, (number, caption) in stat_items
        ]
        context_bullets = [raw for raw, _ in context_items]
        used_planner = False

    deck = []

    # Pack whole fact_groups (never split - a Gemini-linked pair, or a
    # lone fact in the fallback path, is the smallest unit that may
    # move between slides) onto as few slides as their real estimated
    # height allows.
    fact_pages = pack_by_height(
        fact_groups, lambda group: sum(estimate_bullet_height(b) for b in group)
    )
    for i, page_groups in enumerate(fact_pages):
        bullets = [b for group in page_groups for b in group]
        deck.append({
            "type": "facts",
            "title": page_title("THE FACTS", i, len(fact_pages)),
            "bullets": bullets,
            "narration_lines": bullets,
        })

    # Data-first placement: the map opens the numbers section, right
    # after the facts, since it frames where the numbers that follow apply.
    if map_slide:
        deck.append(map_slide)

    if used_planner:
        blocks = group_chart_items(chart_items)
    else:
        # No clean (value, unit) split available without the planner, so
        # every parsed line becomes its own stat block (the old
        # stat-tile behaviour, restyled) rather than attempting
        # bar-chart grouping on unparsed number strings.
        blocks = [{"kind": "stat", "item": it} for it in chart_items]

    numbers_pages = pack_numbers_pages(blocks, context_bullets)

    def source_lines_for(block):
        if block["kind"] == "bars":
            return [it["source_line"] for it in block["items"]]
        item = block["item"]
        return [item.get("source_line", item["label"])]

    for i, (page_blocks, page_context) in enumerate(numbers_pages):
        narration = [line for b in page_blocks for line in source_lines_for(b)] + page_context
        deck.append({
            "type": "numbers",
            "title": page_title("BY THE NUMBERS", i, len(numbers_pages)),
            "chart_blocks": page_blocks,
            "bullets": page_context,
            "narration_lines": narration,
        })

    return deck


def bullet_li_id(slide_id: str, index: int) -> str:
    """Stable id for one bullet <li>, e.g. 'bullet-01-0' - shared by the
    checkpoint preview (harmless there) and the real composition
    (where the sentence-highlight script below selects by this id)."""
    return f"bullet-{slide_id}-{index}"


def render_facts_slide_html(title: str, facts: list, slide_id: str = "00") -> str:
    items = "".join(
        f'<li id="{bullet_li_id(slide_id, i)}">{html.escape(b)}</li>'
        for i, b in enumerate(facts)
    )
    return (
        f'<div class="slide facts-slide">'
        f'<div class="title">{html.escape(title)}</div>'
        f'<ul class="bullets">{items}</ul>'
        f'</div>'
    )


def render_numbers_slide_html(title: str, chart_blocks: list, context_lines: list,
                               slide_id: str = "00") -> str:
    blocks_html = "".join(render_chart_block_html(b) for b in chart_blocks)
    bullets = "".join(
        f'<li id="{bullet_li_id(slide_id, i)}">{html.escape(line)}</li>'
        for i, line in enumerate(context_lines)
    )
    return (
        f'<div class="slide numbers-slide">'
        f'<div class="title">{html.escape(title)}</div>'
        f'<div class="chart-blocks">{blocks_html}</div>'
        f'<ul class="bullets">{bullets}</ul>'
        f'</div>'
    )


def render_slide_html(slide: dict, slide_id: str = "00") -> str:
    """Dispatch a single deck entry to its HTML renderer."""
    if slide["type"] == "facts":
        return render_facts_slide_html(slide["title"], slide["bullets"], slide_id)
    if slide["type"] == "map":
        return render_map_slide_html(slide, slide_id)
    return render_numbers_slide_html(slide["title"], slide["chart_blocks"], slide["bullets"], slide_id)


def render_slides(identifier: str) -> list:
    """
    CHECKPOINT stage. Renders every slide in the deck to
    slides/<identifier>/NN_<type>.html - each one a standalone file you
    can open directly in a browser - and stops. No narration, no
    composition, no video. Look at these before spending time on the
    full narrated build.
    """
    deck = build_slide_deck(identifier)
    if not deck:
        raise ValueError("No verified insights found to build slides from.")

    slide_dir = SLIDES_DIR / identifier
    slide_dir.mkdir(parents=True, exist_ok=True)

    # Copy the vendored fonts alongside the checkpoint files too - they
    # live in slides/, a sibling of render/, so they can't reach
    # render/vendor/fonts/ by a relative path the way the real
    # composition can. A small local copy keeps the checkpoint preview
    # honest about what the final render will actually look like,
    # instead of silently falling back to a system font.
    if FONT_VENDOR_DIR.exists():
        fonts_copy_dir = slide_dir / "fonts"
        fonts_copy_dir.mkdir(exist_ok=True)
        for font_file in FONT_VENDOR_DIR.glob("*.woff2"):
            (fonts_copy_dir / font_file.name).write_bytes(font_file.read_bytes())

    paths = []
    for i, slide in enumerate(deck):
        path = slide_dir / f"{i + 1:02d}_{slide['type']}.html"
        standalone = (
            f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<style>{font_face_css('fonts')}{SLIDE_CSS}</style>"
            f"</head><body>{render_slide_html(slide, f'{i + 1:02d}')}</body></html>"
        )
        path.write_text(standalone, encoding="utf-8")
        paths.append(str(path))
    return paths


def _is_retryable_tts_error(message: str) -> bool:
    """
    True for a transient network-level failure worth retrying - a
    dropped connection or timeout, most likely mid-download of the
    Kokoro model on a machine's first-ever call. False for anything
    else (a bad voice id, a missing binary) - those won't fix
    themselves on retry, so they should surface immediately.
    """
    upper = message.upper()
    return any(snippet in upper for snippet in _TTS_RETRYABLE_ERROR_SNIPPETS)


def generate_narration(text: str, output_path: str, voice: str = VOICE):
    """
    Free, no-API-key, offline narration via HyperFrames' bundled local
    TTS (Kokoro-82M, run through `npx hyperframes tts`). Unlike edge-tts,
    this never calls out over the network once the model is cached, so
    it works the same in a locked-down sandbox as on an open laptop.

    stdin is explicitly closed (not just left to inherit the caller's
    terminal): if npx/npm ever wants to ask "Ok to proceed?" for a
    fresh install, this makes it fail fast with a clear error instead
    of silently blocking forever on a prompt nothing prints, because
    this call's own stdout/stderr are captured and shown to the user
    only after it returns. TTS_TIMEOUT_SECONDS exists for the same
    reason: the very first call ever made on a machine downloads the
    Kokoro-82M model first, which can legitimately take a while on a
    slow connection, but every call after that finishes in single-digit
    seconds - so a call still running past the timeout means something
    is genuinely stuck (a stalled download, a blocked network
    endpoint), not just "slow," and that should raise a clear error
    instead of hanging silently for however long someone waits before
    giving up and asking what's wrong.

    A dropped connection (ECONNRESET and friends) is a different shape
    of failure entirely - it comes back fast, inside the JSON payload,
    not as a hang - and is exactly the kind of thing a plain retry
    often just fixes, so it gets a few attempts with backoff before
    giving up (see _is_retryable_tts_error).
    """
    last_error = None
    for attempt in range(TTS_MAX_RETRIES):
        try:
            result = subprocess.run(
                ["npx", "hyperframes", "tts", text, "-o", str(output_path),
                 "-v", voice, "--json"],
                check=True, capture_output=True, text=True,
                stdin=subprocess.DEVNULL, timeout=TTS_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"`npx hyperframes tts` didn't finish within {TTS_TIMEOUT_SECONDS}s "
                f"for the line: {text[:60]!r}...\n"
                "This is almost always either (a) the FIRST-ever call on this "
                "machine downloading the Kokoro-82M model over a slow or "
                "blocked connection, or (b) npx/npm silently waiting on an "
                "install prompt no one can see (stdin is closed now, so this "
                "specific cause should surface as an error next run instead of "
                "a hang). To see what's actually happening, run this exact "
                "command by hand in a terminal you're watching live:\n"
                f"  npx hyperframes tts \"test\" -o test.wav -v {voice} --json"
            ) from exc

        data = json.loads(result.stdout)
        if data.get("ok"):
            return

        last_error = str(data.get("error", data))
        is_last_attempt = attempt == TTS_MAX_RETRIES - 1
        if not _is_retryable_tts_error(last_error) or is_last_attempt:
            break

        sleep_for = TTS_RETRY_BACKOFF_SECONDS * (2 ** attempt)
        print(f"  Error ({last_error}) narrating this line - "
              f"retry {attempt + 2}/{TTS_MAX_RETRIES}, retrying in {sleep_for:.1f}s...",
              file=sys.stderr)
        time.sleep(sleep_for)

    raise RuntimeError(
        f"hyperframes tts failed for {output_path!r} after "
        f"{TTS_MAX_RETRIES} attempt(s): {last_error}\n"
        "If this is ECONNRESET/ETIMEDOUT, it's most likely a flaky "
        "connection or a firewall/VPN interrupting the Kokoro model's "
        "one-time download - try a different network, or run the same "
        "`npx hyperframes tts \"test\" ...` command a few times by hand "
        "to see if it's a one-off blip or a systematic block."
    )


def build_slide_narration(lines: list, identifier: str, slide_index: int) -> tuple:
    """
    Narrate each of a slide's lines via local TTS, then concatenate them
    into one continuous wav for that slide using ffmpeg's concat
    demuxer (lossless, no re-encode - no MoviePy needed for this
    either).

    Returns (merged_path, line_durations) - line_durations is each
    source line's own probed length (seconds), in order, BEFORE they
    were merged. The merge is lossless concatenation of already-final
    audio, so each line's slice of the merged clip starts exactly where
    the running sum of the previous lines' durations leaves off - the
    composition uses this to work out exactly when, inside the one
    merged clip a slide's <audio> plays, each source line is being
    read (see build_composition's sentence-highlight timing), without
    needing a separate ASR/transcription pass to recover it.

    Prints one line before each call, same reasoning as slide_planner's
    Gemini progress messages: a multi-second (or, on the very first
    call ever, multi-minute) subprocess with nothing streamed to the
    terminal until it returns looks identical to a hang, so it's worth
    saying up front which line it's working on right now.
    """
    part_paths = []
    for i, line in enumerate(lines):
        note = (" (first call - may take a few minutes if this downloads "
                 "the Kokoro model)" if slide_index == 0 and i == 0 else "")
        print(f"  Narrating slide {slide_index + 1}, line {i + 1}/{len(lines)}...{note}",
              file=sys.stderr)
        part_path = TEMP_DIR / f"{identifier}_{slide_index}_{i}.wav"
        generate_narration(line, str(part_path))
        part_paths.append(part_path)

    # Probed here, before the concat step below replaces/deletes these
    # part files - this is the only point where each line's own
    # duration is still directly measurable.
    line_durations = [round(get_audio_duration(p), 3) for p in part_paths]

    merged_path = TEMP_DIR / f"{identifier}_{slide_index}_merged.wav"
    if len(part_paths) == 1:
        part_paths[0].replace(merged_path)
    else:
        list_file = TEMP_DIR / f"{identifier}_{slide_index}_concat.txt"
        list_file.write_text(
            "".join(f"file '{p.resolve()}'\n" for p in part_paths), encoding="utf-8"
        )
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
             "-c", "copy", str(merged_path)],
            check=True, capture_output=True,
        )
        list_file.unlink()
        for p in part_paths:
            if p.exists():
                p.unlink()

    return str(merged_path), line_durations


def get_audio_duration(path: str) -> float:
    """Probe an audio file's duration in seconds via ffprobe (ffmpeg's own CLI)."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(json.loads(result.stdout)["format"]["duration"])


def build_bullet_highlight_tweens(slide: dict, slide_id: str, line_durations: list,
                                   cursor: float) -> list:
    """
    Sentence-level "currently narrated" highlight (user: "adopt
    hyperframes-animation; word-level is too distracting anyway" -
    so this dims/brightens whole <li> bullets, never individual words).

    line_durations is build_slide_narration's per-source-line duration
    list for THIS slide, in the same order narration_lines was built in
    - which for a numbers slide is chart source-lines FIRST, then the
    context bullets (see build_slide_deck's numbers-page assembly:
    `narration = [... for b in page_blocks ...] + page_context`). Only
    the bullets themselves get a <li id>, so `skip` is how many leading
    lines belong to chart items rather than a visible bullet - those
    lines still take up narration time, they just don't correspond to
    anything to highlight. For a facts slide narration_lines IS bullets
    (same list), so skip is 0.

    cursor is this slide's own data-start (seconds into the whole
    composition) - every emitted timestamp is cursor + an offset local
    to this slide's audio, since HyperFrames' one composition-wide
    timeline runs on absolute time, not per-clip time.

    Returns a list of JS statement strings (already newline-free, one
    tl.set()/tl.to() call each) to splice into the composition's single
    paused GSAP timeline - not a timeline of its own, since a
    composition may only register one timeline per composition-id
    (see composition-patterns.md).
    """
    bullets = slide.get("bullets", [])
    if not bullets:
        return []

    narration_lines = slide["narration_lines"]
    skip = len(narration_lines) - len(bullets)
    bullet_durations = line_durations[skip:]
    # GSAP treats a bare string target as a CSS selector, so a plain id
    # like "bullet-01-0" would select an (nonexistent) <bullet-01-0> TAG,
    # not the element with that id - hence the "#" prefix on every
    # target passed to tl.set()/tl.to() below. Confirmed via a headless
    # render: without the "#" every tween below silently no-ops with a
    # console warning ("GSAP target ... not found") instead of erroring,
    # so this is easy to ship broken and not notice until watching the
    # actual video.
    bullet_ids = ["#" + bullet_li_id(slide_id, j) for j in range(len(bullets))]

    # Each bullet's own [start, end) window within this slide's merged
    # narration clip, derived the same way the merge itself was built -
    # a running sum of individual line durations, in order.
    starts = []
    offset = sum(line_durations[:skip])
    for d in bullet_durations:
        starts.append(offset)
        offset += d

    lines = []
    slide_start = round(cursor, 3)

    # Every bullet starts dim the moment this slide's clip appears - even
    # bullet 0, which only actually starts being narrated at cursor+starts[0].
    # On a facts slide (skip=0) that's the same instant as slide_start, so
    # the loop below immediately supersedes this with a same-timestamp
    # tl.set. On a numbers slide (skip>0) bullet 0's narration doesn't
    # begin until the chart lines finish being read, so it stays dim for
    # a real, visible stretch first - it must NOT be marked active from
    # slide_start, or it would look "active" while the chart narration is
    # still playing and nothing on screen is highlighted at all.
    lines.append(
        f"  tl.set({json.dumps(bullet_ids)}, "
        f"{{opacity: {BULLET_DIM_OPACITY}, color: {json.dumps(BULLET_DIM_COLOR)}}}, "
        f"{slide_start});"
    )

    # One dim->active handoff per bullet, at the exact timestamp its own
    # narration line starts playing: bullet j-1 fades dim, bullet j
    # brightens, simultaneously. Bullet 0 has no predecessor to dim; if
    # its own start coincides with slide_start (skip=0) an instant
    # tl.set reads better than a pointless 0-length tween, otherwise
    # (skip>0) it gets the same fade-in tween as every other handoff.
    for j, start in enumerate(starts):
        t = round(cursor + start, 3)
        if j == 0:
            if t <= slide_start:
                lines.append(
                    f"  tl.set({json.dumps(bullet_ids[0])}, "
                    f"{{opacity: 1, color: {json.dumps(BULLET_ACTIVE_COLOR)}}}, {t});"
                )
            else:
                lines.append(
                    f"  tl.to({json.dumps(bullet_ids[0])}, "
                    f"{{opacity: 1, color: {json.dumps(BULLET_ACTIVE_COLOR)}, "
                    f"duration: {BULLET_HIGHLIGHT_TRANSITION_SECONDS}}}, {t});"
                )
            continue
        lines.append(
            f"  tl.to({json.dumps(bullet_ids[j - 1])}, "
            f"{{opacity: {BULLET_DIM_OPACITY}, color: {json.dumps(BULLET_DIM_COLOR)}, "
            f"duration: {BULLET_HIGHLIGHT_TRANSITION_SECONDS}}}, {t});"
        )
        lines.append(
            f"  tl.to({json.dumps(bullet_ids[j])}, "
            f"{{opacity: 1, color: {json.dumps(BULLET_ACTIVE_COLOR)}, "
            f"duration: {BULLET_HIGHLIGHT_TRANSITION_SECONDS}}}, {t});"
        )

    return lines


def build_composition(identifier: str) -> str:
    """
    Narrates every slide and assembles the full HyperFrames composition
    - a STANDALONE (non-<template>) monolithic file: one root with
    every slide + its narration audio as sibling timed `.clip` elements,
    per composition-patterns.md's "Monolithic (single file)" shape.

    Writes:
      render/compositions/<identifier>.html
      render/compositions/<identifier>_audio/NN_<type>.wav

    Returns the composition file's path. Rendering to MP4 is a separate
    step (npx hyperframes render ... - see module docstring), since it
    needs the Node project's own CLI, not this script.
    """
    deck = build_slide_deck(identifier)
    if not deck:
        raise ValueError("No verified insights found to build a composition from.")

    if not GSAP_VENDOR_PATH.exists():
        raise FileNotFoundError(
            f"{GSAP_VENDOR_PATH} is missing - run, once:\n"
            f"  cd {RENDER_DIR} && npm install gsap && "
            f"mkdir -p vendor && cp node_modules/gsap/dist/gsap.min.js vendor/"
        )
    if not FONT_VENDOR_DIR.exists() or not any(FONT_VENDOR_DIR.glob("*.woff2")):
        raise FileNotFoundError(
            f"{FONT_VENDOR_DIR} is missing its woff2 files - see README's "
            "one-time font vendoring step (npm install @fontsource/space-grotesk "
            "@fontsource/inter, then copy the latin woff2 files into vendor/fonts/)."
        )

    TEMP_DIR.mkdir(exist_ok=True)
    COMPOSITIONS_DIR.mkdir(parents=True, exist_ok=True)
    audio_dir = COMPOSITIONS_DIR / f"{identifier}_audio"
    # Wipe and recreate rather than mkdir(exist_ok=True) onto whatever's
    # already there. A run only ever WRITES the filenames its own deck
    # produces (NN_<type>.wav, indexed by this run's own slide count and
    # per-slide types) - it never deletes a name that a *previous* run
    # left behind but the current deck doesn't use. Caught in practice:
    # after the slide count changed from 9 (4 facts + 5 numbers) to 8 (3
    # facts + 5 numbers), `04_facts.wav` and `09_numbers.wav` from the old
    # 9-slide layout were still sitting here - silently orphaned, not
    # referenced by the new composition.html, but a glob copy (`*.wav`)
    # into a runs/ snapshot would happily scoop them up as if they
    # belonged to the new video. Clearing first makes "every file here
    # belongs to the composition that's about to be written" an
    # invariant instead of something to check by hand after the fact.
    shutil.rmtree(audio_dir, ignore_errors=True)
    audio_dir.mkdir(parents=True, exist_ok=True)

    clips_html = []
    highlight_js = []
    cursor = 0.0
    for i, slide in enumerate(deck):
        print(f"Slide {i + 1}/{len(deck)} ({slide['type']})...", file=sys.stderr)
        avatar = slide.get("avatar") if slide["type"] == "map" else None

        if avatar:
            # This slide's spoken narration is the avatar's OWN recorded
            # voice (generate_avatar_clip.py's extracted audio track,
            # already the exact source of the avatar video's lip-sync) -
            # not Kokoro. line_durations is that same script's per-line
            # split, already ordered to match this slide's callouts (see
            # map_slide.load_avatar_manifest). Copied, not moved: unlike
            # a TEMP_DIR narration file, this source lives in
            # avatar_clips/ and must survive to build the NEXT
            # composition too, if this one is regenerated later.
            narration_path = avatar["audio_path"]
            line_durations = avatar["line_durations"]
            duration = round(get_audio_duration(narration_path), 3)
            audio_filename = f"{i + 1:02d}_{slide['type']}.wav"
            shutil.copyfile(narration_path, audio_dir / audio_filename)
        else:
            narration_path, line_durations = build_slide_narration(
                slide["narration_lines"], identifier, i
            )
            # Round once, here, and accumulate the ROUNDED value - not the
            # raw ffprobe float. Rounding data-start and data-duration
            # separately (each to 3dp) at print time can leave one clip's
            # printed end a hair past the next clip's printed start (lint:
            # duplicate_audio_track, a few ms of phantom overlap) even
            # though nothing actually overlaps.
            duration = round(get_audio_duration(narration_path), 3)
            # Move the merged narration into the composition's own audio
            # folder so the <audio src="..."> reference is a short relative path.
            audio_filename = f"{i + 1:02d}_{slide['type']}.wav"
            Path(narration_path).replace(audio_dir / audio_filename)
        audio_src = f"{identifier}_audio/{audio_filename}"

        # Both elements need a stable id - lint's media_missing_id is an
        # ERROR, not a style nit: without an id the renderer can't find
        # the <audio> at all, and that slide's narration is silent in the
        # actual render even though preview can look fine.
        slide_id = f"{i + 1:02d}"
        clip_id = f"slide-{slide_id}"
        audio_id = f"audio-{slide_id}"

        clips_html.append(
            f'<div id="{clip_id}" class="clip" data-start="{cursor:.3f}" '
            f'data-duration="{duration:.3f}" data-track-index="0">'
            f'{render_slide_html(slide, slide_id)}</div>\n'
            f'<audio id="{audio_id}" class="clip" data-start="{cursor:.3f}" '
            f'data-duration="{duration:.3f}" data-track-index="1" '
            f'src="{html.escape(audio_src)}"></audio>'
        )

        if avatar:
            # The lip-synced video itself: a separately timed sibling clip
            # layered over the same box the slide's own (untimed) dashed
            # placeholder would otherwise occupy - see
            # render_avatar_clip_html's docstring for why this works
            # without nesting it inside the slide's own div. Copied once
            # per composition build (not referenced from avatar_clips/
            # directly) so the composition folder stays self-contained,
            # same reasoning as the narration audio above.
            assets_dir = COMPOSITIONS_DIR / f"{identifier}_assets"
            assets_dir.mkdir(parents=True, exist_ok=True)
            video_filename = f"{i + 1:02d}_map_avatar.mp4"
            shutil.copyfile(avatar["video_path"], assets_dir / video_filename)
            clips_html.append(render_avatar_clip_html(
                slide_id, cursor, duration, f"{identifier}_assets/{video_filename}"
            ))

        if slide["type"] == "map":
            highlight_js.extend(
                build_map_highlight_tweens(slide, slide_id, line_durations, cursor)
            )
        else:
            highlight_js.extend(
                build_bullet_highlight_tweens(slide, slide_id, line_durations, cursor)
            )

        cursor = round(cursor + duration, 3)

    safe_id = html.escape(identifier)
    js_id = json.dumps(identifier)  # safe as a JS object key / string literal

    composition = (
        "<!doctype html>\n"
        "<html lang=\"en\">\n"
        "<head>\n"
        "<meta charset=\"UTF-8\" />\n"
        f"<meta name=\"viewport\" content=\"width={VIDEO_WIDTH}, height={VIDEO_HEIGHT}\" />\n"
        f"<title>{safe_id}</title>\n"
        "<script src=\"vendor/gsap.min.js\"></script>\n"
        f"<style>{font_face_css()}{SLIDE_CSS}{STAGE_CSS}</style>\n"
        "</head>\n"
        "<body>\n"
        f'<div id="stage" data-composition-id="{safe_id}" data-start="0" '
        f'data-width="{VIDEO_WIDTH}" data-height="{VIDEO_HEIGHT}" data-duration="{cursor:.3f}">\n'
        + "\n".join(clips_html) +
        "\n</div>\n"
        "<script>\n"
        "  window.__timelines = window.__timelines || {};\n"
        "  const tl = gsap.timeline({ paused: true });\n"
        f"  window.__timelines[{js_id}] = tl;\n"
        + "\n".join(highlight_js) +
        "\n</script>\n"
        "</body>\n"
        "</html>\n"
    )

    composition_path = COMPOSITIONS_DIR / f"{identifier}.html"
    composition_path.write_text(composition, encoding="utf-8")
    return str(composition_path)


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit("Usage: python build_video.py <identifier> [--slides-only]")

    identifier = sys.argv[1]
    slides_only = len(sys.argv) == 3 and sys.argv[2] == "--slides-only"

    if slides_only:
        start = time.perf_counter()
        paths = render_slides(identifier)
        elapsed = format_elapsed(time.perf_counter() - start)
        print(f"Rendered {len(paths)} slide(s) in {elapsed} - review before building the composition:")
        for p in paths:
            print(f"  {p}")
    else:
        # This is the step that actually narrates every line (local
        # Kokoro TTS, one subprocess call per line) - by far the slowest
        # part of the pipeline, so it's the one worth timing and
        # reporting rather than leaving someone watching a blank
        # terminal with no sense of whether it's still working.
        start = time.perf_counter()
        composition_path = build_composition(identifier)
        elapsed = format_elapsed(time.perf_counter() - start)
        print(f"Composition written to {composition_path} in {elapsed}.")
        print("Next: from inside render/, run:\n"
              "  npm run check\n"
              f"  time npx hyperframes render . -c compositions/{identifier}.html "
              f"-o ../videos/{identifier}.mp4 -q draft\n"
              "(the `time` prefix prints how long the render itself took, once it "
              "finishes, so you don't have to watch a clock for that step either. "
              "First render on a fresh machine may also download a Chromium "
              "binary - a one-time cost, not part of the render time itself.)")
