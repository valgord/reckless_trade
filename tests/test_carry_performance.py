from __future__ import annotations

import pytest

from trading.execution.carry_performance import CarryEntryLeg, calculate_carry_performance


def test_active_carry_performance_explains_basis_funding_and_costs() -> None:
    result = calculate_carry_performance(
        CarryEntryLeg(quantity=1, average_price=100, fee_usdt=0.1, fee_rate=0.001),
        CarryEntryLeg(quantity=1, average_price=102, fee_usdt=0.1, fee_rate=0.002),
        current_spot_exit_price=103,
        current_perp_exit_price=101,
        funding_income_usdt=0.5,
    )

    assert result.entry_basis_usdt_per_btc == 2
    assert result.current_basis_usdt_per_btc == -2
    assert result.basis_pnl_usdt == 4
    assert result.opening_fees_usdt == pytest.approx(0.2)
    assert result.estimated_closing_fees_usdt == pytest.approx(0.305)
    assert result.net_pnl_before_exit_costs_usdt == pytest.approx(4.3)
    assert result.estimated_net_pnl_usdt == pytest.approx(3.995)
    assert result.estimated_return_on_capital == pytest.approx(3.995 / 202)


def test_performance_rejects_unequal_legs() -> None:
    with pytest.raises(ValueError, match="equal"):
        calculate_carry_performance(
            CarryEntryLeg(1, 100, 0, 0.001),
            CarryEntryLeg(0.5, 100, 0, 0.001),
            100,
            100,
            0,
        )
