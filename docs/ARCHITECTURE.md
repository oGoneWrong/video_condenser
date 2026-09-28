# Architecture

Stage-by-stage detail: what each step reads, calls, writes, and why it's
shaped that way. For *why this tool over the alternatives*, see
[`DECISIONS.md`](DECISIONS.md) — this file is the "what," that one is the
"why."

A convention that runs through all of it: every stage reads and writes plain
UTF-8 text under a folder named for that stage, keyed by the same
`identifier` (a YouTube video ID, or a local filename) — see
[`storage.py`](../storage.py). That's what lets each stage run standalone from
the command line and still chain into the next one.

```
transcripts/<id>.txt  →  insights/<id>.txt  →  slides/<id>/*.html  →  render/compositions/<id>.html  →  videos/<id>.mp4
```

## Step 1 — Get a transcript ([`youtube_transcript.py`](../youtube_transcript.py))

**Input:** a YouTube URL. **Output:** `transcripts/<id>.txt`.

Priority order:
1. Pull YouTube's own captions (creator-uploaded or auto-generated) via
   `youtube-transcript-api` — free, instant, no audio processing at all.
2. If no captions exist, extract *only* the audio stream via `yt-dlp`
   (`format: bestaudio/best`, converted to WAV) into a `tempfile.TemporaryDirectory()`
   that deletes itself once the ASR call returns — the video itself is never
   downloaded, and nothing persists on disk beyond the transcript.

The extractor pins `extractor_args: {youtube: {player_client: ["android"]}}`
because YouTube's default web client is the one most often caught by
innertube bot-checks (surfaces as a bare `HTTP Error 403`); the Android
client has been the more stable path.

**Known gap:** there's no equivalent entry point for a *local video file* —
see the README's "Known gap" section. `transcribe_audio.py`'s own docstring
references a `video_to_audio.py` that was never built.

## Step 2 — Audio → transcript, fallback path ([`transcribe_audio.py`](../transcribe_audio.py))

**Input:** an audio file path. **Output:** transcript text (returned, not
saved directly — the caller decides where it goes).

A single function, `transcribe(audio_path) -> str`, deliberately shaped to
match what Step 1 needs (`asr_function` parameter) so the same call works
whether it's invoked from `youtube_transcript.py`'s caption-fallback or
directly on a local audio file. Uses AssemblyAI's SDK, which handles the
upload → poll → fetch cycle internally (`transcriber.transcribe()` blocks
until done) rather than this script hand-rolling that loop.

Requires `ASSEMBLYAI_API_KEY` in `.env` (gitignored; `.env.example` is the
committed template).

## Step 3 — Transcript → journalistic insights ([`extract_insights.py`](../extract_insights.py))

**Input:** `transcripts/<id>.txt`. **Output:** `insights/<id>.txt`.

Calls Gemini (`models/gemini-3.8-flash`, free tier — chosen specifically
because Anthropic's Console API is prepaid-credits-only and this needed a
truly free option) with a fixed extraction prompt that produces exactly two
sections:

- **FACTS** — who/what/when, one fact per line as `Label: value`.
- **NUMBERS & CONTEXT** — figures actually stated in the transcript, *plus*
  up to 5 additional figures a reader would want that are explicitly tagged
  `[NOT IN VIDEO - verify externally]: <what to look up and why>` rather than
  invented. This is the mechanism that keeps every on-screen number
  traceable to a real source — nothing downstream is allowed to promote one
  of these placeholders into a stated fact (`slide_planner.py` drops them
  before Gemini ever sees the numbers list in the next stage).

**Why extraction, not paraphrase, avoids plagiarism:** a paraphrase that
keeps the transcript's own sentence order and structure is still derivative
even with every word swapped for a synonym — the shallow "paraphraser"
pattern plagiarism detectors are built to catch. Extraction discards the
original phrasing and structure entirely and re-expresses each fact as an
independent statement; what survives is the information, not the source's
words or shape. This also happens to be the exact shape Step 4 needs:
discrete, ranked, one-idea-per-line points, not flowing prose.

Requires `GEMINI_API_KEY` (same `.env` as Step 2).

## Step 3.5 — Slide planning ([`slide_planner.py`](../slide_planner.py))

**Input:** the FACTS / NUMBERS lines from Step 3 (in memory, not re-read from
disk). **Output:** grouping/labeling decisions consumed by Step 4.

The reasoning layer between raw insights and rendering: decides (a) which
FACTS bullets belong on the same slide (capped at 3, up to 4 only when
tightly linked), and (b) which NUMBERS lines share a unit and are therefore
chartable versus plain context bullets. Reuses the same Gemini key as Step
3 — no new provider, no new signup.

Two design details worth knowing if you're reading the code:

- **Index-based, not verbatim-text-based.** Gemini returns which *index* a
  line belongs to; the actual displayed text always comes from Python's own
  `facts`/`number_lines` lists. An earlier version asked Gemini to echo each
  bullet back verbatim so Python could diff it — but the model doesn't
  reproduce text byte-for-byte even when told to (a re-typed dash, a trimmed
  space), which produced false "planner altered a line" errors on lines that
  were actually fine.
- **Fails soft.** If `GEMINI_API_KEY` is missing, or the call/parse fails,
  callers fall back to the old deterministic regex/pagination logic in
  `build_video.py`'s `build_slide_deck`. A public repo shouldn't hard-fail
  just because someone hasn't set up an API key. 503/429 (temporary
  overload) triggers retry-then-model-fallback within Gemini itself; any
  other error (bad key, malformed response) is treated as a content problem
  and raised immediately rather than burning through retries pointlessly.

## Step 4 — Insights → video ([`build_video.py`](../build_video.py))

**Input:** `insights/<id>.txt`. **Output:** `render/compositions/<id>.html`
(+ per-slide audio), then (via the HyperFrames CLI, run separately)
`videos/<id>.mp4`.

Four sub-steps, each independently runnable:

1. `build_slide_deck(identifier)` — paginates Step 3's insights into facts
   pages and numbers pages, sized so content never clips (height-based
   packing — see below).
2. `render_slides(identifier)` — **checkpoint.** Writes every slide as a
   standalone, browser-openable `.html` file under `slides/<id>/`, with no
   audio or composition yet, so layout can be eyeballed before spending time
   on narration.
3. `build_composition(identifier)` — narrates each slide via local Kokoro-82M
   TTS (through `npx hyperframes tts`, one subprocess call per line,
   concatenated per slide with ffmpeg's concat demuxer), probes each clip's
   real duration with `ffprobe`, and writes a single standalone HyperFrames
   composition with every slide + its audio as timed sibling clips.
4. `npx hyperframes render` (run manually from `render/`) — Chrome and
   ffmpeg do the actual rendering; GSAP and fonts are vendored locally
   (`render/vendor/`), so nothing at render time depends on network access.

**Height-based packing, not fixed item counts:** an earlier version
chunked bullets/charts by a fixed count per slide regardless of how much
room they actually needed. The current packer
(`pack_by_height`/`pack_numbers_pages`) measures each block's real rendered
height from CSS metrics and greedily fills a slide until the next atomic
unit would overflow — verified against actual headless-Chromium
`getBoundingClientRect()` output before shipping, not just estimate math.

**Charting:** NUMBERS & CONTEXT figures that share a unit become a
hand-coded inline SVG bar chart (no chart library, nothing to vendor beyond
what's already local). A figure that's the only one in its unit becomes a
single large stat number instead of a one-bar chart, which would otherwise
compare against nothing.

**Narration highlight:** each bullet dims/brightens in sync with its own
narration line (`build_bullet_highlight_tweens`), timed off that line's real
measured TTS duration. Word-level highlighting was explicitly ruled out as
too distracting.

**Visual identity:** HyperFrames' published "Blue Professional" spec
(parchment `#fdfae7` background, cobalt `#1e2bfa` accent, Space
Grotesk/Inter), vendored locally rather than pulled from a Google Fonts CDN
at render time.

## Step 4a (optional) — Regional map slide ([`map_slide.py`](../map_slide.py))

**Input:** the FACTS and NUMBERS lines, before slide planning/packing runs.
**Output:** one additional slide + composition clip; the metric lines it
uses are *removed* from the numbers section so the same figures are never
shown twice.

Entirely deterministic — no LLM call:

1. Featured cities = Taiwanese cities named in FACTS, in first-mention order.
2. Metric lines = NUMBERS & CONTEXT lines whose label matches a configured
   keyword (`MAP_METRIC`, currently mortgage burden ratio).
3. Each city gets a value from the most specific source available: a figure
   tied to it directly → a line that names it → a regional figure if the
   city falls in that region (shown as e.g. `"40%+"` and captioned as
   regional, never presented as if it were city-specific).
4. Fewer than 2 resolved cities → no map slide at all; nothing else changes.

Map outlines come from `render/vendor/taiwan_map.json`, generated once by
[`tools/taiwan_map/`](../tools/taiwan_map/) (see its own README) from
`taiwan-atlas` + `topojson-simplify` + `d3-geo` — no TopoJSON/d3/network
access needed at build or render time, since the committed JSON already has
projected SVG path strings.

## Step 4b (optional, metered) — Avatar presenter clip

**Scripts:** [`tools/heygen_avatar/generate_avatar_clip.py`](../tools/heygen_avatar/generate_avatar_clip.py)
(generation) and [`resume_download.py`](../tools/heygen_avatar/resume_download.py)
(recovery — see below). **Output:** `avatar_clips/<id>_map.{json,mp4}` +
`_map_audio.wav`, read (never written) by `map_slide.py`.

Deliberately separate from the automatic build — this is the one step in
the whole pipeline that spends a metered, real-money-adjacent allowance
(HeyGen avatar video) rather than an unlimited local resource or a free-tier
call. Nothing else calls it automatically. Free/local alternatives (Wav2Lip,
SadTalker, MuseTalk, Sync) were evaluated and rejected before settling here
— see `docs/DECISIONS.md`.

**Audio-driven, not script-driven:** the avatar lip-syncs to real audio this
pipeline already generates, rather than HeyGen synthesizing its own voice
from a script. Sequence: (1) narrate each line with the same local Kokoro
engine every other slide uses (`build_video.generate_narration`, reused
directly — free, unlimited, same voice throughout the video) and concatenate
into one WAV, so each line's duration is real and ffprobe'd, not a proxy;
(2) upload that WAV via `heygen asset create` (free — storage, not
generation) to get an `audio_asset_id`; (3) exactly one `heygen video
create` call with `type: "avatar"` and `audio_asset_id` (mutually exclusive
with `script`/`voice_id`) — the metered call; (4) download the resulting
clip and write the manifest. There's no audio *extraction* step and no
duration *rescaling* step — both existed only in the earlier script-driven
version to recover timing HeyGen's own TTS didn't expose; audio-driven mode
never loses that information in the first place, since the driving audio
was ours to begin with.

**Guardrails:** refuses to run for an identifier that already has a
manifest unless `--force` (closes an accidental double-spend on a re-run);
a failed `heygen video create` call is diagnosed rather than just dumped —
a billing/plan error is reported as one, and a timeout (HeyGen CLI exit
code 4) is explicitly flagged as "the video likely already exists, don't
re-run this" rather than treated as if nothing happened.

**`resume_download.py`** exists because the download step (a plain
`curl -f`) can 403 even on a valid, unexpired signed URL — CDNs commonly
reject a bare `curl/8.x` User-Agent as a bot-protection rule, which reads
like a permissions error but isn't one — so `generate_avatar_clip.py` now
uses a browser User-Agent from the first attempt. If the download still
fails after the metered call already succeeded, this script retries just
the download (never the generation) using the audio and per-line-duration
sidecar `generate_avatar_clip.py` already wrote to disk before making that
call, so a download hiccup never costs a second avatar generation.

**A second, unrelated way to get the same symptom (a bare download 403):**
`heygen video create --wait` prints its raw stdout, not re-decoded JSON, and
`extract_result_path()` pulls the download URL out of it with a plain
regex. HeyGen's CLI (like most Go JSON encoders) escapes `&` in its JSON
output as `\u0026` by default — so a URL that goes through the regex without
ever being JSON-decoded keeps those six literal characters instead of a
real `&`. That URL curls without a syntax error but is silently wrong: the
server only ever receives the first query parameter, `Expires`/`Signature`
never arrive, and the result is a 403 indistinguishable from a bot-blocked
or genuinely expired URL unless you go looking for a literal `\u0026` in the
failing URL. `extract_result_path()` now runs every URL it finds through
`unescape_json_url()` (only touches `\uXXXX` escapes, leaves everything else
alone) before returning it; `resume_download.py` applies the same
unescape defensively to whatever URL it's handed, since that's usually
hand-copied out of a `heygen video list` JSON dump rather than piped
through a real JSON parser. Found and fixed after the first female-avatar
test run (Aya) hit exactly this — the metered call had already succeeded,
and the fix let the existing clip download without spending a second
generation.

## Failure modes worth knowing about

- **Gemini calls (Steps 3, 3.5) fail soft** — a missing key or bad response
  degrades to a deterministic fallback rather than crashing the build. Step
  3 itself has no fallback (it's the one LLM call with no substitute), so a
  missing `GEMINI_API_KEY` there is a hard stop.
- **The map/avatar slide is additive-optional** — if `avatar_clips/` is
  empty, `map_slide.py` still renders the map with a placeholder where the
  avatar would go and narrates it via Kokoro like every other slide.
- **A sandboxed shell's network allowlist can silently degrade Step 3.5**
  (Gemini) to its regex fallback without erroring — see `DECISIONS.md` for
  why the build and render steps are run natively rather than through an
  agent's remote shell.
