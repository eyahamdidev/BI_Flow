"""CLI: python -m app.cli run --dataset olist [--resume RUN_ID] | status RUN_ID | list"""
from __future__ import annotations

import argparse
import json

from . import runner


def main() -> None:
    p = argparse.ArgumentParser(prog="biflow")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--dataset", default="olist")
    r.add_argument("--resume", metavar="RUN_ID")
    s = sub.add_parser("status")
    s.add_argument("run_id")
    sub.add_parser("list")
    a = p.parse_args()

    if a.cmd == "run":
        m = runner.run_pipeline(a.dataset, run_id=a.resume, resume=bool(a.resume))
        print(f"run {m['run_id']}: {m['status']}")
        for name, st in m["stages"].items():
            print(f"  {name:<18} {st['status']:<8} {st.get('seconds', '')}")
        raise SystemExit(0 if m["status"] == "ok" else 1)
    if a.cmd == "status":
        print(json.dumps(json.loads((runner.data_dir() / "runs" / a.run_id / "run_manifest.json").read_text()), indent=2))
    if a.cmd == "list":
        d = runner.data_dir() / "runs"
        print("\n".join(sorted((x.name for x in d.iterdir()), reverse=True)) if d.exists() else "(no runs)")


if __name__ == "__main__":
    main()
