"""
run_pipeline.py
Thin orchestrator chaining the three pipeline stages that turn a
YouTube URL into a rendered composition: youtube_transcript.py ->
extract_insights.py -> build_video.py. Each stage is a real,
independently-runnable script with its own plain sys.argv[1]-based
CLI (see README.md's "Repo layout"), so this just runs them in order
via subprocess - exactly what you'd type by hand, one command at a
time - and stops at the first failure rather than silently continuing
with stale or missing input.

This is NOT a rewrite of the three stages' logic, and doesn't try to
be one. Running each stage yourself still works exactly as documented
in SETUP.md, and is still the way to go when you want to inspect an
intermediate file (the transcript, the extracted insights) before
moving on to the next stage.

Usage:
    python run_pipeline.py <youtube_url> [--slides-only]
"""

import subprocess
import sys
from pathlib import Path


def run_stage(description: str, script_args: list) -> None:
    print(f"\n=== {description} ===")
    result = subprocess.run([sys.executable] + script_args)
    if result.returncode != 0:
        sys.exit(
            f"'{' '.join(script_args)}' failed (exit {result.returncode}) - "
            "stopping here rather than feeding the next stage stale input."
        )


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit("Usage: python run_pipeline.py <youtube_url> [--slides-only]")

    # Imported here, not at module level: youtube_transcript.py pulls in
    # youtube_transcript_api/yt_dlp at import time, so a bad `--slides-only`
    # typo or a bare `--help` gets the plain usage message above instead of
    # an unrelated ImportError traceback if those packages aren't installed.
    from youtube_transcript import extract_video_id

    youtube_url = sys.argv[1]
    slides_only = len(sys.argv) == 3 and sys.argv[2] == "--slides-only"
    identifier = extract_video_id(youtube_url)

    run_stage("Step 1/3: transcript", ["youtube_transcript.py", youtube_url])

    # youtube_transcript.py always exits 0 (it prints a "needs ASR" note
    # rather than raising when it can't get a transcript), so subprocess
    # returncode alone can't tell us whether Step 1 actually produced
    # something to build on - check the file it would have saved instead.
    transcript_path = Path("transcripts") / f"{identifier}.txt"
    if not transcript_path.exists():
        sys.exit(
            f"No transcript was saved to {transcript_path} - Step 1 likely "
            "needs ASR (transcribe_audio.py + ASSEMBLYAI_API_KEY) set up, "
            "or the video has no captions. See its printed output above "
            "for the exact reason."
        )

    run_stage("Step 2/3: insights", ["extract_insights.py", identifier])

    build_args = ["build_video.py", identifier]
    if slides_only:
        build_args.append("--slides-only")
    run_stage(
        "Step 3/3: composition" + (" (slides only)" if slides_only else ""),
        build_args,
    )

    print(f"\nDone. Identifier: {identifier}")
    if not slides_only:
        print(
            "Next: from inside render/, run `npm run check` and\n"
            f"  npx hyperframes render . -c compositions/{identifier}.html "
            f"-o ../videos/{identifier}.mp4 -q draft\n"
            "to produce the MP4 (build_video.py's own output above has "
            "this exact command too)."
        )
