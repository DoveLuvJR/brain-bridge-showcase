"""Command line.

  python -m brainbridge demo                       build the synthetic workspace (example/workspace)
  python -m brainbridge run    [--config CFG]      index, audit, CURRENT.md, inbox review, digest
  python -m brainbridge search [--config CFG] QUERY [--project NAME]
  python -m brainbridge brief  [--config CFG] --cwd FOLDER
CFG defaults to example/config.json.
"""
import argparse
import sys
from pathlib import Path

from . import briefing, config, demo, digest, pipeline, search
from .store import connect_read_only

DEFAULT_DEMO = Path("example") / "workspace"


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="brainbridge")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo")
    d.add_argument("--out", default=str(DEFAULT_DEMO))
    for name in ("run", "search", "brief"):
        p = sub.add_parser(name)
        p.add_argument("--config", default=str(Path("example") / "config.json"))
        if name == "search":
            p.add_argument("query")
            p.add_argument("--project")
        if name == "brief":
            p.add_argument("--cwd", required=True)
    a = ap.parse_args(argv)

    if a.cmd == "demo":
        cfg = demo.build_workspace(Path(a.out))
        print(f"Synthetic workspace written. Config: {cfg}")
        return 0
    settings = config.load(a.config)
    if a.cmd == "run":
        report = pipeline.run(settings)
        print(f"{'OK' if report['ok'] else 'ALERT'} in {report['seconds']}s · {report['records']} records · "
              f"{report['counters'].get('redactions', 0)} secrets stripped · "
              f"{report['counters'].get('sessions_newly_quarantined', 0)} session(s) quarantined")
        print("Audit: " + ", ".join(f"{k}={v}" for k, v in report["audit"].items() if k != "ok"))
        for h in report["health"]:
            print(f"HEALTH {h}")
        result = digest.publish(settings, report)
        print(f"Digest: {result['status']}" + (f" ({result['reason']})" if "reason" in result else ""))
        return 0 if report["ok"] and result["status"] != "alert" else 1
    if a.cmd == "search":
        db = connect_read_only(settings.db_path)
        for r in search.search(db, a.query, a.project):
            print(f"{r['score']:>7} · {r['date']} · {r['project']} · {r['connector']} · {r['title']}")
        return 0
    if a.cmd == "brief":
        text = briefing.build(settings, str(Path(a.cwd).resolve()))
        print(text or "(no briefing)")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
