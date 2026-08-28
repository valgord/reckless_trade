#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT_DIR"

ENV_FILE=${ENV_FILE:-.env}
export ENV_FILE
[[ -f "$ENV_FILE" ]] || { echo "$ENV_FILE is missing; run: cp .env.home.example .env"; exit 1; }

value_for() {
    awk -F= -v key="$1" '$1 == key {sub(/^[^=]*=/, ""); print; exit}' "$ENV_FILE"
}

deployment=$(value_for OLLAMA_DEPLOYMENT)
deployment=${deployment:-managed}
compose=(docker compose --env-file "$ENV_FILE" -f docker-compose.yml -f docker-compose.home.yml)
services=(postgres qdrant intelligence news-worker trader control-api)
if [[ $deployment == "external" ]]; then
    compose+=(-f docker-compose.home-external-ollama.yml)
elif [[ $deployment == "managed" ]]; then
    services=(postgres ollama qdrant intelligence news-worker trader control-api)
else
    echo "OLLAMA_DEPLOYMENT must be managed or external"
    exit 1
fi

case "${1:-}" in
    up)
        scripts/home_doctor.sh
        "${compose[@]}" --profile intelligence up -d --build "${services[@]}"
        "${compose[@]}" --profile intelligence run --rm trader python -m scripts.init_db
        ;;
    validate)
        "${compose[@]}" --profile intelligence ps
        "${compose[@]}" exec -T postgres pg_isready \
            -U "$(value_for POSTGRES_USER)" -d "$(value_for POSTGRES_DB)"
        curl -fsS --max-time 10 http://localhost:8000/ready >/dev/null
        echo "PASS  Control API and PostgreSQL are ready"
        curl -fsS --max-time 10 http://localhost:8010/health >/dev/null
        echo "PASS  Intelligence API is ready"
        curl -fsS --max-time 10 http://localhost:6333/readyz >/dev/null
        echo "PASS  Qdrant is ready"
        if [[ $deployment == "managed" ]]; then
            "${compose[@]}" --profile intelligence exec -T ollama ollama list \
                | awk '{print $1}' | grep -Fxq "qwen3:14b"
        else
            host_check_url=$(value_for OLLAMA_HOST_CHECK_URL)
            host_check_url=${host_check_url:-http://localhost:11434}
            curl -fsS --max-time 10 "$host_check_url/api/tags" | grep -Fq 'qwen3:14b'
        fi
        echo "PASS  qwen3:14b is available"
        curl -fsS --max-time 10 http://localhost:8000/runtime/demo-strategy | grep -Fq '"orders_enabled":false'
        curl -fsS --max-time 10 http://localhost:8000/runtime/carry | grep -Fq '"orders_enabled":false'
        echo "PASS  Strategy and carry order submission are disabled"
        ;;
    m7)
        "${compose[@]}" --profile intelligence run --rm --no-deps intelligence \
            python -m scripts.m7_analyse --limit "${LIMIT:-5}"
        "${compose[@]}" --profile intelligence run --rm trader python -m scripts.m7_research
        ;;
    history)
        "${compose[@]}" --profile intelligence run --rm trader \
            python -m scripts.bybit_history --days "${DAYS:-365}"
        ;;
    news-once)
        [[ -n ${URL:-} ]] || { echo "URL is required"; exit 2; }
        "${compose[@]}" --profile intelligence run --rm --no-deps \
            -e NEWS_ENABLED=true \
            -e NEWS_RSS_URLS="$URL" \
            -e NEWS_FORWARD_TO_INTELLIGENCE=false \
            news-worker python -m scripts.news_ingest_once
        ;;
    *)
        echo "Usage: $0 up|validate|history|news-once|m7"
        exit 2
        ;;
esac
