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
NEWS_FORWARD_TO_INTELLIGENCE=false
OLLAMA_MODEL=qwen3:14b
```

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
