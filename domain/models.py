from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Mapping


class Side(StrEnum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


class MarketRegime(StrEnum):
    TREND_UP = "trend_up"
    TREND_DOWN = "trend_down"
    RANGE = "range"
    HIGH_VOL = "high_vol"
    LOW_VOL = "low_vol"
    CRISIS = "crisis"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class InstrumentKey:
    venue: str
    symbol: str

    @property
    def canonical(self) -> str:
        return f"{self.venue}:{self.symbol}"


@dataclass(frozen=True, slots=True)
class Bar:
    instrument: InstrumentKey
    ts_event: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def __post_init__(self) -> None:
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("OHLC prices must be positive")
        if self.high < max(self.open, self.close, self.low) or self.low > min(self.open, self.close, self.high):
            raise ValueError("Invalid OHLC ordering")


@dataclass(frozen=True, slots=True)
class Signal:
    source: str
    instrument: InstrumentKey
    direction: float
    strength: float
    confidence: float
    horizon_seconds: int
    ts_event: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Mapping[str, str | float | int | bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not -1.0 <= self.direction <= 1.0:
            raise ValueError("direction must be in [-1, 1]")
        if not 0.0 <= self.strength <= 1.0:
            raise ValueError("strength must be in [0, 1]")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        if self.horizon_seconds <= 0:
            raise ValueError("horizon_seconds must be positive")


@dataclass(frozen=True, slots=True)
class TargetAllocation:
    instrument: InstrumentKey
    weight: float


@dataclass(frozen=True, slots=True)
class PortfolioTarget:
    allocations: tuple[TargetAllocation, ...]
    numeraire: str
    ts_event: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def weights(self) -> dict[str, float]:
        return {item.instrument.canonical: item.weight for item in self.allocations}


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    ts_event: datetime
    equity_numeraire: float
    weights: Mapping[str, float]
    drawdown: float = 0.0


@dataclass(frozen=True, slots=True)
class IntelligenceEvent:
    event_id: str
    source: str
    title: str
    summary: str
    assets: tuple[str, ...]
    event_type: str
    direction: float
    importance: float
    confidence: float
    horizon_seconds: int
    published_at: datetime
    first_seen_at: datetime
    analysis_completed_at: datetime
    available_to_strategy_at: datetime

    def __post_init__(self) -> None:
        if not -1 <= self.direction <= 1:
            raise ValueError("direction must be in [-1, 1]")
        for name, value in (("importance", self.importance), ("confidence", self.confidence)):
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be in [0, 1]")
        if self.available_to_strategy_at < self.analysis_completed_at:
            raise ValueError("event cannot be available before analysis completes")
