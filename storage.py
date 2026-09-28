"""
storage.py
Shared save/load helpers for the pipeline. Every stage writes its
output here in the same UTF-8 plain-text format, under a subfolder
named for that stage (transcripts/, insights/, scripts/, ...), keyed
by the same identifier (the YouTube video ID, or local filename) all
the way through. That's what lets each stage be run standalone and
still chain into the next one just by identifier.
"""

from pathlib import Path

BASE_DIR = Path(".")


def save_text(text: str, identifier: str, stage: str) -> str:
    """
    Save text to <stage>/<identifier>.txt (UTF-8).
    e.g. save_text(bullets, "KjAI9r8tnOs", "insights")
         -> insights/KjAI9r8tnOs.txt
    Returns the path it was saved to.
    """
    stage_dir = BASE_DIR / stage
    stage_dir.mkdir(exist_ok=True)
    file_path = stage_dir / f"{identifier}.txt"
    file_path.write_text(text, encoding="utf-8")
    return str(file_path)


def load_text(identifier: str, stage: str) -> str:
    """Read back previously saved text by its identifier and stage."""
    file_path = BASE_DIR / stage / f"{identifier}.txt"
    if not file_path.exists():
        raise FileNotFoundError(f"No saved '{stage}' file for '{identifier}' at {file_path}")
    return file_path.read_text(encoding="utf-8")


# Thin, readable wrappers for the transcript stage specifically -
# existing calls in youtube_transcript.py use these names.
def save_transcript(text: str, identifier: str) -> str:
    return save_text(text, identifier, "transcripts")


def load_transcript(identifier: str) -> str:
    return load_text(identifier, "transcripts")
