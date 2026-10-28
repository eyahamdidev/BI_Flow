#!/usr/bin/env bash
# Store demo. The model URL is forced unreachable inside demo_check.py.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"
python services/auditor/eval/demo_check.py
