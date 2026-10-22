"""Prove every guard is load-bearing: switch each one off, one at a time, in a throwaway
copy of the code, run the whole test suite, and count the tests that turn red.

    python tools/guard_check.py

A guard whose switch-off leaves every test green is a guard nothing checks; this script
fails (exit 1) if that happens, or if a switch-off no longer matches the code it targets.
"""
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (area, guard, file, exact code, code with the guard switched off)
GUARDS = [
    # --- the index ---
    ("Index", "Secret-stripper", "redact.py",
     "        text = pattern.sub(repl, text)\n", "        pass\n"),
    ("Index", "Strip the whole file before cutting it into records", "connectors.py",
     'text, n = redact(data.decode("utf-8", errors="replace"))', 'text, n = data.decode("utf-8", errors="replace"), 0'),
    ("Index", "Hard exclusions (protected folder, .env, .ssh, secrets)", "exclude.py",
     "def is_excluded(path) -> bool:\n", "def is_excluded(path) -> bool:\n    return False\n"),
    ("Index", "Exclusions ignore trailing dots and spaces", "exclude.py",
     'p.casefold().rstrip(" .") or p.casefold()', "p.casefold()"),
    ("Index", "Session quarantine: every line checked", "connectors.py",
     "if line_names_protected(line):", "if False:"),
    ("Index", "Session quarantine: retroactive delete", "connectors.py",
     "ctx.store.delete_records(path)  # including turns an earlier run stored", "pass"),
    ("Index", "Session quarantine: permanent list", "connectors.py",
     "if ctx.store.is_quarantined(sid):", "if False:"),
    ("Index", "Re-judge every session when the rule changes", "pipeline.py",
     'store.reset_connector("transcripts")', "pass"),
    ("Index", "Transcripts kept after their source deletes them", "pipeline.py",
     'MARKDOWN = ("handoff", "decisions", "vault", "inbox")',
     'MARKDOWN = ("handoff", "decisions", "vault", "inbox", "transcripts")'),
    ("Index", "Removed notes pruned", "pipeline.py",
     "                    store.forget_file(path)", "                    pass"),
    ("Index", "Search: recency boost", "search.py",
     "    return 1 + 0.5 ** (age / HALF_LIFE_DAYS)", "    return 1.0"),
    ("Audit", "Audit: secret-shaped records", "audit.py",
     'if find_secrets(r["title"]) or find_secrets(r["body"]))', "if False)"),
    ("Audit", "Audit: records from excluded paths", "audit.py",
     "if is_excluded(r[0]))", "if False)"),
    ("Audit", "Audit: records from quarantined sessions", "audit.py",
     "if Path(p).stem in quarantined)", "if False)"),
    ("Health", "A quiet run is an ALERT (connector found nothing)", "pipeline.py",
     "problems += [f\"connector '{n}' found no files\" for n in REQUIRED if not found.get(n)]", "pass"),
    ("Health", "A missing source folder is an ALERT", "pipeline.py",
     'if ctx.counters.get("missing_roots"):', "if False:"),
    ("Health", "An exclusion that never fired is an ALERT", "pipeline.py",
     'if any(settings.vault.glob(f"**/{PROTECTED_FOLDER}")) and not ctx.counters.get("excluded_skipped"):',
     "if False:"),
    # --- the briefing ---
    ("Briefing", "No transcript text", "briefing.py",
     'BRIEF_CONNECTORS = ("handoff", "decisions", "vault", "inbox")',
     'BRIEF_CONNECTORS = ("handoff", "decisions", "vault", "inbox", "transcripts")'),
    ("Briefing", "Protected folder: neighbouring sections hidden", "exclude.py",
     "    return any(names_protected(r[0], r[1]) for r in rows)", "    return False"),
    ("Briefing", "Index opened read-only", "store.py", "?mode=ro", "?mode=rwc"),
    ("Briefing", "An error prints nothing", "briefing.py",
     "except BaseException:  # noqa: BLE001 (a briefing must never break a session)",
     "except ImportError:  # switched off"),
    ("Briefing", "Deadline (never stalls a session)", "briefing.py",
     "    worker.join(deadline)", "    worker.join()"),
    ("Briefing", "40-line cap", "briefing.py",
     "        lines = lines[:MAX_LINES - 1]  # the cap: room is always left for the footer", "        pass"),
    ("Briefing", "Framing line (facts, not instructions)", "briefing.py",
     'head = [header, FRAMING, "This project\'s last real status:"]',
     'head = [header, "This project\'s last real status:"]'),
    # --- the digest ---
    ("Digest", "Source gate (transcript text blanked)", "digest.py",
     "CASE WHEN connector IN ({marks}) THEN title ELSE '' END,", "title,"),
    ("Digest", "Page filter (protected and excluded-path lines dropped)", "digest.py",
     "    lines += [ln for ln in body if not names_protected(ln) and not _names_excluded_path(ln)]",
     "    lines += list(body)"),
    ("Digest", "Publish nothing when the index audit failed", "digest.py",
     '    if not report.get("audit", {}).get("ok"):', "    if False:"),
    ("Digest", "Audit the staged files before publishing", "digest.py",
     'if not audit["ok"]:\n        return {"status": "alert", "reason": "audit failed on the staged files: "',
     'if False:\n        return {"status": "alert", "reason": "audit failed on the staged files: "'),
    ("Digest", "Audit the output copy again", "digest.py",
     'if not audit["ok"]:\n        return {"status": "alert", "reason": "audit failed on the output copy: "',
     'if False:\n        return {"status": "alert", "reason": "audit failed on the output copy: "'),
    ("Digest", "Audit: secrets", "digest.py",
     '"secret_shaped": sorted(r for r, t in files.items() if find_secrets(t)),', '"secret_shaped": [],'),
    ("Digest", "Audit: protected folder", "digest.py",
     '"names_protected_folder": sorted(r for r, t in files.items() if names_protected(t)),',
     '"names_protected_folder": [],'),
    ("Digest", "Audit: unexpected files", "digest.py",
     '"unexpected_files": sorted(r for r in files if r not in TOP_FILES and not PROJECT_FILE.match(r)),',
     '"unexpected_files": [],'),
    ("Digest", "Audit: framing line on every file", "digest.py",
     '"missing_framing": sorted(r for r, t in files.items() if t.replace("\\r\\n", "\\n").split("\\n", 1)[0] != FRAMING),',
     '"missing_framing": [],'),
    ("Digest", "Audit: 200 KB cap", "digest.py",
     '"bytes_over_cap": max(0, sum(len(t.encode("utf-8")) for t in files.values()) - CAP_BYTES),',
     '"bytes_over_cap": 0,'),
    ("Digest", "Audit: START-HERE under 150 lines", "digest.py",
     '"start_here_lines_over": max(0, len(start.rstrip("\\n").split("\\n")) - START_MAX_LINES),',
     '"start_here_lines_over": 0,'),
    ("Digest", "Audit: transcript text in the source", "digest.py",
     '"transcript_text_in_source": leaks,', '"transcript_text_in_source": 0,'),
    # --- the scoped auto-push ---
    ("Git", "No force / add-all flags", "digest.py",
     'if (writes and a in _FORBIDDEN_ARGS) or a.startswith("--force") or a.startswith("+"):', "if False:"),
    ("Git", "The only push is 'push origin main'", "digest.py",
     'if args and args[0] == "push" and tuple(args) != ("push", "origin", "main"):', "if False:"),
    ("Git", "Exactly one fetch and one push URL", "digest.py", "if len(urls) != 1:", "if False:"),
    ("Git", "No credentials in the remote URL", "digest.py", "if _CREDS.search(urls[0]):", "if False:"),
    ("Git", "Origin must be the configured remote", "digest.py",
     "if not _same_remote(urls[0], expected_remote):", "if False:"),
    ("Git", "Branch must be main", "digest.py",
     'if git(repo, "symbolic-ref", "--short", "HEAD").stdout.strip() != "main":', "if False:"),
    ("Git", "Nothing but digest files committed", "digest.py", "    if extra:", "    if False:"),
    # --- the inbox ---
    ("Inbox", "Header project must be a real project", "inbox.py",
     'named = known_project(fields["project"], settings)', 'named = fields["project"]'),
    ("Inbox", "No path built from odd project text", "inbox.py",
     "if not name or not project or _UNSAFE.search(project):", "if not name or not project:"),
    ("Inbox", "Header values secret-stripped", "inbox.py",
     "fields = {k.casefold(): redact(v.strip())[0][:60] for k, v in _FIELD.findall(front)}",
     "fields = {k.casefold(): v.strip() for k, v in _FIELD.findall(front)}"),
    ("Inbox", "Notes naming the protected folder withheld", "inbox.py",
     'withheld = names_protected(str(path), note["body"], note["project"])', "withheld = False"),
    ("Inbox", "Filed detection", "inbox.py",
     '    return _norm(body) in _norm(target.read_text(encoding="utf-8", errors="replace"))', "    return False"),
    ("Inbox", "Short notes never count as filed", "inbox.py",
     "if len(_norm(body)) < MIN_FILED_CHARS or target is None or not target.is_file():",
     "if target is None or not target.is_file():"),
    ("Inbox", "Vault write guard (only two generated files)", "vault_write.py",
     "if norm(path) not in {norm(settings.current_md), norm(settings.review_md)}:", "if False:"),
]


def run_suite(folder: Path) -> tuple:
    res = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=folder,
                         capture_output=True, text=True, timeout=600)
    tail = res.stderr.strip().splitlines()[-1] if res.stderr.strip() else ""
    m = re.search(r"Ran (\d+) tests", res.stderr)
    ran = int(m.group(1)) if m else 0
    red = sum(int(n) for n in re.findall(r"(?:failures|errors)=(\d+)", tail))
    return ran, red, res.returncode


def check(guard) -> tuple:
    area, name, fname, old, new = guard
    tmp = Path(tempfile.mkdtemp(prefix="bb-guard-"))
    try:
        shutil.copytree(ROOT / "brainbridge", tmp / "brainbridge")
        shutil.copytree(ROOT / "tests", tmp / "tests")
        target = tmp / "brainbridge" / fname
        code = target.read_text(encoding="utf-8")
        if code.count(old) != 1:
            return guard, None, f"switch-off did not match exactly once ({code.count(old)} matches)"
        target.write_text(code.replace(old, new), encoding="utf-8")
        _, red, _ = run_suite(tmp)
        return guard, red, ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    ran, red, code = run_suite(ROOT)
    print(f"Baseline: {ran} tests, {red} red.")
    if code or red:
        print("The suite must be green before guards are checked.")
        return 1
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(check, GUARDS))
    print("\n| Area | Guard switched off | Tests that go red |\n|---|---|---|")
    bad = 0
    for (area, name, *_), red, problem in results:
        if problem or not red:
            bad += 1
        print(f"| {area} | {name} | {problem or red or '0  <-- NOTHING CHECKS THIS GUARD'} |")
    print(f"\n{len(GUARDS) - bad} of {len(GUARDS)} guards turn at least one test red.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
