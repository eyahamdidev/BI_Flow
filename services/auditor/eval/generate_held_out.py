"""Ask the local model for captions. The prompt does not mention the checker rules.

Writes eval/held_out_raw.json. Labels are added by hand in eval/held_out_prose.json after reading the sheet.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.pop("FAKE_LLM", None)
os.environ["LLM_MODEL_MAIN"] = os.environ.get("LLM_MODEL_MAIN", "llama3.2:latest")
os.environ["LLM_MODEL_FAST"] = os.environ.get("LLM_MODEL_FAST", "llama3.2:latest")

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services" / "auditor"))

from app.prose import render_prompt  # noqa: E402
from biflow_contracts.biflow_llm import chat_text  # noqa: E402

HERE = Path(__file__).resolve().parent


def main() -> None:
    cases = json.loads((HERE / "explain_cases.json").read_text(encoding="utf-8"))["cases"]
    sheet = cases[0]["fact_sheet"]
    user = render_prompt("auditor.adversarial_prose@v1", facts=json.dumps(sheet, ensure_ascii=False))
    text = chat_text(
        "auditor.adversarial_prose@v1",
        "You write dashboard captions.",
        user,
        role="llm_main",
        temperature=0.7,
    )
    out = {
        "model": os.environ["LLM_MODEL_MAIN"],
        "prompt_id": "auditor.adversarial_prose@v1",
        "fact_sheet": sheet,
        "raw": text,
    }
    (HERE / "held_out_raw.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
