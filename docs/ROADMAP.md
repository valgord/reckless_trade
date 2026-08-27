# Roadmap

## M0 - Platform bootstrap
Docker Compose, config separation, secrets policy, tests, health/metrics, ADRs.

## M1 - Bybit Demo integration
Nautilus Bybit Spot data/execution, BTCUSDT instrument discovery, account/balance, submit/cancel minimal order, private event receipt, restart/reconciliation test.

## M2 - Historical data and BacktestNode
Acquire Bybit BTCUSDT history, write Parquet catalog, execute one strategy through BacktestNode, benchmark in BTC and USDT, cost model.

## M3 - Research framework
Experiment registry, parameter sweep with full trial logging, walk-forward, out-of-sample, regime splits, stress fees/slippage, DSR/PBO.

## M4 - Alpha library
Trend/time-series momentum, mean reversion, breakout, volatility; later cross-sectional momentum, pairs/stat-arb, carry/funding, microstructure/market making.

## M5 - Portfolio and risk
Multiple assets/strategies, allocations, exposure constraints, drawdown kill switch, correlation/risk budgets, venue limits.

## M6 - News ingestion
Source plug-ins, raw archive, deduplication, timestamps, provenance, rate limits and source health.

## M7 - LLM intelligence
Structured event extraction, prompt/model/version audit, replay-safe availability timestamps, A/B with LLM disabled, Qdrant historical-event retrieval.

## M8 - Multi-strategy and regime allocation
Strategy portfolio, regime-dependent weights, performance attribution per alpha/strategy.

## M9 - Demo forward test
Long-running demo, reconnect/restart chaos tests, reconciliation, alerting, drift between simulated and realized execution.

## M10 - Live small
Separate credentials, explicit live gate, withdrawal disabled at exchange, IP allowlist, tiny allocation, emergency stop and rollback procedure.
