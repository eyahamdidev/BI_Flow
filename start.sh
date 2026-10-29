#!/usr/bin/env bash
# BIFlow one-command start (macOS / Linux / Git Bash).
#   ./start.sh                     build + start everything, run the demo (1% Olist sample), print the dashboard URL
#   ./start.sh bike_share          run another dataset (olist_sample | bike_share | olist)
#   ./start.sh --full              download the full Olist data (Kaggle) and run it
#   ./start.sh --stop              stop everything
set -euo pipefail
cd "$(dirname "$0")"
DATASET="olist_sample"
case "${1:-}" in
  --stop) docker compose --profile core down; exit 0 ;;
  --full) DATASET="olist"; FULL=1 ;;
  "") ;;
  *) DATASET="$1" ;;
esac

echo "== BIFlow =="
docker info >/dev/null 2>&1 || { echo "Docker is not running. Start Docker, then run this script again."; exit 1; }

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example."
  read -r -p "Optional: paste an LLM API key (Groq or any OpenAI-compatible), or press Enter to run without LLM: " KEY || true
  if [ -n "${KEY:-}" ]; then
    sed "s|^LLM_API_KEY=.*|LLM_API_KEY=${KEY}|" .env > .env.tmp && mv .env.tmp .env
  fi
fi

echo "Building and starting the services (the first time takes several minutes)..."
docker compose --profile core up -d --build || { echo "Build failed (often a network hiccup): run ./start.sh again."; exit 1; }

printf "Waiting for the services"
for _ in $(seq 1 90); do
  up=0
  for p in 8000 8101 8102 8103 8104 8105 8106; do curl -sf -m 3 "http://localhost:$p/v1/meta" >/dev/null && up=$((up+1)); done
  [ "$up" -eq 7 ] && break
  printf "."; sleep 2
done
echo " ready."

if [ "${FULL:-0}" = "1" ]; then
  docker compose run --rm --no-deps -v "$PWD/scripts:/srv/scripts:ro" gateway python /srv/scripts/get_olist.py
fi
echo "Running the pipeline on '$DATASET' (sample: 1-2 min, full Olist: ~4 min)..."
docker compose exec -T gateway python -m app.cli run --dataset "$DATASET" || true
echo
echo "Dashboard: http://localhost:8501   (pick the run in the left sidebar)"
