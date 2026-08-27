from __future__ import annotations

import numpy as np
import pytest

from research.backtests.simple_engine import CostModel
from research.experiments.m3_runner import Candidate
from research.experiments.m5_runner import PortfolioPolicy, _execution_states, simulate_portfolio
from trading.portfolio.risk_budget import InverseVolatilityRiskAllocator, RiskBudgetConfig


def test_inverse_volatility_allocator_respects_asset_total_and_cash_limits() -> None:
    allocator = InverseVolatilityRiskAllocator(RiskBudgetConfig(max_total_weight=0.30, max_asset_weight=0.15))
    result = allocator.allocate(
        {"BTC", "ETH", "SOL"},
        {"BTC": 0.02, "ETH": 0.04, "SOL": 0.08},
        {},
        {"BTC": "BYBIT", "ETH": "BYBIT", "SOL": "BYBIT"},
    )

    assert sum(result.weights.values()) <= 0.30 + 1e-12
    assert max(result.weights.values()) <= 0.15
    assert result.cash_weight >= 0.70
    assert sum(result.risk_contributions.values()) == pytest.approx(1.0)


def test_correlated_pair_is_scaled_to_cluster_budget() -> None:
    config = RiskBudgetConfig(
        max_total_weight=0.40,
        max_asset_weight=0.25,
        max_correlated_pair_weight=0.20,
        correlation_threshold=0.75,
        max_venue_weight=0.40,
    )
    result = InverseVolatilityRiskAllocator(config).allocate(
        {"BTC", "ETH"},
        {"BTC": 0.02, "ETH": 0.02},
        {"BTC": {"ETH": 0.90}},
        {"BTC": "BYBIT", "ETH": "BYBIT"},
    )

    assert sum(result.weights.values()) == pytest.approx(0.20)
    assert any(item.startswith("correlation:") for item in result.constraints_applied)


def test_multi_asset_execution_state_holds_signal_but_forces_regime_exit() -> None:
    candidate = Candidate("trend", ("trend_following",), 4, ("trend_up",))
    states = _execution_states(
        [1.0, 0.0, 0.0, 0.0],
        ["trend_up", "trend_up", "range", "range"],
        candidate,
    )

    assert states == [1.0, 1.0, 0.0, 0.0]


def test_portfolio_drawdown_kill_switch_flattens_permanently() -> None:
    risk = RiskBudgetConfig(
        max_total_weight=0.30,
        max_asset_weight=0.30,
        max_correlated_pair_weight=0.30,
        max_venue_weight=0.30,
    )
    result = simulate_portfolio(
        PortfolioPolicy("equal", "equal"),
        ["BTC"],
        {"BTC": np.asarray([100.0, 80.0, 70.0])},
        {"BTC": [1.0, 1.0, 1.0]},
        0,
        3,
        CostModel(0, 0, 0),
        risk,
        rebalance_bars=1,
        kill_drawdown=0.01,
    )

    assert result.metrics.kill_switch_triggered is True
    assert result.metrics.turnover == pytest.approx(0.60)
