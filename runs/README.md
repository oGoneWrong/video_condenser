# Run history

Snapshots of past renders of the `KjAI9r8tnOs` video, kept so the pipeline's
evolution is visible. None of these are inputs to the current pipeline -
`build_video.py` regenerates everything in `slides/`, `render/compositions/`,
and `videos/` fresh from `insights/` each time it runs, so nothing here is
read by the code, and re-running the pipeline never touches anything under
`runs/` - only these files, copied out by hand after a render, are frozen.

## run_1_pillow_prototype/

The earliest slide-rendering attempt: static PNG slides built with Pillow,
paired with narration audio and a hand-written `composition.html` that
guessed at HyperFrames' HTML/CSS contract rather than following the real
spec (no `data-composition-id`/`data-start` attributes, no registered GSAP
timeline). Superseded once the pipeline switched to generating real
HyperFrames-compatible compositions directly.

## run_2_edge_tts_render/

The first successful end-to-end render through the real HyperFrames CLI:
narration via edge-tts (network-dependent) and slides in the old dark
palette (`--surface-1:#1a1a19; --accent:#3987e5`). Includes the rendered
`KjAI9r8tnOs.mp4`. Superseded by the switch to local Kokoro TTS (no network
dependency, so the published repo works for anyone without extra API
signups) and the Blue Professional visual redesign.

## run_3_kokoro_gemini_render/ - first official result

The first full render of the current pipeline: local Kokoro narration (no
network dependency at render time), Gemini-assisted slide grouping via
`slide_planner.py` (linked-pair fact grouping + chart-item classification),
hand-coded SVG bar charts, Blue Professional palette. 9 slides (4 "THE
FACTS" + 5 "BY THE NUMBERS"), ~4:03 runtime.

Contains:
- `KjAI9r8tnOs.txt` - the Step 3 insights text this run was built from
- `composition/KjAI9r8tnOs.html` + `composition/KjAI9r8tnOs_audio/` - the
  exact composition and narration clips that produced the video below
- `video/KjAI9r8tnOs.mp4` - the rendered output

This is the baseline frozen for before/after comparison against the
refinement pass below.

## run_4_height_n_animation/

First comparison render after the refinement pass, built and rendered
natively in the Mac Terminal so `slide_planner.py`'s Gemini grouping ran
for real (log: "... responded - slide layout ready.") - the same input
path as run_3, so the two are directly comparable.

What changed vs run_3:
- **Height-based slide packing** - replaced the old fixed-item-count
  chunking (`chunk_list`, capped at N bullets/charts per slide regardless
  of how much room they actually needed) with a height-based packer
  (`pack_by_height`/`pack_numbers_pages`) that measures each bullet's /
  chart block's rendered height from CSS metrics and greedily fills each
  slide until the next atomic unit would overflow - verified against a
  headless-Chromium render before shipping (real DOM
  `getBoundingClientRect()` measurements, not just the estimate math).
- **Sentence-level narration highlight** - each bullet dims/brightens in
  sync with its own narration line (`build_bullet_highlight_tweens`, timed
  off each line's real TTS duration); word-level highlighting was
  explicitly ruled out as too distracting.

7 slides (3 "THE FACTS" + 4 "BY THE NUMBERS"), ~4:03 runtime (243.1s).

Note: an earlier attempt at this run was built through Claude's
device-bridge shell, whose sandbox proxy returns `403 Forbidden` for
`generativelanguage.googleapis.com`, so Gemini silently fell back to regex
grouping (8 slides). That attempt was discarded and replaced by this
native build - lesson kept: Gemini-dependent builds run in a real
Terminal, same as the render step.

Contains the same layout as `run_3_kokoro_gemini_render/`:
- `KjAI9r8tnOs.txt` - the Step 3 insights text this run was built from
  (identical to run_3's - Step 3 wasn't touched by this refinement pass)
- `composition/KjAI9r8tnOs.html` + `composition/KjAI9r8tnOs_audio/` - the
  exact composition and narration clips that produced the video below
- `video/KjAI9r8tnOs.mp4` - the rendered output

## run_5_map_avatar_presenter/ - first render with the map + avatar slide

Same input path as run_3/run_4 (identical `KjAI9r8tnOs.txt` insights - Step 3
wasn't touched here either), built and rendered natively for the same reason
run_4 was: `slide_planner.py`'s Gemini grouping and the HyperFrames render
both need real network access. The user marked this one as the first
"official" result worth publishing.

What changed vs run_4:
- **Regional map slide** (`map_slide.py`) - Taiwanese cities named in FACTS
  (Taipei, Taichung, Tainan) plotted on a Taiwan county outline
  (`render/vendor/taiwan_map.json`, generated once by `tools/taiwan_map/`),
  each carrying its own mortgage-burden-ratio callout instead of narrating
  the same figures again as bullets on a numbers slide.
- **HeyGen avatar presenter** on that map slide (`tools/heygen_avatar/`) -
  one metered avatar-video generation (avatar `f9204a6247cd41fda5b7a6f20f5c9ca0`
  "Ronan Livingroom 8", voice `02f211a5ef524caea2ad8447e72b218c`), speaking a
  custom single-line script rather than the map's own two narration lines
  verbatim - which is why every callout lights up together for this slide
  instead of the sequential per-city reveal the two-line version gets.
  The post-generation CDN download 403'd on a browser-User-Agent block (not
  an expired signature - confirmed by checking the URL's own `Expires`);
  recovered via `tools/heygen_avatar/resume_download.py` without spending a
  second generation. See `docs/ARCHITECTURE.md` and `docs/DECISIONS.md` for
  the full mechanism and rationale.

8 slides (3 "THE FACTS" + 1 map + 4 "BY THE NUMBERS"), 3:51 runtime (231.2s).

Contains the same layout as `run_3`/`run_4`, plus two additions specific to
this run:
- `KjAI9r8tnOs.txt` - the Step 3 insights text this run was built from
  (identical to run_3/run_4's)
- `composition/KjAI9r8tnOs.html` + `composition/KjAI9r8tnOs_audio/` - the
  exact composition and narration clips that produced the video below
- `composition/KjAI9r8tnOs_assets/04_map_avatar.mp4` - the avatar clip as
  embedded in the composition (picture-in-picture on the map slide)
- `avatar_manifest.json` - the manifest `generate_avatar_clip.py` wrote for
  this run (avatar/voice ids, script, per-line durations) - avatar_clips/
  itself is gitignored (per-video, metered output), so this is the only
  record of which avatar/voice produced this specific clip
- `video/KjAI9r8tnOs.mp4` - the rendered output

## run_6_audio_driven_avatar/ - avatar generation redesigned to be audio-driven

Same input path as every run since run_3 (identical `KjAI9r8tnOs.txt`
insights). What changed here is entirely inside the avatar step
(`tools/heygen_avatar/`), not the rest of the pipeline.

What changed vs run_5:
- **Audio-driven instead of script-driven.** run_5's avatar spoke a custom
  single line, synthesized by HeyGen's own TTS from a `script`+`voice_id`.
  This run instead narrates the map slide's own two lines with the same
  local Kokoro engine every other slide uses, uploads that WAV as a HeyGen
  asset, and drives the avatar from it (`audio_asset_id`, not `script`) -
  so the avatar now says the same two lines, in the same voice, as the rest
  of the video, and the sequential per-city highlight timing (lost in
  run_5's single-line version) is back.
- **New avatar: Aya, not Ronan.** Kokoro's `af_heart` (used throughout the
  whole pipeline) is a female voice; run_5's avatar (`f9204a6247...`,
  "Ronan Livingroom 8") wasn't. This run uses `b4711b78ab3e4f5189519a2f362b7b04`
  ("Aya Office 8", `photo_avatar`, female) instead, so the presenter's voice
  and appearance actually match. Picking it also surfaced that
  `heygen avatar list` returns avatar *groups*, not individual usable
  `avatar_id`s - `heygen avatar looks list --group-id <id>` is the
  subcommand that returns a look's actual `avatar_id`.
- **Two new guardrails shipped and exercised for real**, not just written:
  the idempotency guard (refuses to regenerate without `--force`, since a
  manifest already existed here from run_5) and fail-fast error diagnosis
  (would have caught a billing/credit error before assuming a download
  problem, had one occurred).
- **A second, different download failure - found and fixed.** The download
  403'd again, but not for run_5's reason (a CDN User-Agent block). HeyGen's
  CLI prints its raw JSON with `&` escaped as `\u0026` (a Go JSON encoder
  default); the regex that pulled the download URL out of that raw text
  never JSON-decoded it, so the URL curl received had six literal
  characters (`\u0026`) glued in instead of real `&` separators - the
  server only ever saw the first query parameter, so `Expires`/`Signature`
  never arrived. Fixed in `generate_avatar_clip.py`/`resume_download.py`
  (both now unescape `\uXXXX` sequences before using a URL) rather than
  worked around by hand - see `docs/ARCHITECTURE.md`. The metered call had
  already succeeded before this was hit, so no second generation was spent
  recovering from it, same as run_5's unrelated download failure.

8 slides (3 "THE FACTS" + 1 map + 4 "BY THE NUMBERS" - one more numbers page
than run_5's grouping; Gemini's slide-grouping call isn't deterministic
run-to-run, the content itself didn't change), 4:03 runtime (243.1s) - about
12s longer than run_5's 231.2s, which tracks: the avatar clip now narrates
the full two-line script (19.7s of driving audio) instead of run_5's single
custom line (7.8s).

Same file layout as `run_5`:
- `KjAI9r8tnOs.txt` - Step 3 insights text (identical to every run since run_3)
- `composition/KjAI9r8tnOs.html` + `composition/KjAI9r8tnOs_audio/` - the
  composition and narration clips that produced the video below
- `composition/KjAI9r8tnOs_assets/04_map_avatar.mp4` - the avatar clip as
  embedded in the composition
- `avatar_manifest.json` - includes `"audio_driven": true` and
  `"recovered_from_download_failure": true`, recording both the redesign
  and that this specific clip's download needed `resume_download.py`
- `video/KjAI9r8tnOs.mp4` - the rendered output

Future comparison renders get their own `run_7_...`, `run_8_...` folders
alongside these rather than overwriting any of them, so before/after is
always a diff away rather than a memory.
