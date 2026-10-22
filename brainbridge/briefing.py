"""Session briefing, run by an AI coding tool's session-start hook.

Prints a short briefing for the project the session started in; the tool adds it to the
new session's context:
  - this project's last real status and its date (HANDOFF, then CHANGELOG / DECISIONS)
  - the date of the last session here (a date only, never transcript text)
  - unfiled brain-inbox notes for this project
  - items from the last 14 days in OTHER projects that mention this one
  - how fresh the index is
In a folder with no project it prints the top rows of CURRENT.md instead.

Safety contract, and every line below serves it:
  - opens the index READ-ONLY and writes nothing;
  - uses only handoff / decisions / vault / inbox records: NO transcript text;
  - drops anything that names the protected folder or sits within 3 sections of it;
  - frames everything as background facts, never instructions (FRAMING);
  - at most MAX_LINES lines, always ending with FOOTER;
  - never blocks a session: on any error, or past DEADLINE_SECONDS, prints NOTHING, exits 0.

Hook command:  python -m brainbridge.briefing --config <config.json>
(the hook passes {"cwd": ...} as JSON on stdin)
"""
import json
import os
import re
import sys
import threading
from datetime import datetime, timedelta

from .config import project_key
from .current import FRAMING, flat, latest_status, unsafe
from .exclude import names_protected
from .store import connect_read_only

DEADLINE_SECONDS = 1.5
MAX_LINES = 40
NEWS_DAYS = 14
MAX_NEWS = 10
BRIEF_CONNECTORS = ("handoff", "decisions", "vault", "inbox")
FOOTER = "For more, search the index (python -m brainbridge search)."


def _status_lines(db, key: str) -> list:
    lines = []
    for label, conns in (("Latest handoff", ("handoff",)), ("Latest changelog / decision", ("decisions",))):
        r = latest_status(db, key, conns)
        if r is None:
            continue
        when = r["date"] + (", file date" if r["date_source"] == "mtime" else "")
        heading = r["title"].split("›")[-1].strip()
        lines.append(f"- {label} ({when}): {flat(heading + ' — ' + r['body'], 200)}")
    last = db.execute("SELECT MAX(date) FROM records WHERE project_key = ? AND connector = 'transcripts'",
                      (key,)).fetchone()[0]
    if last:
        lines.append(f"- Last AI session here: {last}")  # a date only
    return lines


def _inbox_lines(db, key: str) -> list:
    row = db.execute("SELECT value FROM meta WHERE key = 'inbox'").fetchone()
    notes = [e for e in (json.loads(row[0]) if row else [])
             if e["project_key"] == key and not e["filed"] and not e["withheld"]]
    return [f"- {e['date']} · {e['kind']} · {flat(e['headline'], 120)} (inbox, not yet filed)" for e in notes[:4]]


def _news_lines(db, key: str, names: list, today) -> list:
    phrases = ['"' + " ".join(re.findall(r"\w+", n.casefold())) + '"' for n in names if re.search(r"\w", n)]
    if not phrases:
        return []
    marks = ",".join("?" * len(BRIEF_CONNECTORS))
    rows = db.execute(
        f"""SELECT r.* FROM records_fts JOIN records r ON r.id = records_fts.rowid
            WHERE records_fts MATCH ? AND r.project_key != ? AND r.connector IN ({marks}) AND r.date >= ?
            ORDER BY r.date DESC LIMIT 200""",
        ("{title body} : (" + " OR ".join(phrases) + ")", key, *BRIEF_CONNECTORS,
         (today - timedelta(days=NEWS_DAYS)).isoformat())).fetchall()
    out = []
    for r in rows:
        if not unsafe(db, r):
            out.append(f"- {r['date']} · {r['project']} · {flat(r['title'], 110)}")
        if len(out) >= MAX_NEWS:
            break
    return out


def _overview(settings, header: str) -> list:
    text = settings.current_md.read_text(encoding="utf-8")
    section = text.split("## Active projects", 1)[1].split("\n## ", 1)[0]
    table = [ln for ln in section.splitlines() if ln.startswith("|")]
    rows = [ln for ln in table[2:] if not names_protected(ln)]
    return [header, FRAMING, "Top active projects (from CURRENT.md):", *table[:2], *rows[:5]] if rows else []


def project_lines(settings, db, project: str, now: datetime, header: str) -> list:
    """The briefing body for one project (the digest reuses it for projects/<project>.md)."""
    key = project_key(project)
    head = [header, FRAMING, "This project's last real status:"]
    head += _status_lines(db, key) or ["- No HANDOFF / CHANGELOG / DECISIONS found."]
    inbox = _inbox_lines(db, key)
    if inbox:
        head += ["Brain-inbox notes for this project:"] + inbox
    news = _news_lines(db, key, settings.names_for(project), now.date())
    return head + [f"In other projects, last {NEWS_DAYS} days, mentioning {project}:"] + (news or ["- Nothing."])


def build(settings, cwd: str, now: datetime | None = None) -> str:
    """The briefing text, or "" when there is nothing safe to say."""
    from .connectors import project_for
    now = now or datetime.now()
    if not settings.db_path.is_file():
        return ""
    db = connect_read_only(settings.db_path)
    try:
        row = db.execute("SELECT finished FROM runs WHERE finished IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return ""
        freshness = f"index as of {datetime.fromisoformat(row[0]):%Y-%m-%d %H:%M}"
        project = project_for(cwd, settings)
        key = project_key(project)
        known = db.execute(f"SELECT 1 FROM records WHERE project_key = ? AND connector IN "
                           f"({','.join('?' * len(BRIEF_CONNECTORS))}) LIMIT 1", (key, *BRIEF_CONNECTORS)).fetchone()
        if key in ("vault", "unknown") or not known or names_protected(project, cwd):
            lines = _overview(settings, f"Brain Bridge briefing · no project folder · {freshness}")
        else:
            lines = project_lines(settings, db, project, now, f"Brain Bridge briefing · {project} · {freshness}")
        if not lines:
            return ""
        lines = lines[:MAX_LINES - 1]  # the cap: room is always left for the footer
        return "\n".join([flat(ln, 300) if not ln.startswith("|") else ln for ln in lines] + [FOOTER])
    finally:
        db.close()


def main(stdin=None, stdout=None, settings_factory=None, deadline: float = DEADLINE_SECONDS) -> int:
    """Always returns 0. Prints the briefing only if it was built cleanly in time."""
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    box = {}

    def work():
        try:
            raw = "" if stdin is None or stdin.isatty() else stdin.read()
            cwd = (json.loads(raw).get("cwd") if raw.strip() else None) or os.getcwd()
            box["text"] = build(settings_factory(), cwd)
        except BaseException:  # noqa: BLE001 (a briefing must never break a session)
            box["text"] = ""

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    worker.join(deadline)
    text = "" if worker.is_alive() else box.get("text", "")
    if text:
        try:
            stdout.write(text + "\n")
            stdout.flush()
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    from .config import load
    try:
        cfg = sys.argv[sys.argv.index("--config") + 1]
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        code = main(settings_factory=lambda: load(cfg))
    except BaseException:  # noqa: BLE001
        code = 0
    os._exit(code)
