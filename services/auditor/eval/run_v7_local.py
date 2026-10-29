"""Fill the local v7 arms after Ollama is up. Merges into bakeoff_v7.json."""

from __future__ import annotations

import json
from pathlib import Path

import run_v7_bakeoff as bake

HERE = Path(__file__).resolve().parent


def main() -> None:
    cases = bake._cases()
    payload = json.loads((HERE / "bakeoff_v7.json").read_text(encoding="utf-8"))
    payload["arms"]["llama-8b"] = bake._arm("llama-8b", "ollama", "llama3.1:8b", cases, 1)
    payload["arms"]["llama-3b"] = bake._arm("llama-3b", "ollama", "llama3.2:latest", cases, 1)
    local_gate = {}
    for name in ("llama-8b", "llama-3b"):
        arm = payload["arms"][name]
        local_gate[name] = bool(arm.get("first_try_pass_rate") == 1.0 and arm.get("fallback_rate") == 0.0)
    payload["gate"]["local"] = local_gate
    payload["gate"]["low_ram_default"] = "v7" if local_gate.get("llama-3b") else "v4"
    payload["gate"]["ollama_default"] = "v4"
    (HERE / "bakeoff_v7.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (HERE / "bakeoff_v7.md").write_text(bake._markdown(payload), encoding="utf-8")
    print("local_gate", local_gate, flush=True)


if __name__ == "__main__":
    main()
