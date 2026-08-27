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
- Bybit Demo/Mainnet TradingNode factory using the official Nautilus adapter.
- RSS news ingestion, deduplication, Ollama structured JSON classification, strict availability timestamps, and News Alpha adapter.
- PostgreSQL audit models/repository for experiments, raw news, LLM analyses, and strategy decisions.
- Optional Ollama (ROCm), Qdrant, Prometheus, and Grafana Docker Compose profiles.
- Structured logging, health/readiness/status endpoints, backup/restore, CI, and a deterministic synthetic research smoke test.

See `docs/IMPLEMENTATION_STATUS.md`, `docs/RESEARCH_POLICY.md`, and `docs/adr/ADR-001-architecture.md`.

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

For Bybit Demo, create demo credentials, put only `BYBIT_DEMO_API_KEY` and `BYBIT_DEMO_API_SECRET` in `.env`, then run:

```bash
make demo
```

`make demo` is a credential/integration smoke test. Actual continuous Nautilus node execution remains disabled until `RUN_NAUTILUS_NODE=true` is explicitly set.

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
