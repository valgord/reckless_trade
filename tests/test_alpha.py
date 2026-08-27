from domain.models import InstrumentKey
from trading.alpha.models import BreakoutAlpha, MeanReversionAlpha, MomentumAlpha, PriceSeriesContext, TrendFollowingAlpha


def ctx(values):
    return PriceSeriesContext(InstrumentKey("BYBIT", "BTCUSDT"), values)


def test_trend_and_momentum_signal_uptrend():
    values = [100 + i * 0.5 for i in range(120)]
    assert TrendFollowingAlpha(fast=10, slow=50).generate(ctx(values))[0].direction > 0
    assert MomentumAlpha(lookback=10, threshold=0.001).generate(ctx(values))[0].direction > 0


def test_breakout_signal():
    values = [100.0] * 21 + [105.0]
    assert BreakoutAlpha(lookback=20).generate(ctx(values))[0].direction > 0


def test_mean_reversion_signal():
    values = [100.0] * 49 + [80.0]
    assert MeanReversionAlpha(window=50, entry_z=2.0).generate(ctx(values))[0].direction > 0
