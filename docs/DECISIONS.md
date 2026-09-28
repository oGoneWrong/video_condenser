# Decisions

Written ADR-style — context, the choice made, what else was considered, and
the trade-off accepted. Ordered roughly by pipeline stage.

---

### Extraction over paraphrase, for the non-plagiarism requirement

**Context:** the project requires a "journalistic-style rewrite... without
plagiarism," not a summary.

**Decision:** Step 3 extracts discrete facts into a fixed FACTS /
NUMBERS-&-CONTEXT structure rather than generating rewritten prose.

**Alternatives considered:** a straight LLM paraphrase of the transcript.

**Why extraction wins:** a paraphrase that preserves the transcript's own
sentence order and structure is still derivative even with every word
swapped for a synonym — that's exactly the shallow "paraphraser" pattern
plagiarism detectors are built to catch. Extraction discards the source's
phrasing and structure entirely; what survives is the information, not the
source's words or shape. It also happens to produce exactly the shape Step 4
needs (discrete, one-idea-per-line points for slides), so the anti-plagiarism
choice and the downstream data format aren't in tension.

**Trade-off accepted:** the output reads as a fact sheet, not flowing
narration — intentional, since narration is synthesized separately in Step 4.

---

### Flagging unverified numbers instead of asking the model to "fill gaps"

**Context:** Step 3's prompt asks for additional context a reader would
want (adoption rates, spending figures, etc.) that the transcript itself
doesn't state.

**Decision:** anything not actually in the transcript is written as
`[NOT IN VIDEO - verify externally]: <what to look up and why>`, never as a
number.

**Why:** an LLM asked to "supplement with other reliable sources" with no
actual search tool attached will produce a plausible-sounding number that
may simply be invented. The placeholder keeps every number traceable to the
transcript; external verification is a deliberate, visible action by
whoever runs the pipeline, not something silently inherited from a
hallucination.

**Trade-off accepted:** the insights file is visibly incomplete on
first read (placeholders instead of numbers) — a feature, not a bug, for an
artifact meant to be checked before being trusted.

---

### Local Kokoro TTS over edge-tts / a cloud TTS API

**Context:** narration needs a TTS engine; an earlier version (`run_2`) used
`edge-tts`.

**Decision:** local Kokoro-82M (via `npx hyperframes tts`), no network call
at render time.

**Alternatives considered:** `edge-tts` (used in `run_2_edge_tts_render`,
now superseded).

**Why the switch:** two independent reasons converged on the same choice.
(1) `edge-tts` is an unofficial, reverse-engineered hook into a Microsoft
endpoint — not something a public repo should depend on indefinitely; it
could break for anyone cloning this without warning. (2) it's a network call
that gets silently blocked by locked-down sandbox network allowlists, which
matters when the same script needs to "just work" wherever it's run.

**Trade-off accepted:** a one-time ~340 MB model download on first run
(documented in `SETUP.md`, with its own timeout/retry handling since the
download itself has no resume support) — unlimited and offline after that,
versus zero setup but an unofficial, rate-limited, network-dependent
endpoint.

---

### HyperFrames (HTML → MP4) over Pillow + MoviePy

**Context:** the earliest prototype (`run_1_pillow_prototype`) rendered
static PNG slides with Pillow and stitched them with a hand-guessed
composition format.

**Decision:** author each slide as real, inspectable HTML/CSS, rendered to
MP4 by HyperFrames (headless Chrome + ffmpeg under the hood).

**Why:** a PNG handed to ffmpeg is a black box between "here's the text" and
"here's the pixels" — nothing left to read back or reason about once
rendered. An HTML composition stays text the whole way through, which is
what makes the Step 4 "render every slide standalone, review before adding
audio" checkpoint possible at all. The first Pillow-based attempt also
didn't follow HyperFrames' actual composition contract (no
`data-composition-id`/`data-start`, no registered GSAP timeline) — it was
guessing at a spec rather than reading it, which is a separate reason it
didn't hold up.

**Trade-off accepted:** a heavier toolchain (Chrome + ffmpeg + Node) versus
a pure-Python image pipeline — accepted because the composition also needed
to be inspectable and editable, not just correct once.

---

### Gemini for insight extraction and slide planning, with a hard fallback

**Context:** needed an LLM for extraction (Step 3) and, later, for
smarter fact-grouping/chart-detection (Step 3.5).

**Decision:** Google Gemini free tier for both, same API key, no second
provider.

**Alternatives considered:** Anthropic's Console API (prepaid credits only —
disqualified by the "free tools only" constraint) and, for Step 3.5, a
purely deterministic regex/pagination approach (which is exactly what it
falls back to).

**Why Gemini specifically:** it's the only strong free tier with no card
required. Reusing the same key for Step 3.5 adds no new provider or signup
for anyone cloning the repo — the marginal cost of the smarter grouping call
is "negligible," not "another account to create."

**Why Step 3.5 fails soft but Step 3 doesn't:** Step 3.5 (grouping/charting)
is a refinement of output that already exists in a usable deterministic
form — the regex/pagination path. Step 3 (extraction) has no substitute; if
it fails, there's no fallback insights source, so a missing key there is a
hard stop rather than a silent degrade.

**Trade-off accepted:** two Gemini calls per video instead of one, and a
class of bug that's easy to miss — a call that *degrades* instead of
failing loudly (regex fallback instead of an error) can look like success
while quietly producing a worse deck. Mitigated by logging which path was
taken (`"... responded - slide layout ready."` vs `"... handing off to the
regex-based layout instead."`) rather than making the fallback silent.

---

### Index-based validation in slide_planner.py, not verbatim-text matching

**Context:** the first version of `slide_planner.py` asked Gemini to echo
each bullet back verbatim so Python could verify nothing was dropped, added,
or altered.

**Decision:** Gemini returns which *index* a line belongs to; the displayed
text always comes from Python's own in-memory lists, never from model
output.

**Why:** in practice, the model doesn't reproduce text byte-for-byte even
when explicitly told to (a re-typed dash, a trimmed space) — an
exact-string-equality check against real output raised false "planner
dropped/altered a line" errors on lines that were actually fine. Index-based
matching removes the entire class of failure by never giving the model
anything to get slightly wrong.

---

### Height-based slide packing over fixed item counts

**Context:** the original packer (`chunk_list`) capped each slide at a fixed
number of bullets/charts regardless of how much vertical space they
actually used.

**Decision:** measure each block's real rendered height from CSS metrics
and greedily fill a slide until the next atomic unit would overflow.

**Why:** a fixed count either wastes space (short bullets, half-empty slide)
or clips content (long bullets, same cap). Height-based packing was verified
against real headless-Chromium `getBoundingClientRect()` output before
shipping — checked against the actual renderer, not just estimate math that
could drift from what Chrome actually lays out.

---

### The HeyGen avatar step is manual, never automatic

**Context:** HeyGen's avatar video generation draws on a metered,
real-money-adjacent allowance, unlike every other call in this pipeline
(free tier or fully local).

**Decision:** it lives in its own script
(`tools/heygen_avatar/generate_avatar_clip.py`), never invoked by
`build_video.py`, with a `--dry-run` flag that measures durations and prints
the script without spending the metered call, and explicit cost accounting
printed after every real run.

**Why:** an automatic pipeline that can quietly spend real-money-adjacent
quota on every run is the kind of thing that should never exist by default.
Making the spend a deliberate, visible, single-purpose script run by a human
means the cost is always a choice, never a side effect of re-running the
build.

**A downstream consequence, not a separate decision:** because the metered
call is isolated to one script, a failure *after* it (the CDN download 403
covered in `ARCHITECTURE.md`) can be recovered without re-spending — the
recovery script (`resume_download.py`) reuses the already-generated clip's
URL rather than regenerating it.

---

### Build and render run natively, not through a sandboxed agent shell

**Context:** this pipeline has been built and iterated on with AI-assistant
help, which has its own sandboxed remote shell available.

**Decision:** `build_video.py` (specifically its Gemini-dependent slide
planning) and the HyperFrames render step are run in the user's own native
terminal, not through that sandbox.

**Why:** the sandbox's network allowlist blocks `generativelanguage.googleapis.com`
outright (403), which doesn't fail loudly — it silently degrades Step 3.5 to
its regex fallback, producing a *different, worse* deck with no error
raised. An early comparison run was built this way by mistake, produced 8
slides instead of 7, and was discarded once the cause was found. Requiring
the Gemini-dependent build and the render itself to run natively removes an
entire class of "looks fine, quietly wasn't" failure.

**Trade-off accepted:** less automation during development — someone has to
actually run these two commands themselves rather than letting an assistant
do it end to end. Accepted because the alternative failure mode is silent.

---

### Avatar lip-sync stays on HeyGen, redesigned to be audio-driven (alternatives evaluated, not just assumed)

**Context:** the original avatar step (`generate_avatar_clip.py`) hands HeyGen a
script and a `voice_id` and lets HeyGen's own TTS speak it — which is why the
script also needs a whole measure-then-rescale dance (small HeyGen TTS calls
per line, just to recover proxy timing) to sync the map slide's highlight to
audio HeyGen generates internally. Two separate asks followed from
inspecting this: (1) is there a version of this that takes our *own* audio
(the Kokoro narration already produced for this slide) instead of asking
HeyGen to speak from a script, and (2) given the project's "free tools only"
default, is there a free-or-local alternative to HeyGen for this specific
step at all.

**Decision, part 1 — audio-driven, still HeyGen:** HeyGen's `/v3/videos`
endpoint accepts `audio_url`/`audio_asset_id` in place of `script`+`voice_id`
("Bring your own audio... and lip-sync it onto your avatar... with one API
call" — [developers.heygen.com/audio-to-video](https://developers.heygen.com/audio-to-video)).
Feeding it the map slide's real Kokoro-generated WAV removes the
measure/rescale step entirely — the driving audio's real timing *is* the
ground truth, so there's no proxy to reconcile. **Implemented and verified**
against the installed `heygen` CLI's own `--request-schema` output (not just
the web docs) — `audio_asset_id`/`audio_url` are confirmed present on the
`avatar` variant, "mutually exclusive with script." Uploading a local file
goes through `heygen asset create --file <path>` (confirmed via
`heygen asset create --help`; wav is an explicitly supported type, 32 MB
max). See `generate_avatar_clip.py`'s own docstring for the full rewrite.

Two guardrails shipped alongside the rewrite, from the original ask:
- **Idempotency** — the script now refuses to run for an identifier that
  already has a manifest, unless `--force`, closing the accidental
  double-spend gap the v1 script had no protection against.
- **Fail-fast diagnosis** — `heygen`'s documented CLI exit codes (1=general/
  API error, 2=usage error, 3=auth/permission, 4=timeout) are used to give
  a specific message instead of a raw dump: a billing/plan error is
  reported as one (checked against known marker strings like
  `plan_upgrade_required`), and a timeout is explicitly flagged as "the
  video likely already exists, don't re-run this" — a naive retry-on-any-
  failure policy would have risked a second charge on exactly that case,
  since a `--wait` timeout doesn't mean the underlying generation didn't
  happen.

One thing checked and confirmed harmless: `heygen user me get` ("Account
information and billing") doesn't expose a numeric remaining-credits figure
for the base free plan (only itemizes add-on/premium credits, both empty on
this account) — so a true pre-flight balance check isn't available; the
fail-fast diagnosis above is the practical substitute.

**Exercised for real, not just written:** `run_6_audio_driven_avatar/`
(see `runs/README.md`) is a genuine end-to-end run of this rewrite — a real
metered generation against a new avatar (Aya, swapped in because Kokoro's
`af_heart` voice is female and the run_5 avatar wasn't), a real idempotency
refusal (a manifest already existed from run_5, so the real run needed
`--force`), and a real download failure that turned out to be a second,
different bug from run_5's: HeyGen's CLI prints its JSON output with `&`
escaped as `\u0026`, and the code that pulled the download URL out of that
raw text with a regex never JSON-decoded it, so the URL it curled had
literal `\u0026` sequences instead of real `&` separators — a guaranteed
403 regardless of User-Agent, since the server only ever saw the first
query parameter. Fixed at the source (`extract_result_path()` now
unescapes `\uXXXX` sequences before returning a URL; `resume_download.py`
does the same defensively) rather than worked around by hand, and the
metered call itself wasn't re-spent recovering from it — the guardrail this
entry opened with doing its job on the first real test.

**Decision, part 2 — free/local alternatives evaluated, none clear the bar:**
- **Wav2Lip** — free, audio-driven, runs on CPU or GPU. Its own README
  restricts it to "research/academic/personal purposes only... any form of
  commercial use is strictly prohibited"
  ([Rudrabha/Wav2Lip](https://github.com/Rudrabha/Wav2Lip)). A personal
  interview artifact plausibly qualifies as "personal purposes," but that's
  a license judgment call, not a clean yes — and it would run CPU-only on
  this Mac (no NVIDIA GPU), meaning materially slower and lower quality
  (no head motion, known mouth-region softness) than what's already working.
- **SadTalker** — better quality (adds head motion), but Apple Silicon has
  no working GPU path: PyTorch's MPS backend doesn't support the Conv3D op
  it needs, and the one documented workaround (compiling PyTorch from
  source with a custom patch) is described by users in the issue thread
  itself as "impractical for most users without substantial technical
  expertise" ([SadTalker #526](https://github.com/OpenTalker/SadTalker/issues/526)).
- **MuseTalk** — the cleanest license (MIT, commercial use explicitly
  allowed), genuinely audio-driven, but built and benchmarked against an
  NVIDIA Tesla V100 with no CPU/Apple Silicon path documented
  ([sync.so/blog/what-is-musetalk](https://sync.so/blog/what-is-musetalk)).
- **Sync (sync.so)** — the hosted API Wav2Lip's own authors direct
  commercial users toward. Checked the actual pricing page rather than
  trust secondary summaries claiming a free tier: cheapest plan is
  $5/month + $0.05/sec ([sync.so/pricing](https://sync.so/pricing)), not
  free-no-card.

**Why HeyGen wins anyway:** the constraint isn't "avoid HeyGen at any cost,"
it's "free or local where that's actually viable, cost-aware and gated
where it isn't." Every free/local alternative here trades away something
that matters (legal clarity, hardware compatibility, or actual cost) without
a corresponding win in quality or automation. Confirmed-viable-on-this-machine
lost to marketing-page-viable in every case checked.

**Trade-off accepted:** the avatar step remains a metered, manual,
HeyGen-dependent step — same trade-off as before, now with a verified reason
it isn't worth trying to route around, and (see the next entry) real
guardrails against re-spending it by accident.

---

### YouTube URL as the sole input format

**Context:** the original objectives described "Video to Audio" as step
one, which reads as "accepts a video file." What's actually built accepts a
YouTube URL.

**Decision:** the pipeline assumes a URL as input, end to end. A local video
*file* as input is out of scope for now — confirmed, not an oversight to be
fixed opportunistically.

**Alternatives considered:** building `video_to_audio.py` (referenced in a
couple of docstrings, never implemented) to accept an arbitrary local file
via `ffmpeg -i input -vn audio.wav` feeding straight into
`transcribe_audio.py`'s existing `transcribe()`.

**Why URL-only, for now:** a YouTube URL gets the free, instant captions
path (Step 1's first priority) for most real inputs, which a local file can
never have — it always pays for ASR. Narrowing the demonstrated scope to the
path that's actually free-tier-first end to end is a more defensible
artifact than a half-built second entry point. The `ffmpeg` one-liner above
is a known, trivial bridge if a local file ever needs to go through this
pipeline — deliberately not built preemptively.

**Trade-off accepted:** the pipeline can't be pointed at an arbitrary local
recording without a manual pre-step. Acceptable since every actual use of
this pipeline so far has been a YouTube URL.

---

### Resolved since the first draft of these docs

- **`LICENSE`** — MIT, added, copyright held by Sam_c.
- **`requirements.txt`** — added, aggregated from each stage's own
  docstring (which stays the source of truth if a stage's dependencies
  change).
- **YouTube-URL-only scope** — confirmed as a decision, not a gap; see its
  own entry above.

### Known limitation — the map slide is pattern-matching, not a general "what's chart-worthy" decision

**Context:** `map_slide.py`'s trigger is a single hardcoded keyword match
(`MAP_METRIC["keyword"] = "burden"`) against NUMBERS & CONTEXT labels, and
its entity recognition is a hardcoded list of seven Taiwanese cities
(`CITIES` in `map_slide.py`), matched by literal substring - not general
geo-entity recognition. It works, and degrades safely (no map slide at all,
documented in `ARCHITECTURE.md`) for any video that doesn't happen to
mention one of those seven names. But calling this "the pipeline decides
what's worth mapping" overstates what's actually happening: it decides
what's worth mapping *for this one video*, because it was built by reading
this one video's output backward into a config block, not by reasoning
about the general problem.

**Why this is worth stating plainly rather than leaving as an implicit
gap:** the rest of the pipeline earns real credit for using an LLM to make
judgment calls - fact-grouping, chart-vs-context detection by shared unit
(`slide_planner.py`). The map slide doesn't participate in that reasoning
at all, so it would be dishonest to let it ride on the same
"Gemini-assisted" framing as the rest of Step 3.5's work.

**What a general version would actually need** (not built - this is the
refinement gap, spelled out rather than left vague):
1. **A visualization-type classifier, not just a grouping call.**
   `slide_planner.py` already asks Gemini to group facts and detect
   shared-unit chart candidates in one call, over the same NUMBERS &
   CONTEXT data `map_slide.py` re-scans separately with regex. The natural
   fix is one more field per line in that *same* call: is this line
   `bar_chart` (shares a unit with others, no natural entity axis),
   `geo_map` (values are tied to named places), `time_series` (values are
   tied to points in time - not supported at all today), or `plain_stat`
   (a single number, no natural grouping) - replacing map_slide.py's
   keyword match and build_video.py's separate shared-unit detection with
   one consistent decision instead of two independent heuristics.
2. **Real geo-entity recognition, not a fixed city list.** Even with a
   correct `geo_map` classification, rendering still needs actual boundary
   data for whatever places got named - `CITIES` only works because
   `render/vendor/taiwan_map.json` was pre-generated for exactly these
   seven cities (see `tools/taiwan_map/`). Generalizing means either a
   geocoding step that can turn an arbitrary place name into boundary data
   on demand, or accepting that the map slide stays limited to whatever
   regions have been pre-vendored - entity recognition and available-map-
   data are two separate constraints, not one.
3. **A confidence/fallback check.** An LLM asked "is this chart-worthy"
   will sometimes be wrong in exactly the way a keyword match is currently
   right for the wrong reason - a classification result needs the same
   cheap sanity check that already exists downstream (did the callout step
   actually resolve >= 2 real locations from asset data), not blind trust
   in the model's tag.

**Trade-off accepted for now:** shipping a hardcoded, honestly-labeled
special case for one video beat shipping either nothing, or a half-built
general classifier untested against more than one input. This is the one
piece of the pipeline where "Gemini-assisted" is aspirational rather than
actually implemented, and it's flagged as such rather than left to look
more general than it is.

### Open items (still not decided)

- The map/chart-classification generalization above - a real scope of
  work, not a quick fix, so it stays open rather than half-attempted.
