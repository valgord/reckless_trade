#!/usr/bin/env bash
set -euo pipefail
: "${ALLOW_LIVE_TRADING:?ALLOW_LIVE_TRADING must be explicitly set}"
[[ "$ALLOW_LIVE_TRADING" == "true" ]] || { echo "Live trading locked"; exit 1; }
: "${BYBIT_API_KEY:?BYBIT_API_KEY missing}"
: "${BYBIT_API_SECRET:?BYBIT_API_SECRET missing}"
echo "Live safety gate passed"
