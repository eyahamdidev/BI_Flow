"""Regenerate services/<svc>/requirements.lock for every service (or the ones named on the command line).

    python -m uv --version        # needs uv:  pip install uv
    python scripts/lock_all.py            # all services
    python scripts/lock_all.py etl        # one service

The lock targets the CONTAINER (Linux, Python 3.11), not the developer's laptop.
Inputs per service: its requirements.in + the contracts package deps (FastAPI services only).
Rerun after editing any requirements.in or contracts/pyproject.toml, and commit the .lock files.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NO_CONTRACTS = {"dashboard"}  # Streamlit app: talks to the gateway over HTTP, does not use the service kit


def lock(svc: str) -> None:
    d = ROOT / "services" / svc
    inputs = [str(d / "requirements.in")]
    if svc not in NO_CONTRACTS:
        inputs.append(str(ROOT / "contracts" / "pyproject.toml"))
    cmd = [
        sys.executable, "-m", "uv", "pip", "compile", *inputs,
        "--python-version", "3.11", "--python-platform", "x86_64-unknown-linux-gnu",
        "--no-header", "--quiet", "-o", str(d / "requirements.lock"),
    ]
    print(f"locking {svc} ...", flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT)


if __name__ == "__main__":
    names = sys.argv[1:] or sorted(p.name for p in (ROOT / "services").iterdir() if (p / "requirements.in").exists())
    for n in names:
        lock(n)
