"""Post-run audit of what is actually stored, independent of the code path that stored it.

Every run re-scans EVERY stored record. All counts must be zero, or the run is an ALERT
and nothing is published.
"""
import re
from pathlib import Path

from .exclude import is_excluded, line_names_protected
from .redact import find_secrets

_DATE = re.compile(r"^20\d\d-\d\d-\d\d$")


def run_audit(db) -> dict:
    secret = sum(1 for r in db.execute("SELECT title, body FROM records")
                 if find_secrets(r["title"]) or find_secrets(r["body"]))
    excluded = sum(1 for r in db.execute("SELECT DISTINCT source_path FROM records") if is_excluded(r[0]))
    protected = sum(1 for r in db.execute("SELECT title, body FROM records WHERE connector = 'transcripts'")
                    if line_names_protected((r["title"] + "\n" + r["body"]).encode()))
    quarantined = {r[0] for r in db.execute("SELECT session_id FROM quarantine")}
    from_quarantined = sum(n for p, n in db.execute(
        "SELECT source_path, COUNT(*) FROM records WHERE connector = 'transcripts' GROUP BY source_path")
        if Path(p).stem in quarantined)
    undated = sum(1 for r in db.execute("SELECT date FROM records") if not _DATE.match(r[0] or ""))
    result = {
        "secret_shaped_records": secret,
        "excluded_path_records": excluded,
        "protected_folder_transcript_records": protected,
        "quarantined_session_records": from_quarantined,
        "undated_records": undated,
    }
    result["ok"] = not any(result.values())
    return result
