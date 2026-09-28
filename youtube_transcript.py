"""
youtube_transcript.py
Entry point for the pipeline when the input is a YouTube URL instead of
a local video file.

Strategy (in priority order):
  1. Pull YouTube's own transcript (creator-uploaded or auto-generated
     captions) - free, instant, zero audio processing.
  2. If no captions exist, extract ONLY the audio stream (not the full
     video) into a temp directory that auto-deletes itself, hand that
     off to Step 2's ASR call, and never persist the file.

Note: yt-dlp can resolve YouTube's direct CDN audio URL without
downloading at all, which sounds like the "true" zero-download path -
but that URL is usually IP-locked to whoever requested it, so handing
it straight to a cloud ASR API (different IP) tends to 403. The temp-file
approach below is the reliable version of "don't keep the video around."

Install:
    pip install youtube-transcript-api yt-dlp
"""

import re
import sys
import tempfile
from pathlib import Path

from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound


def extract_video_id(url: str) -> str:
    """Pull the 11-character video ID out of common YouTube URL formats."""
    patterns = [
        r"(?:v=|\/)([0-9A-Za-z_-]{11}).*",
        r"youtu\.be\/([0-9A-Za-z_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    raise ValueError(f"Couldn't parse a video ID out of: {url}")


def get_existing_transcript(video_id: str):
    """
    Try YouTube's own captions first. Returns None if unavailable.

    Supports both the old (<=0.6) classmethod API and the new (>=1.0)
    instance-based API, since we don't control which version is
    installed on the machine running this.
    """
    try:
        if hasattr(YouTubeTranscriptApi, "get_transcript"):
            # old API: classmethod returning a list of dicts
            segments = YouTubeTranscriptApi.get_transcript(video_id)
            return " ".join(segment["text"] for segment in segments)
        else:
            # new API: instance method returning a FetchedTranscript object
            fetched = YouTubeTranscriptApi().fetch(video_id)
            return " ".join(segment["text"] for segment in fetched.to_raw_data())
    except (TranscriptsDisabled, NoTranscriptFound):
        return None


def extract_audio_to_temp(url: str, temp_dir: str) -> str:
    """
    Pull just the audio stream into a temp directory. Caller owns the
    directory's lifecycle (see get_transcript below, which wraps this in
    a `with tempfile.TemporaryDirectory()` block so it's deleted
    automatically once the ASR call is done with it).
    """
    import yt_dlp

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": f"{temp_dir}/%(id)s.%(ext)s",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "wav",
            "preferredquality": "192",
        }],
        "quiet": True,
        # YouTube's default web client is the one most often hit by
        # innertube bot-checks (shows up as a bare "HTTP Error 403:
        # Forbidden" on download). The android client is currently the
        # more stable path per yt-dlp maintainers. If this ever starts
        # failing again, the fix is usually: `pip install -U yt-dlp`
        # first (YouTube changes frequently), then revisit this list.
        "extractor_args": {
            "youtube": {"player_client": ["android"]},
        },
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return str(Path(temp_dir) / f"{info['id']}.wav")


def get_transcript(url: str, asr_function=None) -> dict:
    """
    Main entry point. If captions exist, returns them directly.
    If not, extracts audio into a self-deleting temp dir and - if you
    pass in Step 2's ASR function - calls it before the temp file
    disappears. Without an asr_function, it just tells you a fallback
    would be needed, so you can wire it in once Step 2 exists.
    """
    video_id = extract_video_id(url)

    transcript_text = get_existing_transcript(video_id)
    if transcript_text:
        return {"source": "youtube_captions", "text": transcript_text}

    with tempfile.TemporaryDirectory() as temp_dir:
        audio_path = extract_audio_to_temp(url, temp_dir)
        if asr_function is None:
            return {
                "source": "needs_asr",
                "text": None,
                "note": "No captions found. Pass an asr_function to transcribe via Step 2.",
            }
        text = asr_function(audio_path)
        return {"source": "asr_fallback", "text": text}
    # temp_dir and its contents are deleted here automatically


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python youtube_transcript.py <youtube_url>")

    # Step 2 now exists, so wire it in as the fallback ASR function.
    # If transcribe_audio.py or its ASSEMBLYAI_API_KEY isn't set up yet,
    # fall back to the "needs_asr" stub rather than crashing, so this
    # script still works standalone.
    try:
        from transcribe_audio import transcribe as asr_function
    except (ImportError, RuntimeError):
        asr_function = None

    result = get_transcript(sys.argv[1], asr_function=asr_function)
    if result["text"]:
        from storage import save_transcript
        video_id = extract_video_id(sys.argv[1])
        saved_path = save_transcript(result["text"], video_id)
        print(f"[{result['source']}] Saved to {saved_path}")
        print(f"\n{result['text'][:500]}...")
    else:
        print(result["note"])
