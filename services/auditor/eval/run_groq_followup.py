"""Judge the held-out captions with a second Groq model, then rerun 120B v6 cold.

Uses .env. Does not print the API key. The stability run uses a fresh cache file.
"""

from __future__ import annotations

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


def _use_groq(main: str, fast: str) -> None:
    load_env()
    os.environ["LLM_PROVIDER"] = "api"
    os.environ["LLM_BASE_URL"] = "https://api.groq.com/openai/v1"
    os.environ["BIFLOW_PROFILE"] = "api"
    os.environ["LLM_MODEL_MAIN"] = main
    os.environ["LLM_MODEL_FAST"] = fast
    os.environ.pop("FAKE_LLM", None)


def _model_ok(model: str) -> int:
    load_env()
    base = os.environ.get("LLM_BASE_URL", "").rstrip("/")
    key = os.environ.get("LLM_API_KEY", "")
    response = httpx.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": "Reply with the single word pong."}],
            "temperature": 0,
            "max_tokens": 8,
        },
        timeout=60,
    )
    print(f"probe {model} status={response.status_code}", flush=True)
    return response.status_code


def _judge_one(prose: str, sheet: dict) -> bool:
    from app.prose import render_prompt
    from biflow_contracts.biflow_llm import chat_text

    user = render_prompt(
        "auditor.fact_judge@v1",
        section="held-out",
        language="English",
        facts=json.dumps(sheet, ensure_ascii=False),
        prose=prose,
    )
    raw = chat_text("auditor.fact_judge@v1", "You check a paragraph against a fact sheet.", user, role="llm_fast", temperature=0.0)
    verdict = (raw or "").strip().split()
    return bool(verdict) and verdict[0].upper().startswith("FAIL")


def judge(judge_model: str) -> None:
    from app.factcheck import fact_check, unsupported_claims

    _use_groq(os.environ.get("LLM_MODEL_MAIN") or "openai/gpt-oss-120b", judge_model)
    cache = Path(tempfile.gettempdir()) / "biflow-judge-20b.sqlite"
    if cache.exists():
        cache.unlink()
    os.environ["BIFLOW_CACHE"] = str(cache)
    document = json.loads((HERE / "held_out_prose.json").read_text(encoding="utf-8"))
    default_sheet = document.get("fact_sheet") if isinstance(document.get("fact_sheet"), dict) else {}
    items = []
    for item in document.get("items") or []:
        sheet = item.get("fact_sheet") if isinstance(item.get("fact_sheet"), dict) else default_sheet
        items.append({**item, "fact_sheet": sheet})
    unsupported = [item for item in items if item.get("supported") is False]
    supported = [item for item in items if item.get("supported") is True]
    judge_caught = 0
    union_caught = 0
    checker_caught = 0
    union_false = 0
    details = []
    for item in unsupported:
        regex_hit = bool(unsupported_claims(item["prose"], item["fact_sheet"]))
        failed = _judge_one(item["prose"], item["fact_sheet"])
        checker_caught += int(regex_hit)
        judge_caught += int(failed)
        union_caught += int(regex_hit or failed)
        details.append({"id": item["id"], "checker": regex_hit, "judge_fail": failed, "supported": False})
        print("judge", item["id"], "checker" if regex_hit else "checker-miss", "FAIL" if failed else "PASS", flush=True)
    for item in supported:
        regex_hit = not fact_check(item["prose"], item["fact_sheet"])
        failed = _judge_one(item["prose"], item["fact_sheet"])
        union_false += int(regex_hit or failed)
        details.append({"id": item["id"], "checker_reject": regex_hit, "judge_fail": failed, "supported": True})
        print("judge", item["id"], "supported", "FAIL" if failed else "PASS", flush=True)
    n_bad = len(unsupported)
    n_good = len(supported)
    payload = {
        "judge_model": judge_model,
        "writer_model": "llama3.2:latest",
        "writer_note": "Held-out captions were written by llama3.2. The judge is a different Groq model.",
        "n_unsupported": n_bad,
        "n_supported": n_good,
        "recall": round(judge_caught / n_bad, 4) if n_bad else None,
        "checker_recall": round(checker_caught / n_bad, 4) if n_bad else None,
        "union_recall": round(union_caught / n_bad, 4) if n_bad else None,
        "union_false_reject_rate": round(union_false / n_good, 4) if n_good else None,
        "items": details,
    }
    (HERE / "judge_held_out.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    bad_path = HERE / "bad_prose.json"
    planted = json.loads(bad_path.read_text(encoding="utf-8"))
    rows = planted.get("items") if isinstance(planted, dict) else planted
    bad_path.write_text(
        json.dumps(
            {
                "llm_judge_recall": payload["recall"],
                "union_recall": payload["union_recall"],
                "judge_model": judge_model,
                "writer_model": payload["writer_model"],
                "note": "Recall is on the 15 labelled unsupported held-out captions. The development items below are not that set.",
                "items": rows,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    cases = json.loads((HERE / "explain_cases.json").read_text(encoding="utf-8"))["cases"]
    by_id = {case["id"]: case["fact_sheet"] for case in cases}
    bake = json.loads((HERE / "bakeoff_v6.json").read_text(encoding="utf-8"))
    arm = (bake.get("arms") or {}).get("groq-120b-v6") or {}
    flagged = 0
    seen = 0
    v6_rows = []
    for row in arm.get("rows") or []:
        answer = row.get("answer")
        sheet = by_id.get(row.get("id"))
        if not answer or not isinstance(sheet, dict):
            continue
        seen += 1
        failed = _judge_one(answer, sheet)
        flagged += int(failed)
        checker = bool(unsupported_claims(answer, sheet))
        v6_rows.append({"id": row["id"], "checker": checker, "judge_fail": failed})
        print("judge120", row["id"], "FAIL" if failed else "PASS", flush=True)
    v6_payload = {
        "judge_model": judge_model,
        "writer_model": arm.get("model"),
        "prompt_id": arm.get("prompt_id"),
        "n": seen,
        "flag_rate": round(flagged / seen, 4) if seen else None,
        "note": "Flag rate is not recall. These 120B v6 answers are not hand-labelled.",
        "items": v6_rows,
    }
    (HERE / "judge_v6_outputs.json").write_text(json.dumps(v6_payload, indent=2) + "\n", encoding="utf-8")
    print("judge_recall", payload["recall"], "union", payload["union_recall"], "v6_flag_rate", v6_payload["flag_rate"], flush=True)


def stability(main_model: str) -> None:
    from app.prose import write_prose
    from app.templates import explain_template
    from biflow_contracts.biflow_llm import drain_calls

    _use_groq(main_model, "openai/gpt-oss-20b")
    cache = Path(tempfile.gettempdir()) / "biflow-v6-stability.sqlite"
    if cache.exists():
        cache.unlink()
    os.environ["BIFLOW_CACHE"] = str(cache)
    cases = json.loads((HERE / "explain_cases.json").read_text(encoding="utf-8"))["cases"]
    previous = json.loads((HERE / "bakeoff_v6.json").read_text(encoding="utf-8"))
    prior = {row["id"]: row for row in ((previous.get("arms") or {}).get("groq-120b-v6") or {}).get("rows") or []}
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
        old = (prior.get(case["id"]) or {}).get("answer")
        same = result.text == old
        rows.append(
            {
                "id": case["id"],
                "source": result.source,
                "first_try_pass": result.first_try_pass,
                "identical": same,
                "answer": result.text,
            }
        )
        print("stable" if same else "DIFF", case["id"], result.source, result.first_try_pass, flush=True)
    identical = sum(1 for row in rows if row["identical"])
    payload = {
        "model": main_model,
        "prompt_id": "auditor.explain_kpi@v6",
        "cache": "cold sqlite, not the demo cache",
        "n": len(rows),
        "identical": identical,
        "identical_rate": round(identical / len(rows), 4) if rows else None,
        "first_try_pass_rate": round(sum(1 for row in rows if row["source"] == "llm" and row["first_try_pass"] is True) / len(rows), 4) if rows else None,
        "rows": rows,
    }
    (HERE / "bakeoff_v6_stability.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print("identical", identical, "of", len(rows), flush=True)


def warm(main_model: str) -> None:
    from app.prose import write_prose
    from app.templates import explain_template
    from biflow_contracts.biflow_llm import drain_calls

    _use_groq(main_model, "openai/gpt-oss-20b")
    os.environ["BIFLOW_CACHE"] = str(ROOT / ".cache" / "llm.sqlite")
    cases = json.loads((HERE / "explain_cases.json").read_text(encoding="utf-8"))["cases"]
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
        calls = drain_calls()
        hit = all(call.cache_hit for call in calls) if calls else False
        print("warm", case["id"], result.source, "cache_hit" if hit else "stored", flush=True)


def main() -> None:
    load_env()
    judge_model = "openai/gpt-oss-20b"
    if _model_ok(judge_model) != 200:
        judge_model = os.environ.get("LLM_MODEL_MAIN") or "openai/gpt-oss-120b"
        print("judge_substituted", judge_model, flush=True)
        if _model_ok(judge_model) != 200:
            print("judge_unavailable")
            sys.exit(1)
    main_model = os.environ.get("LLM_MODEL_MAIN") or "openai/gpt-oss-120b"
    judge(judge_model)
    stability(main_model)
    warm(main_model)


if __name__ == "__main__":
    main()
