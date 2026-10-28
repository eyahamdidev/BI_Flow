"""Demo checks for the explanation store. Does not print the API key.

(a) three stored cases, model URL unreachable: same text, no model call.
(b) a case that is not stored, model URL unreachable: frame fallback and a warning.
(c) an empty sheet: the abstain sentence, with no model call.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services" / "auditor"))

from app.demo_checks import empty_sheet_ok, store_hit_ok, unreachable_fallback_ok  # noqa: E402
from app.explain_store import explanation_key, load_explanation, response_sha256, save_explanation  # noqa: E402
from app.factsheet import explain_fact_sheet  # noqa: E402
from app.handlers import explain  # noqa: E402
from biflow_contracts import RunRequest  # noqa: E402

HERE = Path(__file__).resolve().parent
PROMPT = "auditor.explain_kpi@v7"
MODEL = "openai/gpt-oss-120b"
UNREACHABLE = "http://127.0.0.1:9"


def load_env() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _say(ok: bool, name: str, detail: str) -> bool:
    print(f"{'PASS' if ok else 'FAIL'} {name} {detail}", flush=True)
    return ok


def _block_network() -> None:
    os.environ["DATA_DIR"] = str(ROOT / "data")
    os.environ["FAKE_LLM"] = "0"
    os.environ.pop("FAKE_LLM", None)
    os.environ["BIFLOW_MOCK"] = "0"
    os.environ["BIFLOW_MIN_INTERVAL"] = "0"
    os.environ["LLM_PROVIDER"] = "api"
    os.environ["LLM_BASE_URL"] = UNREACHABLE
    os.environ["LLM_MODEL_MAIN"] = MODEL
    os.environ["BIFLOW_PROFILE"] = "api"
    os.environ["explain_kpi_version"] = "v7"
    os.environ["EXPLAIN_KPI_VERSION"] = "v7"


def _write_case_files(run_id: str, case: dict) -> dict:
    sheet = case["fact_sheet"]
    definition = sheet.get("definition") if isinstance(sheet.get("definition"), dict) else {}
    defs = [
        {
            "id": case["kpi_id"],
            "name": definition.get("name"),
            "description": definition.get("description"),
            "sql": definition.get("sql"),
            "unit": definition.get("unit"),
            "grain": definition.get("grain"),
            "caveats": definition.get("caveats"),
        }
    ]
    base = ROOT / "data" / "runs" / run_id
    drivers_path = base / "05_insights" / "drivers.json"
    defs_path = base / "04_kpi" / "kpi_definitions.json"
    drivers_path.parent.mkdir(parents=True, exist_ok=True)
    defs_path.parent.mkdir(parents=True, exist_ok=True)
    drivers_path.write_text(json.dumps([sheet.get("drivers") or {}], ensure_ascii=False), encoding="utf-8")
    defs_path.write_text(json.dumps(defs, ensure_ascii=False), encoding="utf-8")
    inputs = {
        "analyse.drivers": f"runs/{run_id}/05_insights/drivers.json",
        "kpi_compute.kpi_definitions": f"runs/{run_id}/04_kpi/kpi_definitions.json",
    }
    runtime = explain_fact_sheet(
        kpi_id=str(case["kpi_id"]),
        period=str(case["period"]),
        compare_to=case.get("compare_to"),
        definitions=defs,
        graph={},
        drivers_doc=[sheet.get("drivers") or {}],
        insights=[],
    )
    return {"inputs": inputs, "sheet": runtime}


def _explain(run_id: str, case: dict, inputs: dict) -> dict:
    body = {
        "request_id": "demo-check",
        "run_id": run_id,
        "dataset": "olist",
        "mode": "explain",
        "lang": "en",
        "options": {
            "offline_registry": True,
            "explain_kpi_version": "v7",
            "kpi_id": case["kpi_id"],
            "period": case["period"],
            "compare_to": case.get("compare_to"),
        },
        "inputs": inputs,
    }
    return explain(RunRequest(**body))


def _copy_published_text(case: dict, runtime_sheet: dict) -> str | None:
    published_key = explanation_key(
        str(case["kpi_id"]),
        str(case["period"]),
        case.get("compare_to"),
        case["fact_sheet"],
        PROMPT,
        MODEL,
    )
    stored = load_explanation(published_key)
    if stored is None:
        return None
    runtime_key = explanation_key(
        str(case["kpi_id"]),
        str(case["period"]),
        case.get("compare_to"),
        runtime_sheet,
        PROMPT,
        MODEL,
    )
    save_explanation(
        {
            "key": runtime_key,
            "response_sha256": response_sha256(stored["text"]),
            "text": stored["text"],
            "prose_source": stored.get("prose_source") or "llm",
            "attempts": stored.get("attempts") or 1,
            "warning": stored.get("warning"),
            "citations": stored.get("citations") or [],
            "citation_method": stored.get("citation_method") or "declared_field_id",
            "prompt_version": PROMPT,
            "model": MODEL,
        }
    )
    return str(stored["text"])


def main() -> int:
    load_env()
    _block_network()
    cases = json.loads((HERE / "explain_cases.json").read_text(encoding="utf-8"))["cases"][:3]
    ok = True
    for case in cases:
        prepared = _write_case_files(f"demo-{case['id']}", case)
        expected = _copy_published_text(case, prepared["sheet"])
        if expected is None:
            ok = _say(False, f"store-hit {case['id']}", "no published v7 text in the store") and ok
            continue
        result = _explain(f"demo-{case['id']}", case, prepared["inputs"])
        passed = store_hit_ok(result, expected)
        calls = len(result.get("llm_calls") or [])
        ok = _say(passed, f"store-hit {case['id']}", f"store={result['metrics'].get('explanation_store')} calls={calls}") and ok

    missing = {
        "id": "demo-missing",
        "kpi_id": "revenue",
        "period": f"1999-{uuid.uuid4().hex[:8]}",
        "compare_to": "1998-12",
        "fact_sheet": {
            "kpi_id": "revenue",
            "period": "1999-01",
            "compare_to": "1998-12",
            "definition": {"name": "Revenue", "unit": "BRL", "description": "Total payments received"},
            "drivers": {"total_delta": 10, "contributions": [{"dimension_value": "SP", "delta": 10}, {"dimension_value": "RJ", "delta": 4}]},
        },
    }
    prepared = _write_case_files("demo-missing", missing)
    result = _explain("demo-missing", missing, prepared["inputs"])
    warning = "; ".join(result.get("warnings") or [])
    ok = _say(
        unreachable_fallback_ok(result),
        "unreachable-fallback",
        f"source={result['metrics'].get('prose_source')} store={result['metrics'].get('explanation_store')} warning={warning[:160]}",
    ) and ok

    empty_case = {"id": "demo-empty", "kpi_id": "revenue", "period": "1999-02", "compare_to": "1999-01", "fact_sheet": {}}
    result = _explain("demo-empty", empty_case, {})
    ok = _say(
        empty_sheet_ok(result),
        "empty-sheet",
        f"answer={result['metrics'].get('answer')} calls={len(result.get('llm_calls') or [])}",
    ) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
