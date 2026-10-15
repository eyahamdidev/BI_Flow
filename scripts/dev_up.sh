#!/usr/bin/env bash
# Start every module + gateway locally without Docker, each with its own venv. Logs in .run/.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p .run data
[ -f .env ] && set -a && . ./.env && set +a
export DATA_DIR="$(pwd)/data"
declare -A PORTS=( [etl]=8101 [auditor]=8102 [profile_clean]=8103 [ingest_quality]=8104 [semantic_kpi]=8105 [analyst]=8106 [gateway]=8000 )
for s in "${!PORTS[@]}"; do
  (cd "services/$s" && nohup .venv/bin/uvicorn app.main:app --port "${PORTS[$s]}" > "../../.run/$s.log" 2>&1 & echo $! > "../../.run/$s.pid")
  echo "started $s on :${PORTS[$s]}"
done
echo "dashboard: make run SERVICE=dashboard   |   pipeline: (cd services/gateway && .venv/bin/python -m app.cli run --dataset olist)"
