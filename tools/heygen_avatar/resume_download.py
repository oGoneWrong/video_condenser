"""
resume_download.py (v2 - matches the audio-driven generate_avatar_clip.py)
Recovery step for when the METERED avatar video call already succeeded
(HeyGen already synthesized the lip-synced clip) but the download that
follows it failed - e.g. curl exiting with a bare "403" even with a
browser User-Agent already applied. Does NOT call `heygen video create`
again, so it never spends a second avatar generation.

Since v2's avatar generation is audio-driven, the driving audio was
generated and saved as avatar_clips/<identifier>_map_audio.wav BEFORE the
metered call ever ran - so, unlike v1, there's no per-line duration to
remeasure and no audio to extract from the finished clip. This script only
retries the download and writes the manifest, using the audio and (if the
failed run got far enough to write it) the per-line duration sidecar
that's already on disk.

Where to get <url>: generate_avatar_clip.py printed a line right before the
failed download - "Downloading <url> ..." - scroll up in the same
terminal to find it. If that's scrolled out of view, `heygen video list
--limit 5` is free and read-only and will show the same clip so you can
re-resolve its URL without generating anything new.

Usage:
    python3 tools/heygen_avatar/resume_download.py <identifier> <url> \
        --avatar-id <id> [--script "custom single line"]

    --avatar-id and --script are only recorded in the manifest for the
    record (matching what the original call used) - they don't affect the
    download itself.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

# Reuses generate_avatar_clip.py's own helpers rather than duplicating
# them, so this stays in sync with any future change there.
from generate_avatar_clip import (  # noqa: E402
    run, die, BROWSER_UA, get_map_narration_lines, TMP_DIR, unescape_json_url,
)
from map_slide import AVATAR_CLIPS_DIR  # noqa: E402


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("identifier")
    ap.add_argument(
        "url", help="The .mp4 URL generate_avatar_clip.py printed before the failed download"
    )
    ap.add_argument("--avatar-id", required=True,
                     help="Only recorded in the manifest - doesn't affect the download.")
    ap.add_argument("--script", default=None)
    args = ap.parse_args()
    # Defensive: a URL hand-copied out of `heygen video list`'s raw JSON
    # (rather than piped through a JSON parser) can still carry literal
    # `\u0026` escapes instead of `&` - see unescape_json_url()'s docstring
    # in generate_avatar_clip.py. Re-running it here is a no-op on an
    # already-clean URL.
    args.url = unescape_json_url(args.url)

    video_path = AVATAR_CLIPS_DIR / f"{args.identifier}_map.mp4"
    audio_path = AVATAR_CLIPS_DIR / f"{args.identifier}_map_audio.wav"

    if not audio_path.exists():
        die(
            f"{audio_path} doesn't exist - this recovery script expects the "
            "driving audio generate_avatar_clip.py already wrote before "
            "making the metered call. If it's genuinely missing, don't just "
            "re-run generate_avatar_clip.py - that would spend a second "
            "generation for a clip that already exists on HeyGen's side. "
            "Recover the audio first (it's identical to what's embedded in "
            "the finished clip, so extracting it from the video once "
            "downloaded is also an option: ffmpeg -i <video> -vn <audio.wav>)."
        )

    print(f"Re-attempting download with a browser User-Agent:\n  {args.url}", file=sys.stderr)
    dl = run(["curl", "-L", "-f", "-A", BROWSER_UA, "-o", str(video_path), args.url])
    if dl.returncode != 0:
        die(
            "Download still failing even with a browser User-Agent - this "
            "points to the signed URL itself (expired or scoped narrowly) "
            f"rather than a UA block:\n{dl.stderr}\n\n"
            "Re-resolve a fresh URL with `heygen video list --limit 5` and "
            "re-run this script with that URL. Still spends no additional "
            "avatar generation - the clip already exists on HeyGen's side."
        )

    probe = run(["ffprobe", "-v", "quiet", "-print_format", "json",
                 "-show_format", str(audio_path)])
    real_total = float(json.loads(probe.stdout)["format"]["duration"])

    lines = [args.script] if args.script else get_map_narration_lines(args.identifier)

    # Recover per-line timing from the sidecar generate_avatar_clip.py
    # wrote before the metered call, if it's still there. Falls back to an
    # even split (matching the old rescale_durations' degenerate case) only
    # if that sidecar is gone - a fallback, not the normal path.
    sidecar = TMP_DIR / f"_avatar_{args.identifier}_line_durations.json"
    if sidecar.exists():
        line_durations = json.loads(sidecar.read_text(encoding="utf-8"))
        sidecar.unlink(missing_ok=True)
    else:
        print(
            f"Note: {sidecar} not found - falling back to an even split "
            "across lines for line_durations (cosmetic only; total_duration "
            "below is still the real measured value).",
            file=sys.stderr,
        )
        line_durations = [real_total / len(lines)] * len(lines)

    manifest = {
        "identifier": args.identifier,
        "avatar_id": args.avatar_id,
        "script": " ".join(lines),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "video_path": f"avatar_clips/{video_path.name}",
        "audio_path": f"avatar_clips/{audio_path.name}",
        "line_durations": [round(d, 3) for d in line_durations],
        "total_duration": round(real_total, 3),
        "audio_driven": True,
        "recovered_from_download_failure": True,
    }
    manifest_path = AVATAR_CLIPS_DIR / f"{args.identifier}_map.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"\n✓ Recovered {manifest_path}, {video_path}, {audio_path}")
    print(f"  Total clip duration: {real_total:.2f}s across {len(lines)} line(s).")
    print(f"\nNext: python3 build_video.py {args.identifier}")


if __name__ == "__main__":
    main()
