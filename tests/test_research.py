from datetime import UTC, datetime, timedelta

from research.backtests.simple_engine import BacktestPoint, CostModel, LongOnlyBarBacktester
from research.validation.metrics import max_drawdown, profit_factor, sortino
from research.validation.robustness import bootstrap_terminal_equity


def test_backtester_applies_costs():
    now = datetime.now(UTC)
    points = [BacktestPoint(now + timedelta(days=i), 100 + i) for i in range(5)]
    no_cost = LongOnlyBarBacktester(cost_model=CostModel(0, 0, 0)).run(points, lambda i, c: 1.0)
    cost = LongOnlyBarBacktester(cost_model=CostModel(10, 2, 1)).run(points, lambda i, c: 1.0)
    assert cost.equity[-1] < no_cost.equity[-1]
    assert cost.trades == 1


def test_validation_metrics_and_bootstrap():
    returns = [0.01, -0.005, 0.012, -0.003, 0.004]
    assert sortino(returns, 365) > 0
    assert profit_factor(returns) > 1
    assert max_drawdown([1, 1.1, 0.9, 1.2]) < 0
    summary = bootstrap_terminal_equity(returns, paths=100, seed=1)
    assert summary.p05_terminal <= summary.median_terminal <= summary.p95_terminal
