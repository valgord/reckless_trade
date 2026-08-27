# Backtests

Production backtests use NautilusTrader `BacktestNode` over a `ParquetDataCatalog`.
Keep strategy code identical between backtest/demo/live. Every experiment must record:

- code commit SHA;
- strategy/config hash;
- dataset identity and time range;
- fees/slippage/fill model;
- objective/numeraire and benchmark;
- all tried parameter sets, not only the winner;
- walk-forward / out-of-sample results;
- robustness tests with worse fees/slippage and regime splits.

Custom news/LLM data must respect `available_to_strategy_at`, never `published_at`, to avoid lookahead.
