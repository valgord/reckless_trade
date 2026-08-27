from __future__ import annotations

from research.backtests.simple_engine import CostModel
from research.experiments.m3_runner import (
    Candidate,
    PreparedCandidate,
    candidate_is_eligible,
    default_m4_candidates,
    simulate_candidate,
)
from research.validation.selection import deflated_sharpe_probability, probability_of_backtest_overfitting


def test_minimum_hold_reduces_turnover() -> None:
    closes = [100.0, 101.0, 100.0, 101.0, 100.0, 101.0]
    targets = [0.1, 0.0, 0.1, 0.0, 0.1, 0.0]
    regimes = ["range"] * len(closes)
    fast = PreparedCandidate(Candidate("fast", ("momentum",)), targets, regimes, {})
    held = PreparedCandidate(Candidate("held", ("momentum",), 3), targets, regimes, {})

    fast_result = simulate_candidate(fast, closes, 0, len(closes), CostModel())
    held_result = simulate_candidate(held, closes, 0, len(closes), CostModel())

    assert held_result.metrics.trades < fast_result.metrics.trades
    assert held_result.metrics.turnover < fast_result.metrics.turnover


def test_selection_risk_metrics_distinguish_stable_candidate() -> None:
    stable = [0.01] * 50 + [0.009]
    assert deflated_sharpe_probability(stable, trials=5) > 0.75
    pbo = probability_of_backtest_overfitting(
        {
            "stable": [0.02] * 8,
            "unstable": [0.10, -0.10] * 4,
        }
    )
    assert 0.0 <= pbo <= 1.0


def test_m4_candidates_include_regime_gates_and_volatility_alpha() -> None:
    candidates = default_m4_candidates()

    assert any(item.allowed_regimes == ("trend_up",) for item in candidates)
    assert any("volatility_breakout" in item.enabled for item in candidates)
    assert {item.regime_entry_bars for item in candidates} >= {4, 16, 48}


def test_disallowed_regime_forces_exit_before_minimum_hold() -> None:
    candidate = Candidate("gated", ("trend_following",), 10, ("trend_up",))
    prepared = PreparedCandidate(candidate, [0.1, 0.0, 0.0], ["trend_up", "range", "range"], {})

    result = simulate_candidate(prepared, [100.0, 101.0, 102.0], 0, 3, CostModel(0, 0, 0))

    assert result.metrics.trades == 2
    assert result.metrics.exposure == 0.5


def test_zero_trade_candidate_is_not_eligible_for_selection() -> None:
    candidate = Candidate("cash", ("trend_following",))
    prepared = PreparedCandidate(candidate, [0.0, 0.0, 0.0], ["range"] * 3, {})
    result = simulate_candidate(prepared, [100.0, 90.0, 80.0], 0, 3, CostModel())

    assert candidate_is_eligible(result, periods=3, full_periods=3) is False
