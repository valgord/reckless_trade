from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from research.experiments.carry_runner import CarryConfig, CarryObservation, CarryPolicy, simulate_carry


def observations(rate: float, count: int = 40) -> list[CarryObservation]:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    return [CarryObservation(start + timedelta(hours=8 * index), rate, 100.0, 100.0) for index in range(count)]


def test_positive_funding_produces_explainable_usdt_return():
    result = simulate_carry(
        observations(0.001),
        CarryPolicy("always_on"),
        CarryConfig(spot_fee_bps=0, spot_slippage_bps=0, perp_fee_bps=0, perp_slippage_bps=0),
    )

    assert result.metrics.return_usdt > 0
    assert result.metrics.funding_income > 0
    assert result.metrics.basis_pnl == 0
    assert result.metrics.trading_costs == 0
    assert result.metrics.maximum_absolute_coin_delta == 0
    assert result.metrics.return_usdt == pytest.approx(
        result.metrics.funding_income + result.metrics.basis_pnl - result.metrics.trading_costs
    )


def test_negative_funding_and_costs_are_not_hidden():
    result = simulate_carry(observations(-0.001), CarryPolicy("always_on"), CarryConfig())

    assert result.metrics.return_usdt < 0
    assert result.metrics.negative_funding_paid > 0
    assert result.metrics.trading_costs > 0


def test_prior_rate_policy_cannot_use_current_unsettled_rate():
    result = simulate_carry(
        observations(0.001, count=6),
        CarryPolicy("prior_positive", lookback_settlements=3, minimum_average_rate=0),
        CarryConfig(spot_fee_bps=0, spot_slippage_bps=0, perp_fee_bps=0, perp_slippage_bps=0),
    )

    assert result.metrics.active_settlements == 2
