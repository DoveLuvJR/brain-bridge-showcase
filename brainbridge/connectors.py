"""Read-only connectors. Each file belongs to exactly one, claimed in this order:

  inbox      <repo>/brain-inbox/YYYY-MM-DD-<project>-<kind>.md  (notes sessions leave behind)
  handoff    HANDOFF / CONTINUATION files                        (the latest real status)
  decisions  DECISIONS / CHANGELOG files                         (what was decided, and when)
  vault      any other markdown note in the vault
  transcripts  AI session transcripts (.jsonl), one record per turn

Nothing here writes to a source. Every text is secret-stripped as a whole before it is
cut into records, and each record is stripped again.
"""
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from .chunk import markdown_records
from .config import Settings, project_key
from .exclude import is_excluded, line_names_protected
from .redact import redact
from .store import Store, norm

INBOX_FOLDER = "brain-inbox"
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv"}
MAX_MARKDOWN_BYTES = 2_000_000


@dataclass
class Context:
    settings: Settings
    store: Store
    today: date
    counters: dict = field(default_factory=dict)  # run-wide counts (excluded_skipped, redactions ...)
    found: dict = field(default_factory=dict)     # connector -> files seen this run
    errors: list = field(default_factory=list)

    def count(self, key: str, n: int = 1):
        self.counters[key] = self.counters.get(key, 0) + n


# ---- which project a path belongs to -------------------------------------------
def _under(path, folder) -> tuple | None:
    """The parts of `path` below `folder`, or None when it is not inside it."""
    p, f = norm(path), norm(folder).rstrip("\\/")
    if p == f:
        return ()
    if not p.startswith(f + os.sep):
        return None
    return tuple(Path(p[len(f) + 1:]).parts)


def project_for(path, settings: Settings) -> str:
    rest = _under(path, settings.projects_dir)
    if rest:
        return settings.canonical(rest[0])
    for root in settings.sources:
        rest = _under(path, root)
        if rest:
            return settings.canonical(rest[0])
    return "vault" if _under(path, settings.vault) is not None else "unknown"


# ---- the walk ------------------------------------------------------------------
def classify(path: Path, settings: Settings) -> str | None:
    name = path.name.casefold()
    if path.parent.name.casefold() == INBOX_FOLDER:
        return "inbox"
    if "handoff" in name or "continuation" in name:
        return "handoff"
    if "decision" in name or "changelog" in name:
        return "decisions"
    if _under(path, settings.vault) is not None:
        return "vault"
    return None


def walk(ctx: Context) -> dict:
    """{connector: [Path]} for every markdown file in the vault and the source folders.
    Excluded folders are pruned before they are entered, so their files are never opened."""
    s = ctx.settings
    never = {norm(s.state_dir), norm(s.digest_out), norm(s.current_md), norm(s.review_md)}
    out = {"inbox": [], "handoff": [], "decisions": [], "vault": []}
    for root in [s.vault, *s.sources]:
        if not root.is_dir():
            ctx.count("missing_roots")
            continue
        for dirpath, dirs, files in os.walk(root):
            keep = []
            for d in dirs:
                full = Path(dirpath) / d
                if d in SKIP_DIRS or norm(full) in never:
                    continue
                if is_excluded(full):
                    ctx.count("excluded_skipped")
                    continue
                keep.append(d)
            dirs[:] = sorted(keep)
            for f in sorted(files):
                full = Path(dirpath) / f
                if not f.lower().endswith(".md") or norm(full) in never:
                    continue
                if is_excluded(full):
                    ctx.count("excluded_skipped")
                    continue
                conn = classify(full, s)
                if conn:
                    out[conn].append(full)
    return out


# ---- markdown ------------------------------------------------------------------
def finish_record(ctx: Context, rec: dict, connector: str, path, project: str) -> dict:
    title, n1 = redact(rec["title"])
    body, n2 = redact(rec["body"])
    ctx.count("redactions", n1 + n2)
    return dict(rec, title=title, body=body, connector=connector, source_path=str(path),
                project=project, project_key=project_key(project))


def index_markdown(ctx: Context, path: Path, connector: str, project: str | None = None) -> str:
    if is_excluded(path):  # belt and braces: the walk already refuses these
        ctx.count("excluded_skipped")
        return "excluded"
    st = path.stat()
    if st.st_size > MAX_MARKDOWN_BYTES:
        ctx.count("too_big")  # keep what is stored; say so in the health check
        return "too_big"
    row = ctx.store.get_file(path)
    if row and row["mtime"] == st.st_mtime and row["size"] == st.st_size:
        return "unchanged"
    data = path.read_bytes()
    sha1 = hashlib.sha1(data).hexdigest()
    if row and row["sha1"] == sha1:
        ctx.store.upsert_file(path, connector, st.st_mtime, st.st_size, sha1)
        return "unchanged"
    project = project or project_for(path, ctx.settings)
    # Strip the whole file first: a secret cut in half by chunking escapes every pattern.
    text, n = redact(data.decode("utf-8", errors="replace"))
    ctx.count("redactions", n)
    records = [finish_record(ctx, r, connector, path, project)
               for r in markdown_records(path, text, st.st_mtime, ctx.today)]
    ctx.store.delete_records(path)
    ctx.store.insert_records(records)
    ctx.store.upsert_file(path, connector, st.st_mtime, st.st_size, sha1)
    return "indexed"


def index_inbox_note(ctx: Context, path: Path) -> str:
    from .inbox import parse
    note = parse(path.read_text(encoding="utf-8", errors="replace"), path, ctx.settings)
    return index_markdown(ctx, path, "inbox", note["project"])


# ---- transcripts ---------------------------------------------------------------
# Protected-folder rule (owner's ruling, which replaced an earlier 3-turn window): if ANY
# line of a session names the protected folder as a path (typed, reply, tool call, tool
# output, or the session's working folder), NONE of that session's turns are indexed. A
# session that names it in a later run loses the records an earlier run stored, and its
# id goes into the permanent quarantine table.
GUARD_VERSION = "session-quarantine-1"  # bump when the rule changes: every session is re-judged
MAX_USER, MAX_REPLY = 3000, 5000
_MESSAGE = re.compile(rb'"type"\s*:\s*"(?:user|assistant)"')
_TOOL_RESULT = re.compile(rb'"type"\s*:\s*"tool_result"')


def transcript_files(settings: Settings) -> list:
    root = settings.transcripts
    return sorted(root.glob("*/*.jsonl")) if root.is_dir() else []


def _text(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text").strip()
    return ""


def parse_turns(data: bytes, offset: int) -> tuple:
    """(turns, end_offset, names_protected, cwd). Every line is checked for the protected
    folder BEFORE anything is parsed, tool calls and tool output included."""
    end = data.rfind(b"\n") + 1
    turns, cur, pos, cwd = [], None, offset, None
    for line in data[:end].splitlines(keepends=True):
        start, pos = pos, pos + len(line)
        if line_names_protected(line):
            return [], offset + end, True, None
        if not _MESSAGE.search(line) or _TOOL_RESULT.search(line):
            continue  # tool output is never indexed
        try:
            d = json.loads(line)
        except ValueError:
            continue
        cwd = d.get("cwd") or cwd
        text = _text((d.get("message") or {}).get("content"))
        if not text:
            continue
        if d.get("type") == "user":
            if cur:
                turns.append(cur)
            cur = {"ts": d.get("timestamp"), "user": text, "replies": [], "start": start}
        elif cur is not None:
            cur["replies"].append(text)
    if cur:
        turns.append(cur)
    return turns, offset + end, False, cwd


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + " …"


def _turn_date(ts, mtime) -> tuple:
    if ts:
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).date().isoformat(), "timestamp"
        except ValueError:
            pass
    return datetime.fromtimestamp(mtime).date().isoformat(), "mtime"


def index_transcript(ctx: Context, path: Path) -> str:
    sid = path.stem
    if ctx.store.is_quarantined(sid):
        ctx.store.delete_records(path)  # out forever, whatever the file does now
        return "quarantined"
    st = path.stat()
    row = ctx.store.get_file(path)
    if row and row["mtime"] == st.st_mtime and row["size"] == st.st_size:
        return "unchanged"
    offset, next_chunk = (row["offset"], row["next_chunk"]) if row else (0, 0)
    if st.st_size < offset:
        # Rewritten, not appended: keep what is stored, read it again from the top, and
        # number the new turns after the old ones.
        offset, next_chunk = 0, ctx.store.max_chunk(path) + 1
    with open(path, "rb") as fh:
        fh.seek(offset)
        data = fh.read()
    turns, end_offset, protected, cwd = parse_turns(data, offset)
    if protected:
        ctx.store.quarantine(sid)
        ctx.store.delete_records(path)  # including turns an earlier run stored
        ctx.store.upsert_file(path, "transcripts", st.st_mtime, st.st_size, offset=end_offset)
        ctx.count("sessions_newly_quarantined")
        return "quarantined"
    if not turns:
        ctx.store.upsert_file(path, "transcripts", st.st_mtime, st.st_size, offset=end_offset, next_chunk=next_chunk)
        return "unchanged"
    project = project_for(cwd, ctx.settings) if cwd else ctx.settings.canonical(path.parent.name)
    records = []
    for i, t in enumerate(turns):
        user, n1 = redact(t["user"])  # strip before clipping, so no cut can split a secret
        reply, n2 = redact("\n\n".join(t["replies"]))
        ctx.count("redactions", n1 + n2)
        d, src = _turn_date(t["ts"], st.st_mtime)
        rec = {"chunk": next_chunk + i, "title": f"Session › {user.splitlines()[0][:100]}",
               "body": f"USER: {_clip(user, MAX_USER)}\n\nASSISTANT: {_clip(reply, MAX_REPLY)}",
               "date": d, "date_source": src}
        records.append(finish_record(ctx, rec, "transcripts", path, project))
    ctx.store.delete_records(path, from_chunk=next_chunk)
    ctx.store.insert_records(records)
    # The cursor sits at the start of the last turn: its reply may still be being written.
    ctx.store.upsert_file(path, "transcripts", st.st_mtime, st.st_size, offset=turns[-1]["start"],
                          next_chunk=next_chunk + len(turns) - 1)
    return "indexed"
