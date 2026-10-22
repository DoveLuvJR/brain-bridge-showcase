"""Hard exclusions and the protected-folder rules.

These are rulings, not settings: they live in code so that editing the config can never
switch them off. Matching ignores case, slash direction and the trailing dots/spaces
Windows ignores.

PROTECTED_FOLDER holds third parties' personal data (in the real system, people a
client asked us to work with). Three layers keep it out:
  1. its files are never read (is_excluded);
  2. any AI session that names it, anywhere, is quarantined whole (line_names_protected);
  3. anything SHOWN to a reader is dropped if it, or a section within NEARBY_SECTIONS of
     it, mentions the folder (names_protected / near_protected).
"""
import re
from pathlib import PureWindowsPath

PROTECTED_FOLDER = "protected-people"

_EXCLUDED_DIRS = {PROTECTED_FOLDER, ".ssh"}
_EXCLUDED_NAMES = {".credentials.json", "secrets.conf", "id_rsa", "id_ed25519"}

# A transcript line that names the protected folder as a path: typed, in a reply, in a
# tool call, in tool output, or as the session's working folder.
_PROTECTED_RAW = re.compile(rb"(?i)[\\/]" + re.escape(PROTECTED_FOLDER.encode()) + rb"(?:[\\/\"'`\s]|$)")
NEARBY_SECTIONS = 3


def _parts(path) -> tuple:
    return tuple(p.casefold().rstrip(" .") or p.casefold() for p in PureWindowsPath(str(path)).parts)


def is_excluded(path) -> bool:
    parts = _parts(path)
    if not parts:
        return False
    name = parts[-1]
    if name.startswith(".env") or name.startswith("secrets") or name in _EXCLUDED_NAMES:
        return True
    return any(p in _EXCLUDED_DIRS for p in parts)


def line_names_protected(raw: bytes) -> bool:
    return bool(_PROTECTED_RAW.search(raw))


def names_protected(*texts) -> bool:
    """Stricter test for anything shown to a reader: the name anywhere, path or not."""
    return any(PROTECTED_FOLDER in (t or "").casefold() for t in texts)


def near_protected(db, source_path: str, chunk: int) -> bool:
    """True when this record, or any record within NEARBY_SECTIONS of it in the same
    file, mentions the protected folder. A neighbouring section can talk about the same
    people without naming the folder."""
    if names_protected(source_path):
        return True
    rows = db.execute("SELECT title, body FROM records WHERE source_path = ? AND chunk BETWEEN ? AND ?",
                      (source_path, chunk - NEARBY_SECTIONS, chunk + NEARBY_SECTIONS))
    return any(names_protected(r[0], r[1]) for r in rows)
