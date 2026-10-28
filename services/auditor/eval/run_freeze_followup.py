"""Seed and reasoning-effort rerun, then the 20B judge on the 30 supported sentences.

Uses .env. Does not print the API key. Each v6 run has its own cold cache.
The labelled CSV is imported only when every supported cell is filled.
"""

from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services" / "auditor"))
os.environ.pop("FAKE_LLM", None)

HERE = Path(__file__).resolve().parent
MAIN = "openai/gpt-oss-120b"
JUDGE = "openai/gpt-oss-20b"
SEED = 7


def load_env() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip()


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {os.environ.get('LLM_API_KEY', '')}", "Content-Type": "application/json"}


def probe_effort(model: str) -> str | None:
    """Return the lowest reasoning effort this model accepts, or None."""
    base = os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
    for effort in ("low", "minimal", "medium"):
        response = httpx.post(
            f"{base}/chat/completions",
            headers=_headers(),
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Reply with the single word pong."}],
                "temperature": 0,
                "max_tokens": 16,
                "seed": SEED,
                "reasoning_effort": effort,
            },
            timeout=60,
        )
        print(f"probe reasoning_effort={effort} status={response.status_code}", flush=True)
        if response.status_code == 200:
            return effort
    return None


def _install_payload(effort: str | None) -> None:
    import biflow_contracts.biflow_llm as llm

    original = llm.httpx.post

    def wrapped(url, json=None, **kwargs):
        payload = json
        if isinstance(payload, dict) and "messages" in payload:
            payload = dict(payload)
            payload["seed"] = SEED
            if effort:
                payload["reasoning_effort"] = effort
        return original(url, json=payload, **kwargs)

    llm.httpx.post = wrapped


def _use_groq(main: str, fast: str) -> None:
    load_env()
    os.environ["LLM_PROVIDER"] = "api"
    os.environ["LLM_BASE_URL"] = "https://api.groq.com/openai/v1"
    os.environ["BIFLOW_PROFILE"] = "api"
    os.environ["LLM_MODEL_MAIN"] = main
    os.environ["LLM_MODEL_FAST"] = fast
    os.environ["EXPLAIN_KPI_VERSION"] = "v6"
    os.environ.pop("FAKE_LLM", None)


def _one_run(tag: str) -> list[dict]:
    from app.prose import write_prose
    from app.templates import explain_template
    from biflow_contracts.biflow_llm import drain_calls

    cache = Path(tempfile.gettempdir()) / f"biflow-v6-seed-{tag}.sqlite"
    if cache.exists():
        cache.unlink()
    os.environ["BIFLOW_CACHE"] = str(cache)
    cases = json.loads((HERE / "explain_cases.json").read_text(encoding="utf-8"))["cases"]
    rows = []
    for case in cases:
        drain_calls()
        result = write_prose(
            prompt_id="auditor.explain_kpi@v6",
            fact_sheet=case["fact_sheet"],
            template=explain_template(case["fact_sheet"], "en"),
            lang="en",
            section=f"Explain {case['kpi_id']} for {case['period']}",
            min_sentences=3,
            max_sentences=5,
            temperature=0.0,
        )
        rows.append(
            {
                "id": case["id"],
                "source": result.source,
                "first_try_pass": result.first_try_pass,
                "answer": result.text,
            }
        )
        print(tag, case["id"], result.source, result.first_try_pass, flush=True)
    return rows


def determinism(effort: str | None) -> dict:
    _use_groq(MAIN, JUDGE)
    _install_payload(effort)
    first = _one_run("a")
    second = _one_run("b")
    by_id = {row["id"]: row for row in second}
    identical = 0
    rows = []
    for row in first:
        other = by_id[row["id"]]
        same = row["answer"] == other["answer"]
        identical += int(same)
        rows.append(
            {
                "id": row["id"],
                "identical": same,
                "first_try_a": row["first_try_pass"],
                "first_try_b": other["first_try_pass"],
                "source_a": row["source"],
                "source_b": other["source"],
                "answer_a": row["answer"],
                "answer_b": other["answer"],
            }
        )
        print("same" if same else "DIFF", row["id"], flush=True)
    n = len(rows)
    first_try = sum(1 for row in rows if row["source_a"] == "llm" and row["first_try_a"] is True and row["source_b"] == "llm" and row["first_try_b"] is True)
    payload = {
        "model": MAIN,
        "prompt_id": "auditor.explain_kpi@v6",
        "temperature": 0,
        "seed": SEED,
        "reasoning_effort": effort,
        "cache": "two cold sqlite files, not the demo cache",
        "n": n,
        "identical": identical,
        "identical_rate": round(identical / n, 4) if n else None,
        "both_first_try_pass": first_try,
        "note": "Groq does not guarantee determinism. Identical counts answers that match between these two runs.",
        "rows": rows,
    }
    (HERE / "bakeoff_v6_seed.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print("identical", identical, "of", n, "both_first_try", first_try, flush=True)
    return payload


def judge_valid() -> dict:
    from app.eval_runner import _sheet_of
    from app.prose import render_prompt
    from biflow_contracts.biflow_llm import chat_text

    _use_groq(MAIN, JUDGE)
    cache = Path(tempfile.gettempdir()) / "biflow-judge-valid.sqlite"
    if cache.exists():
        cache.unlink()
    os.environ["BIFLOW_CACHE"] = str(cache)
    document = json.loads((HERE / "valid_prose.json").read_text(encoding="utf-8"))
    default_sheet = document.get("default_sheet") if isinstance(document.get("default_sheet"), dict) else {}
    rows = []
    rejected = 0
    for item in document.get("sentences") or []:
        sheet = _sheet_of(item, default_sheet)
        user = render_prompt(
            "auditor.fact_judge@v1",
            section="valid-prose",
            language="English",
            facts=json.dumps(sheet, ensure_ascii=False),
            prose=item["prose"],
        )
        raw = chat_text("auditor.fact_judge@v1", "You check a paragraph against a fact sheet.", user, role="llm_fast", temperature=0.0)
        verdict = (raw or "").strip().split()
        failed = bool(verdict) and verdict[0].upper().startswith("FAIL")
        rejected += int(failed)
        rows.append({"id": item["id"], "judge_fail": failed})
        print("valid", item["id"], "FAIL" if failed else "PASS", flush=True)
    n = len(rows)
    payload = {
        "judge_model": JUDGE,
        "n": n,
        "false_rejects": rejected,
        "false_reject_rate": round(rejected / n, 4) if n else None,
        "note": "These 30 sentences are author-written and supported. A FAIL is a false reject. This is not the held-out recall.",
        "items": rows,
    }
    (HERE / "judge_valid_prose.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print("judge_false_reject", payload["false_reject_rate"], rejected, "of", n, flush=True)
    return payload


def labelled_csv() -> bool:
    path = HERE / "faithfulness_template.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    filled = [row for row in rows if str(row.get("supported (1/0)") or "").strip() in {"0", "1"}]
    print("csv_rows", len(rows), "labelled", len(filled), flush=True)
    return bool(rows) and len(filled) == len(rows)


def main() -> None:
    load_env()
    if labelled_csv():
        print("csv_labelled", flush=True)
    else:
        print("csv_not_labelled import_skipped", flush=True)
    effort = probe_effort(MAIN)
    print("reasoning_effort", effort if effort else "rejected", flush=True)
    determinism(effort)
    judge_valid()


if __name__ == "__main__":
    main()
