from __future__ import annotations

from dataclasses import dataclass

from domain.models import PortfolioSnapshot, PortfolioTarget


@dataclass(slots=True)
class PortfolioRiskPolicy:
    max_single_asset_weight: float = 0.35
    max_total_invested: float = 0.90
    max_drawdown: float = 0.15
    min_equity: float = 0.0

    def validate_target(self, target: PortfolioTarget) -> tuple[bool, list[str]]:
        errors: list[str] = []
        total = sum(a.weight for a in target.allocations)
        if total > self.max_total_invested + 1e-12:
            errors.append(f"total allocation {total:.4f} exceeds {self.max_total_invested:.4f}")
        for allocation in target.allocations:
            if allocation.weight > self.max_single_asset_weight + 1e-12:
                errors.append(f"{allocation.instrument.canonical} exceeds single-asset limit")
            if allocation.weight < 0:
                errors.append(f"{allocation.instrument.canonical} has negative weight in long-only policy")
        return not errors, errors

    def validate_runtime(self, snapshot: PortfolioSnapshot) -> tuple[bool, list[str]]:
        errors: list[str] = []
        if snapshot.drawdown <= -abs(self.max_drawdown):
            errors.append(f"drawdown {snapshot.drawdown:.2%} breaches {-abs(self.max_drawdown):.2%}")
        if snapshot.equity_numeraire < self.min_equity:
            errors.append("equity is below configured floor")
        return not errors, errors
