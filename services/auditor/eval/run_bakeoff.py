"""Template vs one live model on the 20 explain cases, plus one judge pass.

qwen2.5:7b-instruct is used when that tag is installed. Otherwise the script records that it was not run.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

os.environ.pop("FAKE_LLM", None)

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services" / "auditor"))

from app.factcheck import fact_check, unsupported_claims  # noqa: E402
from app.prose import render_prompt, write_prose  # noqa: E402
from app.templates import explain_template  # noqa: E402
from biflow_contracts.biflow_llm import LLMUnavailable, chat_text  # noqa: E402

HERE = Path(__file__).resolve().parent


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((pct / 100) * (len(ordered) - 1))
    return round(ordered[index], 1)


def _summarize(rows: list[dict]) -> dict:
    finished = [row for row in rows if row.get("error") is None]
    latencies = [row["latency_ms"] for row in finished]
    first = [row for row in finished if row["first_try_pass"] is not None]
    return {
        "n": len(finished),
        "errors": len(rows) - len(finished),
        "first_try_pass_rate": round(sum(1 for row in first if row["first_try_pass"]) / len(first), 4) if first else None,
        "fallback_rate": round(sum(1 for row in finished if row["source"] == "template") / len(finished), 4) if finished else None,
        "latency_ms_p50": _percentile(latencies, 50),
        "latency_ms_p95": _percentile(latencies, 95),
    }


def _template_rows(cases: list[dict]) -> list[dict]:
    rows = []
    for case in cases:
        started = time.perf_counter()
        answer = explain_template(case["fact_sheet"], "en")
        passed = fact_check(answer, case["fact_sheet"])
        rows.append(
            {
                "id": case["id"],
                "source": "code",
                "first_try_pass": passed,
                "attempts": 1,
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "error": None,
            }
        )
    return rows


def _model_rows(cases: list[dict], model: str, on_row=None) -> list[dict]:
    os.environ["LLM_MODEL_MAIN"] = model
    os.environ["LLM_MODEL_FAST"] = model
    rows = []
    for case in cases:
        started = time.perf_counter()
        try:
            result = write_prose(
                prompt_id=os.environ.get("PROMPT_ID", "auditor.explain_kpi@v3"),
                fact_sheet=case["fact_sheet"],
                template=explain_template(case["fact_sheet"], "en"),
                lang="en",
                section=f"Explain {case['kpi_id']} for {case['period']}",
                min_sentences=3,
                max_sentences=5,
            )
            rows.append(
                {
                    "id": case["id"],
                    "source": result.source,
                    "first_try_pass": result.first_try_pass,
                    "attempts": result.attempts,
                    "warning": result.warning,
                    "answer": result.text,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                    "error": None,
                }
            )
        except (LLMUnavailable, TimeoutError, OSError) as exc:
            rows.append({"id": case["id"], "source": None, "first_try_pass": None, "attempts": 0, "latency_ms": None, "error": str(exc)})
        print(case["id"], rows[-1]["source"], rows[-1]["first_try_pass"], rows[-1]["latency_ms"], flush=True)
        if on_row is not None:
            on_row(rows)
    return rows


def _judge(items: list[dict], model: str) -> dict:
    os.environ["LLM_MODEL_FAST"] = model
    unsupported = [item for item in items if item.get("supported") is False]
    misses = []
    caught = 0
    judge_on_miss = 0
    for item in unsupported:
        regex_hit = bool(unsupported_claims(item["prose"], item["fact_sheet"]))
        if not regex_hit:
            misses.append(item["id"])
        user = render_prompt(
            "auditor.fact_judge@v1",
            section="held-out",
            language="English",
            facts=json.dumps(item["fact_sheet"], ensure_ascii=False),
            prose=item["prose"],
        )
        try:
            raw = chat_text("auditor.fact_judge@v1", "You check a paragraph against a fact sheet.", user, role="llm_fast", temperature=0.0)
        except (LLMUnavailable, TimeoutError, OSError) as exc:
            return {"model": model, "recall": None, "error": str(exc), "n": len(unsupported)}
        verdict = (raw or "").strip().split()
        failed = bool(verdict) and verdict[0].upper().startswith("FAIL")
        caught += int(failed)
        if not regex_hit and failed:
            judge_on_miss += 1
        print("judge", item["id"], "regex" if regex_hit else "regex-miss", verdict[:1], flush=True)
    return {
        "model": model,
        "n": len(unsupported),
        "recall": round(caught / len(unsupported), 4) if unsupported else None,
        "regex_misses": misses,
        "judge_catches_of_regex_misses": judge_on_miss,
    }


def _write(payload: dict) -> None:
    out = Path(os.environ.get("BAKEOFF_OUT", str(HERE / "bakeoff_results.json")))
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    cases = json.loads((HERE / "explain_cases.json").read_text(encoding="utf-8"))["cases"]
    model = os.environ.get("BAKEOFF_MODEL", "llama3.2:latest")
    prompt_id = os.environ.get("PROMPT_ID", "auditor.explain_kpi@v3")
    template = _template_rows(cases)
    payload: dict = {
        "note": "Live calls only. qwen2.5:7b-instruct is not installed. llama3.2:latest is the local 3B.",
        "prompt_id": prompt_id,
        "template": {**_summarize(template), "rows": template},
        model: {"rows": []},
        "judge": {"recall": None},
    }
    _write(payload)

    def _checkpoint(rows: list[dict]) -> None:
        payload[model] = {**_summarize(rows), "rows": rows}
        _write(payload)

    live = _model_rows(cases, model, _checkpoint)
    payload[model] = {**_summarize(live), "rows": live}
    _write(payload)
    held_path = HERE / "held_out_prose.json"
    if held_path.exists() and os.environ.get("SKIP_JUDGE") != "1":
        held_doc = json.loads(held_path.read_text(encoding="utf-8"))
        default_sheet = held_doc.get("fact_sheet") if isinstance(held_doc.get("fact_sheet"), dict) else {}
        items = []
        for item in held_doc.get("items") or []:
            sheet = item.get("fact_sheet") if isinstance(item.get("fact_sheet"), dict) else default_sheet
            items.append({**item, "fact_sheet": sheet})
        payload["judge"] = _judge(items, model)
    _write(payload)
    print(json.dumps({"template": payload["template"], model: {k: v for k, v in payload[model].items() if k != "rows"}, "judge": payload["judge"]}, indent=2))


if __name__ == "__main__":
    main()
