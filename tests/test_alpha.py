from domain.models import InstrumentKey
from trading.alpha.models import (
    BreakoutAlpha,
    MeanReversionAlpha,
    MomentumAlpha,
    PriceSeriesContext,
    TrendFollowingAlpha,
    VolatilityBreakoutAlpha,
)


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


def test_volatility_breakout_requires_expansion_and_uses_momentum_direction():
    quiet = [100 + (index % 2) * 0.01 for index in range(101)]
    expansion = [quiet[-1]]
    for index in range(21):
        expansion.append(expansion[-1] + (10.0 if index % 2 == 0 else -5.0))
    signal = VolatilityBreakoutAlpha(expansion_ratio=1.2).generate(ctx(quiet + expansion))[0]

    assert signal.direction > 0
    assert signal.metadata["short_vol"] > signal.metadata["long_vol"]
