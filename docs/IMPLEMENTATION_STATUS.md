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
- Typed NautilusTrader Bybit TradingNode configuration for Demo/Mainnet Spot with startup reconciliation.
- Demo instrument/ticker discovery, authenticated account/balance presence and open-order reconciliation smoke checks.
- Separately gated, notional-capped Demo submit/cancel smoke with cancellation on unknown submit outcome.
- Orderless continuous Demo observer connecting live/historical bars to the domain strategy pipeline, with runtime status.
- Bybit Demo authenticated access, submit/cancel lifecycle, restart reconciliation and continuous observer verified end to end.
- Incremental Bybit bar ingestion, continuity validation, Nautilus Parquet catalog and BacktestNode strategy execution.
- USDT and BTC-relative benchmark report with configured all-in fill costs and an API status endpoint.
- Append-only experiment registry, alpha ablations, minimum-hold sweep, expanding walk-forward/OOS selection,
  regime attribution, cost stress, bootstrap, DSR/PBO and automatic promotion gate.
- Fast-research winners are re-run through Nautilus BacktestNode before they can satisfy the research gate.
- Volatility-expansion alpha, hard regime gating, configurable regime-entry confirmation and minimum-activity
  eligibility which prevents inactive cash strategies from winning selection.
- Aligned BTC/ETH/SOL portfolio research with inverse-volatility sizing, single/total/venue exposure limits,
  correlated-pair budgets, turnover costs, risk-matched benchmarks and a drawdown kill switch.
- Independent RSS ingestion with HTTP timeouts, atomic raw archive, durable fingerprints, PostgreSQL deduplication,
  provenance, publication/first-seen timestamps, per-source rate limits and health reporting.
- RSS ingestion worker with deduplication and LLM analysis HTTP handoff.
- Strict Ollama structured-event contract with deterministic temperature, prompt/model/hash audit, stable replay IDs
  and preserved publication, first-seen, analysis-start, completion and strategy-availability timestamps.
- PostgreSQL-hydrated Qdrant similarity candidates and a costed M7 A/B replay with an explicit LLM-disabled arm,
  minimum coverage gates and future-information blocking.
- Trade-level M4/M5 gross/net attribution plus public Bybit funding and replay-safe mark-price ingestion.
- Delta-neutral BTC Spot/Perp carry simulation with funding, basis PnL, fees, slippage, monthly rebalancing,
  margin/liquidation proxy, walk-forward selection, cost stress, bootstrap robustness and separate research/execution gates.
- Mixed Bybit Spot+Linear Demo client configuration and an orderless carry readiness observer with startup
  reconciliation, balance/open-order inspection, delta and notional guards, margin proxy and risk-reducing repair plans.
- Exact-confirmation one-shot Demo carry executor with isolated 1x Linear configuration, equal-quantity paired market
  orders, fill reconciliation, compensating unwind and an atomic strategy-ownership ledger.
- Read-only Demo carry performance monitor with persisted entry fills, actual funding settlements, basis attribution,
  actual opening fees, estimated closing fees and executable-price net PnL.
- Deterministic carry alerts for stale state, reconciliation, leg risk, funding and PnL thresholds, with an optional
  advisory-only local Ollama explanation, change-only webhook and explicit human confirmation policy.
- PostgreSQL audit models, Docker Compose, optional Qdrant, Prometheus/Grafana, backup/restore and CI.
- Live trading lock and physically separate demo/live credential names.

## Deliberately not faked

- No strategy is claimed profitable before historical and forward validation.
- No hard-coded live order sizing exists before instrument/account metadata is reconciled from Bybit.
- The M7 machinery is validated, but the current report contains zero model analyses. No model quality or news alpha
  benefit is claimed until a sufficiently large replay-aligned event set exists.
- Market making and statistical arbitrage still need L2/specialized datasets. Carry is research-only and has no
  continuous autonomous order path; its one-shot Demo executor cannot use live credentials.
- Production backtests use Nautilus BacktestNode; the local simple engine exists only for fast mathematical sanity checks.
