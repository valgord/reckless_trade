from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from domain.models import MarketRegime, PortfolioTarget, Signal
from trading.alpha.aggregation import WeightedSignalAggregator
from trading.portfolio.constructor import LongOnlySignalPortfolioConstructor
from trading.risk.policy import PortfolioRiskPolicy


@dataclass(frozen=True, slots=True)
class PipelineDecision:
    raw_signals: tuple[Signal, ...]
    aggregated_signals: tuple[Signal, ...]
    target: PortfolioTarget
    accepted: bool
    risk_errors: tuple[str, ...]
    regime: MarketRegime


class StrategyPipeline:
    def __init__(
        self,
        aggregator: WeightedSignalAggregator,
        portfolio_constructor: LongOnlySignalPortfolioConstructor,
        risk_policy: PortfolioRiskPolicy,
        regime_weights: dict[MarketRegime, dict[str, float]] | None = None,
    ) -> None:
        self.aggregator = aggregator
        self.portfolio_constructor = portfolio_constructor
        self.risk_policy = risk_policy
        self.regime_weights = regime_weights or {}

    def decide(self, signals: Iterable[Signal], numeraire: str, regime: MarketRegime) -> PipelineDecision:
        raw = tuple(signals)
        previous = dict(self.aggregator.weights)
        overrides = self.regime_weights.get(regime, {})
        if overrides:
            self.aggregator.weights.update(overrides)
        try:
            aggregated = tuple(self.aggregator.aggregate(raw))
        finally:
            self.aggregator.weights = previous
        target = self.portfolio_constructor.construct(aggregated, numeraire)
        accepted, errors = self.risk_policy.validate_target(target)
        return PipelineDecision(raw, aggregated, target, accepted, tuple(errors), regime)
