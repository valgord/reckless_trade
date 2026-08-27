# Roadmap

## M0 - Platform bootstrap
Docker Compose, config separation, secrets policy, tests, health/metrics, ADRs.

## M1 - Bybit Demo integration
Nautilus Bybit Spot data/execution, BTCUSDT instrument discovery, account/balance, submit/cancel minimal order, private event receipt, restart/reconciliation test.

## M2 - Historical data and BacktestNode
Acquire Bybit BTCUSDT history, write Parquet catalog, execute one strategy through BacktestNode, benchmark in BTC and USDT, cost model.

Baseline complete: 365 days of validated 15-minute bars and a reproducible BacktestNode report. The initial strategy
underperformed in absolute terms and is not promoted to order-enabled Demo trading.

## M3 - Research framework
Experiment registry, parameter sweep with full trial logging, walk-forward, out-of-sample, regime splits, stress fees/slippage, DSR/PBO.

Baseline complete: ten candidates, 63 fully logged trials, four expanding walk-forward folds, nine cost scenarios,
bootstrap, DSR/PBO and a Nautilus confirmation. The best low-turnover candidate still lost money and failed the
promotion gate, so Demo order submission remains disabled.

## M4 - Alpha library
Trend/time-series momentum, mean reversion, breakout, volatility; later cross-sectional momentum, pairs/stat-arb, carry/funding, microstructure/market making.

Initial single-asset pass complete: volatility-expansion alpha, hard regime exits, confirmed regime entries and
minimum-activity eligibility were tested in 63 logged trials. The best qualified candidate reduced losses but remained
negative full-sample and OOS, so it was not promoted to Demo orders.

## M5 - Portfolio and risk
Multiple assets/strategies, allocations, exposure constraints, drawdown kill switch, correlation/risk budgets, venue limits.

Initial BTC/ETH/SOL pass complete on aligned 15-minute data: inverse-volatility allocation, asset/total/venue limits,
correlated-pair caps, turnover-aware rebalancing and a permanent drawdown kill switch are implemented. Crypto return
correlations were high and the multi-asset variants underperformed the BTC-only control; no portfolio was promoted.

## M6 - News ingestion
Source plug-ins, raw archive, deduplication, timestamps, provenance, rate limits and source health.

Baseline complete: HTTP-fetched RSS sources, atomic raw archive, durable restart-safe fingerprints, PostgreSQL
deduplication, publication/first-seen timestamps, feed/article provenance, per-source poll limits and health status.
Forwarding to LLM intelligence is a separate opt-in and remains disabled for the M6 ingestion path.

## M7 - LLM intelligence
Structured event extraction, prompt/model/version audit, replay-safe availability timestamps, A/B with LLM disabled, Qdrant historical-event retrieval.

Foundation complete: strict schema validation, content-derived prompt hashes, stable analysis IDs, relational event
hydration, availability-safe Qdrant candidates and a costed LLM-disabled A/B replay are implemented. The initial report
covered 35,039 BTC bars but had no LLM analyses, so it correctly failed the minimum-coverage gate. Model evaluation
and any news-alpha promotion remain pending; forwarding to the trading path stays disabled.

## M8 - Multi-strategy and regime allocation
Strategy portfolio, regime-dependent weights, performance attribution per alpha/strategy.

## M9 - Demo forward test
Long-running demo, reconnect/restart chaos tests, reconciliation, alerting, drift between simulated and realized execution.

## M10 - Live small
Separate credentials, explicit live gate, withdrawal disabled at exchange, IP allowlist, tiny allocation, emergency stop and rollback procedure.
