"""BIFlow CLI (runs inside the gateway container):

    python -m app.cli run --dataset olist                         # full pipeline
    python -m app.cli run --dataset olist --ingest-from dev-sample  # DEV: start from a seeded 00_ingest
    python -m app.cli run --resume <RUN_ID>                       # continue at the first stage that is not ok
    python -m app.cli run --resume <RUN_ID> --from etl            # redo etl and everything after it
    python -m app.cli list | status <RUN_ID> | graph
    python -m app.cli bench --dataset olist_sample --runs 5      # time-to-insight benchmark -> data/bench/<ts>/report.md
    python -m app.cli eval --all                                  # every module's /v1/eval -> data/eval/<ts>/results.md
"""
from __future__ import annotations

import argparse
import json
import textwrap

from . import runner


def _print_run(m: dict) -> None:
    print(f"run {m['run_id']}: {m['status']}   (total {m.get('total_seconds')} s, commit {m.get('git_commit')})")
    print(f"  {'stage':<18} {'status':<8} {'seconds':>8}  source")
    for name, st in m["stages"].items():
        src = "seeded" if st.get("seeded_from") else ("mock" if st.get("mock") else ("real" if st.get("mock") is False else ""))
        err = f"  <- {st['error'].get('code')}: {st['error'].get('message', '')[:90]}" if st.get("error") else ""
        print(f"  {name:<18} {st['status']:<8} {st.get('seconds', ''):>8}  {src}{err}")
    s = m.get("summary") or {}
    if s:
        print(f"\nsummary ({s['source']}, fact-check: {s['fact_check']}):")
        print(textwrap.fill(s["text"], width=110, initial_indent="  ", subsequent_indent="  "))


def main() -> None:
    p = argparse.ArgumentParser(prog="biflow")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--dataset", default="olist")
    r.add_argument("--resume", metavar="RUN_ID")
    r.add_argument("--from", dest="rerun_from", metavar="STAGE", help="with --resume: redo STAGE and every later stage")
    r.add_argument("--ingest-from", metavar="RUN_ID", help="DEV: reuse data/runs/<RUN_ID>/00_ingest instead of the ingest module")
    r.add_argument("--lang", default="en", choices=["en", "fr"])
    s = sub.add_parser("status")
    s.add_argument("run_id")
    sub.add_parser("list")
    sub.add_parser("graph", help="print the pipeline graph as Mermaid")
    b = sub.add_parser("bench", help="benchmark N full runs (+ cold/cached LLM, --resume, reproducibility)")
    b.add_argument("--dataset", default="olist_sample")
    b.add_argument("--runs", type=int, default=5)
    b.add_argument("--resume-from", default="etl")
    b.add_argument("--warm", action="store_true", help="keep the LLM cache (default: run 1 starts cold)")
    e = sub.add_parser("eval", help="run every module's /v1/eval and render one results table")
    e.add_argument("--all", action="store_true")
    e.add_argument("--module", action="append")
    a = p.parse_args()

    if a.cmd == "run":
        m = runner.run_pipeline(a.dataset, run_id=a.resume, resume=bool(a.resume), ingest_from=a.ingest_from, lang=a.lang,
                                rerun_from=a.rerun_from)
        _print_run(m)
        raise SystemExit(0 if m["status"] == "ok" else 1)
    if a.cmd == "status":
        print(json.dumps(json.loads((runner.data_dir() / "runs" / a.run_id / "run_manifest.json").read_text()), indent=2))
    if a.cmd == "list":
        d = runner.data_dir() / "runs"
        print("\n".join(sorted((x.name for x in d.iterdir()), reverse=True)) if d.exists() else "(no runs)")
    if a.cmd == "graph":
        print(runner.build_graph().get_graph().draw_mermaid())
    if a.cmd == "bench":
        from .bench import bench, to_markdown

        rep = bench(a.dataset, runs=a.runs, cold_first=not a.warm, resume_from=a.resume_from)
        print(to_markdown(rep))
        print(f"report: {rep['report_dir']}")
    if a.cmd == "eval":
        from .evaluate import evaluate, to_markdown as eval_md

        rep = evaluate(None if a.all or not a.module else a.module)
        print(eval_md(rep))
        print(f"results: {rep['report_dir']}")


if __name__ == "__main__":
    main()
