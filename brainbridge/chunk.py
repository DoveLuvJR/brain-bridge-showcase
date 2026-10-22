"""Cut markdown into dated records, one per heading section.

A section's date comes from, in order: a YYYY-MM-DD in its heading ('heading'), one in
its first lines ('section'), else the file's date: file name ('filename'), front matter
('frontmatter'), or last-modified time ('mtime'). Every record carries the source of its
date, so a reader can tell a stated date from a guess.
"""
import re
from datetime import date, datetime, timedelta
from pathlib import Path

HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*#*\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")
DATE = re.compile(r"(?<!\d)(20\d\d)-(\d\d)-(\d\d)(?!\d)")
FRONTMATTER_DATE = re.compile(r"(?im)^\s*(?:date|created|updated)\s*:\s*['\"]?(20\d\d-\d\d-\d\d)")
MAX_PART = 4000


def find_date(text: str, today: date | None = None) -> str | None:
    """First plausible YYYY-MM-DD in the text (never in the future)."""
    limit = (today or date.today()) + timedelta(days=1)
    for m in DATE.finditer(text):
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
        if d <= limit:
            return d.isoformat()
    return None


def split_frontmatter(text: str):
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[3:end], text[end + 4:].lstrip("\r\n")
    return "", text


def file_date(path: Path, frontmatter: str, mtime: float, today: date | None = None):
    d = find_date(path.name, today)
    if d:
        return d, "filename"
    m = FRONTMATTER_DATE.search(frontmatter)
    if m and find_date(m.group(1), today):
        return m.group(1), "frontmatter"
    return datetime.fromtimestamp(mtime).date().isoformat(), "mtime"


def sections(text: str) -> list:
    """[(heading, body)] split on #, ## and ### outside code fences."""
    out, heading, lines, in_fence = [], "", [], False
    for line in text.splitlines():
        if FENCE.match(line):
            in_fence = not in_fence
        m = None if in_fence else HEADING.match(line)
        if m:
            out.append((heading, "\n".join(lines)))
            heading, lines = m.group(2).strip(), []
        else:
            lines.append(line)
    out.append((heading, "\n".join(lines)))
    return [(h, b.strip()) for h, b in out if b.strip()]


def _parts(body: str) -> list:
    """Long sections are cut into pieces of at most MAX_PART characters."""
    return [body[i:i + MAX_PART] for i in range(0, len(body), MAX_PART)] or [body]


def markdown_records(path: Path, text: str, mtime: float, today: date | None = None) -> list:
    """[{chunk, title, body, date, date_source}] for one markdown file."""
    frontmatter, body = split_frontmatter(text)
    fdate, fsource = file_date(path, frontmatter, mtime, today)
    records, chunk = [], 0
    for heading, sbody in sections(body):
        if heading and find_date(heading, today):
            d, src = find_date(heading, today), "heading"
        elif find_date(sbody[:300], today):
            d, src = find_date(sbody[:300], today), "section"
        else:
            d, src = fdate, fsource
        base = f"{path.stem} › {heading}" if heading else path.stem
        pieces = _parts(sbody)
        for i, piece in enumerate(pieces):
            title = base if len(pieces) == 1 else f"{base} (part {i + 1})"
            records.append({"chunk": chunk, "title": title, "body": piece, "date": d, "date_source": src})
            chunk += 1
    return records
