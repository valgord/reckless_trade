from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import mean, pstdev

from domain.models import InstrumentKey, Signal


@dataclass(slots=True)
class PriceSeriesContext:
    instrument: InstrumentKey
    closes: list[float]
    volumes: list[float] | None = None

    @property
    def returns(self) -> list[float]:
        return [b / a - 1.0 for a, b in zip(self.closes, self.closes[1:], strict=False) if a > 0]


@dataclass(slots=True)
class MeanReversionAlpha:
    window: int = 50
    entry_z: float = 2.0
    horizon_seconds: int = 3600

    def generate(self, context: PriceSeriesContext) -> list[Signal]:
        if len(context.closes) < self.window:
            return []
        sample = context.closes[-self.window :]
        sigma = pstdev(sample)
        if sigma == 0:
            return []
        z = (sample[-1] - mean(sample)) / sigma
        if abs(z) < self.entry_z:
            return []
        direction = -1.0 if z > 0 else 1.0
        strength = min((abs(z) - self.entry_z) / max(self.entry_z, 1e-9) + 0.5, 1.0)
        return [
            Signal(
                "mean_reversion",
                context.instrument,
                direction,
                strength,
                min(0.5 + strength / 2, 1.0),
                self.horizon_seconds,
                metadata={"zscore": z},
            )
        ]


@dataclass(slots=True)
class MomentumAlpha:
    lookback: int = 20
    threshold: float = 0.01
    vol_lookback: int = 20
    horizon_seconds: int = 4 * 3600

    def generate(self, context: PriceSeriesContext) -> list[Signal]:
        if len(context.closes) <= max(self.lookback, self.vol_lookback):
            return []
        ret = context.closes[-1] / context.closes[-1 - self.lookback] - 1.0
        if abs(ret) < self.threshold:
            return []
        returns = context.returns[-self.vol_lookback :]
        vol = pstdev(returns) * sqrt(self.vol_lookback) if len(returns) >= 2 else 0.0
        score = abs(ret) / max(vol, self.threshold)
        strength = min(score, 1.0)
        return [
            Signal(
                "momentum",
                context.instrument,
                1.0 if ret > 0 else -1.0,
                strength,
                min(0.55 + strength * 0.35, 0.95),
                self.horizon_seconds,
                metadata={"return": ret, "realized_vol": vol},
            )
        ]


@dataclass(slots=True)
class BreakoutAlpha:
    lookback: int = 20
    buffer: float = 0.0
    horizon_seconds: int = 4 * 3600

    def generate(self, context: PriceSeriesContext) -> list[Signal]:
        if len(context.closes) <= self.lookback:
            return []
        previous = context.closes[-1 - self.lookback : -1]
        last = context.closes[-1]
        upper = max(previous) * (1 + self.buffer)
        lower = min(previous) * (1 - self.buffer)
        if last > upper:
            return [
                Signal("breakout", context.instrument, 1.0, 0.7, 0.7, self.horizon_seconds, metadata={"upper": upper})
            ]
        if last < lower:
            return [
                Signal("breakout", context.instrument, -1.0, 0.7, 0.7, self.horizon_seconds, metadata={"lower": lower})
            ]
        return []


@dataclass(slots=True)
class TrendFollowingAlpha:
    fast: int = 20
    slow: int = 100
    min_separation: float = 0.002
    horizon_seconds: int = 24 * 3600

    def generate(self, context: PriceSeriesContext) -> list[Signal]:
        if len(context.closes) < self.slow:
            return []
        fast_ma = mean(context.closes[-self.fast :])
        slow_ma = mean(context.closes[-self.slow :])
        separation = fast_ma / slow_ma - 1.0
        if abs(separation) < self.min_separation:
            return []
        strength = min(abs(separation) / (self.min_separation * 5), 1.0)
        return [
            Signal(
                "trend_following",
                context.instrument,
                1.0 if separation > 0 else -1.0,
                strength,
                min(0.6 + strength * 0.3, 0.9),
                self.horizon_seconds,
                metadata={"fast_ma": fast_ma, "slow_ma": slow_ma},
            )
        ]


@dataclass(slots=True)
class VolatilityBreakoutAlpha:
    short_window: int = 20
    long_window: int = 100
    expansion_ratio: float = 1.5
    momentum_lookback: int = 20
    horizon_seconds: int = 4 * 3600

    def generate(self, context: PriceSeriesContext) -> list[Signal]:
        required = max(self.long_window + 1, self.momentum_lookback + 1)
        if len(context.closes) < required:
            return []
        returns = context.returns
        short_vol = pstdev(returns[-self.short_window :])
        long_vol = pstdev(returns[-self.long_window :])
        if long_vol == 0 or short_vol < long_vol * self.expansion_ratio:
            return []
        momentum = context.closes[-1] / context.closes[-1 - self.momentum_lookback] - 1.0
        if momentum == 0:
            return []
        expansion = short_vol / long_vol
        strength = min((expansion - self.expansion_ratio) / self.expansion_ratio + 0.5, 1.0)
        return [
            Signal(
                "volatility_breakout",
                context.instrument,
                1.0 if momentum > 0 else -1.0,
                strength,
                min(0.55 + strength * 0.3, 0.90),
                self.horizon_seconds,
                metadata={"short_vol": short_vol, "long_vol": long_vol, "momentum": momentum},
            )
        ]
