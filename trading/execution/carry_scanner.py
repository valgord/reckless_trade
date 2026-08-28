from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CarryScannerConfig:
    target_notional_usdt: float = 100.0
    horizon_settlements: int = 3
    minimum_turnover_24h_usdt: float = 10_000_000.0
    minimum_funding_samples: int = 6
    minimum_positive_funding_share: float = 0.6
    spot_taker_fee_rate: float = 0.001
    perp_taker_fee_rate: float = 0.00055

    def __post_init__(self) -> None:
        values = (
            self.target_notional_usdt,
            self.minimum_turnover_24h_usdt,
            self.minimum_positive_funding_share,
            self.spot_taker_fee_rate,
            self.perp_taker_fee_rate,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("carry scanner config values must be finite")
        if self.target_notional_usdt <= 0 or self.minimum_turnover_24h_usdt < 0:
            raise ValueError("carry scanner notionals and turnover must be positive")
        if self.horizon_settlements < 1 or self.minimum_funding_samples < 1:
            raise ValueError("carry scanner settlement and sample counts must be positive")
        if not 0 <= self.minimum_positive_funding_share <= 1:
            raise ValueError("minimum positive funding share must be between zero and one")
        if self.spot_taker_fee_rate < 0 or self.perp_taker_fee_rate < 0:
            raise ValueError("carry scanner fees cannot be negative")


@dataclass(frozen=True, slots=True)
class CarryScanCandidate:
    symbol: str
    eligible: bool
    reasons: tuple[str, ...]
    rank_score: float
    funding: dict[str, Any]
    market: dict[str, float]
    liquidity: dict[str, float]
    estimate: dict[str, float | None]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_carry_candidate(
    symbol: str,
    spot_ticker: dict[str, Any],
    perp_ticker: dict[str, Any],
    spot_instrument: dict[str, Any],
    perp_instrument: dict[str, Any],
    funding_rates: list[float],
    config: CarryScannerConfig,
) -> CarryScanCandidate:
    spot_ask = _positive(spot_ticker, "ask1Price")
    spot_bid = _positive(spot_ticker, "bid1Price")
    perp_bid = _positive(perp_ticker, "bid1Price")
    perp_ask = _positive(perp_ticker, "ask1Price")
    perp_mark = _positive(perp_ticker, "markPrice")
    spot_ask_size = _positive(spot_ticker, "ask1Size")
    perp_bid_size = _positive(perp_ticker, "bid1Size")
    spot_turnover = _non_negative(spot_ticker, "turnover24h")
    perp_turnover = _non_negative(perp_ticker, "turnover24h")
    current_funding = _finite(perp_ticker, "fundingRate")
    if not funding_rates or not all(math.isfinite(rate) for rate in funding_rates):
        raise ValueError(f"{symbol} has invalid funding history")

    average_funding = sum(funding_rates) / len(funding_rates)
    positive_share = sum(rate > 0 for rate in funding_rates) / len(funding_rates)
    quantity = config.target_notional_usdt / spot_ask
    top_book_capacity_qty = min(spot_ask_size, perp_bid_size)
    top_book_capacity_usdt = min(spot_ask_size * spot_ask, perp_bid_size * perp_bid)
    minimum_pair_notional = _minimum_pair_notional(spot_instrument, perp_instrument, spot_ask, perp_bid)

    spread_pnl = quantity * ((spot_bid - spot_ask) + (perp_bid - perp_ask))
    roundtrip_fees = quantity * (
        (spot_ask + spot_bid) * config.spot_taker_fee_rate
        + (perp_bid + perp_ask) * config.perp_taker_fee_rate
    )
    funding_per_settlement = quantity * perp_mark * average_funding
    horizon_funding = funding_per_settlement * config.horizon_settlements
    estimated_net = spread_pnl - roundtrip_fees + horizon_funding
    break_even_settlements = (
        max(0.0, roundtrip_fees - spread_pnl) / funding_per_settlement if funding_per_settlement > 0 else None
    )

    reasons = []
    if current_funding <= 0:
        reasons.append("current_funding_not_positive")
    if len(funding_rates) < config.minimum_funding_samples:
        reasons.append("insufficient_funding_history")
    if positive_share < config.minimum_positive_funding_share:
        reasons.append("positive_funding_share_below_threshold")
    if spot_turnover < config.minimum_turnover_24h_usdt:
        reasons.append("spot_turnover_below_threshold")
    if perp_turnover < config.minimum_turnover_24h_usdt:
        reasons.append("perp_turnover_below_threshold")
    if top_book_capacity_usdt < config.target_notional_usdt:
        reasons.append("insufficient_top_of_book_capacity")
    if config.target_notional_usdt < minimum_pair_notional:
        reasons.append("target_below_minimum_pair_notional")
    if estimated_net <= 0:
        reasons.append("estimated_horizon_net_not_positive")

    eligible = not reasons
    return CarryScanCandidate(
        symbol=symbol,
        eligible=eligible,
        reasons=tuple(reasons),
        rank_score=estimated_net,
        funding={
            "current_rate": current_funding,
            "historical_average_rate": average_funding,
            "positive_share": positive_share,
            "sample_count": len(funding_rates),
            "interval_minutes": int(perp_instrument.get("fundingInterval") or 0),
            "next_funding_at_ms": int(perp_ticker.get("nextFundingTime") or 0),
        },
        market={
            "spot_entry_ask": spot_ask,
            "spot_exit_bid": spot_bid,
            "perp_entry_bid": perp_bid,
            "perp_exit_ask": perp_ask,
            "perp_mark": perp_mark,
            "entry_basis_bps": (perp_bid / spot_ask - 1) * 10_000,
        },
        liquidity={
            "spot_turnover_24h_usdt": spot_turnover,
            "perp_turnover_24h_usdt": perp_turnover,
            "top_book_capacity_quantity": top_book_capacity_qty,
            "top_book_capacity_usdt": top_book_capacity_usdt,
            "minimum_pair_notional_usdt": minimum_pair_notional,
        },
        estimate={
            "target_notional_usdt": config.target_notional_usdt,
            "quantity": quantity,
            "roundtrip_spread_pnl_usdt": spread_pnl,
            "roundtrip_fees_usdt": roundtrip_fees,
            "average_funding_per_settlement_usdt": funding_per_settlement,
            "funding_over_horizon_usdt": horizon_funding,
            "estimated_net_over_horizon_usdt": estimated_net,
            "break_even_settlements": break_even_settlements,
        },
    )


def _minimum_pair_notional(
    spot_instrument: dict[str, Any],
    perp_instrument: dict[str, Any],
    spot_price: float,
    perp_price: float,
) -> float:
    spot_lot = spot_instrument.get("lotSizeFilter") or {}
    perp_lot = perp_instrument.get("lotSizeFilter") or {}
    return max(
        float(spot_lot.get("minOrderAmt") or 0),
        float(spot_lot.get("minOrderQty") or 0) * spot_price,
        float(perp_lot.get("minNotionalValue") or 0),
        float(perp_lot.get("minOrderQty") or 0) * perp_price,
    )


def _positive(payload: dict[str, Any], key: str) -> float:
    value = _finite(payload, key)
    if value <= 0:
        raise ValueError(f"{key} must be positive")
    return value


def _non_negative(payload: dict[str, Any], key: str) -> float:
    value = _finite(payload, key)
    if value < 0:
        raise ValueError(f"{key} cannot be negative")
    return value


def _finite(payload: dict[str, Any], key: str) -> float:
    try:
        value = float(payload[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{key} is missing or invalid") from exc
    if not math.isfinite(value):
        raise ValueError(f"{key} must be finite")
    return value
