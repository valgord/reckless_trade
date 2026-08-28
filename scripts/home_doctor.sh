#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT_DIR"

ENV_FILE=${ENV_FILE:-.env}
CONFIG_ONLY=false
[[ ${1:-} == "--config-only" ]] && CONFIG_ONLY=true

failures=0
warnings=0

pass() { printf 'PASS  %s\n' "$1"; }
warn() { printf 'WARN  %s\n' "$1"; warnings=$((warnings + 1)); }
fail() { printf 'FAIL  %s\n' "$1"; failures=$((failures + 1)); }

value_for() {
    awk -F= -v key="$1" '$1 == key {sub(/^[^=]*=/, ""); print; exit}' "$ENV_FILE"
}

if [[ ! -f "$ENV_FILE" ]]; then
    fail "$ENV_FILE is missing; start with: cp .env.home.example .env"
    exit 1
fi

load_home_environment() {
    local key value
    local keys=(
        TRADING_MODE ALLOW_LIVE_TRADING RUN_NAUTILUS_NODE ENABLE_DEMO_STRATEGY ENABLE_CARRY_OBSERVER
        NEWS_FORWARD_TO_INTELLIGENCE INTELLIGENCE_ENABLED
        CARRY_ALERT_LLM_ENABLED CARRY_ALERT_STALE_SECONDS CARRY_ALERT_PROFIT_REVIEW_USDT
        CARRY_ALERT_MAXIMUM_LOSS_USDT CARRY_ALERT_MIN_FUNDING_SETTLEMENTS CARRY_ALERT_WEBHOOK_URL
        TELEGRAM_ALERTS_ENABLED TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID
        CARRY_SCANNER_REST_URL CARRY_SCANNER_SYMBOLS CARRY_SCANNER_MAX_SYMBOLS
        CARRY_SCANNER_FUNDING_HISTORY_LIMIT CARRY_SCANNER_TARGET_NOTIONAL_USDT
        CARRY_SCANNER_HORIZON_SETTLEMENTS CARRY_SCANNER_MIN_TURNOVER_24H_USDT
        CARRY_SCANNER_MIN_FUNDING_SAMPLES CARRY_SCANNER_MIN_POSITIVE_SHARE
        CARRY_SCANNER_HISTORY_DB CARRY_SCANNER_HISTORY_RETENTION_DAYS CARRY_SCANNER_ALERT_STATE_PATH
        POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD DATABASE_URL
        QDRANT_URL QDRANT_COLLECTION
        OLLAMA_DEPLOYMENT OLLAMA_IMAGE OLLAMA_VOLUME_NAME OLLAMA_BASE_URL OLLAMA_EXTERNAL_URL
        OLLAMA_HOST_CHECK_URL OLLAMA_EXTERNAL_DOCKER_NETWORK OLLAMA_MODEL HOME_DOCKER_SUBNET
    )
    for key in "${keys[@]}"; do
        value=$(value_for "$key")
        if [[ -n $value ]]; then
            export "$key=$value"
        else
            unset "$key"
        fi
    done
}

load_home_environment
deployment=$(value_for OLLAMA_DEPLOYMENT)
deployment=${deployment:-managed}
compose=(docker compose --env-file "$ENV_FILE" -f docker-compose.yml -f docker-compose.home-network.yml)
case "$deployment" in
    managed) compose+=(-f docker-compose.home.yml) ;;
    external)
        compose+=(-f docker-compose.home.yml -f docker-compose.home-external-ollama.yml)
        external_network=$(value_for OLLAMA_EXTERNAL_DOCKER_NETWORK)
        if [[ -n $external_network ]]; then
            compose+=(-f docker-compose.home-external-ollama-network.yml)
        fi
        ;;
    *) fail "OLLAMA_DEPLOYMENT must be managed or external" ;;
esac

if command -v docker >/dev/null 2>&1; then
    pass "Docker CLI is installed"
else
    fail "Docker CLI is not installed"
fi

if [[ $failures -eq 0 ]] && "${compose[@]}" config --quiet >/dev/null 2>&1; then
    pass "Home Compose configuration is valid ($deployment Ollama)"
else
    fail "Home Compose configuration is invalid"
fi

[[ $(value_for TRADING_MODE) == "demo" ]] && pass "Trading mode is demo" || fail "TRADING_MODE must be demo"
[[ $(value_for ALLOW_LIVE_TRADING) == "false" ]] && pass "Live trading is locked" || fail "ALLOW_LIVE_TRADING must be false"
[[ $(value_for RUN_NAUTILUS_NODE) == "false" ]] \
    && pass "Nautilus runtime is initially disabled" \
    || fail "RUN_NAUTILUS_NODE must be false for initial validation"
[[ $(value_for ENABLE_CARRY_OBSERVER) == "false" ]] \
    && pass "Carry observer is initially disabled" \
    || fail "ENABLE_CARRY_OBSERVER must be false for initial validation"
[[ $(value_for NEWS_FORWARD_TO_INTELLIGENCE) == "false" ]] \
    && pass "Automatic news forwarding is locked" \
    || fail "NEWS_FORWARD_TO_INTELLIGENCE must be false for initial validation"
[[ $(value_for OLLAMA_MODEL) == "qwen3:14b" ]] && pass "Target model is qwen3:14b" || warn "Target model is not qwen3:14b"

if $CONFIG_ONLY; then
    printf '\nConfig check complete: %d failure(s), %d warning(s).\n' "$failures" "$warnings"
    [[ $failures -eq 0 ]]
    exit
fi

docker info >/dev/null 2>&1 && pass "Docker daemon is reachable" || fail "Docker daemon is not reachable"

if [[ $deployment == "managed" ]]; then
    [[ -c /dev/kfd ]] && pass "/dev/kfd is available" || fail "/dev/kfd is unavailable"
    [[ -d /dev/dri ]] && pass "/dev/dri is available" || fail "/dev/dri is unavailable"
else
    pass "GPU device checks belong to the external Ollama container"
    if [[ -n ${external_network:-} ]]; then
        docker network inspect "$external_network" >/dev/null 2>&1 \
            && pass "External Ollama Docker network is available" \
            || fail "External Ollama Docker network is unavailable: $external_network"
    fi
fi

postgres_password=$(value_for POSTGRES_PASSWORD)
if [[ -z "$postgres_password" || "$postgres_password" == "replace-with-long-random-password" || "$postgres_password" == "change-me" ]]; then
    fail "POSTGRES_PASSWORD must be replaced"
else
    pass "PostgreSQL password is configured"
fi

[[ -n $(value_for BYBIT_DEMO_API_KEY) ]] && pass "Bybit Demo API key is configured" || fail "Bybit Demo API key is missing"
[[ -n $(value_for BYBIT_DEMO_API_SECRET) ]] \
    && pass "Bybit Demo API secret is configured" \
    || fail "Bybit Demo API secret is missing"

if [[ $deployment == "managed" ]]; then
    ollama_id=$("${compose[@]}" --profile intelligence ps -q ollama 2>/dev/null || true)
    if [[ -n "$ollama_id" ]] && [[ $(docker inspect -f '{{.State.Running}}' "$ollama_id" 2>/dev/null) == "true" ]]; then
        if "${compose[@]}" --profile intelligence exec -T ollama ollama list 2>/dev/null | awk '{print $1}' | grep -Fxq "qwen3:14b"; then
            pass "qwen3:14b is visible in managed Ollama"
        else
            fail "Managed Ollama is running but qwen3:14b is not visible"
        fi
    else
        warn "Managed Ollama is stopped; model presence will be checked by make home-validate"
    fi
else
    host_check_url=$(value_for OLLAMA_HOST_CHECK_URL)
    host_check_url=${host_check_url:-http://localhost:11434}
    if curl -fsS --max-time 5 "$host_check_url/api/tags" 2>/dev/null | grep -Fq 'qwen3:14b'; then
        pass "qwen3:14b is visible in external Ollama"
    else
        fail "qwen3:14b is not reachable through $host_check_url"
    fi
fi

printf '\nHome doctor complete: %d failure(s), %d warning(s).\n' "$failures" "$warnings"
[[ $failures -eq 0 ]]
