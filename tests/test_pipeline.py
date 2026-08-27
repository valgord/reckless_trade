from domain.models import InstrumentKey, MarketRegime, Signal
from trading.alpha.aggregation import WeightedSignalAggregator
from trading.portfolio.constructor import LongOnlySignalPortfolioConstructor
from trading.risk.policy import PortfolioRiskPolicy
from trading.strategy.pipeline import StrategyPipeline


def test_pipeline_builds_accepted_target():
    instrument = InstrumentKey("BYBIT", "BTCUSDT")
    signals = [Signal("momentum", instrument, 1, 0.8, 0.9, 3600), Signal("trend", instrument, 1, 0.7, 0.8, 3600)]
    pipeline = StrategyPipeline(
        WeightedSignalAggregator(),
        LongOnlySignalPortfolioConstructor(max_asset_weight=0.35),
        PortfolioRiskPolicy(max_single_asset_weight=0.35),
    )
    decision = pipeline.decide(signals, "BTC", MarketRegime.TREND_UP)
    assert decision.accepted
    assert decision.target.allocations[0].weight <= 0.35
