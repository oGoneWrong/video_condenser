# Setup notes

## One-time TTS model download (Kokoro)

Narration uses [Kokoro](https://github.com/thewh1teagle/kokoro-onnx) through
the `hyperframes tts` CLI. The first time `hyperframes tts` runs on a given
machine, it downloads and caches two files for good:

| File | Size | Cached at |
|---|---|---|
| `kokoro-v1.0.onnx` | ~311 MB | `~/.cache/hyperframes/tts/models/kokoro-v1.0.onnx` |
| `voices-v1.0.bin` | ~27 MB | `~/.cache/hyperframes/tts/voices/voices-v1.0.bin` |

That download has no resume support and only a 30-second *idle* timeout, so
on a slow or flaky connection it can look like the pipeline has hung rather
than just downloaded slowly. `build_video.py`'s narration step (see
`generate_narration()`) now has its own timeout and retry so a real failure
surfaces as an error instead of a silent hang - but the very first run on a
new machine can still take several minutes while this downloads.

### Pre-warming the cache

To avoid waiting on this mid-run (or to recover after an interrupted first
download), run once, by hand:

```bash
mkdir -p ~/.cache/hyperframes/tts/models ~/.cache/hyperframes/tts/voices

curl -L --retry 20 --retry-delay 3 --retry-all-errors -C - \
  -o ~/.cache/hyperframes/tts/models/kokoro-v1.0.onnx \
  https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx

curl -L --retry 20 --retry-delay 3 --retry-all-errors -C - \
  -o ~/.cache/hyperframes/tts/voices/voices-v1.0.bin \
  https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
```

The cache check is existence-only (no checksum), so a file placed at the
exact path above is accepted without re-downloading.

These files are **not** committed to this repo - at ~338 MB combined they'd
be well past what's practical for a public git repo without Git LFS (which
brings its own cost tier). This is a one-time local setup step, not part of
the pipeline itself.

If a first attempt is interrupted, a stray `<file>.<pid>.<uuid>.tmp` file can
be left behind in the same cache folders. It's harmless leftover clutter -
safe to delete, and never mistaken for the real cached file (the tool only
ever checks the exact final filename, e.g. `kokoro-v1.0.onnx`).

## Regional map slide (Taiwan county outlines)

The map slide (`map_slide.py`) reads `render/vendor/taiwan_map.json`,
pre-projected SVG outlines of Taiwan's counties. That file is **committed**,
so nothing needs installing to use it. It's regenerated only if you change the
map's size, simplification level or excluded islands. For the packages
involved (`taiwan-atlas`, `topojson-client`, `topojson-simplify`, `d3-geo`,
all free and MIT/ISC licensed) and how to regenerate, see
[`tools/taiwan_map/README.md`](tools/taiwan_map/README.md).

The map slide only appears when the insights support it. It needs at least
two Taiwanese cities named in FACTS, each with a figure in NUMBERS & CONTEXT
matching the configured metric (`MAP_METRIC` in `map_slide.py`, currently
mortgage burden ratio). Those figures are moved onto the map and not repeated
on a "BY THE NUMBERS" slide.

## Optional: HeyGen CLI (avatar presenter / HeyGen voices)

Only needed for the optional avatar presenter on the map slide. Every other
step runs without it.

1. Install the CLI from HeyGen's own instructions:
   <https://developers.heygen.com/cli>, then `heygen update`.
2. Sign in with OAuth: `heygen auth login --oauth`. **Use `--oauth`, not an
   API key.** OAuth draws on the free web-plan allowance. An API key bills API
   credits instead.
3. Check the setup: `cd render && npx hyperframes media-use resolve --doctor`

**Cost note:** HeyGen TTS and avatar video use a **metered free allowance**
(TTS is about 10 min/month per HeyGen's docs; avatar video has its own quota).
That makes them unlike local Kokoro narration, which is unlimited. Nothing in
this pipeline calls HeyGen automatically. Every HeyGen call is a deliberate,
manual step.

Run HeyGen commands in your own terminal. Sandboxed or proxied environments
(like an AI assistant's remote shell) may block `api.heygen.com`, and that
failure looks like an auth error when it isn't one.

### Generating the avatar clip

`tools/heygen_avatar/generate_avatar_clip.py` generates the map slide's
presenter clip. It's **audio-driven**: it narrates the script with the same
local Kokoro voice as every other slide, then hands that real audio to
HeyGen to lip-sync - not a HeyGen-voiced script, so there's no second voice
in the video and no separate "voice id" to look up.

```bash
cd ~/Desktop/video_condenser

# 1. Find an avatar id (free, read-only, two steps - `avatar list` only
#    returns avatar GROUPS, e.g. "Aya" with 30 looks; you need a specific
#    look's id, not the group's):
heygen avatar list --ownership public --limit 5
heygen avatar looks list --group-id <group id from above> --human

# 2. Preview the narration and its real duration WITHOUT spending the
#    avatar allowance (--dry-run stops before the upload and the video call):
python3 tools/heygen_avatar/generate_avatar_clip.py KjAI9r8tnOs --dry-run

# 3. Generate for real (spends 1 avatar-video generation):
python3 tools/heygen_avatar/generate_avatar_clip.py KjAI9r8tnOs \
  --avatar-id <id from step 1>

# 4. Rebuild - it picks up the new avatar_clips/ manifest automatically:
python3 build_video.py KjAI9r8tnOs
```

Re-running step 3 for the same identifier is refused by default (it would
otherwise silently spend a second generation) - pass `--force` if you
actually mean to regenerate. Add `--script "custom line"` to have the
avatar speak one custom line instead of the map slide's own two narration
lines (see the script's own docstring for what that changes about the
highlight timing).

This writes `avatar_clips/<identifier>_map.{json,mp4}` and
`_map_audio.wav` (git-ignored - regenerate rather than commit, same
reasoning as `slides/` and `videos/*.mp4`). Without these files the map
slide just shows a dashed placeholder where the avatar will go and keeps
narrating in Kokoro, so nothing else in the pipeline depends on this step.

If `heygen video create` fails, the script tries to say why rather than
just dumping the error: a billing/plan message (e.g. `plan_upgrade_required`)
is reported as a billing issue, not a bug; a timeout (exit code 4) is
called out explicitly as "the video probably already exists, don't
re-run this" rather than treated as if nothing happened. If only the
*download* fails after a successful (paid) generation - HeyGen's CDN has
been seen to 403 a bare `curl` User-Agent on an otherwise-valid URL - use
`tools/heygen_avatar/resume_download.py <identifier> <url> --avatar-id <id>`
to retry just the download, never the generation itself.
