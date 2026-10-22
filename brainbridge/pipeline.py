"""One run of the pipe (scheduled hourly in the real system):

  walk -> index (handoff, decisions, vault, inbox, transcripts) -> audit everything stored
  -> health check -> CURRENT.md + inbox review -> one log line.

A run is ALERT, not OK, when the audit finds anything, or when it was quiet for a bad
reason: a quiet run that checked nothing looks exactly like a clean one.
"""
import json
import os
import time
from datetime import date, datetime

from . import audit, connectors, current, inbox, vault_write
from .exclude import PROTECTED_FOLDER
from .store import Store, check_fts5

LOCK_STALE_SECONDS = 3 * 3600
REQUIRED = ("handoff", "decisions", "vault", "transcripts")  # finding none of these = something is wrong
MARKDOWN = ("handoff", "decisions", "vault", "inbox")


class AlreadyRunning(RuntimeError):
    pass


def take_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        if time.time() - path.stat().st_mtime < LOCK_STALE_SECONDS:
            raise AlreadyRunning(f"another run holds {path.name}")
        path.unlink()
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)


def health_problems(settings, found: dict, ctx) -> list:
    problems = []
    if ctx.errors:
        problems.append(f"{len(ctx.errors)} file(s) failed to index")
    problems += [f"connector '{n}' found no files" for n in REQUIRED if not found.get(n)]
    if ctx.counters.get("missing_roots"):
        problems.append(f"{ctx.counters['missing_roots']} source folder(s) are missing")
    if any(settings.vault.glob(f"**/{PROTECTED_FOLDER}")) and not ctx.counters.get("excluded_skipped"):
        problems.append("the protected folder exists but the exclusion never fired")
    if ctx.counters.get("too_big"):
        problems.append(f"{ctx.counters['too_big']} file(s) over the size cap were not re-read")
    return problems


def run(settings, today: date | None = None) -> dict:
    check_fts5()
    started = time.monotonic()
    lock = settings.state_dir / "run.lock"
    take_lock(lock)
    store = Store(settings.db_path)
    try:
        run_id = store.start_run()
        if store.get_meta("transcript_guard") != connectors.GUARD_VERSION:
            store.reset_connector("transcripts")  # the rule changed: judge every session again
            store.set_meta("transcript_guard", connectors.GUARD_VERSION)
        ctx = connectors.Context(settings, store, today or date.today())
        found = connectors.walk(ctx)
        found["transcripts"] = connectors.transcript_files(settings)

        for name in ("handoff", "decisions", "vault"):
            for path in found[name]:
                _safely(ctx, path, connectors.index_markdown, name)
        for path in found["inbox"]:
            _safely(ctx, path, connectors.index_inbox_note)
        for path in found["transcripts"]:
            _safely(ctx, path, connectors.index_transcript)

        # Markdown that left disk is pruned. Transcripts are kept: the tool that writes them
        # deletes old sessions, and keeping them is half the point of the index.
        on_disk = {str(p) for name in MARKDOWN for p in found[name]}
        for name in MARKDOWN:
            for path in store.known_files(name):
                if path not in on_disk:
                    store.forget_file(path)

        entries = inbox.collect(settings, found["inbox"])
        store.set_meta("inbox", json.dumps(entries))
        store.db.commit()

        report = {"audit": audit.run_audit(store.db), "health": health_problems(settings, found, ctx),
                  "records": store.count(), "counters": ctx.counters}
        report["ok"] = report["audit"]["ok"] and not report["health"]
        now = datetime.now()
        vault_write.write(settings, settings.current_md, current.build(store.db, ctx.today, report))
        vault_write.write(settings, settings.review_md, inbox.review_text(entries, f"{now:%Y-%m-%d %H:%M}"))
        report["seconds"] = round(time.monotonic() - started, 2)
        store.finish_run(run_id, "OK" if report["ok"] else "ALERT")
        _log(settings, now, report)
        return report
    finally:
        store.close()
        try:
            lock.unlink()
        except OSError:
            pass


def _safely(ctx, path, fn, *args):
    try:
        fn(ctx, path, *args)
    except (OSError, UnicodeError, ValueError) as exc:
        ctx.errors.append(f"{path.name}: {type(exc).__name__}")


def _log(settings, now, report):
    status = "OK" if report["ok"] else "ALERT"
    c = report["counters"]
    line = (f"{now:%Y-%m-%d %H:%M:%S} {status} {report['seconds']}s records={report['records']} "
            f"redactions={c.get('redactions', 0)} quarantined_new={c.get('sessions_newly_quarantined', 0)} "
            f"audit={'ok' if report['audit']['ok'] else 'FAILED'}\n")
    line += "".join(f"  HEALTH {p}\n" for p in report["health"])
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    with open(settings.log_path, "a", encoding="utf-8") as fh:
        fh.write(line)
