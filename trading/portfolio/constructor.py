from __future__ import annotations

from collections.abc import Iterable

from domain.models import PortfolioTarget, Signal, TargetAllocation


class LongOnlySignalPortfolioConstructor:
    def __init__(self, max_asset_weight: float = 0.35, reserve_weight: float = 0.10, min_signal: float = 0.05) -> None:
        if not 0 <= reserve_weight < 1:
            raise ValueError("reserve_weight must be in [0, 1)")
        self.max_asset_weight = max_asset_weight
        self.reserve_weight = reserve_weight
        self.min_signal = min_signal

    def construct(self, signals: Iterable[Signal], numeraire: str) -> PortfolioTarget:
        candidates = [s for s in signals if s.direction > 0 and s.direction * s.strength * s.confidence >= self.min_signal]
        if not candidates:
            return PortfolioTarget((), numeraire)
        scores = [s.direction * s.strength * s.confidence for s in candidates]
        total = sum(scores)
        budget = 1.0 - self.reserve_weight
        raw = [budget * score / total for score in scores]
        capped = [min(self.max_asset_weight, value) for value in raw]
        leftover = budget - sum(capped)
        uncapped = {i for i, value in enumerate(raw) if value < self.max_asset_weight}
        while leftover > 1e-12 and uncapped:
            add = leftover / len(uncapped)
            next_uncapped: set[int] = set()
            for i in uncapped:
                room = self.max_asset_weight - capped[i]
                delta = min(add, room)
                capped[i] += delta
                leftover -= delta
                if capped[i] < self.max_asset_weight - 1e-12:
                    next_uncapped.add(i)
            if next_uncapped == uncapped:
                break
            uncapped = next_uncapped
        allocations = tuple(TargetAllocation(signal.instrument, weight) for signal, weight in zip(candidates, capped, strict=True))
        return PortfolioTarget(allocations, numeraire)
