"""The brain inbox: untrusted notes, filing, the review file, and the vault write guard."""
import json
import unittest

from brainbridge import demo, inbox, vault_write
from brainbridge.exclude import PROTECTED_FOLDER
from helpers import Workspace


class Inbox(Workspace):
    def entries(self):
        s = self.store()
        return json.loads(s.get_meta("inbox"))

    def note(self, name: str, header: dict, body: str):
        path = self.settings.sources[0] / "project-a" / "brain-inbox" / name
        path.write_text("---\n" + "".join(f"{k}: {v}\n" for k, v in header.items()) + "---\n" + body,
                        encoding="utf-8")
        return path

    def test_a_hostile_header_project_is_refused(self):
        e = next(e for e in self.entries() if "project-b" in e["path"])
        self.assertEqual(e["project"], "Project B")
        self.assertTrue(any("not a known project" for p in e["problems"] for _ in [p]))
        self.assertIsNone(inbox.target_for(self.settings, "../../outside", "lesson"))

    def test_header_values_are_secret_stripped(self):
        path = self.note(f"{self.today}-project-a-lesson.md",
                         {"project": "Project A", "date": demo.FAKE_KEY, "kind": "lesson", "source": "local"},
                         "A long enough lesson about stripping secrets out of note headers.\n")
        note = inbox.parse(path.read_text(encoding="utf-8"), path, self.settings)
        self.assertNotIn(demo.FAKE_KEY, json.dumps(note))

    def test_notes_naming_the_protected_folder_are_withheld(self):
        self.note(f"{self.today}-project-a-changelog.md",
                  {"project": "Project A", "date": self.today, "kind": "changelog", "source": "cloud"},
                  f"Moved files out of {PROTECTED_FOLDER} for {demo.PERSON}.\n")
        self.run_pipe()
        e = next(e for e in self.entries() if e["kind"] == "changelog")
        self.assertTrue(e["withheld"])
        self.assertNotIn(demo.PERSON, json.dumps(self.entries()))

    def test_a_note_is_filed_once_its_text_is_in_the_target(self):
        target = self.settings.projects_dir / "Project A" / "DECISIONS.md"
        target.write_text("# Decisions\n\nChose CSV as the default export because every accounting\n"
                          "tool imports it.\n", encoding="utf-8")
        self.run_pipe()
        e = next(e for e in self.entries() if e["project"] == "Project A")
        self.assertTrue(e["filed"])
        self.assertNotIn("Chose CSV", self.settings.review_md.read_text(encoding="utf-8"))

    def test_a_short_note_never_counts_as_filed(self):
        target = self.settings.projects_dir / "Project A" / "LESSONS.md"
        target.write_text("ok\n", encoding="utf-8")
        self.assertFalse(inbox.is_filed("ok", target))


class VaultWriteGuard(Workspace):
    def test_only_the_two_generated_files_may_be_written(self):
        note = self.settings.projects_dir / "Project A" / "notes.md"
        before = note.read_text(encoding="utf-8")
        with self.assertRaises(vault_write.VaultWriteRefused):
            vault_write.write(self.settings, note, "overwritten")
        self.assertEqual(note.read_text(encoding="utf-8"), before)
        vault_write.write(self.settings, self.settings.current_md, "# ok\n")


if __name__ == "__main__":
    unittest.main()
