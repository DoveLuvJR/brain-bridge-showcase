"""The session briefing: no transcript text, no protected material, framed, capped,
read-only, and never able to break or stall a session."""
import io
import sqlite3
import sys
import time
import unittest
from datetime import timedelta

from brainbridge import briefing, demo
from brainbridge.current import FRAMING
from brainbridge.store import connect_read_only
from helpers import Workspace


class Briefing(Workspace):
    def brief(self, repo: str) -> str:
        return briefing.build(self.settings, str(self.settings.sources[0] / repo))

    def test_project_briefing_has_status_inbox_and_news(self):
        text = self.brief("project-a")
        self.assertIn("Batch 7 shipped", text)
        self.assertIn("(inbox, not yet filed)", text)
        self.assertIn("Project B", text)  # another project mentioning this one

    def test_no_transcript_text(self):
        # The Project A session mentions Project B; only a date may come through.
        text = self.brief("project-b")
        self.assertNotIn("CSV export so Project B", text)

    def test_protected_folder_and_its_neighbours_are_hidden(self):
        text = self.brief("project-c")
        for hidden in ("Shortlist format", "Data handling", "Follow-up wording", demo.PERSON):
            self.assertNotIn(hidden, text)
        self.assertIn("Shortlist sent", text)  # a HANDOFF that never names the folder still shows

    def test_framing_line_and_footer(self):
        lines = self.brief("project-a").splitlines()
        self.assertEqual(lines[1], FRAMING)
        self.assertEqual(lines[-1], briefing.FOOTER)

    def test_line_cap(self):
        notes = self.settings.projects_dir / "Project B" / "many.md"
        days = [(self.today - timedelta(days=i % 10)).isoformat() for i in range(60)]
        notes.write_text("\n\n".join(f"## {d} Item {i}\n\nProject A item {i}." for i, d in enumerate(days)),
                         encoding="utf-8")
        old = briefing.MAX_NEWS
        briefing.MAX_NEWS = 100
        try:
            self.run_pipe()
            lines = self.brief("project-a").splitlines()
        finally:
            briefing.MAX_NEWS = old
        self.assertLessEqual(len(lines), briefing.MAX_LINES)
        self.assertEqual(lines[-1], briefing.FOOTER)

    def test_index_is_opened_read_only(self):
        db = connect_read_only(self.settings.db_path)
        self.addCleanup(db.close)
        with self.assertRaises(sqlite3.OperationalError):
            db.execute("DELETE FROM records")

    def test_no_project_folder_gets_the_overview(self):
        text = briefing.build(self.settings, str(self.tmp))
        self.assertIn("Top active projects", text)


class NeverBreaksASession(Workspace):
    def _main(self, factory, deadline=briefing.DEADLINE_SECONDS):
        out, err = io.StringIO(), io.StringIO()
        old_err, sys.stderr = sys.stderr, err
        try:
            code = briefing.main(stdin=io.StringIO('{"cwd": "x"}'), stdout=out, settings_factory=factory,
                                 deadline=deadline)
        finally:
            sys.stderr = old_err
        return code, out.getvalue(), err.getvalue()

    def test_an_error_prints_nothing_and_exits_0(self):
        def broken():
            raise RuntimeError("config is broken")
        self.assertEqual(self._main(broken), (0, "", ""))

    def test_a_slow_index_prints_nothing_within_the_deadline(self):
        def slow():
            time.sleep(3)
            return self.settings
        started = time.monotonic()
        code, out, _ = self._main(slow, deadline=0.2)
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertEqual((code, out), (0, ""))


if __name__ == "__main__":
    unittest.main()
