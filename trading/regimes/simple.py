from __future__ import annotations

from dataclasses import dataclass
from statistics import pstdev

from domain.models import MarketRegime


@dataclass(slots=True)
class VolatilityTrendRegimeProvider:
    vol_high: float = 0.03
    trend_threshold: float = 0.02

    def regime(self, returns: list[float]) -> MarketRegime:
        if len(returns) < 20:
            return MarketRegime.UNKNOWN
        vol = pstdev(returns[-20:])
        cumulative = 1.0
        for value in returns[-20:]:
            cumulative *= 1.0 + value
        trend = cumulative - 1.0
        if vol >= self.vol_high:
            return MarketRegime.HIGH_VOL
        if trend >= self.trend_threshold:
            return MarketRegime.TREND_UP
        if trend <= -self.trend_threshold:
            return MarketRegime.TREND_DOWN
        return MarketRegime.RANGE
