"""One cold v6 run after the evaluative-word and required-id rules.

Uses .env. Does not print the API key. Does not write the demo cache.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services" / "auditor"))
os.environ.pop("FAKE_LLM", None)

HERE = Path(__file__).resolve().parent
MAIN = "openai/gpt-oss-120b"
SEED = 7
EFFORT = "low"


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


def _install_payload() -> None:
    import biflow_contracts.biflow_llm as llm

    original = llm.httpx.post

    def wrapped(url, json=None, **kwargs):
        payload = json
        if isinstance(payload, dict) and "messages" in payload:
            payload = dict(payload)
            payload["seed"] = SEED
            payload["reasoning_effort"] = EFFORT
        return original(url, json=payload, **kwargs)

    llm.httpx.post = wrapped


def main() -> None:
    from app.factcheck import unsupported_claims
    from app.prose import write_prose
    from app.templates import explain_template
    from biflow_contracts.biflow_llm import drain_calls

    load_env()
    os.environ["LLM_PROVIDER"] = "api"
    os.environ["LLM_BASE_URL"] = "https://api.groq.com/openai/v1"
    os.environ["BIFLOW_PROFILE"] = "api"
    os.environ["LLM_MODEL_MAIN"] = MAIN
    os.environ["LLM_MODEL_FAST"] = "openai/gpt-oss-20b"
    os.environ["EXPLAIN_KPI_VERSION"] = "v6"
    os.environ.pop("FAKE_LLM", None)
    cache = Path(tempfile.gettempdir()) / "biflow-v6-rules.sqlite"
    if cache.exists():
        cache.unlink()
    os.environ["BIFLOW_CACHE"] = str(cache)
    _install_payload()
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
        issues = unsupported_claims(result.text, case["fact_sheet"])
        rows.append(
            {
                "id": case["id"],
                "source": result.source,
                "first_try_pass": result.first_try_pass,
                "attempts": result.attempts,
                "unsupported": bool(issues),
                "answer": result.text,
            }
        )
        print(case["id"], result.source, result.first_try_pass, result.attempts, flush=True)
    n = len(rows)
    first = sum(1 for row in rows if row["source"] == "llm" and row["first_try_pass"] is True)
    after = sum(1 for row in rows if row["source"] == "llm" and row["first_try_pass"] is False)
    fallback = sum(1 for row in rows if row["source"] == "template")
    payload = {
        "model": MAIN,
        "prompt_id": "auditor.explain_kpi@v6",
        "temperature": 0,
        "seed": SEED,
        "reasoning_effort": EFFORT,
        "n": n,
        "first_try_pass_rate": round(first / n, 4) if n else None,
        "pass_after_retry_rate": round(after / n, 4) if n else None,
        "fallback_rate": round(fallback / n, 4) if n else None,
        "unsupported_statement_rate": round(sum(1 for row in rows if row["unsupported"]) / n, 4) if n else None,
        "rows": rows,
    }
    (HERE / "bakeoff_v6_rules.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print("first_try", payload["first_try_pass_rate"], "after_retry", payload["pass_after_retry_rate"], "fallback", payload["fallback_rate"], flush=True)


if __name__ == "__main__":
    main()
