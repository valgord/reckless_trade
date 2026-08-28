from __future__ import annotations

from datetime import UTC, datetime, timedelta

from apps.trader.carry_observer import build_carry_observer_strategy
from apps.trader.demo_strategy import DemoDecisionEngine, build_demo_observer_strategy
from apps.trader.main import runtime_risk_config
from domain.models import Bar, InstrumentKey
from platform_core.settings import load_settings


def test_demo_decision_engine_runs_domain_pipeline() -> None:
    settings = load_settings("demo")
    instrument = InstrumentKey("BYBIT", "BTCUSDT")
    engine = DemoDecisionEngine(settings.raw, instrument)
    start = datetime(2026, 1, 1, tzinfo=UTC)

    result = None
    for index in range(120):
        close = 100.0 + index
        result = engine.on_bar(Bar(instrument, start + timedelta(minutes=15 * index), close, close, close, close, 1.0))

    assert result is not None
    assert result["bar_count"] == 120
    assert result["regime"] == "trend_up"
    assert result["accepted"] is True
    assert result["target_weights"]["BYBIT:BTCUSDT"] <= 0.35


def test_demo_observer_is_explicitly_orderless() -> None:
    settings = load_settings("demo")
    strategy = build_demo_observer_strategy(settings.raw)

    assert str(strategy.config.instrument_id) == "BTCUSDT-SPOT.BYBIT"
    assert str(strategy.config.bar_type) == "BTCUSDT-SPOT.BYBIT-15-MINUTE-LAST-EXTERNAL"
    assert not hasattr(strategy, "buy")


def test_carry_observer_targets_spot_and_linear_but_remains_orderless() -> None:
    settings = load_settings("demo")
    strategy = build_carry_observer_strategy(settings.raw)

    assert str(strategy.config.spot_instrument_id) == "BTCUSDT-SPOT.BYBIT"
    assert str(strategy.config.perp_instrument_id) == "BTCUSDT-LINEAR.BYBIT"
    assert strategy.guard.config.target_notional_usdt == 100
    assert strategy.guard.config.minimum_free_reserve_usdt == 50
    assert not hasattr(strategy, "buy")


def test_carry_risk_limit_does_not_expand_ordinary_demo_runtime() -> None:
    settings = load_settings("demo")

    assert runtime_risk_config(settings.raw, carry_enabled=False)["max_order_notional_usdt"] == 10
    assert runtime_risk_config(settings.raw, carry_enabled=True)["max_order_notional_usdt"] == 100
