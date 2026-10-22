"""A synthetic workspace for the quick start and the tests.

EVERYTHING here is fabricated: the projects, the notes, the "people", and the secrets.
The fake secrets are assembled at runtime so that no secret-shaped string sits in this
source file (a secret scanner over the repo stays at zero).

Layout:
  vault/projects/<Project>/...           notes, decisions, and one protected folder
  repos/<repo>/HANDOFF.md, CHANGELOG.md  ... and brain-inbox/ notes
  sessions/<folder>/<session-id>.jsonl   AI session transcripts
"""
import json
from datetime import date, timedelta
from pathlib import Path

from .exclude import PROTECTED_FOLDER

# Fabricated secrets, built at runtime.
FAKE_KEY = "sk-" + "ant-" + "FAKEdemo0123456789abcdefXYZ"
FAKE_ENV_NAME = "VENDOR_" + "TOKEN"
FAKE_ENV = FAKE_ENV_NAME + "=" + "demo7f3a9c2e11"
PERSON = "Sample Person 01"  # fabricated personal data that must never be indexed or shown

SESSION_OK = "11111111-aaaa-4aaa-8aaa-000000000001"
SESSION_PROTECTED = "22222222-bbbb-4bbb-8bbb-000000000002"


def _w(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _jsonl(path: Path, lines: list):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")


def turn(cwd: str, when: date, user: str, reply: str) -> list:
    ts = f"{when.isoformat()}T10:00:00Z"
    return [{"type": "user", "timestamp": ts, "cwd": cwd, "message": {"role": "user", "content": user}},
            {"type": "assistant", "timestamp": ts, "cwd": cwd,
             "message": {"role": "assistant", "content": [{"type": "text", "text": reply}]}}]


def tool_output(cwd: str, when: date, output: str) -> list:
    ts = f"{when.isoformat()}T10:05:00Z"
    return [{"type": "user", "timestamp": ts, "cwd": cwd,
             "message": {"role": "user", "content": [{"type": "tool_result", "content": output}]}}]


def build_workspace(root: Path, today: date | None = None) -> Path:
    """Write the synthetic workspace under `root` and return its config file."""
    today = today or date.today()
    d = lambda n: (today - timedelta(days=n)).isoformat()  # noqa: E731
    root = Path(root).resolve()
    vault, repos, sessions = root / "vault", root / "repos", root / "sessions"

    # --- the vault ---
    _w(vault / "projects" / "Project A" / "notes.md",
       f"# Project A notes\n\n## {d(20)} Pricing idea\n\nTry a flat monthly price for small teams.\n")
    _w(vault / "projects" / "Project B" / "notes.md",
       f"# Project B notes\n\n## {d(3)} Calendar sync\n\nProject A's invoice export could feed the calendar.\n")
    _w(vault / "projects" / "Project C" / "DECISIONS.md",
       f"# Project C decisions\n\n## {d(4)} Shortlist format\n\nShortlists are a table of five, with reasons.\n\n"
       f"## {d(6)} Data handling\n\nPeople's records live only in the {PROTECTED_FOLDER} folder.\n\n"
       f"## {d(7)} Follow-up wording\n\nFollow-ups mention the role and the next step only.\n")
    _w(vault / "projects" / "Project C" / PROTECTED_FOLDER / "person-01.md",
       f"# {PERSON}\n\nPhone: 555-0100. Notes: fabricated record for tests.\n")
    _w(vault / "ideas.md", f"# Ideas\n\n## {d(10)} Morning page\n\nOne page that says what needs me today.\n")

    # --- the repos ---
    _w(repos / "project-a" / "HANDOFF.md",
       f"# Handoff\n\n## {d(2)} Batch 7 shipped\n\nInvoice export works end to end; 41 tests pass.\n"
       f"Deploy key for staging: {FAKE_KEY}\n")
    _w(repos / "project-a" / "CHANGELOG.md",
       f"# Changelog\n\n## {d(2)} Batch 7: invoice export\n\nCSV and PDF export shipped.\n\n"
       f"## {d(45)} Batch 1: skeleton\n\nFirst screens.\n")
    _w(repos / "project-a" / ".env", f"{FAKE_ENV}\n")
    _w(repos / "project-a" / "brain-inbox" / f"{d(1)}-project-a-decision.md",
       f"---\nproject: Project A\ndate: {d(1)}\nkind: decision\nsource: cloud\n---\n"
       "Chose CSV as the default export because every accounting tool imports it.\n")
    _w(repos / "project-b" / "HANDOFF.md",
       f"# Handoff\n\n## {d(5)} Sync paused\n\nCalendar sync is paused until the Project A export settles.\n")
    _w(repos / "project-b" / "DECISIONS.md",
       f"# Decisions\n\n## {d(3)} Weekly view first\n\nThe weekly view ships before the monthly view.\n")
    _w(repos / "project-b" / "brain-inbox" / f"{d(1)}-project-b-lesson.md",
       f"---\nproject: ../../outside\ndate: {d(1)}\nkind: lesson\nsource: cloud\n---\n"
       "Time zones: store UTC, show local. A one-hour bug came from mixing them.\n")
    _w(repos / "project-c" / "HANDOFF.md",
       f"# Handoff\n\n## {d(4)} Shortlist sent\n\nFive-person shortlist sent for review.\n")

    # --- the sessions ---
    a_cwd, b_cwd = str(repos / "project-a"), str(repos / "project-b")
    _jsonl(sessions / "project-a" / f"{SESSION_OK}.jsonl",
           turn(a_cwd, today - timedelta(days=2), "Add the CSV export so Project B can read it.",
                "Done. CSV export added; 41 tests pass.")
           + turn(a_cwd, today - timedelta(days=2), f"Here is the staging key: {FAKE_KEY}",
                  "Stored it in the secret manager; never commit it."))
    _jsonl(sessions / "project-b" / f"{SESSION_PROTECTED}.jsonl",
           turn(b_cwd, today - timedelta(days=3), "Summarise the shortlist for me.", "Reading the files now.")
           + tool_output(b_cwd, today - timedelta(days=3),
                         f"{vault}/projects/Project C/{PROTECTED_FOLDER}/person-01.md: {PERSON}"))

    config = {
        "vault": "vault", "sources": ["repos"], "transcripts": "sessions",
        "state_dir": ".brain", "digest_out": "digest-out",
        "aliases": {"project-a": "Project A", "project-b": "Project B", "project-c": "Project C"},
    }
    _w(root / "config.json", json.dumps(config, indent=2) + "\n")
    return root / "config.json"
