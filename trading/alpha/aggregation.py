from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from domain.models import Signal


class WeightedSignalAggregator:
    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self.weights = weights or {}

    def aggregate(self, signals: Iterable[Signal]) -> list[Signal]:
        grouped: dict[str, list[Signal]] = defaultdict(list)
        for signal in signals:
            grouped[signal.instrument.canonical].append(signal)

        result: list[Signal] = []
        for items in grouped.values():
            denominator = sum(self.weights.get(s.source, 1.0) * s.confidence for s in items)
            if denominator == 0:
                continue
            score = (
                sum(self.weights.get(s.source, 1.0) * s.confidence * s.direction * s.strength for s in items)
                / denominator
            )
            confidence = min(sum(s.confidence for s in items) / len(items), 1.0)
            result.append(
                Signal(
                    "aggregate",
                    items[0].instrument,
                    max(-1.0, min(1.0, score)),
                    abs(score),
                    confidence,
                    max(s.horizon_seconds for s in items),
                    metadata={"contributors": len(items)},
                )
            )
        return result
