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

## M7.5 - Fiat alpha discovery
Directional trade attribution, public funding/mark-price ingestion and delta-neutral Spot/Perp carry research.

Baseline complete on 4,993 funding settlements from February 2022: directional alpha was negative before costs, while
the always-on carry candidate returned 12.78% after modeled costs, 7.71% across chained walk-forward test windows and
11.25% at triple costs. The research gate passed, but the execution gate remains closed until Demo-only derivative
execution, margin controls, atomic leg handling, reconciliation and forward testing exist.

## M7.6 - Carry Demo readiness
Spot+Linear client configuration, startup reconciliation and an orderless carry observer are implemented. The guard
fails closed on missing quotes, incomplete reconciliation or open orders; detects invalid direction, notional excess,
delta mismatch and low margin; and produces risk-reducing repair guidance (`reduce_only` only on Linear). Demo order submission remains the next gated
increment after the observer is verified against a dedicated Demo account.

The first live Demo readiness check correctly blocked because 0.001 BTC required roughly 80 USDT per leg above the
original 10 USDT cap. The explicitly approved carry-only Demo cap is now 100 USDT per leg; ordinary Demo smoke limits
remain 10 USDT and live configuration remains unchanged.

## M7.7 - Gated Demo pair execution
A one-shot, exact-confirmation executor now configures isolated `1x` Linear trading, validates a flat reconciled state,
submits equal Spot/Linear market legs, waits for both fills and atomically updates carry ownership. Partial fills,
rejects and timeouts invoke compensating orders for confirmed exposure. Continuous automatic opening remains disabled;
the first virtual pair requires a separately confirmed operator action.

## M7.8 - Demo carry performance
Persist the actual entry fills, collect private funding settlements and attribute the open pair's USDT result to basis,
funding and fees. Report both pre-exit PnL and executable-price net PnL after estimated closing fees. The monitor is
read-only; a final realized result still requires a separately confirmed paired close.

## M7.9 - Alerts and manual approval
Watch observer/performance freshness and deterministic risk states, emit change-deduplicated alerts and optionally use
the local 14B model to explain them. The LLM cannot alter severity, choose an execution action or access credentials.
Its structured response is accepted only when the echoed state, position phase and alert codes exactly match the
deterministic input. Pair repair/close remains a one-shot operator-confirmed command; continuous autonomous execution
stays disabled.

## M7.10 - Multi-pair carry discovery

Continuously scan the public Bybit USDT Spot/Linear intersection and rank a bounded liquid universe using executable
top-of-book prices, recent funding stability, minimum order constraints and explicit round-trip fees. This stage is
observation-only: no candidate can create an execution intent or receive exchange credentials. Multi-pair ownership,
portfolio limits and Demo execution remain separate future gates. Candidate history is stored locally for trend
analysis, and Telegram emits a deduplicated review notice only when a symbol newly passes every deterministic filter.

## M8 - Multi-strategy and regime allocation
Strategy portfolio, regime-dependent weights, performance attribution per alpha/strategy.

## M9 - Demo forward test
Long-running demo, reconnect/restart chaos tests, reconciliation, alerting, drift between simulated and realized execution.

## M10 - Live small
Separate credentials, explicit live gate, withdrawal disabled at exchange, IP allowlist, tiny allocation, emergency stop and rollback procedure.
