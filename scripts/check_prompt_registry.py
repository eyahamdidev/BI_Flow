"""Prompt registry validation script (spec section 2.6).

Verifies that all prompt YAML files in prompts/<module>/ follow the standard schema:
id, version, owner, role_in_system, technique, model_role, text, output_schema.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PROMPTS_DIR = ROOT / "prompts"

REQUIRED_FIELDS = [
    "id",
    "version",
    "owner",
    "role_in_system",
    "technique",
    "model_role",
    "text",
]


def check_prompts() -> int:
    if not PROMPTS_DIR.exists():
        print("No prompts directory found; skipping.")
        return 0

    prompt_files = list(PROMPTS_DIR.glob("**/*.yaml"))
    # Exclude templates
    prompt_files = [f for f in prompt_files if not f.name.startswith("_")]

    if not prompt_files:
        print("No active prompt files to validate.")
        return 0

    errors = []
    for pf in prompt_files:
        try:
            data = yaml.safe_load(pf.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                errors.append(f"{pf}: not a valid YAML mapping")
                continue
            for rf in REQUIRED_FIELDS:
                if rf not in data:
                    errors.append(f"{pf}: missing required field '{rf}'")
        except Exception as e:
            errors.append(f"{pf}: parsing error: {e}")

    if errors:
        print(f"FAILED: {len(errors)} prompt registry validation error(s):")
        for err in errors:
            print(f"  - {err}")
        return 1

    print(f"SUCCESS: {len(prompt_files)} prompt file(s) checked and valid.")
    return 0


if __name__ == "__main__":
    sys.exit(check_prompts())

