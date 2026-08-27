# ADR-001: Trading platform architecture

Status: Accepted, 2026-08-27

## Decision

Use NautilusTrader 1.231.0 as the trading kernel, isolated behind the `apps/trader` integration boundary. Keep domain,
research, intelligence, portfolio objectives and strategy-selection logic independent of Nautilus-specific classes.

The system is multi-venue, multi-asset and multi-strategy by design. Bybit Spot BTC/USDT is only the first deployment.

## Core flow

Market/custom data -> Alpha models -> normalized Signals -> aggregation -> PortfolioTarget -> global risk -> execution plan -> Nautilus execution -> venue.

News -> ingestion/dedup -> LLM structured IntelligenceEvent -> optional historical retrieval -> News Alpha -> the same Signal pipeline.
LLM never receives exchange credentials and never calls execution APIs.

## Runtime topology

- `trader`: Nautilus live/backtest integration and strategies.
- `control-api`: health, control and metrics surface.
- `news-worker`: asynchronous external-source ingestion.
- `intelligence`: replaceable LLM analysis API.
- `postgres`: relational state/metadata/audit.
- `ParquetDataCatalog`: historical market/custom data.
- optional `ollama` + `qdrant` profile.
- optional `prometheus` + `grafana` profile.

Do not add Kafka/Kubernetes or split risk/portfolio/execution into network services until a demonstrated scaling need exists.

## Backtest integrity rules

1. Same alpha/portfolio/risk code in backtest, demo and live.
2. Model fees, spread, slippage, latency and fills at the fidelity required by the strategy horizon.
3. Record every attempted parameter configuration.
4. Mandatory out-of-sample/walk-forward evaluation before demo promotion.
5. Stress costs and split results by market regime.
6. For news, the earliest legal timestamp is `available_to_strategy_at`.
7. Compare against the objective-specific benchmark, e.g. BTC buy-and-hold when BTC is numeraire.
8. Add DSR/PBO before large-scale strategy search is trusted.

## Version policy

Pin NautilusTrader exactly. 1.231.0 is the final planned 1.x line before the v2 Rust/PyO3 cutover; no automatic kernel upgrades.
Each upgrade requires integration tests, replay/backtest comparison and demo soak before live use.
