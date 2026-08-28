from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass

from research.backtests.simple_engine import CostModel
from research.experiments.m3_runner import PreparedCandidate, simulate_candidate


@dataclass(frozen=True, slots=True)
class ClosedTrade:
    entry_index: int
    exit_index: int
    bars_held: int
    entry_price: float
    exit_price: float
    underlying_return: float
    weighted_gross_return: float
    estimated_round_trip_cost: float
    regime_at_entry: str


def attribute_directional_candidate(
    prepared: PreparedCandidate,
    closes: list[float],
    costs: CostModel,
) -> dict:
    """Explain a candidate without changing its original execution state machine."""

    net = simulate_candidate(prepared, closes, 0, len(closes), costs)
    gross = simulate_candidate(prepared, closes, 0, len(closes), CostModel(0.0, 0.0, 0.0))
    trades = _closed_trades(prepared, closes, costs)
    winners = [trade for trade in trades if trade.weighted_gross_return > trade.estimated_round_trip_cost]
    regime_counts = Counter(trade.regime_at_entry for trade in trades)
    average_hold = sum(trade.bars_held for trade in trades) / len(trades) if trades else 0.0
    average_underlying = sum(trade.underlying_return for trade in trades) / len(trades) if trades else 0.0
    gross_return = gross.metrics.return_usdt
    net_return = net.metrics.return_usdt
    return {
        "candidate": asdict(prepared.candidate),
        "gross_return_usdt": gross_return,
        "net_return_usdt": net_return,
        "cost_drag": gross_return - net_return,
        "gross_edge_positive": gross_return > 0,
        "profit_factor_net": net.metrics.profit_factor,
        "exposure": net.metrics.exposure,
        "turnover": net.metrics.turnover,
        "position_changes": net.metrics.trades,
        "closed_trades": len(trades),
        "winning_closed_trades_after_estimated_cost": len(winners),
        "win_rate_after_estimated_cost": len(winners) / len(trades) if trades else 0.0,
        "average_hold_bars": average_hold,
        "average_underlying_return_per_trade": average_underlying,
        "entries_by_regime": dict(sorted(regime_counts.items())),
        "worst_closed_trades": [asdict(trade) for trade in sorted(trades, key=lambda item: item.underlying_return)[:5]],
        "best_closed_trades": [
            asdict(trade) for trade in sorted(trades, key=lambda item: item.underlying_return, reverse=True)[:5]
        ],
    }


def _closed_trades(
    prepared: PreparedCandidate,
    closes: list[float],
    costs: CostModel,
) -> list[ClosedTrade]:
    position = 0.0
    bars_held = prepared.candidate.min_hold_bars
    entry_index: int | None = None
    entry_weight = 0.0
    entry_regime = "unknown"
    records: list[ClosedTrade] = []
    for index in range(len(closes) - 1):
        desired = prepared.targets[index]
        regime_allowed = (
            not prepared.candidate.allowed_regimes or prepared.regimes[index] in prepared.candidate.allowed_regimes
        )
        forced_exit = position > 0 and not regime_allowed
        if desired != position and (forced_exit or bars_held >= prepared.candidate.min_hold_bars):
            if position > 0 and desired == 0 and entry_index is not None:
                underlying_return = closes[index] / closes[entry_index] - 1.0
                records.append(
                    ClosedTrade(
                        entry_index,
                        index,
                        index - entry_index,
                        closes[entry_index],
                        closes[index],
                        underlying_return,
                        entry_weight * underlying_return,
                        2.0 * entry_weight * costs.one_way_rate,
                        entry_regime,
                    )
                )
                entry_index = None
            if position == 0 and desired > 0:
                entry_index = index
                entry_weight = desired
                entry_regime = prepared.regimes[index]
            position = desired
            bars_held = 0
        else:
            bars_held += 1
    return records
