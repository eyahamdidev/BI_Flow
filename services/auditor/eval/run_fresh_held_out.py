"""Ask gpt-oss-120b for 15 captions from one fact sheet. The prompt has no checker rules.

Writes eval/held_out_fresh_raw.json. Labels are added after reading the sheet.
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
    from app.prose import render_prompt
    from biflow_contracts.biflow_llm import chat_text

    load_env()
    os.environ["LLM_PROVIDER"] = "api"
    os.environ["LLM_BASE_URL"] = "https://api.groq.com/openai/v1"
    os.environ["BIFLOW_PROFILE"] = "api"
    os.environ["LLM_MODEL_MAIN"] = "openai/gpt-oss-120b"
    os.environ["LLM_MODEL_FAST"] = "openai/gpt-oss-20b"
    os.environ.pop("FAKE_LLM", None)
    cache = Path(tempfile.gettempdir()) / "biflow-fresh-held-out.sqlite"
    if cache.exists():
        cache.unlink()
    os.environ["BIFLOW_CACHE"] = str(cache)
    cases = json.loads((HERE / "explain_cases.json").read_text(encoding="utf-8"))["cases"]
    sheet = next(case["fact_sheet"] for case in cases if case["id"] == "ex10")
    user = render_prompt("auditor.adversarial_prose@v2", facts=json.dumps(sheet, ensure_ascii=False))
    text = chat_text(
        "auditor.adversarial_prose@v2",
        "You write dashboard captions.",
        user,
        role="llm_main",
        temperature=0.7,
    )
    out = {
        "model": "openai/gpt-oss-120b",
        "prompt_id": "auditor.adversarial_prose@v2",
        "source_case": "ex10",
        "fact_sheet": sheet,
        "raw": text,
    }
    (HERE / "held_out_fresh_raw.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
