# Research policy

A strategy is not promoted because one backtest looks profitable.

Required evidence before demo:

1. Explicit hypothesis and economic/mechanical rationale.
2. Frozen data range definitions before final evaluation.
3. Costs appropriate to venue, order type and horizon.
4. No lookahead/survivorship leakage.
5. Walk-forward or other time-respecting validation.
6. Untouched out-of-sample result.
7. Parameter-neighborhood stability rather than a narrow optimum.
8. Cost stress at 1.5x/2x and slippage stress.
9. Regime-specific attribution.
10. Benchmark in configured numeraire and risk metrics.
11. Full trial count retained for multiple-testing correction.
12. DSR/PBO added before trusting broad parameter/strategy searches.

Required evidence before live:

- demo forward test;
- reconnect/restart/reconciliation tests;
- live-vs-simulated execution comparison;
- hard risk limits and kill switch;
- tiny initial allocation.
