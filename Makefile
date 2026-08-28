SHELL := /bin/bash
PYTHON ?= python3
M75_START ?= 2022-02-05T07:00:00+00:00

.PHONY: doctor home-doctor home-config home-up home-validate home-history home-news-once home-m7 install test lint compile research-smoke history history-m5 carry-data m75-data m75 nautilus-backtest m2 m3 m4 m5 m6 m7 news-once up down logs demo-public demo demo-order-smoke demo-observe demo-carry-observe demo-carry-report demo-carry-open demo-carry-close demo-pause live intelligence observability health status backup init-db restore

doctor:
	@echo "== Host =="; uname -a
	@echo "== Docker =="; docker --version
	@echo "== Compose =="; docker compose version
	@echo "== Git =="; git --version
	@echo "== Python =="; $(PYTHON) --version
	@echo "== Disk =="; df -h .

home-config:
	ENV_FILE=.env.home.example ./scripts/home_doctor.sh --config-only

home-doctor:
	./scripts/home_doctor.sh

home-up:
	./scripts/home_stack.sh up

home-validate:
	./scripts/home_stack.sh validate

home-history:
	DAYS=$${DAYS:-365} ./scripts/home_stack.sh history

home-news-once:
	@test -n "$(URL)" || (echo "Usage: make home-news-once URL=https://example.com/rss" && exit 1)
	URL="$(URL)" ./scripts/home_stack.sh news-once

home-m7:
	LIMIT=$${LIMIT:-5} ./scripts/home_stack.sh m7

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

history:
	$(PYTHON) -m scripts.bybit_history --days $${DAYS:-365}

history-m5:
	$(PYTHON) -m scripts.bybit_history --instrument ETHUSDT-SPOT.BYBIT --days $${DAYS:-365}
	$(PYTHON) -m scripts.bybit_history --instrument SOLUSDT-SPOT.BYBIT --days $${DAYS:-365}

carry-data:
	$(PYTHON) -m scripts.bybit_carry_data --days $${DAYS:-365}

m75-data:
	$(PYTHON) -m scripts.bybit_history --start $(M75_START)
	$(PYTHON) -m scripts.bybit_carry_data --start $(M75_START)

m75:
	$(PYTHON) -m scripts.m75_research

nautilus-backtest:
	$(PYTHON) -m scripts.nautilus_backtest

m2: history nautilus-backtest

m3:
	$(PYTHON) -m scripts.m3_research

m4:
	$(PYTHON) -m scripts.m4_research

m5:
	$(PYTHON) -m scripts.m5_research

m6:
	docker compose --profile news up -d --build news-worker control-api

m7:
	docker compose --profile intelligence up -d ollama qdrant
	docker compose exec ollama ollama pull $${OLLAMA_MODEL:-qwen3:0.6b}
	INTELLIGENCE_ENABLED=true OLLAMA_MODEL=$${OLLAMA_MODEL:-qwen3:0.6b} docker compose --profile intelligence run --rm --build intelligence python -m scripts.m7_analyse --limit $${LIMIT:-5}
	docker compose run --rm --build trader python -m scripts.m7_research

news-once:
	@test -n "$(URL)" || (echo "Usage: make news-once URL=https://example.com/rss" && exit 1)
	docker compose --profile news run --rm -e NEWS_RSS_URLS="$(URL)" -e NEWS_ENABLED=true news-worker python -m scripts.news_ingest_once

up:
	docker compose up -d --build postgres trader control-api

down:
	docker compose --profile intelligence --profile observability --profile carry down

logs:
	docker compose logs -f --tail=200

demo-public:
	TRADING_MODE=demo docker compose run --rm trader python -m apps.trader.bybit_smoke --public-only

demo:
	@test -f .env || (echo "Create .env from .env.example first" && exit 1)
	TRADING_MODE=demo docker compose run --rm trader python -m apps.trader.bybit_smoke

demo-order-smoke:
	@test "$(CONFIRM)" = "I_UNDERSTAND_THIS_PLACES_A_DEMO_ORDER" || (echo "Refusing: pass CONFIRM=I_UNDERSTAND_THIS_PLACES_A_DEMO_ORDER" && exit 1)
	TRADING_MODE=demo docker compose run --rm -e BYBIT_DEMO_ORDER_SMOKE_CONFIRMATION="$(CONFIRM)" trader python -m apps.trader.bybit_smoke --order-smoke

demo-observe:
	docker compose --profile carry stop carry-monitor
	TRADING_MODE=demo RUN_NAUTILUS_NODE=true ENABLE_DEMO_STRATEGY=true ENABLE_CARRY_OBSERVER=false docker compose up -d --build --force-recreate trader control-api

demo-carry-observe:
	TRADING_MODE=demo RUN_NAUTILUS_NODE=true ENABLE_DEMO_STRATEGY=false ENABLE_CARRY_OBSERVER=true docker compose --profile carry up -d --build --force-recreate trader control-api carry-monitor

demo-carry-report:
	docker compose --profile carry run --rm --build carry-monitor python -m apps.trader.carry_monitor

demo-carry-open:
	@test "$(CONFIRM)" = "I_UNDERSTAND_THIS_PLACES_DEMO_CARRY_ORDERS" || (echo "Refusing: pass CONFIRM=I_UNDERSTAND_THIS_PLACES_DEMO_CARRY_ORDERS" && exit 1)
	docker compose run --rm --build -e BYBIT_DEMO_CARRY_CONFIRMATION="$(CONFIRM)" trader python -m apps.trader.carry_pair open

demo-carry-close:
	@test "$(CONFIRM)" = "I_UNDERSTAND_THIS_PLACES_DEMO_CARRY_ORDERS" || (echo "Refusing: pass CONFIRM=I_UNDERSTAND_THIS_PLACES_DEMO_CARRY_ORDERS" && exit 1)
	docker compose run --rm --build -e BYBIT_DEMO_CARRY_CONFIRMATION="$(CONFIRM)" trader python -m apps.trader.carry_pair close

demo-pause:
	docker compose --profile carry stop carry-monitor
	TRADING_MODE=demo RUN_NAUTILUS_NODE=false ENABLE_DEMO_STRATEGY=false ENABLE_CARRY_OBSERVER=false docker compose up -d --force-recreate trader control-api

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
