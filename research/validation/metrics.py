from __future__ import annotations

import math
from statistics import mean, pstdev


def max_drawdown(equity: list[float] | tuple[float, ...]) -> float:
    if not equity:
        return 0.0
    peak = equity[0]
    worst = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return worst


def sharpe(returns: list[float] | tuple[float, ...], periods_per_year: float) -> float:
    if len(returns) < 2:
        return 0.0
    sigma = pstdev(returns)
    return 0.0 if sigma == 0 else mean(returns) / sigma * math.sqrt(periods_per_year)


def sortino(returns: list[float] | tuple[float, ...], periods_per_year: float) -> float:
    if len(returns) < 2:
        return 0.0
    downside = [min(r, 0.0) ** 2 for r in returns]
    downside_dev = math.sqrt(sum(downside) / len(downside))
    return 0.0 if downside_dev == 0 else mean(returns) / downside_dev * math.sqrt(periods_per_year)


def annualized_return(equity: list[float] | tuple[float, ...], periods: int, periods_per_year: float) -> float:
    if len(equity) < 2 or equity[0] <= 0 or periods <= 0:
        return 0.0
    return (equity[-1] / equity[0]) ** (periods_per_year / periods) - 1.0


def annualized_volatility(returns: list[float] | tuple[float, ...], periods_per_year: float) -> float:
    return pstdev(returns) * math.sqrt(periods_per_year) if len(returns) >= 2 else 0.0


def calmar(equity: list[float] | tuple[float, ...], periods_per_year: float) -> float:
    dd = abs(max_drawdown(equity))
    ann = annualized_return(equity, max(len(equity) - 1, 1), periods_per_year)
    return 0.0 if dd == 0 else ann / dd


def profit_factor(returns: list[float] | tuple[float, ...]) -> float:
    gains = sum(r for r in returns if r > 0)
    losses = abs(sum(r for r in returns if r < 0))
    return math.inf if losses == 0 and gains > 0 else (gains / losses if losses else 0.0)


def turnover(weights: list[dict[str, float]]) -> float:
    if len(weights) < 2:
        return 0.0
    return sum(
        sum(abs(curr.get(k, 0.0) - prev.get(k, 0.0)) for k in set(prev) | set(curr))
        for prev, curr in zip(weights, weights[1:], strict=False)
    )
