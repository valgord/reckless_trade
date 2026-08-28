from __future__ import annotations

import pytest

from trading.execution.carry import (
    CarryAccountSnapshot,
    CarryExecutionGuard,
    CarryGuardConfig,
    CarryOwnership,
    CarryPairFillDecision,
    CarryPhase,
    evaluate_pair_fills,
    read_carry_ownership,
    write_carry_ownership,
)


def snapshot(**overrides) -> CarryAccountSnapshot:
    values = {
        "reconciliation_complete": True,
        "spot_quantity": 0.0,
        "perp_quantity": 0.0,
        "spot_price": 100_000.0,
        "perp_price": 100_000.0,
        "free_usdt": 50.0,
        "open_orders": 0,
    }
    values.update(overrides)
    return CarryAccountSnapshot(**values)


def test_flat_account_produces_grouped_equal_quantity_pair() -> None:
    decision = CarryExecutionGuard(CarryGuardConfig()).evaluate(snapshot())

    assert decision.phase == CarryPhase.FLAT_READY
    assert [action.side for action in decision.actions] == ["buy", "sell"]
    assert {action.group for action in decision.actions} == {"open_pair"}
    assert decision.actions[0].quantity == decision.actions[1].quantity == 0.0001


def test_reconciliation_and_open_orders_block_new_pair() -> None:
    guard = CarryExecutionGuard(CarryGuardConfig())

    assert guard.evaluate(snapshot(reconciliation_complete=False)).phase == CarryPhase.BLOCKED
    assert guard.evaluate(snapshot(open_orders=1)).phase == CarryPhase.BLOCKED


def test_insufficient_balance_blocks_new_pair() -> None:
    decision = CarryExecutionGuard(CarryGuardConfig()).evaluate(snapshot(free_usdt=29.99))

    assert decision.phase == CarryPhase.BLOCKED
    assert "below required" in decision.reasons[0]


def test_exchange_minimum_quantity_blocks_pair_above_notional_cap() -> None:
    decision = CarryExecutionGuard(CarryGuardConfig()).evaluate(
        snapshot(minimum_quantity=0.001, quantity_increment=0.001)
    )

    assert decision.phase == CarryPhase.BLOCKED
    assert "minimum shared quantity" in decision.reasons[0]


def test_target_quantity_rounds_down_to_shared_increment() -> None:
    decision = CarryExecutionGuard(CarryGuardConfig(target_notional_usdt=10.09)).evaluate(
        snapshot(spot_price=100_000.0, perp_price=100_000.0, minimum_quantity=0.00001, quantity_increment=0.00001)
    )

    assert decision.phase == CarryPhase.FLAT_READY
    assert decision.target_quantity == 0.0001


def test_quantity_mismatch_only_reduces_excess_leg() -> None:
    guard = CarryExecutionGuard(CarryGuardConfig(target_notional_usdt=10))

    long_excess = guard.evaluate(snapshot(spot_quantity=0.0001, perp_quantity=-0.00008))
    short_excess = guard.evaluate(snapshot(spot_quantity=0.00008, perp_quantity=-0.0001))

    assert long_excess.phase == CarryPhase.REPAIR_REQUIRED
    assert [(action.instrument, action.side) for action in long_excess.actions] == [("BTCUSDT-SPOT.BYBIT", "sell")]
    assert short_excess.phase == CarryPhase.REPAIR_REQUIRED
    assert [(action.instrument, action.side) for action in short_excess.actions] == [("BTCUSDT-LINEAR.BYBIT", "buy")]
    assert all(action.risk_reducing for action in long_excess.actions + short_excess.actions)
    assert long_excess.actions[0].reduce_only is False
    assert short_excess.actions[0].reduce_only is True


def test_low_margin_closes_both_legs() -> None:
    decision = CarryExecutionGuard(CarryGuardConfig(minimum_margin_ratio=3)).evaluate(
        snapshot(spot_quantity=0.0001, perp_quantity=-0.0001, free_usdt=1.0)
    )

    assert decision.phase == CarryPhase.CLOSE_REQUIRED
    assert [action.side for action in decision.actions] == ["sell", "buy"]
    assert all(action.risk_reducing for action in decision.actions)
    assert [action.reduce_only for action in decision.actions] == [False, True]


def test_balanced_capped_pair_is_hedged() -> None:
    decision = CarryExecutionGuard(CarryGuardConfig()).evaluate(snapshot(spot_quantity=0.0001, perp_quantity=-0.0001))

    assert decision.phase == CarryPhase.HEDGED
    assert decision.coin_delta == 0
    assert decision.actions == ()


def test_ownership_ledger_defaults_empty_and_round_trips(tmp_path) -> None:
    path = tmp_path / "carry-ownership.json"

    assert read_carry_ownership(path) == CarryOwnership()
    write_carry_ownership(path, CarryOwnership(0.001, -0.001))

    assert read_carry_ownership(path) == CarryOwnership(0.001, -0.001)


def test_ownership_ledger_rejects_invalid_direction(tmp_path) -> None:
    path = tmp_path / "carry-ownership.json"
    path.write_text(
        '{"schema_version": 1, "spot_quantity": 0.001, "perp_quantity": 0.001}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="non-positive"):
        read_carry_ownership(path)


def test_pair_fill_decision_requires_two_complete_legs() -> None:
    assert evaluate_pair_fills(0.001, 0.001, 0.001) == CarryPairFillDecision(True, 0.0, 0.0)
    assert evaluate_pair_fills(0.001, 0.001, 0.0004) == CarryPairFillDecision(False, 0.001, 0.0004)
    assert evaluate_pair_fills(0.001, 0.0, 0.001) == CarryPairFillDecision(False, 0.0, 0.001)
