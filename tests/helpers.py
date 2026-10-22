"""Shared fixture: a fresh synthetic workspace (brainbridge.demo) in a temp folder."""
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

from brainbridge import config, demo, pipeline
from brainbridge.store import Store


class Workspace(unittest.TestCase):
    run_first = True

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bb-test-"))
        self.today = date.today()
        self.cfg_path = demo.build_workspace(self.tmp, self.today)
        self.settings = config.load(self.cfg_path)
        self.report = self.run_pipe() if self.run_first else None

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_pipe(self) -> dict:
        return pipeline.run(self.settings, self.today)

    def store(self) -> Store:
        s = Store(self.settings.db_path)
        self.addCleanup(s.close)
        return s

    def all_text(self) -> str:
        s = self.store()
        return "\n".join(r["title"] + "\n" + r["body"] for r in s.db.execute("SELECT title, body FROM records"))

    def records_of(self, path) -> int:
        s = self.store()
        return s.db.execute("SELECT COUNT(*) FROM records WHERE source_path = ?", (str(path),)).fetchone()[0]

    def session(self, sid: str, folder: str) -> Path:
        return self.settings.transcripts / folder / f"{sid}.jsonl"
