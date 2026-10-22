"""The only door through which the pipe writes a file into the vault.

Ruling: the pipe never edits a human-written note. It may write exactly two generated
files: CURRENT.md (the hourly briefing) and inbox/INBOX-REVIEW.md (the weekly review).
Every other path is refused, so a bug elsewhere cannot become an edit of a real note.
"""
import os
from pathlib import Path

from .store import norm


class VaultWriteRefused(PermissionError):
    pass


def write(settings, path: Path, text: str):
    """Atomic write (temp file + replace) of one of the two allowed files."""
    if norm(path) not in {norm(settings.current_md), norm(settings.review_md)}:
        raise VaultWriteRefused(f"the pipe may not write {path} (only CURRENT.md and the inbox review)")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
