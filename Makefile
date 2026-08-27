SHELL := /bin/bash
PYTHON ?= python3

.PHONY: doctor install test lint compile research-smoke up down logs demo live intelligence observability health status backup init-db restore

doctor:
	@echo "== Host =="; uname -a
	@echo "== Docker =="; docker --version
	@echo "== Compose =="; docker compose version
	@echo "== Git =="; git --version
	@echo "== Python =="; $(PYTHON) --version
	@echo "== Disk =="; df -h .

install:
	$(PYTHON) -m pip install -e '.[dev,research,intelligence]'

compile:
	$(PYTHON) -m compileall -q apps domain trading research intelligence storage platform_core scripts

test: compile
	pytest

lint:
	ruff check .

research-smoke:
	$(PYTHON) -m scripts.research_smoke

up:
	docker compose up -d --build postgres trader control-api

down:
	docker compose --profile intelligence --profile observability down

logs:
	docker compose logs -f --tail=200

demo:
	@test -f .env || (echo "Create .env from .env.example first" && exit 1)
	TRADING_MODE=demo docker compose run --rm trader python -m apps.trader.bybit_smoke

live:
	@test "$$ALLOW_LIVE_TRADING" = "true" || (echo "Refusing: export ALLOW_LIVE_TRADING=true explicitly" && exit 1)
	TRADING_MODE=live RUN_NAUTILUS_NODE=true docker compose up -d --build trader

intelligence:
	docker compose --profile intelligence up -d --build ollama qdrant intelligence news-worker

observability:
	docker compose --profile observability up -d prometheus grafana

health:
	curl -fsS http://localhost:8000/health && echo

status:
	curl -fsS http://localhost:8000/status && echo

backup:
	@mkdir -p backups
	docker compose exec -T postgres pg_dump -U $${POSTGRES_USER:-trading} $${POSTGRES_DB:-trading} | gzip > backups/postgres-$$(date +%Y%m%d-%H%M%S).sql.gz

init-db:
	docker compose run --rm trader python -m scripts.init_db

restore:
	@test -n "$(FILE)" || (echo "Usage: make restore FILE=backups/file.sql.gz" && exit 1)
	./scripts/restore_backup.sh "$(FILE)"
