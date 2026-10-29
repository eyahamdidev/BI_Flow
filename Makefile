# BIFlow developer commands. SERVICE is a folder name under services/ (etl, auditor, profile_clean, ...).
SERVICES := ingest_quality profile_clean etl semantic_kpi analyst auditor gateway dashboard
PORT_ingest_quality=8104
PORT_profile_clean=8103
PORT_etl=8101
PORT_semantic_kpi=8105
PORT_analyst=8106
PORT_auditor=8102
PORT_gateway=8000
PORT_dashboard=8501
PY ?= python3

.PHONY: help init venv run test test-all lint dev stop smoke schemas up down env

help:
	@echo "make init                 create .env and a venv for every service"
	@echo "make venv SERVICE=etl     venv + deps for one service"
	@echo "make run SERVICE=etl      run one service (BIFLOW_MOCK=1 by default)"
	@echo "make test SERVICE=etl     tests for one service"
	@echo "make test-all             tests for every service"
	@echo "make dev / make stop      start / stop ALL services locally (no Docker)"
	@echo "make smoke                end-to-end pipeline on mocks"
	@echo "make schemas              regenerate contracts/schemas/*.json"
	@echo "make up / make down       docker compose (profile core)"

env:
	@test -f .env || cp .env.example .env && echo ".env ready (edit it: Ollama or API key)"

init: env
	@for s in $(SERVICES); do $(MAKE) --no-print-directory venv SERVICE=$$s; done

venv:
	@test -n "$(SERVICE)" || (echo "usage: make venv SERVICE=etl" && exit 1)
	cd services/$(SERVICE) && $(PY) -m venv .venv && .venv/bin/pip install -q --upgrade pip \
	  && .venv/bin/pip install -q -e ../../contracts uvicorn pytest \
	  && .venv/bin/pip install -q -r requirements.in

run:
	@test -n "$(SERVICE)" || (echo "usage: make run SERVICE=etl" && exit 1)
	@set -a; test -f .env && . ./.env; set +a; export DATA_DIR=$$(pwd)/data; \
	if [ "$(SERVICE)" = "dashboard" ]; then cd services/dashboard && .venv/bin/streamlit run app/main.py --server.port=$(PORT_dashboard); \
	else cd services/$(SERVICE) && .venv/bin/uvicorn app.main:app --reload --port $(PORT_$(SERVICE)); fi

test:
	@test -n "$(SERVICE)" || (echo "usage: make test SERVICE=etl" && exit 1)
	cd services/$(SERVICE) && .venv/bin/python -m pytest -q

test-all:
	@for s in $(SERVICES); do echo "== $$s"; (cd services/$$s && .venv/bin/python -m pytest -q) || exit 1; done

lint:
	ruff check . && ruff format --check .

dev:
	@./scripts/dev_up.sh

stop:
	@./scripts/dev_down.sh

smoke:
	$(PY) -m pytest tests/smoke -q

schemas:
	$(PY) scripts/export_schemas.py

up:
	docker compose --profile core up --build

down:
	docker compose --profile core --profile ollama --profile ml down
