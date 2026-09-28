"""
generate_avatar_clip.py (v2 - audio-driven)
Manual, cost-aware generator for the map slide's optional HeyGen avatar
presenter. Produces the three files map_slide.load_avatar_manifest() reads:
  avatar_clips/<identifier>_map.json       - manifest
  avatar_clips/<identifier>_map.mp4        - the rendered avatar clip
  avatar_clips/<identifier>_map_audio.wav  - the driving audio (generated
                                              BEFORE the metered call, not
                                              extracted after it - see below)

Deliberately SEPARATE from build_video.py's own build: this is the one step
in the whole pipeline that spends a metered, real-money-adjacent allowance
(HeyGen avatar video) rather than an unlimited local resource (Kokoro) or a
free-tier API call (Gemini). Nothing else calls this automatically - run it
yourself, once per video, only when you've decided the avatar is worth
generating.

Why audio-driven instead of script-driven (v1): v1 handed HeyGen a script
and a voice_id and let HeyGen's own TTS speak it, which meant this script
also had to run a small HeyGen TTS call per line JUST to measure each
line's proxy duration, then rescale those proxies once the real clip
existed - two rounds of indirection to recover timing information Kokoro
already has for free. v2 feeds HeyGen the REAL Kokoro-generated audio
directly: `POST /v3/videos`'s avatar variant accepts `audio_asset_id` /
`audio_url`, explicitly "mutually exclusive with script" - confirmed
against the installed CLI's own --request-schema, not just the web docs.
Result: one voice throughout the whole video (Kokoro, not a second HeyGen
voice for one slide), no proxy measurement or rescaling (the driving
audio's own real, ffprobe'd duration per line IS the ground truth), and no
audio EXTRACTION from the finished clip either (we already have the exact
audio we fed in - HeyGen just lip-syncs a face to it). See
docs/DECISIONS.md's "Avatar lip-sync stays on HeyGen, redesigned to be
audio-driven" for the full evaluation of free/local alternatives that were
considered and ruled out first (Wav2Lip, SadTalker, MuseTalk, Sync) before
landing here.

Run this NATIVELY (your own Mac Terminal), from the repo root - not through
an AI assistant's remote/sandboxed shell. Two reasons: (1) a sandboxed
shell's network allowlist has been observed to block api.heygen.com
outright, so this would just fail there; (2) this step spends money-adjacent
quota, and running it only where you can see it run is the point.

Setup (see SETUP.md's HeyGen section):
    heygen auth login --oauth
    heygen avatar list --ownership public --limit 5
        (copy an avatar_id from here for --avatar-id below, or omit it and
         this script will print that same list and stop, the first time,
         so you can choose)

Usage:
    python3 tools/heygen_avatar/generate_avatar_clip.py <identifier> \
        --avatar-id <id> [--voice af_heart] [--script "custom single line"] \
        [--dry-run] [--force]

    Default (no --script): the avatar reads the map slide's own two
    narration lines verbatim - the sequential per-city highlight keeps
    working exactly as it does for Kokoro (see
    map_slide.build_map_highlight_tweens).
    --script "...": the avatar instead speaks ONE custom line, and every
    callout lights up together for the whole clip instead of one at a time.

What it spends, each run:
  - Kokoro narration for each line - free, local, unlimited (same engine,
    same voice, as every other slide).
  - One `heygen asset create` upload - free (storage, not generation).
  - Exactly ONE HeyGen avatar video generation - the metered call.

Guardrails:
  - Idempotent by default: refuses to run for an identifier that already
    has a manifest (avatar_clips/<id>_map.json), so an accidental re-run
    never silently spends a second generation. Pass --force to override.
  - Fails fast on known billing/quota error text instead of assuming a
    network problem - see diagnose_heygen_error. HeyGen's CLI exit codes
    (documented via `heygen --help`) are 1=general/API error,
    2=usage error, 3=auth/permission error, 4=timeout (the video was
    likely already created despite the timeout - NOT the same as
    "nothing happened", so this case explicitly says not to re-run).
  - The download step uses a browser User-Agent from the start (HeyGen's
    CDN has been observed to 403 curl's bare User-Agent on an otherwise
    valid, unexpired signed URL - see resume_download.py's own history of
    this exact failure).
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from storage import load_text  # noqa: E402
from build_video import parse_sections, generate_narration, VOICE  # noqa: E402
from map_slide import AVATAR_CLIPS_DIR, build_map_slide  # noqa: E402

TMP_DIR = REPO_ROOT / ".video_build_tmp"

# HeyGen's CDN has been seen to 403 curl's default "curl/8.x" User-Agent on
# an otherwise-valid signed URL (bot-protection, not an access error) -
# used from the first attempt now rather than discovered via a failure.
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

# Substrings HeyGen has been observed to use in billing/quota errors -
# checked case-insensitively against combined stdout+stderr so a metered
# failure is reported as what it is, not chased as a network bug. Extend
# this list if a new billing error shape shows up.
BILLING_ERROR_MARKERS = [
    "plan_upgrade_required", "insufficient_credit", "insufficient credits",
    "payment_required", "quota_exceeded", "out of credits",
]

VIDEO_URL_RE = re.compile(r"https?://[^\s\"'<>]+\.mp4[^\s\"'<>]*")


def unescape_json_url(url: str) -> str:
    """
    `heygen video create --wait` prints its raw stdout, not re-encoded
    JSON - so a URL that contains a JSON-escaped `\u0026` (the HeyGen
    CLI, like most Go JSON encoders, escapes `&` this way by default)
    comes through extract_result_path() with those six literal
    characters still in it, not a real `&`. A URL like that curls fine
    syntactically but is silently wrong: the server only ever sees the
    first query param, so Expires/Signature never arrive - which reads
    as a plain 403, indistinguishable from a bot-blocked or expired URL
    unless you go looking for `\\u0026` in the raw text (see
    resume_download.py's earlier, unrelated 403 - this is a second,
    different way to get the same symptom). Only `\\uXXXX` escapes are
    touched here, so a URL with no such escape is returned unchanged.
    """
    return re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), url)


def die(message: str, code: int = 1):
    print(f"✗ {message}", file=sys.stderr)
    sys.exit(code)


def run(cmd: list, **kwargs) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}", file=sys.stderr)
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def get_map_narration_lines(identifier: str) -> list:
    """
    The map slide's own narration_lines, via the SAME extraction
    build_video.py's real deck uses (map_slide.build_map_slide) - never
    hand-typed here, so the avatar always reads exactly what the video
    would otherwise have shown as text.
    """
    insights_text = load_text(identifier, "insights")
    sections = parse_sections(insights_text)
    slide, _ = build_map_slide(sections["facts"], sections["numbers"], None)
    if slide is None:
        die(f"No map slide for {identifier!r} - nothing to generate an avatar for.")
    return slide["narration_lines"]


def synthesize_driving_audio(lines: list, voice: str, out_path: Path) -> list:
    """
    Generates each line's real Kokoro narration (free, local, same engine
    every other slide uses via build_video.generate_narration), concatenates
    them into one WAV via ffmpeg's concat demuxer (same technique
    build_composition() uses per-slide), and returns each line's own real,
    ffprobe'd duration. No proxy measurement, no rescaling needed - this
    already IS the ground truth audio and its real timing.
    """
    TMP_DIR.mkdir(exist_ok=True)
    clip_paths = []
    durations = []
    for i, line in enumerate(lines):
        clip_path = TMP_DIR / f"_avatar_line_{i}.wav"
        print(f"Narrating line {i + 1}/{len(lines)} via Kokoro...", file=sys.stderr)
        generate_narration(line, str(clip_path), voice=voice)
        probe = run(["ffprobe", "-v", "quiet", "-print_format", "json",
                     "-show_format", str(clip_path)])
        durations.append(float(json.loads(probe.stdout)["format"]["duration"]))
        clip_paths.append(clip_path)

    if len(clip_paths) == 1:
        clip_paths[0].rename(out_path)
    else:
        concat_list = TMP_DIR / "_avatar_concat.txt"
        concat_list.write_text(
            "\n".join(f"file '{p.resolve()}'" for p in clip_paths), encoding="utf-8"
        )
        cat = run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                   "-i", str(concat_list), "-c", "copy", str(out_path)])
        if cat.returncode != 0:
            die(f"ffmpeg concat failed: {cat.stderr}")
        concat_list.unlink(missing_ok=True)
        for p in clip_paths:
            p.unlink(missing_ok=True)

    return durations


def upload_audio_asset(audio_path: Path) -> str:
    """
    `heygen asset create --file <path>` - free (storage, not generation).
    Returns the asset_id parsed from the JSON response. The exact response
    shape isn't pinned down in the CLI's own --help beyond "returns an
    asset_id" - this checks a few plausible key paths rather than assuming
    one, same philosophy as extract_result_path below for the video-create
    response. If none match, the raw response is surfaced so the parser can
    be fixed against the real shape.
    """
    print(f"Uploading driving audio ({audio_path.name}) to HeyGen...", file=sys.stderr)
    r = run(["heygen", "asset", "create", "--file", str(audio_path)])
    if r.returncode != 0:
        die(f"heygen asset create failed:\n{r.stdout}\n{r.stderr}")
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        die(f"Couldn't parse asset upload response as JSON:\n{r.stdout}")
    asset_id = (
        data.get("asset_id") or data.get("id")
        or (data.get("data") or {}).get("asset_id")
        or (data.get("data") or {}).get("id")
    )
    if not asset_id:
        die(
            "Uploaded, but couldn't find an asset_id in the response - paste "
            f"this back so the parser can be fixed:\n{r.stdout}"
        )
    return asset_id


def diagnose_heygen_error(returncode: int, stdout: str, stderr: str) -> str:
    """
    Turns a failed `heygen video create` into an actionable message instead
    of a raw dump - distinguishes a billing/quota problem (fail fast, don't
    retry blindly) from everything else, using HeyGen's documented CLI exit
    codes (from `heygen --help`): 1=general/API error, 2=usage error (our
    own bad params), 3=auth/permission error, 4=timeout - the video was
    likely already created despite the timeout (this is NOT the same as
    "nothing happened"), so re-running would risk a second paid generation.
    """
    combined = f"{stdout}\n{stderr}".lower()
    if any(marker in combined for marker in BILLING_ERROR_MARKERS):
        return (
            "HeyGen reports a billing/plan limit, not a bug here - check "
            "your plan/credits at https://app.heygen.com before retrying "
            f"anything (exit code {returncode}):\n{stdout}\n{stderr}"
        )
    if returncode == 3:
        return (
            "HeyGen auth/permission error - check `heygen auth login --oauth` "
            f"and re-run:\n{stdout}\n{stderr}"
        )
    if returncode == 4:
        return (
            "HeyGen timed out waiting for the video to finish. IMPORTANT: the "
            "video was likely already created (the metered call is spent "
            "regardless of the --wait timeout), it just isn't ready yet. "
            "Check `heygen video list --limit 5` for it rather than "
            "re-running this script, which would risk spending a second "
            f"generation:\n{stdout}\n{stderr}"
        )
    return f"heygen video create failed (exit {returncode}):\n{stdout}\n{stderr}"


def extract_result_path(stdout: str) -> str:
    """
    `heygen video create --wait` prints its result, exact shape not fully
    pinned down - so this looks for either a downloadable URL or an
    existing local file path in the output, rather than assuming a
    specific JSON schema. If neither is found the raw output is surfaced
    so the pattern can be fixed here, rather than guessed at.
    """
    m = VIDEO_URL_RE.search(stdout)
    if m:
        return unescape_json_url(m.group(0))
    for token in re.findall(r"\S+\.mp4\b", stdout):
        if Path(token).exists():
            return token
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("identifier")
    ap.add_argument("--avatar-id", default=None,
                     help="HeyGen avatar id - see `heygen avatar list --ownership public --limit 5`. "
                          "Omit once to have this script print that list and stop.")
    ap.add_argument("--voice", default=VOICE,
                     help=f"Kokoro voice for the driving narration (default: {VOICE!r}, "
                          "same voice every other slide uses).")
    ap.add_argument("--script", default=None,
                     help="A custom single line for the avatar to speak, replacing the "
                          "map slide's own two verbatim narration lines - see "
                          "map_slide.build_map_highlight_tweens for the highlight-timing "
                          "effect this has.")
    ap.add_argument("--dry-run", action="store_true",
                     help="Generate and measure the driving audio, then stop BEFORE "
                          "the metered avatar video call (and before uploading anything).")
    ap.add_argument("--force", action="store_true",
                     help="Regenerate even if a manifest already exists for this "
                          "identifier (normally refused, to avoid an accidental "
                          "second metered generation).")
    args = ap.parse_args()

    manifest_path = AVATAR_CLIPS_DIR / f"{args.identifier}_map.json"
    if manifest_path.exists() and not args.force:
        die(
            f"{manifest_path} already exists - refusing to spend another metered "
            "avatar generation for an identifier that already has one. Pass "
            "--force if you actually mean to regenerate it.", code=0,
        )

    if not args.avatar_id:
        print("No --avatar-id given - listing public avatars (free, read-only):\n", file=sys.stderr)
        r = run(["heygen", "avatar", "list", "--ownership", "public", "--limit", "5"])
        print(r.stdout or r.stderr)
        die("Pick an avatar id from above and re-run with --avatar-id <id>.", code=0)

    if args.script:
        lines = [args.script]
        print(f"Custom avatar script (overriding the map slide's own narration):\n  - {args.script}",
              file=sys.stderr)
    else:
        lines = get_map_narration_lines(args.identifier)
        print(f"Map slide narration ({len(lines)} line(s)):", file=sys.stderr)
        for line in lines:
            print(f"  - {line}", file=sys.stderr)

    AVATAR_CLIPS_DIR.mkdir(exist_ok=True)
    video_path = AVATAR_CLIPS_DIR / f"{args.identifier}_map.mp4"
    audio_path = AVATAR_CLIPS_DIR / f"{args.identifier}_map_audio.wav"

    line_durations = synthesize_driving_audio(lines, args.voice, audio_path)
    real_total = sum(line_durations)

    if args.dry_run:
        print(f"\n--dry-run: driving audio written to {audio_path} "
              f"({real_total:.2f}s across {len(lines)} line(s)) - stopping "
              "before the metered avatar video call.")
        print(f"Per-line durations: {[round(d, 3) for d in line_durations]}")
        return

    # Persisted so resume_download.py can recover per-line timing if THIS
    # process dies after the metered call but before writing the manifest
    # (e.g. the download 403s) - the audio file alone only gives the total.
    durations_sidecar = TMP_DIR / f"_avatar_{args.identifier}_line_durations.json"
    durations_sidecar.write_text(json.dumps(line_durations), encoding="utf-8")

    audio_asset_id = upload_audio_asset(audio_path)

    body = json.dumps({
        "type": "avatar",
        "avatar_id": args.avatar_id,
        "audio_asset_id": audio_asset_id,
        "resolution": "720p",
    })
    print("\nRequesting avatar video (this is the metered call)...", file=sys.stderr)
    r = run(["heygen", "video", "create",
             "--headers", "X-HeyGen-Client-Source: media-use",
             "--wait", "-d", body])
    if r.returncode != 0:
        die(diagnose_heygen_error(r.returncode, r.stdout, r.stderr))

    result = extract_result_path(r.stdout)
    if not result:
        die(
            "Couldn't find a downloadable URL or local file path in the "
            "`heygen video create` output below - paste this back so the "
            f"parser can be fixed:\n\n{r.stdout}\n{r.stderr}"
        )

    if result.startswith("http"):
        print(f"Downloading {result} ...", file=sys.stderr)
        dl = run(["curl", "-L", "-f", "-A", BROWSER_UA, "-o", str(video_path), result])
        if dl.returncode != 0:
            die(
                f"Download failed even with a browser User-Agent: {dl.stderr}\n\n"
                "The metered generation already succeeded - do NOT re-run this "
                "script (that would risk a second charge). Instead run:\n"
                f"  python3 tools/heygen_avatar/resume_download.py {args.identifier} "
                f"'{result}' --avatar-id {args.avatar_id}"
            )
    else:
        shutil.copyfile(result, video_path)

    manifest = {
        "identifier": args.identifier,
        "avatar_id": args.avatar_id,
        "voice": args.voice,
        "script": " ".join(lines),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "video_path": f"avatar_clips/{video_path.name}",
        "audio_path": f"avatar_clips/{audio_path.name}",
        "line_durations": [round(d, 3) for d in line_durations],
        "total_duration": round(real_total, 3),
        "audio_driven": True,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    durations_sidecar.unlink(missing_ok=True)

    print(f"\n✓ Wrote {manifest_path}, {video_path}, {audio_path}")
    print(f"  Total clip duration: {real_total:.2f}s across {len(lines)} line(s).")
    print(
        "\nCost summary: Kokoro narration (free) + 1 asset upload (free) + "
        "1 HeyGen avatar video generation (metered - check your HeyGen "
        "dashboard for remaining allowance)."
    )
    print(
        "\nNext: re-run the pipeline's own build "
        f"(python3 build_video.py {args.identifier}) - it will pick this "
        "manifest up automatically and use it instead of Kokoro for the "
        "map slide, then render as usual."
    )


if __name__ == "__main__":
    main()
