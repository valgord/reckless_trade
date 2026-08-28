# Home server deployment

The home profile targets Bybit Demo, an AMD RX 7900 XTX and `qwen3:14b`. Its first start is deliberately passive:
the Nautilus strategy is disabled, order submission is absent, news forwarding is disabled and live trading is locked.

## 1. Prepare configuration

```bash
git clone <repository-url> reckless_trade
cd reckless_trade
cp .env.home.example .env
```

Edit `.env` locally. Replace the PostgreSQL password in both `POSTGRES_PASSWORD` and `DATABASE_URL`, add only the
Bybit Demo key and secret, and leave these values unchanged:

```dotenv
TRADING_MODE=demo
ALLOW_LIVE_TRADING=false
RUN_NAUTILUS_NODE=false
ENABLE_DEMO_STRATEGY=false
ENABLE_CARRY_OBSERVER=false
NEWS_FORWARD_TO_INTELLIGENCE=false
OLLAMA_MODEL=qwen3:14b
```

`HOME_DOCKER_SUBNET` defaults to `172.30.0.0/24` so the home stack does not depend on Docker's automatic address-pool
availability. Change it before first start if that subnet overlaps the host LAN, VPN or another Docker network.

The home scripts load deployment and safety values from `ENV_FILE` before invoking Compose. Exported shell variables
with the same names therefore cannot silently override the file that `home-doctor` inspected.

`.env`, Docker volumes, PostgreSQL contents and `data/` are not stored in Git.

## 2. Choose the Ollama owner

Use `managed` when the Ollama container and its model volume belong to this Compose project:

```dotenv
OLLAMA_DEPLOYMENT=managed
OLLAMA_IMAGE=ollama/ollama:rocm
OLLAMA_BASE_URL=http://ollama:11434
```

The managed volume name is fixed by `OLLAMA_VOLUME_NAME` and defaults to `reckless_trade_ollama_data`. Before relying on
an existing model, confirm that the existing Ollama container uses that volume or arrange a volume migration. The
validation command never pulls a model automatically.

Use `external` when another container publishes Ollama on the home host:

```dotenv
OLLAMA_DEPLOYMENT=external
OLLAMA_EXTERNAL_URL=http://host.docker.internal:11434
OLLAMA_HOST_CHECK_URL=http://localhost:11434
```

The external container must listen beyond its own loopback interface and publish port `11434` to the host. The project
does not start or modify that container.

If Ollama intentionally publishes only on host loopback, attach the two model-client services to its existing Docker
network instead. Use the Ollama service/container DNS name in the URL:

```dotenv
OLLAMA_EXTERNAL_URL=http://existing-ollama:11434
OLLAMA_EXTERNAL_DOCKER_NETWORK=existing-ollama-network
```

The network must already exist. The project joins it but does not create, restart or modify the external Ollama
container. `home-doctor` checks the network, and `home-validate` performs a structured carry-advisor inference through
the same container route used at runtime.

## 3. Inspect before starting

```bash
make home-doctor
```

For managed Ollama this checks `/dev/kfd`, `/dev/dri`, Docker, the safe trading flags, non-default PostgreSQL password,
presence of Demo credentials and, when the container is already running, `qwen3:14b`. For external Ollama it queries
the configured tags endpoint. Secret values are never printed.

## 4. Start passively

```bash
make home-up
make home-validate
```

`home-up` starts PostgreSQL, Qdrant, the intelligence API, disabled news worker, passive trader and control API. In
managed mode it also starts the ROCm Ollama service. It initializes new database tables but does not download a model.

`home-validate` checks PostgreSQL, Qdrant, both APIs, model visibility and `orders_enabled=false`.

## 5. Validate M7 manually

Git does not contain the price catalog or raw news archive. On a fresh server, acquire public BTC history and ingest a
feed once without continuous forwarding:

```bash
DAYS=365 make home-history
make home-news-once URL=https://cointelegraph.com/rss
```

Then analyse a small archived batch without enabling continuous forwarding:

```bash
LIMIT=5 make home-m7
curl -fsS http://localhost:8000/research/m7
```

Only after inspecting structured analyses, timestamps and the M7 report should news ingestion and forwarding be enabled.
Demo order submission remains a separate later decision.

## 6. Reproduce M7.5 research

Public Spot, funding and mark-price data need no API key. From the project virtual environment run:

```bash
make m75-data
make m75
curl -fsS http://localhost:8000/research/m75
```

The download starts after the known February 2022 Bybit Spot-history gap and may take several minutes. M7.5 never
submits an order; even a passing research gate leaves derivative execution and live trading disabled.

## 7. Observe carry readiness in Demo

After `home-validate` succeeds, start the separate Spot+Linear observer and inspect its state:

```bash
make demo-carry-observe
curl -fsS http://localhost:8000/runtime/carry
make demo-pause
```

Use a dedicated Demo account without unrelated BTC holdings or BTCUSDT Linear positions. The observer emits an advisory
pair or risk-reducing repair plan, but contains no order-submission path and always reports `orders_enabled=false`.
The carry-only Demo cap is 100 USDT per leg with a 50 USDT reserve. This is enough for the current `0.001 BTC` Linear
minimum; the ordinary Demo/order-smoke cap remains 10 USDT and live settings are not changed.

## 8. One-shot Demo pair

Only after `/runtime/carry` reports `flat_ready`, open one virtual pair with the exact confirmation:

```bash
make demo-carry-open CONFIRM=I_UNDERSTAND_THIS_PLACES_DEMO_CARRY_ORDERS
make demo-carry-observe
curl -fsS http://localhost:8000/runtime/carry
```

Close only the quantity recorded in the ownership ledger with:

```bash
make demo-carry-close CONFIRM=I_UNDERSTAND_THIS_PLACES_DEMO_CARRY_ORDERS
```

Both commands reconcile fills and compensate incomplete pairs. They affect Demo only; automatic execution and live
trading remain disabled.

Keep the pair observer and read-only performance monitor running, or request a one-time report:

```bash
make demo-carry-observe
make demo-carry-report
curl -fsS http://localhost:8000/runtime/carry
```

The report separates basis PnL, actual funding and fees. Treat `estimated_net_pnl_usdt` as mark-to-market only until a
confirmed paired close establishes the realized result.

If an executor-created Demo pair is still open but the local `data/runtime/carry-pair.json` and ownership journal were
lost, first run the observer and then use `make demo-carry-recover`. Recovery is local-only: it searches read-only
Bybit execution history for exactly one matching `rt-carry-open-*` Spot/Linear pair, verifies the reconciled short,
BTC coverage and absence of open orders, and refuses to overwrite existing journals. It never submits an order.
Use `make home-carry-recover` while the home Compose stack is running so recovery reuses the same network overlays.

## 9. Start alerts with the local 14B model

After `make home-validate` confirms `qwen3:14b`, start the carry observer, performance monitor and alert worker through
the same managed/external Ollama Compose selection:

```bash
make home-carry
curl -fsS http://localhost:8000/runtime/carry
```

The model only explains deterministic alerts. It has no exchange credentials, order API or authority to approve a
repair/close. Set `CARRY_ALERT_WEBHOOK_URL` only for an endpoint you control; sanitized state is sent once when the alert
fingerprint changes. With no webhook, alerts remain available through the runtime API and JSON status file.

For Telegram delivery, create a bot, send it `/start`, and put only its token in `TELEGRAM_BOT_TOKEN`. Keep delivery
disabled while discovering and testing the destination:

```bash
make home-telegram-setup
# Copy the returned numeric chat_id into TELEGRAM_CHAT_ID in .env.
make home-telegram-test
```

After the test message arrives, set `TELEGRAM_ALERTS_ENABLED=true` and restart `carry-alerts`. Telegram receives a
message only when the deterministic alert fingerprint changes. The notifier sends messages but does not poll or
implement Telegram commands.

```bash
make home-carry-alerts-restart
```

The 14B response is accepted only if its echoed monitor state, position phase and alert codes exactly match the
deterministic payload. A mismatch hides all generated prose and Telegram shows a safe rejection notice instead.

## 10. Scan multiple carry candidates without orders

Run a one-shot public market scan:

```bash
make home-carry-scan
curl -fsS http://localhost:8000/runtime/carry-scanner
```

After validating the first snapshot, start continuous five-minute refreshes with `make home-carry-scanner-start`.
This target recreates only `carry-scanner` and `control-api`; it does not restart the trader or open-pair monitor.

The scanner receives no Bybit credentials. By default it examines up to 20 of the most liquid common USDT Spot and
Linear Perpetual symbols and records recent funding stability, top-of-book capacity, minimum pair notional, explicit
round-trip taker fees and the estimated net result over three settlements. It cannot open or recommend a pair for
execution; multi-pair Demo trading requires a later ownership and portfolio-risk gate.

Each five-minute snapshot is compacted into a local SQLite history with 90-day retention:

```bash
curl -fsS 'http://localhost:8000/runtime/carry-scanner/history?symbol=BTCUSDT&limit=100'
```

The first alert-worker observation is a silent baseline. If a later snapshot changes a symbol from ineligible to
eligible, Telegram sends one review-only notification. The persistent transition state prevents duplicate messages
after restarts; it does not approve or submit a pair.
