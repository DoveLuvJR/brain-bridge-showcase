"""The index: secret-stripper, exclusions, session quarantine, audit, health, recency."""
import json
import os
import unittest
from datetime import date, timedelta
from pathlib import Path

from brainbridge import audit, chunk, demo
from brainbridge.exclude import PROTECTED_FOLDER, is_excluded
from brainbridge.redact import find_secrets, redact
from brainbridge.search import search
from brainbridge.store import Store
from helpers import Workspace


class SecretStripper(unittest.TestCase):
    def test_known_shapes_are_stripped(self):
        for secret in (demo.FAKE_KEY, demo.FAKE_ENV, "Authorization: Bearer " + "abcDEF0123456789abcDEF0123",
                       "postgres://app:" + "s3cretpass" + "@db.example.invalid/x"):
            clean, n = redact(f"before {secret} after")
            self.assertGreater(n, 0, secret)
            self.assertEqual(find_secrets(clean), [], secret)

    def test_prose_is_spared(self):
        text = "The password: see the team vault. Rotate the token monthly."
        self.assertEqual(redact(text), (text, 0))


class Exclusions(unittest.TestCase):
    def test_case_slashes_and_trailing_dots(self):
        for p in (f"vault/{PROTECTED_FOLDER}/a.md", f"VAULT\\{PROTECTED_FOLDER.upper()}.\\a.md",
                  "repo/.env.local", "home/.ssh/config", "repo/secrets.yaml"):
            self.assertTrue(is_excluded(p), p)
        self.assertFalse(is_excluded("repo/HANDOFF.md"))


class Index(Workspace):
    def test_run_is_ok_and_audit_is_zero(self):
        self.assertTrue(self.report["ok"], self.report)
        self.assertTrue(self.report["audit"]["ok"])

    def test_secrets_never_stored(self):
        text = self.all_text()
        self.assertNotIn(demo.FAKE_KEY, text)
        self.assertIn("[REDACTED:anthropic]", text)

    def test_secret_split_across_records_is_still_stripped(self):
        # A key that straddles the cut between two records: per-record stripping alone misses it.
        cut = chunk.MAX_PART - len("sk-ant-FAKEd")
        note = self.settings.projects_dir / "Project A" / "long.md"
        note.write_text(f"# Long\n\n{'x' * cut}{demo.FAKE_KEY} tail\n", encoding="utf-8")
        self.run_pipe()
        s = self.store()
        bodies = "".join(r[0] for r in s.db.execute(
            "SELECT body FROM records WHERE source_path = ? ORDER BY chunk", (str(note),)))
        self.assertEqual(find_secrets(bodies), [])

    def test_protected_folder_is_never_read(self):
        self.assertNotIn(demo.PERSON, self.all_text())
        self.assertGreater(self.report["counters"].get("excluded_skipped", 0), 0)

    def test_session_naming_protected_folder_is_quarantined_whole(self):
        path = self.session(demo.SESSION_PROTECTED, "project-b")
        self.assertEqual(self.records_of(path), 0)  # its first turn never named the folder; still out
        self.assertTrue(self.store().is_quarantined(demo.SESSION_PROTECTED))

    def test_quarantine_is_retroactive(self):
        path = self.session(demo.SESSION_OK, "project-a")
        self.assertGreater(self.records_of(path), 0)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "user", "message": {"content": f"open /{PROTECTED_FOLDER}/x"}}) + "\n")
        self.run_pipe()
        self.assertEqual(self.records_of(path), 0)

    def test_quarantine_is_permanent(self):
        # The session file is later rewritten without the line that named the folder.
        path = self.session(demo.SESSION_PROTECTED, "project-b")
        clean = [ln for ln in path.read_text(encoding="utf-8").splitlines() if PROTECTED_FOLDER not in ln]
        path.write_text("\n".join(clean) + "\n", encoding="utf-8")
        self.run_pipe()
        self.assertEqual(self.records_of(path), 0)

    def test_a_rewritten_transcript_is_read_again(self):
        path = self.session(demo.SESSION_OK, "project-a")
        first = path.read_text(encoding="utf-8").splitlines()[:1]  # rewritten shorter: one typed line left
        path.write_text("\n".join(first) + "\n", encoding="utf-8")
        before = self.records_of(path)
        self.run_pipe()
        self.assertEqual(self.records_of(path), before + 1)  # kept the old turns, added the re-read one

    def test_rule_change_rescans_every_session(self):
        # Simulate an index built under an older, looser rule: the session was kept.
        path = self.session(demo.SESSION_PROTECTED, "project-b")
        s = Store(self.settings.db_path)
        s.db.execute("DELETE FROM quarantine")
        s.insert_records([{"connector": "transcripts", "source_path": str(path), "chunk": 0, "project": "Project B",
                           "project_key": "projectb", "title": "Session › planted", "body": "quotes a person",
                           "date": self.today.isoformat(), "date_source": "timestamp"}])
        st = path.stat()
        s.upsert_file(path, "transcripts", st.st_mtime, st.st_size, offset=st.st_size)
        s.set_meta("transcript_guard", "older-rule")
        s.close()
        self.run_pipe()
        self.assertEqual(self.records_of(path), 0)

    def test_transcripts_survive_deletion_of_their_source(self):
        path = self.session(demo.SESSION_OK, "project-a")
        before = self.records_of(path)
        os.remove(path)
        self.run_pipe()
        self.assertEqual(self.records_of(path), before)

    def test_removed_markdown_is_pruned(self):
        handoff = self.settings.sources[0] / "project-b" / "HANDOFF.md"
        handoff.unlink()
        self.run_pipe()
        self.assertEqual(self.records_of(handoff), 0)

    def test_every_record_is_dated(self):
        self.assertEqual(self.report["audit"]["undated_records"], 0)


class Audit(Workspace):
    def _plant(self, **kw):
        s = self.store()
        rec = {"connector": "vault", "source_path": "planted.md", "chunk": 0, "project": "P", "project_key": "p",
               "title": "planted", "body": "", "date": self.today.isoformat(), "date_source": "heading"}
        rec.update(kw)
        s.insert_records([rec])
        return s

    def test_audit_catches_a_planted_secret(self):
        s = self._plant(body=demo.FAKE_KEY)
        result = audit.run_audit(s.db)
        self.assertEqual(result["secret_shaped_records"], 1)
        self.assertFalse(result["ok"])

    def test_audit_catches_records_from_a_quarantined_session(self):
        path = str(self.session(demo.SESSION_PROTECTED, "project-b"))
        s = self._plant(connector="transcripts", source_path=path, body="quotes a person")
        self.assertEqual(audit.run_audit(s.db)["quarantined_session_records"], 1)

    def test_audit_catches_excluded_paths(self):
        s = self._plant(source_path=f"vault/{PROTECTED_FOLDER}/x.md")
        self.assertEqual(audit.run_audit(s.db)["excluded_path_records"], 1)


class Health(Workspace):
    def test_a_quiet_run_is_an_alert(self):
        for f in self.settings.transcripts.glob("*/*.jsonl"):
            f.unlink()
        report = self.run_pipe()
        self.assertFalse(report["ok"])
        self.assertIn("connector 'transcripts' found no files", report["health"])

    def test_an_exclusion_that_never_fires_is_an_alert(self):
        from brainbridge import connectors
        real = connectors.is_excluded
        connectors.is_excluded = lambda p: False  # a broken exclusion, as a bug would leave it
        try:
            report = self.run_pipe()
        finally:
            connectors.is_excluded = real
        self.assertIn("the protected folder exists but the exclusion never fired", report["health"])

    def test_a_missing_source_folder_is_an_alert(self):
        self.settings.sources.append(self.tmp / "does-not-exist")
        report = self.run_pipe()
        self.assertFalse(report["ok"])


class Recency(unittest.TestCase):
    def test_newer_wins_over_a_slightly_better_old_match(self):
        tmp = Path(__import__("tempfile").mkdtemp())
        s = Store(tmp / "i.db")
        today = date.today()
        rows = [("old.md", "deploy rollback deploy", (today - timedelta(days=700)).isoformat()),
                ("new.md", "deploy rollback", today.isoformat())]
        s.insert_records([{"connector": "vault", "source_path": p, "chunk": 0, "project": "P", "project_key": "p",
                           "title": "notes", "body": b, "date": d, "date_source": "heading"} for p, b, d in rows])
        s.db.commit()
        top = search(s.db, "deploy rollback", today=today)[0]
        s.close()
        self.assertEqual(top["source_path"], "new.md")


if __name__ == "__main__":
    unittest.main()
