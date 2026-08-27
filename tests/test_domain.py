from domain.models import InstrumentKey, PortfolioTarget, Signal, TargetAllocation
from trading.alpha.aggregation import WeightedSignalAggregator
from trading.alpha.models import MeanReversionAlpha, PriceSeriesContext
from trading.portfolio.constructor import LongOnlySignalPortfolioConstructor
from trading.risk.policy import PortfolioRiskPolicy


def test_mean_reversion_emits_countertrend_signal():
    closes = [100.0] * 49 + [120.0]
    signal = MeanReversionAlpha(window=50, entry_z=2.0).generate(PriceSeriesContext(InstrumentKey("BYBIT", "BTCUSDT"), closes))[0]
    assert signal.direction == -1.0


def test_aggregator_combines_sources():
    instrument = InstrumentKey("BYBIT", "BTCUSDT")
    signals = [Signal("a", instrument, 1.0, 0.8, 1.0, 60), Signal("b", instrument, -1.0, 0.2, 1.0, 60)]
    result = WeightedSignalAggregator().aggregate(signals)
    assert len(result) == 1
    assert result[0].direction > 0


def test_portfolio_and_risk():
    instrument = InstrumentKey("BYBIT", "BTCUSDT")
    signal = Signal("a", instrument, 1.0, 1.0, 1.0, 60)
    target = LongOnlySignalPortfolioConstructor(max_asset_weight=0.25, reserve_weight=0.1).construct([signal], "BTC")
    assert target.allocations[0].weight == 0.25
    ok, errors = PortfolioRiskPolicy(max_single_asset_weight=0.35, max_total_invested=0.9).validate_target(target)
    assert ok and not errors


def test_risk_rejects_oversized_target():
    target = PortfolioTarget((TargetAllocation(InstrumentKey("BYBIT", "BTCUSDT"), 0.8),), "BTC")
    ok, errors = PortfolioRiskPolicy(max_single_asset_weight=0.35, max_total_invested=0.9).validate_target(target)
    assert not ok and errors
