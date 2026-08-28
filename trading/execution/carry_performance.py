from __future__ import annotations

import math
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class CarryEntryLeg:
    quantity: float
    average_price: float
    fee_usdt: float
    fee_rate: float

    def __post_init__(self) -> None:
        values = (self.quantity, self.average_price, self.fee_usdt, self.fee_rate)
        if any(not math.isfinite(value) or value < 0 for value in values):
            raise ValueError("carry entry leg values must be finite and non-negative")
        if self.quantity <= 0 or self.average_price <= 0:
            raise ValueError("carry entry quantity and price must be positive")


@dataclass(frozen=True, slots=True)
class CarryPerformance:
    quantity: float
    opening_notional_usdt: float
    entry_basis_usdt_per_btc: float
    current_basis_usdt_per_btc: float
    basis_pnl_usdt: float
    funding_income_usdt: float
    opening_fees_usdt: float
    estimated_closing_fees_usdt: float
    net_pnl_before_exit_costs_usdt: float
    estimated_net_pnl_usdt: float
    estimated_return_on_capital: float

    def as_dict(self) -> dict:
        return asdict(self)


def calculate_carry_performance(
    spot: CarryEntryLeg,
    perp: CarryEntryLeg,
    current_spot_exit_price: float,
    current_perp_exit_price: float,
    funding_income_usdt: float,
) -> CarryPerformance:
    values = (current_spot_exit_price, current_perp_exit_price, funding_income_usdt)
    if any(not math.isfinite(value) for value in values):
        raise ValueError("carry performance inputs must be finite")
    if current_spot_exit_price <= 0 or current_perp_exit_price <= 0:
        raise ValueError("current carry exit prices must be positive")
    if abs(spot.quantity - perp.quantity) > max(spot.quantity * 1e-9, 1e-12):
        raise ValueError("carry performance requires equal entry quantities")

    quantity = spot.quantity
    spot_pnl = quantity * (current_spot_exit_price - spot.average_price)
    perp_pnl = quantity * (perp.average_price - current_perp_exit_price)
    basis_pnl = spot_pnl + perp_pnl
    opening_fees = spot.fee_usdt + perp.fee_usdt
    estimated_closing_fees = quantity * (
        current_spot_exit_price * spot.fee_rate + current_perp_exit_price * perp.fee_rate
    )
    net_before_exit = basis_pnl + funding_income_usdt - opening_fees
    estimated_net = net_before_exit - estimated_closing_fees
    opening_notional = quantity * (spot.average_price + perp.average_price)

    return CarryPerformance(
        quantity=quantity,
        opening_notional_usdt=opening_notional,
        entry_basis_usdt_per_btc=perp.average_price - spot.average_price,
        current_basis_usdt_per_btc=current_perp_exit_price - current_spot_exit_price,
        basis_pnl_usdt=basis_pnl,
        funding_income_usdt=funding_income_usdt,
        opening_fees_usdt=opening_fees,
        estimated_closing_fees_usdt=estimated_closing_fees,
        net_pnl_before_exit_costs_usdt=net_before_exit,
        estimated_net_pnl_usdt=estimated_net,
        estimated_return_on_capital=estimated_net / opening_notional,
    )
