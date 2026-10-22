"""The brain inbox: how sessions (local or cloud) write back without touching the vault.

A session that makes a decision, fixes a hard bug or ends a batch drops a note in its
repo's brain-inbox/ folder:

    ---
    project: Project A
    date: 2026-10-21
    kind: decision          # decision | changelog | lesson
    source: local           # local | cloud
    ---
    Three to ten plain-English lines: what happened, why, where the proof is.

The pipe indexes the notes and lists the unfiled ones in one weekly review file. A human
files them (pastes the text into the project's DECISIONS / CHANGELOG / LESSONS file). A
note counts as FILED once its text appears in that target file.

Notes are UNTRUSTED (a cloud session can write one), so:
  - the header's project is accepted only if it names a real project, else the repo's own
    project is used and the problem is listed; it later becomes part of a path;
  - header values are secret-stripped and length-capped;
  - notes that mention the protected folder are listed by path only ("withheld").
"""
import re
from pathlib import Path

from .chunk import split_frontmatter
from .config import project_key
from .exclude import names_protected
from .redact import redact

TARGETS = {"decision": "DECISIONS.md", "changelog": "CHANGELOG.md", "lesson": "LESSONS.md"}
KINDS = tuple(TARGETS)
SOURCES = ("local", "cloud")
MIN_FILED_CHARS = 40  # shorter notes ("ok") would match almost any file and vanish unfiled
FILENAME = re.compile(r"^(20\d\d-\d\d-\d\d)-(.+)-(decision|changelog|lesson)(?:-\d+)?\.md$", re.I)
_FIELD = re.compile(r"(?im)^\s*(project|date|kind|source)\s*:\s*['\"]?([^'\"#\r\n]*?)['\"]?\s*(?:#.*)?$")
_UNSAFE = re.compile(r"[\\/:*?\"<>|]|\.\.")


def known_project(name: str, settings) -> str | None:
    """The canonical name if `name` is a real project (an alias, or a folder under the
    vault's projects/), else None. Free text is never accepted."""
    if not name or len(name) > 80 or _UNSAFE.search(name):
        return None
    key = project_key(name)
    if not key:
        return None
    if key in settings.aliases:
        return settings.aliases[key]
    if key in {project_key(c) for c in settings.aliases.values()}:
        return settings.canonical(name)
    if settings.projects_dir.is_dir():
        for d in settings.projects_dir.iterdir():
            if d.is_dir() and project_key(d.name) == key:
                return d.name
    return None


def parse(text: str, path: Path, settings) -> dict:
    from .connectors import project_for
    front, body = split_frontmatter(text.lstrip("﻿"))  # Notepad may add a BOM
    fields = {k.casefold(): redact(v.strip())[0][:60] for k, v in _FIELD.findall(front)}
    problems = []
    m = FILENAME.match(path.name)
    if not m:
        problems.append("file name is not YYYY-MM-DD-<project>-<kind>.md")
    for key in ("project", "date", "kind", "source"):
        if not fields.get(key):
            problems.append(f"header has no '{key}:'")
    kind = (fields.get("kind") or (m.group(3) if m else "")).casefold()
    if kind and kind not in KINDS:
        problems.append(f"kind '{kind}' is not decision / changelog / lesson")
    folder_project = project_for(path, settings)
    project = folder_project
    if fields.get("project"):
        named = known_project(fields["project"], settings)
        if named:
            project = named
        elif project_key(fields["project"]) != project_key(folder_project):
            problems.append(f"project '{fields['project']}' is not a known project; "
                            f"listed under this repo's project ({folder_project})")
    return {"project": project, "date": fields.get("date") or (m.group(1) if m else ""),
            "kind": kind, "source": fields.get("source", "").casefold(),
            "body": body.strip(), "problems": problems}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def target_for(settings, project: str, kind: str) -> Path | None:
    name = TARGETS.get(kind)
    if not name or not project or _UNSAFE.search(project):  # never build a path from odd text
        return None
    return settings.projects_dir / project / name


def is_filed(body: str, target: Path | None) -> bool:
    if len(_norm(body)) < MIN_FILED_CHARS or target is None or not target.is_file():
        return False
    return _norm(body) in _norm(target.read_text(encoding="utf-8", errors="replace"))


def _headline(body: str) -> str:
    for line in body.splitlines():
        line = line.strip().lstrip("#").strip()
        if line:
            line = redact(line)[0]
            return line if len(line) <= 120 else line[:119].rstrip() + "…"
    return "(empty note)"


def collect(settings, paths) -> list:
    """One entry per note, newest first."""
    out = []
    for path in paths:
        note = parse(path.read_text(encoding="utf-8", errors="replace"), path, settings)
        target = target_for(settings, note["project"], note["kind"])
        withheld = names_protected(str(path), note["body"], note["project"])
        out.append({
            "path": str(path), "project": note["project"], "project_key": project_key(note["project"]),
            "date": note["date"], "kind": note["kind"], "source": note["source"],
            "headline": "(withheld: mentions the protected folder; open it on the PC)"
                        if withheld else _headline(note["body"]),
            "target": str(target) if target else None,
            "filed": is_filed(note["body"], target),
            "withheld": withheld,
            "problems": note["problems"],
        })
    out.sort(key=lambda e: (e["date"], e["path"]), reverse=True)
    return out


def review_text(entries: list, stamp: str) -> str:
    unfiled = [e for e in entries if not e["filed"]]
    lines = ["# Brain inbox — weekly review", "",
             f"> Rebuilt every run ({stamp}). Do not edit. The pipe never edits the vault: a review",
             "> session proposes the exact edits and applies them only after the owner says yes.", "",
             f"**{len(unfiled)} unfiled** · {len(entries) - len(unfiled)} filed", ""]
    by_project = {}
    for e in unfiled:
        by_project.setdefault(e["project"], []).append(e)
    for project in sorted(by_project, key=str.casefold):
        lines += [f"## {project}", ""]
        for e in by_project[project]:
            lines.append(f"- **{e['date'] or '?'}** · {e['kind'] or '?'} · {e['source'] or '?'} · {e['headline']}")
            lines.append(f"  - File into: `{Path(e['target']).name if e['target'] else '(no target)'}`")
            lines += [f"  - ⚠ {p}" for p in e["problems"]]
        lines.append("")
    if not unfiled:
        lines.append("_Nothing to file._")
    return "\n".join(lines) + "\n"
