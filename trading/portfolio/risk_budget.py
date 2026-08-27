from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RiskBudgetConfig:
    max_total_weight: float = 0.30
    max_asset_weight: float = 0.15
    max_correlated_pair_weight: float = 0.20
    correlation_threshold: float = 0.75
    max_venue_weight: float = 0.30

    def __post_init__(self) -> None:
        weights = (self.max_total_weight, self.max_asset_weight, self.max_correlated_pair_weight, self.max_venue_weight)
        if any(value <= 0 or value > 1 for value in weights):
            raise ValueError("risk budget weights must be in (0, 1]")
        if not 0 <= self.correlation_threshold <= 1:
            raise ValueError("correlation_threshold must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class RiskBudgetAllocation:
    weights: dict[str, float]
    cash_weight: float
    risk_contributions: dict[str, float]
    concentration_hhi: float
    constraints_applied: tuple[str, ...]


class InverseVolatilityRiskAllocator:
    def __init__(self, config: RiskBudgetConfig | None = None) -> None:
        self.config = config or RiskBudgetConfig()

    def allocate(
        self,
        active: set[str],
        volatilities: dict[str, float],
        correlations: dict[str, dict[str, float]],
        venues: dict[str, str],
    ) -> RiskBudgetAllocation:
        if not active:
            return RiskBudgetAllocation({}, 1.0, {}, 0.0, ())
        missing = active - set(volatilities)
        if missing:
            raise ValueError(f"missing volatilities for {sorted(missing)}")
        inverse = {name: 1.0 / max(float(volatilities[name]), 1e-9) for name in active}
        scale = self.config.max_total_weight / sum(inverse.values())
        weights = {name: min(value * scale, self.config.max_asset_weight) for name, value in inverse.items()}
        constraints: list[str] = []
        if any(inverse[name] * scale > self.config.max_asset_weight for name in active):
            constraints.append("max_asset_weight")

        names = sorted(active)
        for left_index, left in enumerate(names):
            for right in names[left_index + 1 :]:
                correlation = abs(float(correlations.get(left, {}).get(right, 0.0)))
                pair_weight = weights[left] + weights[right]
                if (
                    correlation >= self.config.correlation_threshold
                    and pair_weight > self.config.max_correlated_pair_weight
                ):
                    pair_scale = self.config.max_correlated_pair_weight / pair_weight
                    weights[left] *= pair_scale
                    weights[right] *= pair_scale
                    constraints.append(f"correlation:{left}:{right}")

        venue_totals: dict[str, float] = {}
        for name, weight in weights.items():
            venue = venues.get(name, "UNKNOWN")
            venue_totals[venue] = venue_totals.get(venue, 0.0) + weight
        for venue, total in venue_totals.items():
            if total > self.config.max_venue_weight:
                venue_scale = self.config.max_venue_weight / total
                for name in weights:
                    if venues.get(name, "UNKNOWN") == venue:
                        weights[name] *= venue_scale
                constraints.append(f"venue:{venue}")

        total = sum(weights.values())
        risk_units = {name: weights[name] * max(float(volatilities[name]), 0.0) for name in weights}
        total_risk = sum(risk_units.values())
        contributions = (
            {name: value / total_risk for name, value in risk_units.items()}
            if total_risk
            else {name: 0.0 for name in weights}
        )
        hhi = sum((weight / total) ** 2 for weight in weights.values()) if total else 0.0
        return RiskBudgetAllocation(
            weights=dict(sorted(weights.items())),
            cash_weight=1.0 - total,
            risk_contributions=dict(sorted(contributions.items())),
            concentration_hhi=hhi,
            constraints_applied=tuple(sorted(set(constraints))),
        )
