"""SQLite store: dated records, an FTS5 (BM25) index over them, per-file cursors, the
permanent session quarantine, and a log of runs.

The `files` table is how each connector remembers where it stopped: size + mtime + sha1
for markdown, a byte offset + next turn number for transcripts.
"""
import os
import sqlite3
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS records(
    id INTEGER PRIMARY KEY,
    connector TEXT NOT NULL,
    source_path TEXT NOT NULL,
    chunk INTEGER NOT NULL,
    project TEXT NOT NULL,
    project_key TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    date TEXT NOT NULL,
    date_source TEXT NOT NULL,
    UNIQUE(source_path, chunk)
);
CREATE INDEX IF NOT EXISTS records_project ON records(project_key, date);

CREATE VIRTUAL TABLE IF NOT EXISTS records_fts USING fts5(
    title, body, project, content='records', content_rowid='id', tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS records_ai AFTER INSERT ON records BEGIN
    INSERT INTO records_fts(rowid, title, body, project) VALUES (new.id, new.title, new.body, new.project);
END;
CREATE TRIGGER IF NOT EXISTS records_ad AFTER DELETE ON records BEGIN
    INSERT INTO records_fts(records_fts, rowid, title, body, project)
    VALUES ('delete', old.id, old.title, old.body, old.project);
END;

CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);

-- Sessions that named the protected folder. Kept forever: a quarantined session is
-- never indexed again, whatever its file does later.
CREATE TABLE IF NOT EXISTS quarantine(
    session_id TEXT PRIMARY KEY,
    quarantined_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS files(
    path TEXT PRIMARY KEY,
    connector TEXT NOT NULL,
    mtime REAL NOT NULL,
    size INTEGER NOT NULL,
    sha1 TEXT,
    offset INTEGER NOT NULL DEFAULT 0,
    next_chunk INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS runs(
    id INTEGER PRIMARY KEY,
    started TEXT NOT NULL,
    finished TEXT,
    status TEXT
);
"""


def check_fts5():
    db = sqlite3.connect(":memory:")
    try:
        db.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
    except sqlite3.OperationalError as exc:
        raise SystemExit("This Python's SQLite has no FTS5 full-text search. Use a python.org "
                         "build of Python 3.10+ (FTS5 is included).") from exc
    finally:
        db.close()


class Store:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(db_path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.commit()
        self.db.close()

    # ---- files (cursors) ----
    def get_file(self, path):
        return self.db.execute("SELECT * FROM files WHERE path = ?", (str(path),)).fetchone()

    def upsert_file(self, path, connector, mtime, size, sha1=None, offset=0, next_chunk=0):
        self.db.execute(
            """INSERT INTO files(path, connector, mtime, size, sha1, offset, next_chunk)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(path) DO UPDATE SET connector=excluded.connector, mtime=excluded.mtime,
                 size=excluded.size, sha1=excluded.sha1, offset=excluded.offset,
                 next_chunk=excluded.next_chunk""",
            (str(path), connector, mtime, size, sha1, offset, next_chunk))

    def known_files(self, connector: str) -> list:
        return [r[0] for r in self.db.execute("SELECT path FROM files WHERE connector = ?", (connector,))]

    def forget_file(self, path):
        self.delete_records(path)
        self.db.execute("DELETE FROM files WHERE path = ?", (str(path),))

    def reset_connector(self, connector: str):
        """Re-read every file of a connector from the start on the next pass."""
        self.db.execute("UPDATE files SET mtime = -1, offset = 0, next_chunk = 0 WHERE connector = ?",
                        (connector,))

    # ---- records ----
    def delete_records(self, path, from_chunk: int = 0):
        self.db.execute("DELETE FROM records WHERE source_path = ? AND chunk >= ?", (str(path), from_chunk))

    def insert_records(self, records: list):
        self.db.executemany(
            """INSERT OR REPLACE INTO records(connector, source_path, chunk, project, project_key,
                                              title, body, date, date_source)
               VALUES (:connector, :source_path, :chunk, :project, :project_key,
                       :title, :body, :date, :date_source)""", records)

    def max_chunk(self, path) -> int:
        row = self.db.execute("SELECT MAX(chunk) FROM records WHERE source_path = ?", (str(path),)).fetchone()
        return row[0] if row[0] is not None else -1

    def count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM records").fetchone()[0]

    # ---- quarantine ----
    def quarantine(self, session_id: str):
        self.db.execute("INSERT OR IGNORE INTO quarantine(session_id, quarantined_at) VALUES (?, ?)",
                        (session_id, datetime.now().isoformat(timespec="seconds")))

    def is_quarantined(self, session_id: str) -> bool:
        return self.db.execute("SELECT 1 FROM quarantine WHERE session_id = ?", (session_id,)).fetchone() is not None

    # ---- meta ----
    def get_meta(self, key: str, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def set_meta(self, key: str, value: str):
        self.db.execute("INSERT INTO meta(key, value) VALUES (?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    # ---- runs ----
    def start_run(self) -> int:
        cur = self.db.execute("INSERT INTO runs(started) VALUES (?)", (datetime.now().isoformat(timespec="seconds"),))
        return cur.lastrowid

    def finish_run(self, run_id: int, status: str):
        self.db.execute("UPDATE runs SET finished = ?, status = ? WHERE id = ?",
                        (datetime.now().isoformat(timespec="seconds"), status, run_id))


def connect_read_only(db_path: Path) -> sqlite3.Connection:
    """Read-only connection: the briefing can never change the index."""
    db = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True, timeout=1.0)
    db.row_factory = sqlite3.Row
    return db


def norm(path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))
