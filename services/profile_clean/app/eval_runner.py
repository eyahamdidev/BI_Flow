"""Fast eval subset for POST /v1/eval (FAKE_LLM-safe)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def run_eval_subset() -> dict:
    eval_dir = Path(__file__).parent.parent / "eval"
    script = eval_dir / "run_all.py"
    if script.exists():
        proc = subprocess.run(
            [sys.executable, str(script), "--fast"],
            capture_output=True,
            text=True,
            timeout=110,
            cwd=str(eval_dir.parent),
            env={**dict(__import__("os").environ), "FAKE_LLM": "1"},
        )
        if proc.returncode == 0 and (eval_dir / "results" / "last_eval_metrics.json").exists():
            import json

            return json.loads((eval_dir / "results" / "last_eval_metrics.json").read_text(encoding="utf-8"))
    return {"note": "eval subset not run", "status": "partial"}
