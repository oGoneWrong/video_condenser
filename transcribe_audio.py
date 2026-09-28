"""
transcribe_audio.py
Step 2 of the pipeline: audio -> transcript text, via AssemblyAI's
managed API.

Design note: this exposes a single function, transcribe(audio_path),
with the signature (path: str) -> str. That's deliberate - it's the
exact shape youtube_transcript.py's get_transcript(url, asr_function=...)
expects, and it's what video_to_audio.py's output feeds into for local
files. Same function, two entry points into the pipeline.

Setup:
    1. Sign up free at https://www.assemblyai.com/ and grab an API key
       from the dashboard.
    2. pip install assemblyai python-dotenv
    3. Copy .env.example to .env and fill in your real key.
       .env is UTF-8 plain text (KEY=VALUE), gitignored so the real
       key never gets committed - only .env.example (the template,
       no real key) is meant to be checked in.

Usage:
    python transcribe_audio.py path/to/audio.wav
"""

import os
import sys

import assemblyai as aai
from dotenv import load_dotenv

load_dotenv()  # reads .env in the current directory into os.environ, if present


def transcribe(audio_path: str, api_key: str = None) -> str:
    """
    Send an audio file to AssemblyAI and return the transcript text.

    AssemblyAI's SDK handles the upload + poll-until-done loop
    internally (transcriber.transcribe() blocks until the job finishes),
    so this stays a single call rather than us hand-rolling the
    upload/poll/fetch cycle ourselves.
    """
    key = api_key or os.environ.get("ASSEMBLYAI_API_KEY")
    if not key:
        raise RuntimeError(
            "No API key found. Set the ASSEMBLYAI_API_KEY environment "
            "variable, or pass api_key= directly."
        )

    aai.settings.api_key = key

    transcriber = aai.Transcriber()
    transcript = transcriber.transcribe(audio_path)

    if transcript.status == aai.TranscriptStatus.error:
        raise RuntimeError(f"Transcription failed: {transcript.error}")

    return transcript.text


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python transcribe_audio.py <audio_file>")

    text = transcribe(sys.argv[1])
    print(text)
