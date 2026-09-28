"""
map_slide.py
The "regional map" slide for Step 4 (build_video.py): a map of Taiwan
with the cities the video reports on highlighted, each carrying one
headline figure as a callout, instead of narrating those same figures
again as bullets on a "BY THE NUMBERS" slide.

Why a separate module: build_video.py's slides are all "a title plus
bullets and/or charts," built from whatever Step 3 extracted. A map is
different in kind - it needs geography (which city is where) and a way
to tie each number to a place - so it lives here, next to its own
extraction rule, CSS and highlight logic, rather than growing
build_video.py further.

How it decides what goes on the map (deterministic, no LLM call):
  1. Featured cities = the Taiwanese cities named in the FACTS section,
     in the order they first appear (for this video: "reporting on
     housing markets in Taipei, Taichung, and Tainan").
  2. Metric lines = NUMBERS & CONTEXT lines whose label contains
     MAP_METRIC["keyword"] (here: "burden", i.e. mortgage burden ratio).
  3. Each featured city gets a value from those lines, most specific
     source first:
       - a figure tied to it directly ("nearing 45% in Taichung"),
       - else a line whose label names it ("Taipei mortgage burden
         ratio: ... roughly 60% ..."),
       - else a REGIONAL figure ("exceed 40% ... in major central and
         southern municipalities") if the city is in that region - shown
         as "40%+" and captioned as a regional figure, so the slide never
         presents a region-wide number as if it were city-specific.
  4. Fewer than 2 cities resolved -> no map slide at all; the metric
     lines stay in NUMBERS & CONTEXT and the deck is exactly as before.

The metric lines used here are REMOVED from the numbers section before
slide_planner / packing runs, so the same figures are never narrated or
shown twice (user decision: "prioritize visuals, avoid duplicates").

The map outlines come from render/vendor/taiwan_map.json - pre-projected
SVG paths generated once by tools/taiwan_map/ (see its README.md). No
TopoJSON, d3 or network access is needed at build or render time.

Optional HeyGen avatar presenter (picture-in-picture, bottom-right of
this slide): generated separately and OFFLINE from this module's own
build, by tools/heygen_avatar/generate_avatar_clip.py (a manual,
cost-aware step - see that script's own docstring). This module only
ever READS whatever that script already produced:
  avatar_clips/<identifier>_map.json   - manifest (paths + per-line
                                          durations, see AvatarManifest)
  avatar_clips/<identifier>_map.mp4    - the rendered avatar clip
  avatar_clips/<identifier>_map_audio.wav - its audio track, extracted
                                          once so it can be reused as
                                          this slide's own <audio> clip
                                          without re-touching the mp4
No manifest for an identifier -> build_map_slide's "avatar" field is
None and render_map_slide_html draws a dashed placeholder in its place
instead - the pipeline never depends on HeyGen having been run.
"""

import html
import json
import re
from pathlib import Path

MAP_ASSET_PATH = Path("render") / "vendor" / "taiwan_map.json"
AVATAR_CLIPS_DIR = Path("avatar_clips")

# What the map shows. Kept as one explicit config block rather than
# inferred, so it's obvious (and easy to change) which metric the map is
# built around. The keyword is matched against the label (text before
# the first ":") of each NUMBERS & CONTEXT line.
MAP_METRIC = {
    "keyword": "burden",
    "title": "MORTGAGE BURDEN BY CITY",
    "subtitle": "Share of household income going to the mortgage",
}

# City -> (county name in taiwan_map.json, region). Longer names first so
# "New Taipei" is matched before "Taipei" (see _find_cities).
CITIES = [
    ("New Taipei", "New Taipei City", "north"),
    ("Taipei", "Taipei City", "north"),
    ("Taoyuan", "Taoyuan City", "north"),
    ("Hsinchu", "Hsinchu City", "north"),
    ("Taichung", "Taichung City", "central"),
    ("Tainan", "Tainan City", "south"),
    ("Kaohsiung", "Kaohsiung City", "south"),
]
REGION_WORDS = {"central": "central", "southern": "south", "northern": "north"}
APPROX_WORDS = r"(?:roughly|approximately|about|around|nearly|nearing|almost|close to)"
ABOVE_WORDS = r"(?:exceed|exceeds|exceeding|over|above|more than|surpass(?:es)?)"

# Layout (slide pixel space, inside the slide's 90px padding).
MAP_LEFT, MAP_TOP = -60, 250        # map box offset within .map-slide's content area
CALLOUT_LEFT = 560                  # callout column x, content-area coordinates
CALLOUT_MIN_GAP = 250               # min vertical distance between callouts
CALLOUT_ANCHOR_DY = 40              # where the leader line meets the callout (its number's midline)

# Highlight - same dim/active idea as build_video's bullet highlight.
CALLOUT_DIM_OPACITY = 0.3
HIGHLIGHT_TRANSITION_SECONDS = 0.3

# Avatar picture-in-picture box, in the same content-area coordinates as
# CALLOUT_LEFT above (i.e. relative to the div at left:90/top:90 - add 90
# to get stage-absolute pixels, done once in render_avatar_clip_html).
# Sized/placed to clear the lowest callout (Tainan's, the third of three)
# with room to spare - re-check against render_map_slide_html's actual
# callout layout if a future video features a 4th city.
AVATAR_LEFT, AVATAR_TOP, AVATAR_SIZE = 500, 1320, 380


MAP_SLIDE_CSS = """
.map-slide { position: relative; }
.map-slide .subtitle {
  font-family: "Inter", system-ui, sans-serif;
  font-size: 34px;
  color: var(--muted);
  margin: -56px 0 0 0;
}
.map-slide .map-layer { position: absolute; left: 0; top: 0; overflow: visible; }
.map-slide .county { fill: rgba(30, 43, 250, 0.07); stroke: rgba(30, 43, 250, 0.35); stroke-width: 1.2; }
.map-slide .county.featured { fill: var(--cobalt); stroke: var(--canvas); stroke-width: 1.5; }
.map-slide .leader { stroke: var(--cobalt); stroke-width: 2.5; }
.map-slide .pin { fill: var(--canvas); stroke: var(--cobalt); stroke-width: 4; }
.map-slide .callout { position: absolute; font-family: "Space Grotesk", system-ui, sans-serif; }
.map-slide .callout-value { font-size: 88px; font-weight: 700; color: var(--cobalt); line-height: 1; }
.map-slide .callout-city { font-size: 40px; font-weight: 600; color: var(--ink); margin-top: 8px; }
.map-slide .callout-caption {
  font-family: "Inter", system-ui, sans-serif;
  font-size: 28px; color: var(--muted); margin-top: 6px; max-width: 330px;
}
.map-slide .avatar-placeholder {
  position: absolute;
  border-radius: 50%;
  border: 3px dashed var(--cobalt-border);
  background: repeating-linear-gradient(45deg, var(--cobalt-tint) 0 22px, transparent 22px 44px);
  display: flex; align-items: center; justify-content: center; text-align: center;
  font-family: "Space Grotesk", system-ui, sans-serif; font-weight: 600;
  font-size: 26px; color: var(--muted); line-height: 1.3; padding: 24px; box-sizing: border-box;
}
"""


def load_map_asset(path: Path = MAP_ASSET_PATH):
    """The pre-projected county outlines, or None if the asset is missing
    (in which case the map slide is simply skipped - it's an enhancement,
    not something a build should fail over)."""
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def avatar_manifest_path(identifier: str) -> Path:
    return AVATAR_CLIPS_DIR / f"{identifier}_map.json"


def load_avatar_manifest(identifier: str):
    """
    The manifest generate_avatar_clip.py writes for this identifier, or
    None if it hasn't been generated (or the identifier wasn't given -
    build_slide_deck() passes it; a standalone caller that omits it just
    gets the no-avatar placeholder, same as before this feature existed).

    Shape (all paths relative to the project root, as written by
    generate_avatar_clip.py - resolved here against AVATAR_CLIPS_DIR's
    parent so this works regardless of the caller's own cwd assumptions):
      {"avatar_id", "voice_id", "script", "generated_at",
       "video_path", "audio_path", "line_durations": [float, ...],
       "total_duration": float}
    line_durations is in the SAME order as the slide's own
    narration_lines / callouts' line_index - see build_map_highlight_tweens.
    """
    if not identifier:
        return None
    path = avatar_manifest_path(identifier)
    if not path.exists():
        return None
    manifest = json.loads(path.read_text(encoding="utf-8"))
    root = AVATAR_CLIPS_DIR.parent
    for key in ("video_path", "audio_path"):
        p = Path(manifest[key])
        manifest[key] = str(p if p.is_absolute() else root / p)
    return manifest


def _find_cities(text: str) -> list:
    """Known city names in text, in order of first appearance. Longer
    names are masked out first so 'New Taipei' doesn't also count as
    'Taipei'."""
    found, masked = [], text
    for name, _county, _region in CITIES:
        for m in re.finditer(rf"\b{re.escape(name)}\b", masked):
            found.append((m.start(), name))
        masked = re.sub(rf"\b{re.escape(name)}\b", lambda m: "#" * len(m.group()), masked)
    seen, ordered = set(), []
    for _pos, name in sorted(found):
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def _fmt(number: str, approx: bool, above: bool = False) -> str:
    return ("~" if approx else "") + number + "%" + ("+" if above else "")


def extract_regional_callouts(facts: list, number_lines: list):
    """
    Returns (callouts, used_lines), or (None, []) when there isn't enough
    for a meaningful map (fewer than two cities resolved).

    callouts: list of dicts {city, county, value, caption, kind, line_index}
      ordered north -> south (by map position, applied later), where
      line_index is the position in used_lines of the line that supplied
      it - the narration/highlight code uses it to light each callout up
      while its own source line is being read.
    used_lines: the metric lines, in their original order - these become
      the map slide's narration and are removed from NUMBERS & CONTEXT.
    """
    region_of = {name: region for name, _c, region in CITIES}
    county_of = {name: county for name, county, _r in CITIES}

    featured = _find_cities(" ".join(facts))
    if len(featured) < 2:
        return None, []

    metric_lines = [
        line for line in number_lines
        if MAP_METRIC["keyword"].lower() in line.split(":", 1)[0].lower()
    ]
    if not metric_lines:
        return None, []

    values = {}  # city -> (value, caption, kind, line_index)
    for idx, line in enumerate(metric_lines):
        label, _, body = line.partition(":")
        caption = "of household income" if "income" in line.lower() else ""

        # 1) figure tied directly to a city: "nearing 45% in Taichung"
        for m in re.finditer(
            rf"({APPROX_WORDS}\s+)?(\d+(?:\.\d+)?)%\s+(?:in|for)\s+([A-Z][A-Za-z ]+?)\b(?=[.,;]|$)",
            body,
        ):
            for city in _find_cities(m.group(3)):
                if city in featured and city not in values:
                    values[city] = (_fmt(m.group(2), bool(m.group(1))), caption, "city", idx)

        # 2) the line's label names a city: "Taipei mortgage burden ratio: ... roughly 60% ..."
        for city in _find_cities(label):
            if city in featured and city not in values:
                m = re.search(rf"({APPROX_WORDS}\s+)?(\d+(?:\.\d+)?)%", body)
                if m:
                    values[city] = (_fmt(m.group(2), bool(m.group(1))), caption, "city", idx)

        # 3) a regional floor: "exceed 40% ... in major central and southern municipalities"
        regions = {REGION_WORDS[w] for w in REGION_WORDS if re.search(rf"\b{w}\b", line, re.I)}
        m = re.search(rf"{ABOVE_WORDS}\s+(\d+(?:\.\d+)?)%", body, re.I)
        if regions and m:
            for city in featured:
                if city not in values and region_of[city] in regions:
                    region_caption = " & ".join(
                        w for w in ("central", "southern", "northern") if REGION_WORDS[w] in regions
                    )
                    values[city] = (
                        _fmt(m.group(1), False, above=True),
                        f"regional figure ({region_caption} cities)",
                        "regional",
                        idx,
                    )

    callouts = [
        {"city": city, "county": county_of[city], "value": v[0],
         "caption": v[1], "kind": v[2], "line_index": v[3]}
        for city in featured if city in values
        for v in [values[city]]
    ]
    if len(callouts) < 2:
        return None, []

    # Only lines that actually fed a callout are consumed; anything else
    # matching the keyword stays in NUMBERS & CONTEXT.
    used_idx = sorted({c["line_index"] for c in callouts})
    remap = {old: new for new, old in enumerate(used_idx)}
    for c in callouts:
        c["line_index"] = remap[c["line_index"]]
    used_lines = [metric_lines[i] for i in used_idx]
    return callouts, used_lines


def build_map_slide(facts: list, number_lines: list, identifier: str = None):
    """
    Returns (slide_or_None, remaining_number_lines). The slide dict
    follows the deck shape build_video.py uses:
      {"type": "map", "title", "subtitle", "callouts", "narration_lines",
       "avatar": manifest_or_None}

    identifier is used only to look up an already-generated avatar
    manifest (see load_avatar_manifest) - passing None (the default)
    just means "no avatar for this call," not "no avatar ever": the
    manifest is produced entirely outside this module's own build.
    """
    asset = load_map_asset()
    if asset is None:
        return None, number_lines
    callouts, used_lines = extract_regional_callouts(facts, number_lines)
    if not callouts:
        return None, number_lines
    counties = {c["name_en"] for c in asset["counties"]}
    callouts = [c for c in callouts if c["county"] in counties]
    if len(callouts) < 2:
        return None, number_lines
    remaining = [line for line in number_lines if line not in used_lines]
    slide = {
        "type": "map",
        "title": MAP_METRIC["title"],
        "subtitle": MAP_METRIC["subtitle"],
        "callouts": callouts,
        "narration_lines": used_lines,
        "avatar": load_avatar_manifest(identifier),
    }
    return slide, remaining


def callout_id(slide_id: str, index: int) -> str:
    return f"callout-{slide_id}-{index}"


def _layout_callouts(callouts: list, centroids: dict) -> list:
    """Place callouts in a right-hand column, each as close to its
    city's own height on the map as possible, pushed apart to at least
    CALLOUT_MIN_GAP so labels never overlap. Returns (callout, pin_xy, top)
    tuples ordered north -> south."""
    placed = []
    for c in sorted(callouts, key=lambda c: centroids[c["county"]][1]):
        cx, cy = centroids[c["county"]]
        pin = (cx + MAP_LEFT, cy + MAP_TOP)
        top = pin[1] - CALLOUT_ANCHOR_DY
        if placed:
            top = max(top, placed[-1][2] + CALLOUT_MIN_GAP)
        placed.append((c, pin, top))
    return placed


def render_map_slide_html(slide: dict, slide_id: str = "00", asset=None) -> str:
    asset = asset or load_map_asset()
    featured = {c["county"] for c in slide["callouts"]}
    centroids = {c["name_en"]: c["centroid"] for c in asset["counties"]}
    order = {c["city"]: i for i, c in enumerate(slide["callouts"])}

    paths = []
    for county in asset["counties"]:
        cls = "county featured" if county["name_en"] in featured else "county"
        cid = ""
        if county["name_en"] in featured:
            idx = next(i for i, c in enumerate(slide["callouts"]) if c["county"] == county["name_en"])
            cid = f' id="{callout_id(slide_id, idx)}-area"'
        paths.append(f'<path{cid} class="{cls}" d="{county["d"]}"/>')

    placed = _layout_callouts(slide["callouts"], centroids)
    w, h = asset["width"], asset["height"]
    leaders, pins, callouts_html = [], [], []
    for c, (px, py), top in placed:
        idx = order[c["city"]]
        el_id = callout_id(slide_id, idx)
        leaders.append(
            f'<line id="{el_id}-leader" class="leader" x1="{px:.1f}" y1="{py:.1f}" '
            f'x2="{CALLOUT_LEFT - 24}" y2="{top + CALLOUT_ANCHOR_DY:.1f}"/>'
        )
        pins.append(f'<circle class="pin" cx="{px:.1f}" cy="{py:.1f}" r="9"/>')
        caption = f'<div class="callout-caption">{html.escape(c["caption"])}</div>' if c["caption"] else ""
        callouts_html.append(
            f'<div id="{el_id}" class="callout" style="left:{CALLOUT_LEFT}px;top:{top:.0f}px">'
            f'<div class="callout-value">{html.escape(c["value"])}</div>'
            f'<div class="callout-city">{html.escape(c["city"])}</div>'
            f'{caption}</div>'
        )

    # One SVG in content-area coordinates: county paths translated into
    # place, leader lines and pins drawn on top. Width/height cover the
    # whole content area so leaders can reach the callout column.
    svg = (
        f'<svg class="map-layer" width="900" height="1740" viewBox="0 0 900 1740">'
        f'<g transform="translate({MAP_LEFT},{MAP_TOP})">{"".join(paths)}</g>'
        f'{"".join(leaders)}{"".join(pins)}</svg>'
    )
    # The avatar itself is never drawn here: when a manifest exists it's a
    # separately timed <video> clip (see render_avatar_clip_html), layered
    # on top of this slide's own clip at the identical box so it reads as
    # "inside" this frame without this (untimed) markup needing to know
    # about video timing at all. Only the no-avatar case draws anything
    # in that spot, so the checkpoint preview always shows where it'll go.
    avatar_html = "" if slide.get("avatar") else (
        f'<div class="avatar-placeholder" style="left:{AVATAR_LEFT}px;top:{AVATAR_TOP}px;'
        f'width:{AVATAR_SIZE}px;height:{AVATAR_SIZE}px">HeyGen avatar<br>(not yet generated)</div>'
    )
    return (
        f'<div class="slide map-slide">'
        f'<div class="title">{html.escape(slide["title"])}</div>'
        f'<div class="subtitle">{html.escape(slide["subtitle"])}</div>'
        f'<div style="position:absolute;left:90px;top:90px;width:900px;height:1740px">'
        f'{svg}{"".join(callouts_html)}{avatar_html}</div>'
        f'</div>'
    )


def render_avatar_clip_html(slide_id: str, start: float, duration: float, src: str) -> str:
    """
    The avatar's own <video> clip - a root-level sibling of this slide's
    `.clip` div and `<audio>` (same data-start/data-duration as both, per
    tracks-and-clips.md: "data-start is in seconds, measured from the
    start of the composition", so nesting isn't required for correct
    timing). Muted: this slide's actual sound comes from the sibling
    <audio> element (the SAME recording, extracted once by
    generate_avatar_clip.py - see that script - not this video's own
    baked-in track), so nothing here needs data-has-audio either.

    class="clip" is deliberately omitted (data-attributes.md: "Omit it
    on <video> and <audio>") - this element's inline style already gives
    it an explicit, non-full-frame position/size, so it doesn't need
    (and shouldn't get) the shared `.clip { inset: 0 }` full-frame rule.
    """
    left, top = 90 + AVATAR_LEFT, 90 + AVATAR_TOP
    style = (
        f"position:absolute;left:{left}px;top:{top}px;"
        f"width:{AVATAR_SIZE}px;height:{AVATAR_SIZE}px;"
        f"border-radius:50%;object-fit:cover;z-index:2;"
    )
    return (
        f'<video id="avatar-{slide_id}" data-start="{start:.3f}" data-duration="{duration:.3f}" '
        f'data-track-index="2" muted playsinline style="{style}" src="{html.escape(src)}"></video>'
    )


def build_map_highlight_tweens(slide: dict, slide_id: str, line_durations: list,
                               cursor: float) -> list:
    """
    Same sentence-level highlight as the bullets (build_video's
    build_bullet_highlight_tweens), applied to callouts: while a
    narration line is playing, the callout(s) it supplied - plus their
    leader line and county shape - are at full strength and the rest are
    dimmed. Returns GSAP statement strings for the composition's single
    timeline; every target id carries its "#" prefix (a bare id is read
    by GSAP as a tag selector and silently no-ops).
    """
    callouts = slide["callouts"]
    if not callouts:
        return []

    def targets(indices):
        ids = []
        for i in indices:
            base = "#" + callout_id(slide_id, i)
            ids += [base, base + "-leader", base + "-area"]
        return json.dumps(ids)

    everyone = range(len(callouts))
    slide_start = round(cursor, 3)

    if len(line_durations) <= 1:
        # One merged narration line (e.g. a custom single-line avatar
        # script - see generate_avatar_clip.py's --script) covers every
        # callout at once. There's no per-line boundary left to key a
        # sequential reveal off, so every callout lights up together for
        # the whole slide instead of the dim/undim handoff below, which
        # would otherwise strand any callout whose line_index isn't 0
        # dimmed for the entire slide (nothing ever un-dims it).
        return [f"  tl.set({targets(everyone)}, {{opacity: 1}}, {slide_start});"]

    lines = [f"  tl.set({targets(everyone)}, {{opacity: {CALLOUT_DIM_OPACITY}}}, {slide_start});"]

    offset = 0.0
    for line_idx, dur in enumerate(line_durations):
        t = round(cursor + offset, 3)
        active = [i for i, c in enumerate(callouts) if c["line_index"] == line_idx]
        inactive = [i for i in everyone if i not in active]
        if active:
            lines.append(
                f"  tl.to({targets(active)}, {{opacity: 1, "
                f"duration: {HIGHLIGHT_TRANSITION_SECONDS}}}, {t});"
            )
        if inactive and line_idx > 0:
            lines.append(
                f"  tl.to({targets(inactive)}, {{opacity: {CALLOUT_DIM_OPACITY}, "
                f"duration: {HIGHLIGHT_TRANSITION_SECONDS}}}, {t});"
            )
        offset += dur
    return lines
