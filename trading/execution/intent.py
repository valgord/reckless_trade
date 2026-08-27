from __future__ import annotations

from dataclasses import dataclass

from domain.models import InstrumentKey


@dataclass(frozen=True, slots=True)
class ExecutionIntent:
    instrument: InstrumentKey
    target_weight: float
    algorithm: str = "adaptive_limit"


class ExecutionPlanner:
    def plan(self, current: dict[str, float], target: dict[str, float]) -> list[ExecutionIntent]:
        keys = set(current) | set(target)
        intents: list[ExecutionIntent] = []
        for key in sorted(keys):
            delta = target.get(key, 0.0) - current.get(key, 0.0)
            if abs(delta) < 1e-6:
                continue
            venue, symbol = key.split(":", 1)
            intents.append(ExecutionIntent(InstrumentKey(venue, symbol), target.get(key, 0.0)))
        return intents
