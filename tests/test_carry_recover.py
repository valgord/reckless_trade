from __future__ import annotations

import pytest

from scripts.carry_recover import CarryRecoveryError, select_open_pair, validate_observer


def row(link: str, side: str, quantity: str = "0.001") -> dict:
    return {"orderLinkId": link, "side": side, "execQty": quantity}


def test_selects_one_equal_pair() -> None:
    pair_id, quantity = select_open_pair(
        [row("rt-carry-open-26335d104f-s", "Buy")],
        [row("rt-carry-open-26335d104f-p", "Sell")],
    )

    assert pair_id == "rt-carry-open-26335d104f"
    assert quantity == 0.001


def test_rejects_ambiguous_or_unequal_history() -> None:
    with pytest.raises(CarryRecoveryError, match="exactly one"):
        select_open_pair([], [])
    with pytest.raises(CarryRecoveryError, match="equal positive"):
        select_open_pair(
            [row("rt-carry-open-26335d104f-s", "Buy")],
            [row("rt-carry-open-26335d104f-p", "Sell", "0.002")],
        )


def test_observer_must_confirm_position_and_balance() -> None:
    validate_observer(
        {
            "reconciliation_complete": True,
            "account_btc_total": 1.000999,
            "snapshot": {"open_orders": 0, "perp_quantity": -0.001},
        },
        0.001,
    )
    with pytest.raises(CarryRecoveryError, match="Linear short"):
        validate_observer(
            {
                "reconciliation_complete": True,
                "account_btc_total": 1.000999,
                "snapshot": {"open_orders": 0, "perp_quantity": 0},
            },
            0.001,
        )
