"""One pass of the 20 explain cases through v8.

Writes eval/v8_sample.json. Calls are one at a time. The API key is never printed.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services" / "auditor"))

HERE = Path(__file__).resolve().parent
OUT = HERE / "v8_sample.json"
PROMPT = "auditor.explain_kpi@v8"
PAUSE_S = 2.0


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


def largest_labels(sheet: dict) -> list[str]:
    drivers = sheet.get("drivers") if isinstance(sheet.get("drivers"), dict) else {}
    rows = drivers.get("contributions") if isinstance(drivers, dict) else None
    scored: list[tuple[float, str]] = []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            delta = row.get("delta")
            label = row.get("dimension_value")
            if isinstance(delta, (int, float)) and not isinstance(delta, bool) and label is not None:
                scored.append((float(delta), str(label)))
    if not scored:
        return []
    best = max(delta for delta, _label in scored)
    return [label for delta, label in scored if delta == best]


def main() -> None:
    load_env()
    os.environ.pop("FAKE_LLM", None)
    os.environ["BIFLOW_MOCK"] = "0"
    os.environ["LLM_PROVIDER"] = "api"
    os.environ["BIFLOW_PROFILE"] = "api"
    os.environ["explain_kpi_version"] = "v8"
    os.environ["LLM_BASE_URL"] = os.environ.get("LLM_BASE_URL") or "https://api.groq.com/openai/v1"

    from app.factcheck import unsupported_claims
    from app.redact import redact
    from app.templates import explain_template
    from app.v8 import analyst_facts, write_v8

    model = os.environ.get("LLM_MODEL_MAIN") or ""
    cases = json.loads((HERE / "explain_cases.json").read_text(encoding="utf-8"))["cases"]
    rows: list[dict] = []
    payload = {
        "prompt": PROMPT,
        "model": model,
        "n": len(cases),
        "pause_seconds": PAUSE_S,
        "note": "One run. No human faithfulness labels. A pass means the checker accepted the paragraph.",
        "rows": rows,
    }
    print(f"model {model}", flush=True)
    print(f"cases {len(cases)}", flush=True)
    for index, item in enumerate(cases):
        sheet = item["fact_sheet"]
        lang = item.get("lang") or "en"
        facts = analyst_facts(sheet)
        started = time.perf_counter()
        try:
            result = write_v8(
                prompt_id=PROMPT,
                fact_sheet=sheet,
                template=explain_template(sheet, lang),
                lang=lang,
                section=f"Explain {item.get('kpi_id') or item['id']} for {item.get('period') or ''}",
            )
            choice = result.choice or {}
            kept = [entry.get("value") for entry in choice.get("kept") or []]
            dropped = [entry.get("value") for entry in choice.get("dropped") or []]
            issues = unsupported_claims(result.text, sheet)
            row = {
                "id": item["id"],
                "kpi_id": item.get("kpi_id"),
                "period": item.get("period"),
                "compare_to": item.get("compare_to"),
                "lang": lang,
                "n_facts": len(facts),
                "offered": [fact.shown for fact in facts],
                "source": result.source,
                "attempts": result.attempts,
                "first_try": result.first_try_pass,
                "warning": redact(result.warning) if result.warning else None,
                "kept": kept,
                "dropped": dropped,
                "text": result.text,
                "checker_issues": issues,
                "largest": largest_labels(sheet),
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            }
        except Exception as exc:
            row = {
                "id": item["id"],
                "kpi_id": item.get("kpi_id"),
                "period": item.get("period"),
                "compare_to": item.get("compare_to"),
                "lang": lang,
                "n_facts": len(facts),
                "offered": [fact.shown for fact in facts],
                "source": "error",
                "attempts": None,
                "first_try": None,
                "warning": redact(type(exc).__name__ + ": " + str(exc))[:300],
                "kept": [],
                "dropped": [],
                "text": "",
                "checker_issues": [],
                "largest": largest_labels(sheet),
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            }
        rows.append(row)
        OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(
            f"{row['id']} facts={row['n_facts']} source={row['source']} attempts={row['attempts']} "
            f"first_try={row['first_try']} issues={len(row['checker_issues'])} ms={row['latency_ms']}",
            flush=True,
        )
        if index < len(cases) - 1:
            time.sleep(PAUSE_S)

    accepted = [row for row in rows if row["source"] == "llm"]
    first = [row for row in accepted if row["first_try"] is True]
    retried = [row for row in accepted if row["first_try"] is False]
    backup = [row for row in rows if row["source"] == "template"]
    bad = [row for row in rows if row["checker_issues"]]
    print("---", flush=True)
    print(f"model_text {len(accepted)}/{len(rows)}", flush=True)
    print(f"first_try {len(first)}/{len(rows)}", flush=True)
    print(f"accepted_after_rewrite {len(retried)}/{len(rows)}", flush=True)
    print(f"python_backup {len(backup)}/{len(rows)}", flush=True)
    print(f"published_with_checker_issues {len(bad)}/{len(rows)}", flush=True)
    print(f"wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
