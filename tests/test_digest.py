"""The digest: source gate, page filter, the audit on disk, publish order, git guards."""
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from brainbridge import demo, digest
from brainbridge.exclude import PROTECTED_FOLDER
from helpers import Workspace

HAS_GIT = shutil.which("git") is not None


class Digest(Workspace):
    def test_publishes_and_contains_no_transcript_text(self):
        result = digest.publish(self.settings, self.report)
        self.assertEqual(result["status"], "published")
        text = "\n".join(digest.read_folder(self.settings.digest_out).values())
        self.assertIn("Batch 7 shipped", text)
        self.assertNotIn("CSV export so Project B", text)
        self.assertNotIn(demo.FAKE_KEY, text)

    def test_source_gate_blanks_transcript_text(self):
        db = digest.gated_copy(self.settings.db_path)
        self.addCleanup(db.close)
        rows = db.execute("SELECT title, body FROM records WHERE connector = 'transcripts'").fetchall()
        self.assertTrue(rows)
        self.assertTrue(all(r["title"] == "" and r["body"] == "" for r in rows))
        self.assertEqual(digest.gate_leaks(db), 0)

    def test_a_failed_index_audit_publishes_nothing(self):
        bad = dict(self.report, audit={"ok": False})
        self.assertEqual(digest.publish(self.settings, bad)["status"], "alert")
        self.assertFalse(self.settings.digest_out.exists())

    def test_a_poisoned_build_never_reaches_the_output(self):
        real = digest.build

        def poisoned(*a, **kw):
            files = real(*a, **kw)
            files["START-HERE.md"] += f"\nleaked {demo.FAKE_KEY}\n"  # bypasses the page filter
            return files
        digest.build = poisoned
        try:
            result = digest.publish(self.settings, self.report)
        finally:
            digest.build = real
        self.assertEqual(result["status"], "alert")
        self.assertIn("secret_shaped", result["reason"])
        self.assertFalse(self.settings.digest_out.exists())

    def test_a_stray_file_in_the_output_blocks_publishing(self):
        out = self.settings.digest_out
        out.mkdir(parents=True)
        (out / "notes.txt").write_text("someone dropped this here\n", encoding="utf-8")
        result = digest.publish(self.settings, self.report)
        self.assertEqual(result["status"], "alert")
        self.assertIn("output copy", result["reason"])

    def test_page_drops_protected_and_excluded_lines(self):
        text = digest.page(["keep me", f"see /{PROTECTED_FOLDER}/a.md", "open ~/.env.local now"], datetime.now())
        self.assertIn("keep me", text)
        self.assertNotIn(PROTECTED_FOLDER, text)
        self.assertNotIn(".env", text)


class AuditOnDisk(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        now = datetime.now()
        for name in digest.TOP_FILES:
            (self.dir / name).write_text(digest.page(["# ok"], now), encoding="utf-8")

    def check(self, key, rel, text):
        p = self.dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        result = digest.audit_folder(self.dir, 0)
        self.assertTrue(result[key], result)
        self.assertFalse(result["ok"])

    def test_clean_folder_passes(self):
        self.assertTrue(digest.audit_folder(self.dir, 0)["ok"])

    def test_secret(self):
        self.check("secret_shaped", "CURRENT.md", digest.FRAMING + "\n" + demo.FAKE_KEY + "\n")

    def test_protected_folder(self):
        self.check("names_protected_folder", "CURRENT.md", digest.FRAMING + f"\nsee {PROTECTED_FOLDER}\n")

    def test_unexpected_file(self):
        self.check("unexpected_files", "notes.txt", digest.FRAMING + "\n")

    def test_missing_framing(self):
        self.check("missing_framing", "README.md", "# no framing\n")

    def test_size_cap(self):
        self.check("bytes_over_cap", "projects/big.md", digest.FRAMING + "\n" + "x" * (digest.CAP_BYTES + 1))

    def test_start_here_line_cap(self):
        self.check("start_here_lines_over", "START-HERE.md", digest.FRAMING + "\n" + "line\n" * 200)

    def test_transcript_leak_in_source(self):
        result = digest.audit_folder(self.dir, 1)
        self.assertFalse(result["ok"])


class GitGuards(unittest.TestCase):
    def test_force_and_add_all_are_refused(self):
        for args in (("push", "--force", "origin", "main"), ("push", "-f", "origin", "main"),
                     ("push", "origin", "+main"), ("add", "-A"), ("add", ".")):
            with self.assertRaises(digest.GitGuard, msg=args):
                digest.check_git_args(args)

    def test_the_only_push_is_push_origin_main(self):
        for args in (("push", "origin", "other"), ("push", "backup", "main"), ("push",)):
            with self.assertRaises(digest.GitGuard, msg=args):
                digest.check_git_args(args)
        digest.check_git_args(("push", "origin", "main"))

    def test_read_only_commands_may_use_all(self):
        digest.check_git_args(("remote", "get-url", "--all", "origin"))


@unittest.skipUnless(HAS_GIT, "git is not installed")
class GitPublish(Workspace):
    """The scoped auto-push, end to end, against a local bare repo standing in for GitHub."""

    def setUp(self):
        super().setUp()
        self.remote = self.tmp / "remote.git"
        g = lambda *a, cwd=None: subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)  # noqa: E731
        g("init", "--bare", "-b", "main", str(self.remote))
        out = self.settings.digest_out
        g("clone", str(self.remote), str(out))
        for k, v in (("user.name", "Digest Bot"), ("user.email", "digest-bot"), ("commit.gpgsign", "false")):
            g("config", k, v, cwd=out)
        g("commit", "--allow-empty", "-m", "start", cwd=out)
        g("push", "origin", "main", cwd=out)
        self.settings.digest_remote = str(self.remote)

    def remote_head(self) -> str:
        return subprocess.run(["git", "--git-dir", str(self.remote), "rev-parse", "main"],
                              capture_output=True, text=True).stdout.strip()

    def test_pushes_then_reports_unchanged(self):
        before = self.remote_head()
        self.assertEqual(digest.publish(self.settings, self.report)["status"], "pushed")
        self.assertNotEqual(self.remote_head(), before)
        self.assertEqual(digest.publish(self.settings, self.report)["status"], "unchanged")

    def test_a_failed_audit_pushes_nothing(self):
        before = self.remote_head()
        real = digest.build
        digest.build = lambda *a, **kw: dict(real(*a, **kw), **{"CURRENT.md": demo.FAKE_KEY})
        try:
            self.assertEqual(digest.publish(self.settings, self.report)["status"], "alert")
        finally:
            digest.build = real
        self.assertEqual(self.remote_head(), before)

    def test_nothing_but_digest_files_may_be_committed(self):
        out = self.settings.digest_out
        (out / "stray.txt").write_text("not part of the digest\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(out), "add", "stray.txt"], check=True, capture_output=True)
        (out / "stray.txt").unlink()  # staged, but gone from disk: only the staging check can see it
        before = self.remote_head()
        result = digest.publish(self.settings, self.report)
        self.assertEqual(result["status"], "alert")
        self.assertIn("other than the digest", result["reason"])
        self.assertEqual(self.remote_head(), before)

    def test_a_second_url_is_refused(self):
        out = self.settings.digest_out
        subprocess.run(["git", "-C", str(out), "remote", "set-url", "--add", "origin", str(self.tmp / "x.git")],
                       check=True, capture_output=True)
        self.assertIn("exactly one", digest.check_repo(out, str(self.remote)))

    def test_any_other_remote_is_refused(self):
        self.assertIn("not the configured", digest.check_repo(self.settings.digest_out, str(self.tmp / "other.git")))

    def test_a_branch_other_than_main_is_refused(self):
        out = self.settings.digest_out
        subprocess.run(["git", "-C", str(out), "checkout", "-q", "-b", "side"], check=True, capture_output=True)
        self.assertIn("not on main", digest.check_repo(out, str(self.remote)))

    def test_credentials_in_the_url_are_refused(self):
        out = self.settings.digest_out
        subprocess.run(["git", "-C", str(out), "remote", "set-url", "origin", "https://user:pw" + "@example.invalid/d.git"],
                       check=True, capture_output=True)
        self.assertIn("credentials", digest.check_repo(out, "https://example.invalid/d.git"))


if __name__ == "__main__":
    unittest.main()
