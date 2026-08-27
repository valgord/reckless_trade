from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone

from research.backtests.simple_engine import BacktestPoint, CostModel, LongOnlyBarBacktester
from research.validation.metrics import calmar, max_drawdown, sharpe, sortino
from research.validation.robustness import bootstrap_terminal_equity


def main() -> None:
    # Deterministic synthetic series validates the research plumbing; it is not evidence of profitability.
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    prices = [100 * math.exp(0.0003 * i + 0.02 * math.sin(i / 12)) for i in range(400)]
    points = [BacktestPoint(start + timedelta(hours=i), price) for i, price in enumerate(prices)]

    def target(i: int, closes: list[float]) -> float:
        if len(closes) < 50:
            return 0.0
        fast = sum(closes[-10:]) / 10
        slow = sum(closes[-50:]) / 50
        return 0.35 if fast > slow else 0.0

    result = LongOnlyBarBacktester(cost_model=CostModel()).run(points, target)
    metrics = {
        "terminal_equity": result.equity[-1],
        "max_drawdown": max_drawdown(result.equity),
        "sharpe": sharpe(result.returns, 24 * 365),
        "sortino": sortino(result.returns, 24 * 365),
        "calmar": calmar(result.equity, 24 * 365),
        "turnover": result.turnover,
        "trades": result.trades,
        "bootstrap": str(bootstrap_terminal_equity(list(result.returns), paths=500)),
    }
    print(json.dumps(metrics, indent=2, default=str))


if __name__ == "__main__":
    main()
