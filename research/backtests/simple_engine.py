from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from domain.models import InstrumentKey, Signal


@dataclass(frozen=True, slots=True)
class BacktestPoint:
    ts: datetime
    close: float


@dataclass(frozen=True, slots=True)
class CostModel:
    fee_bps: float = 10.0
    slippage_bps: float = 2.0
    spread_bps: float = 1.0

    @property
    def one_way_rate(self) -> float:
        return (self.fee_bps + self.slippage_bps + self.spread_bps / 2) / 10_000


@dataclass(frozen=True, slots=True)
class BacktestResult:
    equity: tuple[float, ...]
    returns: tuple[float, ...]
    turnover: float
    fees_paid: float
    trades: int


class LongOnlyBarBacktester:
    """Research-only sanity engine. Production backtests use Nautilus BacktestNode."""

    def __init__(self, initial_equity: float = 1.0, cost_model: CostModel | None = None) -> None:
        self.initial_equity = initial_equity
        self.cost_model = cost_model or CostModel()

    def run(self, points: list[BacktestPoint], target_fn: Callable[[int, list[float]], float]) -> BacktestResult:
        if len(points) < 2:
            return BacktestResult((self.initial_equity,), (), 0.0, 0.0, 0)
        closes = [p.close for p in points]
        equity = self.initial_equity
        position = 0.0
        curve = [equity]
        rets: list[float] = []
        turnover = fees = 0.0
        trades = 0
        for i in range(1, len(points)):
            target = max(0.0, min(1.0, float(target_fn(i - 1, closes[:i]))))
            delta = abs(target - position)
            cost = delta * self.cost_model.one_way_rate
            fees += equity * cost
            turnover += delta
            if delta > 1e-12:
                trades += 1
            equity *= max(0.0, 1.0 - cost)
            period_return = closes[i] / closes[i - 1] - 1.0
            before = equity
            equity *= 1.0 + target * period_return
            rets.append(equity / before - 1.0 if before else 0.0)
            position = target
            curve.append(equity)
        return BacktestResult(tuple(curve), tuple(rets), turnover, fees, trades)
