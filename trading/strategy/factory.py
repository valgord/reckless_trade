from __future__ import annotations

from typing import Any

from trading.alpha.aggregation import WeightedSignalAggregator
from trading.alpha.models import BreakoutAlpha, MeanReversionAlpha, MomentumAlpha, TrendFollowingAlpha
from trading.portfolio.constructor import LongOnlySignalPortfolioConstructor
from trading.risk.policy import PortfolioRiskPolicy
from trading.strategy.pipeline import StrategyPipeline


def build_alpha_models(config: dict[str, Any]) -> list[object]:
    items: list[object] = []
    strategies = config.get("strategies", {})
    for name, values in strategies.items():
        if not values.get("enabled", False):
            continue
        if name == "trend_following":
            items.append(TrendFollowingAlpha(fast=int(values.get("fast", 20)), slow=int(values.get("slow", 100)),
                                             min_separation=float(values.get("min_separation", 0.002))))
        elif name == "mean_reversion":
            items.append(MeanReversionAlpha(window=int(values.get("window", 50)), entry_z=float(values.get("entry_z", 2.0))))
        elif name == "momentum":
            items.append(MomentumAlpha(lookback=int(values.get("lookback", 20)), threshold=float(values.get("threshold", 0.01))))
        elif name == "breakout":
            items.append(BreakoutAlpha(lookback=int(values.get("lookback", 20)), buffer=float(values.get("buffer", 0.0))))
    return items


def build_pipeline(config: dict[str, Any]) -> StrategyPipeline:
    strategies = config.get("strategies", {})
    weights = {name: float(values.get("weight", 1.0)) for name, values in strategies.items() if values.get("enabled", False)}
    portfolio = config.get("portfolio", {})
    risk = config.get("risk", {})
    return StrategyPipeline(
        WeightedSignalAggregator(weights),
        LongOnlySignalPortfolioConstructor(max_asset_weight=float(portfolio.get("max_asset_weight", 0.35)),
                                           reserve_weight=float(portfolio.get("reserve_weight", 0.10)),
                                           min_signal=float(portfolio.get("min_signal", 0.05))),
        PortfolioRiskPolicy(max_single_asset_weight=float(risk.get("max_single_asset_weight", 0.35)),
                            max_total_invested=float(risk.get("max_total_invested", 0.90)),
                            max_drawdown=float(risk.get("kill_switch_drawdown", 0.15))),
    )
