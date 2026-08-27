# Implementation status

## Implemented now

- Engine-agnostic domain models for instruments, bars, signals, portfolio targets, snapshots and intelligence events.
- Alpha library: trend following, momentum, mean reversion and breakout.
- Weighted signal aggregation and regime-aware strategy pipeline.
- Long-only portfolio construction with reserve and asset caps.
- Portfolio target and runtime drawdown risk guards.
- Execution intent planning.
- Lightweight research backtester with fee/spread/slippage costs for fast hypothesis rejection.
- Research metrics, expanding walk-forward folds and bootstrap robustness analysis.
- Official NautilusTrader Bybit TradingNode factory for Demo/Mainnet Spot.
- RSS ingestion worker with deduplication and LLM analysis HTTP handoff.
- Ollama JSON news classifier with deterministic temperature and timing audit fields.
- PostgreSQL audit models, Docker Compose, optional Qdrant, Prometheus/Grafana, backup/restore and CI.
- Live trading lock and physically separate demo/live credential names.

## Deliberately not faked

- No strategy is claimed profitable before historical and forward validation.
- No hard-coded live order sizing exists before instrument/account metadata is reconciled from Bybit.
- Qdrant similarity results are not promoted into domain events until relational timing/audit hydration is implemented.
- Market making, statistical arbitrage and funding/basis strategies need L2/funding datasets and have contracts but are not represented by toy implementations.
- Production backtests use Nautilus BacktestNode; the local simple engine exists only for fast mathematical sanity checks.
