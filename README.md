# Trading Platform

Production-oriented, home-server-friendly algorithmic trading platform. The first deployment target is Bybit Demo + BTC/USDT Spot, but domain and strategy code is venue/asset independent.

## What is already implemented

- NautilusTrader 1.231.0 is pinned as the trading kernel and isolated under `apps/trader/integrations`.
- Separate `backtest`, `demo`, and `live` configurations; live needs an explicit environment gate.
- Domain model for instruments, bars, normalized signals, portfolio targets/snapshots, and replay-safe LLM events.
- Alpha library: trend following, volatility-normalized momentum, z-score mean reversion, and breakout.
- Weighted signal aggregation, configurable strategy weights, long-only portfolio construction, reserve budget, and asset caps.
- Portfolio target risk validation plus runtime drawdown kill-switch policy.
- Execution-intent planning kept separate from alpha generation.
- Research-only fast bar backtester with fee, spread, and slippage modeling; production backtests are intended for Nautilus `BacktestNode` + Parquet catalog.
- Research metrics, walk-forward folds, and bootstrap robustness checks.
- Typed Bybit Demo/Mainnet TradingNode configuration using the official Nautilus adapter.
- Bybit Demo public, authenticated read-only, reconciliation and guarded order/cancel smoke checks.
- RSS news ingestion, deduplication, Ollama structured JSON classification, strict availability timestamps, and News Alpha adapter.
- PostgreSQL audit models/repository for experiments, raw news, LLM analyses, and strategy decisions.
- Optional Ollama (ROCm), Qdrant, Prometheus, and Grafana Docker Compose profiles.
- Structured logging, health/readiness/status endpoints, backup/restore, CI, and a deterministic synthetic research smoke test.

See `docs/IMPLEMENTATION_STATUS.md`, `docs/RESEARCH_POLICY.md`, and `docs/adr/ADR-001-architecture.md`.

The RX 7900 XTX deployment path, including managed and external Ollama modes, is documented in
[`docs/HOME_SERVER.md`](docs/HOME_SERVER.md). `make home-doctor` performs a read-only preflight; `make home-up` starts a
passive Demo stack, and `make home-validate` verifies the services and confirms that order submission is disabled.

## Architecture

```text
Exchange market data -----> Nautilus adapter -----> alpha models -----+
                                                                    |
News/RSS -> dedup -> LLM -> IntelligenceEvent -> NewsAlpha --------+--> Signal Aggregator
                                                                         |
                                                                  Portfolio Constructor
                                                                         |
                                                                      Risk
                                                                         |
                                                                  Execution Planner
                                                                         |
                                                               Nautilus Execution
                                                                         |
                                                                      Venue
```

LLM/intelligence never receives exchange credentials and cannot call execution APIs.

## First local run

```bash
cp .env.example .env
make doctor
make install
make test
make research-smoke
make up
make init-db
make health
make status
```

The public Bybit Demo connectivity check does not require credentials:

```bash
make demo-public
```

For authenticated account, balance and open-order reconciliation checks, create Demo credentials, put only
`BYBIT_DEMO_API_KEY` and `BYBIT_DEMO_API_SECRET` in `.env`, then run:

```bash
make demo
```

The order lifecycle check is separately locked. It submits a small post-only Demo limit order and immediately attempts
to cancel it, including when the submit response is lost:

```bash
make demo-order-smoke CONFIRM=I_UNDERSTAND_THIS_PLACES_A_DEMO_ORDER
```

The order notional is capped by `BYBIT_DEMO_ORDER_SMOKE_MAX_NOTIONAL` (10 USDT by default). Smoke results contain no
keys, personal account data or balance amounts. They are written to `data/runtime/bybit-smoke.json` and exposed at
`GET /integrations/bybit`.

Actual continuous Nautilus node execution remains disabled until `RUN_NAUTILUS_NODE=true` is explicitly set.

The first continuous runtime is an orderless Demo observer. It requests historical bars, subscribes to live bars and
runs the existing alpha, portfolio and risk pipeline without an order submission path:

```bash
make demo-observe
```

Its sanitized state is exposed at `GET /runtime/demo-strategy`. The Nautilus risk engine is still active with a
10 USDT per-order ceiling and a one-submit-per-minute throttle. Return to the passive runtime with `make demo-pause`.

## Nautilus historical backtest

Download completed public Bybit bars into the incremental Parquet catalog and run the same domain pipeline through
Nautilus `BacktestNode`:

```bash
make m2
```

Use `DAYS=30 make history` for a shorter data update. The report is written atomically to
`data/runtime/nautilus-backtest.json` and exposed at `GET /research/backtest`. The configured one-way cost is charged
on every simulated fill as `fees + slippage + half-spread`; the default is `12.5 bps`.

The first 365-day baseline produced `-25.96%` in USDT versus `-27.95%` buy-and-hold, with 2,048 orders. This is a
pipeline validation result, not evidence that the strategy is suitable for Demo orders.

## M3 research validation

Run the candidate ablation/sweep, expanding walk-forward selection, regime attribution, cost stress, DSR/PBO,
bootstrap analysis and final Nautilus confirmation with:

```bash
make m3
```

Every trial is appended to `data/runtime/experiment-registry.jsonl`. The summary is written to
`data/runtime/m3-research.json` and exposed at `GET /research/m3`. Promotion remains automatically rejected unless
all OOS, stress, selection-risk and Nautilus-fidelity criteria pass.

## M4 alpha research

Run the regime-gated trend, core and volatility-expansion candidates with the same validation and Nautilus
confirmation path:

```bash
make m4
```

The M4 report is written to `data/runtime/m4-research.json` and exposed at `GET /research/m4`. Candidates must meet a
minimum activity threshold; a cash-only or practically inactive strategy cannot win merely by avoiding a falling BTC
benchmark.

## M5 portfolio research

Download the additional ETH/SOL history once, then run the aligned multi-asset portfolio experiment:

```bash
make history-m5
make m5
```

M5 compares BTC-only, equal-active, inverse-volatility and correlation-budgeted allocations. It enforces total,
single-asset, correlated-pair and venue limits, charges turnover costs and permanently flattens a trial at the drawdown
kill switch. The report is written to `data/runtime/m5-research.json` and exposed at `GET /research/m5`.

## M6 news ingestion

Configure comma-separated feeds in `NEWS_RSS_URLS`, keep `NEWS_FORWARD_TO_INTELLIGENCE=false` for ingestion-only
operation, and start the independent news profile:

```bash
make m6
```

For a deterministic one-shot operational check use `make news-once URL=https://example.com/feed`. Articles are archived
before optional downstream delivery under `data/news/raw/YYYY/MM/DD`, deduplicated by fingerprint, and stored with
separate publication and first-seen timestamps. Durable source health is exposed at `GET /intelligence/news`.

## M7 LLM intelligence

M7 validates model output against a strict versioned schema, hashes the actual prompt contract, assigns stable event
IDs and stores every timing boundary needed for honest replay. Qdrant supplies only similarity candidates; PostgreSQL
hydrates the audited event and filters it by `available_to_strategy_at`.

The generic development default uses the CPU-sized `qwen3:0.6b`; the home ROCm profile targets `qwen3:14b`. Run a small
development analysis batch with `LIMIT=5 make m7`, or use `LIMIT=5 make home-m7` on the home server without an automatic
model pull. The report is written to `data/runtime/m7-research.json` and exposed at `GET /research/m7`.
The gate requires at least 100 analysed events and 100 active event-bars; insufficient coverage never promotes the
news alpha. `NEWS_FORWARD_TO_INTELLIGENCE=false` remains the safe ingestion default.

## M7.5 fiat alpha discovery

M7.5 separates the failed directional strategy's gross return from its cost drag, then evaluates a delta-neutral BTC
carry hypothesis: long equal-quantity Spot and short perpetual, collecting positive funding while largely cancelling
BTC price exposure. Download the longest continuous Bybit dataset used by the experiment and reproduce the report:

```bash
make m75-data
make m75
```

The dataset starts at `2022-02-05T07:00:00Z`, immediately after a verified four-day gap in Bybit's public Spot
history; no prices are synthesized. The report is written to `data/runtime/m75-research.json` and exposed at
`GET /research/m75`. The initial 4.5-year run passed its research gate, including 21/24 positive 60-day OOS folds and
positive return at triple modeled costs. Its execution gate remains closed: perpetual execution, isolated-margin
controls, leg-risk handling and reconciliation are not implemented, and no result is a promise of future profit.

## M7.6 carry Demo observer

The first runtime step remains orderless. It loads both `BTCUSDT-SPOT.BYBIT` and `BTCUSDT-LINEAR.BYBIT`, relies on
Nautilus startup reconciliation, watches both quotes and evaluates balances, open orders, delta mismatch, notional cap
and a conservative margin-ratio proxy:

```bash
make demo-carry-observe
curl -fsS http://localhost:8000/runtime/carry
make demo-pause
```

The status may be `blocked`, `flat_ready`, `hedged`, `repair_required` or `close_required`. Suggested leg actions are
advisory only: `orders_enabled` and the execution gate remain unconditionally locked in this stage. Use a dedicated
Demo account because the observer treats all visible BTC and BTCUSDT Linear exposure as relevant to reconciliation.
The guard also reads live instrument constraints. With Bybit's current BTCUSDT Linear minimum of `0.001 BTC`, the
carry-only Demo cap is 100 USDT per leg, while the ordinary Demo runtime and order smoke retain their 10 USDT limits.
At current prices the shared minimum rounds the advisory pair to about 80 USDT per leg. Live configuration is unchanged.

## M7.7 gated Demo pair

The pair executor is a one-shot command, not part of the continuous observer. It configures BTCUSDT Linear as isolated
margin, one-way mode and `1x`; refuses non-flat ownership, unexpected positions or open orders; submits equal Spot and
Linear market quantities; and commits the ownership ledger only after both full fills. A partial/rejected/timed-out
pair triggers compensating market orders for every confirmed fill.

Opening and closing both require the exact explicit confirmation:

```bash
make demo-carry-open CONFIRM=I_UNDERSTAND_THIS_PLACES_DEMO_CARRY_ORDERS
make demo-carry-close CONFIRM=I_UNDERSTAND_THIS_PLACES_DEMO_CARRY_ORDERS
```

The sanitized result is stored in `data/runtime/carry-pair.json` and returned as `last_pair` by
`GET /runtime/carry`. These commands can place virtual Bybit Demo orders; neither is used by normal startup, and live
credentials/configuration remain outside this path.

## M7.8 Demo carry performance

The read-only performance monitor recovers actual entry fills and fees by the pair's Bybit `orderLinkId`, reads actual
funding settlements from the Unified account transaction log, marks both legs at executable Spot bid/Linear ask and
estimates the cost of closing. It exposes basis PnL, funding, opening fees, estimated closing fees and estimated net
USDT PnL without containing an order-submission method:

```bash
make demo-carry-report
make demo-carry-observe
curl -fsS http://localhost:8000/runtime/carry
```

The entry is persisted in `data/runtime/carry-cycle.json`, while the latest report is written to
`data/runtime/carry-performance.json`. `net_pnl_before_exit_costs_usdt` is not a realizable result;
`estimated_net_pnl_usdt` also subtracts estimated exit fees and uses executable exit prices. Only a completed paired
close can establish final realized PnL.

## M7.9 carry alerts and approval

`carry-alerts` evaluates deterministic stale-data, reconciliation, leg mismatch, guard-close, negative-funding,
loss-limit and profit-review rules every 30 seconds. It can send sanitized JSON to an optional webhook only when the
alert fingerprint changes. Every trade-related recommendation has `confirmation_required=true`; the worker has no
execution client and reports `automatic_actions_enabled=false`.

An optional local Ollama advisor explains the unchanged deterministic decision in Russian. The model receives no
exchange credentials or execution tool and cannot authorize an action. The `carry-alerts` and `intelligence` services
use explicit environment allowlists instead of inheriting the trading `.env`. Enable the advisor only after the
configured model is reachable:

```dotenv
CARRY_ALERT_LLM_ENABLED=true
OLLAMA_MODEL=qwen3:14b
```

Run `make demo-carry-alerts` for one snapshot, `make demo-carry-observe` for continuous monitoring, or `make home-carry`
when using the managed/external Ollama selection from the home deployment files. Alerts are included in
`GET /runtime/carry` and persisted at `data/runtime/carry-alerts.json`.
`make home-validate` also performs one schema-validated advisor inference, so model visibility alone is not treated as
proof that the runtime container can reach it.

For push delivery, the optional Telegram notifier sends only change-deduplicated alert text and the 14B explanation.
It does not accept trading commands. After sending `/start` to a new bot, use `make home-telegram-setup` to discover
the private chat ID and `make home-telegram-test` to verify delivery before setting `TELEGRAM_ALERTS_ENABLED=true`.
Restart only the notifier with `make home-carry-alerts-restart`. Before generated prose can reach Telegram, the model
must echo the deterministic monitor state, position phase and alert codes exactly; otherwise its entire response is
rejected and replaced with a safe notice.

## M7.10 multi-pair carry scanner

`carry-scanner` uses public Bybit market data only and has no API credentials or order client. It intersects active
USDT Spot and Linear Perpetual instruments, preselects a bounded liquid universe, then ranks candidates using current
funding, recent funding history, first-level executable prices and capacity, minimum order notional, explicit taker
fees and a configurable settlement horizon. The estimate is a snapshot, not a forecast or an execution signal.

```bash
make home-carry-scan
curl -fsS http://localhost:8000/runtime/carry-scanner
```

Use `make home-carry-scanner-start` to run the five-minute scanner continuously and refresh the Control API without
restarting the active trader or single-pair carry monitor.

An empty `CARRY_SCANNER_SYMBOLS` enables liquidity-based discovery. Set a comma-separated allowlist to constrain the
universe. `orders_enabled=false` and `automatic_actions_enabled=false` are persisted in every successful or failed
scanner status.

Compact candidate observations are retained for 90 days in a local SQLite database and exposed through
`GET /runtime/carry-scanner/history?symbol=BTCUSDT&limit=100`. The alert worker records the first scanner snapshot as a
silent baseline. On a later `eligible=false` to `eligible=true` transition, it sends one deterministic Telegram review
notice; repeated reads of the same snapshot are deduplicated and never place an order.

`make demo-carry-summary` (or `HOURS=24 make demo-carry-summary`) aggregates that history without an LLM. The summary
reports scan coverage, positive-funding and positive-net shares, estimated net ranges, break-even settlements and how
often each symbol passed every filter. It is evidence for later review, not a forecast or an execution signal.

## Operator decision journal

Open `http://localhost:8000/operator` (shown by `make operator`) for the read-only operator console. It combines the
current Demo carry state, after-cost scanner history, the immutable strategy-decision audit trail and the latest news.
Archived news remains visible when the 14B service is offline; articles that have not been analysed are labelled as
pending rather than assigned a synthetic interpretation.

Future autonomous decision producers must persist the versioned `AlgorithmDecisionAudit` contract: action, plain
summary, confidence, strategy and news explanations, linked news event IDs, passed risk checks, execution status and
exchange order IDs. The same record can be rendered as a concise Telegram notification. The console and formatter do
not enable autonomous execution; existing confirmation and risk gates remain authoritative.

## Safety

- Never grant withdrawal permission to the bot key.
- Demo and live keys use different variable names.
- `ALLOW_LIVE_TRADING=false` by default; `make live` refuses to start without an explicit override.
- Start with Spot only; no leverage is assumed by the domain strategy layer.
- A backtest result is not treated as evidence until out-of-sample, cost-stress, robustness, and forward-demo checks pass.
- Historical news can only become visible at `available_to_strategy_at`, not its publication timestamp.

## Directory map

```text
apps/           runtime entrypoints and Nautilus integration boundary
domain/         engine-independent contracts and immutable domain models
trading/        alpha, strategy pipeline, portfolio, risk, objectives, execution, regimes
research/       fast hypothesis tests, validation and future Nautilus backtest jobs
intelligence/   news, LLM providers, News Alpha and semantic-store adapters
storage/        PostgreSQL models, database session and audit repositories
platform_core/  settings and logging
configs/        backtest/demo/live policy
infra/          Docker/Prometheus/Grafana
scripts/        operational and research smoke tools
docs/           ADR, research policy, roadmap and implementation status
```

## Important boundary

The lightweight `research/backtests/simple_engine.py` is deliberately not the production simulator. It exists to reject bad hypotheses cheaply. Promotion-quality simulations should use NautilusTrader `BacktestNode` with the Parquet catalog and execution fidelity appropriate for the strategy horizon.
