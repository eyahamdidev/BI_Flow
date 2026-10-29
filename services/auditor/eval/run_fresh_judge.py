"""Judge the fresh captions with gpt-oss-20b and score the checker. Does not print the API key."""

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
JUDGE = "openai/gpt-oss-20b"


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


def main() -> None:
    from app.factcheck import unsupported_claims
    from app.prose import render_prompt
    from biflow_contracts.biflow_llm import chat_text

    load_env()
    os.environ["LLM_PROVIDER"] = "api"
    os.environ["LLM_BASE_URL"] = "https://api.groq.com/openai/v1"
    os.environ["BIFLOW_PROFILE"] = "api"
    os.environ["LLM_MODEL_MAIN"] = "openai/gpt-oss-120b"
    os.environ["LLM_MODEL_FAST"] = JUDGE
    os.environ.pop("FAKE_LLM", None)
    cache = Path(tempfile.gettempdir()) / "biflow-fresh-judge.sqlite"
    if cache.exists():
        cache.unlink()
    os.environ["BIFLOW_CACHE"] = str(cache)
    doc = json.loads((HERE / "held_out_fresh.json").read_text(encoding="utf-8"))
    sheet = doc["fact_sheet"]
    rows = []
    checker_caught = 0
    judge_caught = 0
    union_caught = 0
    for item in doc["items"]:
        issues = unsupported_claims(item["prose"], sheet)
        regex_hit = bool(issues)
        user = render_prompt(
            "auditor.fact_judge@v1",
            section="fresh-held-out",
            language="English",
            facts=json.dumps(sheet, ensure_ascii=False),
            prose=item["prose"],
        )
        raw = chat_text(
            "auditor.fact_judge@v1",
            "You check a paragraph against a fact sheet.",
            user,
            role="llm_fast",
            temperature=0.0,
        )
        verdict = (raw or "").strip().split()
        failed = bool(verdict) and verdict[0].upper().startswith("FAIL")
        checker_caught += int(regex_hit)
        judge_caught += int(failed)
        union_caught += int(regex_hit or failed)
        rows.append({"id": item["id"], "checker": regex_hit, "judge_fail": failed, "issues": issues})
        print(item["id"], "CATCH" if regex_hit else "checker-miss", "FAIL" if failed else "PASS", flush=True)
    n = len(rows)
    payload = {
        "writer_model": doc["model"],
        "judge_model": JUDGE,
        "prompt_id": doc["prompt_id"],
        "source_case": doc["source_case"],
        "n_unsupported": n,
        "n_supported": 0,
        "checker_recall": round(checker_caught / n, 4) if n else None,
        "judge_recall": round(judge_caught / n, 4) if n else None,
        "union_recall": round(union_caught / n, 4) if n else None,
        "false_reject_rate": None,
        "note": "No supported captions in this set, so false-reject is not measured. Recall is on 15 captions labelled unsupported by reading the ex10 sheet.",
        "items": rows,
    }
    (HERE / "judge_fresh_held_out.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("checker", payload["checker_recall"], "judge", payload["judge_recall"], "union", payload["union_recall"], flush=True)


if __name__ == "__main__":
    main()
