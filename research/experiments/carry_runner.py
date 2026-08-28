from __future__ import annotations

import bisect
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from research.data.bybit_carry import CarryMarketData
from research.validation.metrics import max_drawdown, sharpe
from research.validation.robustness import bootstrap_terminal_equity
from research.validation.walk_forward import expanding_walk_forward


@dataclass(frozen=True, slots=True)
class CarryObservation:
    ts: datetime
    funding_rate: float
    spot_price: float
    mark_price: float


@dataclass(frozen=True, slots=True)
class CarryPolicy:
    name: str
    lookback_settlements: int = 0
    minimum_average_rate: float = -1.0


@dataclass(frozen=True, slots=True)
class CarryConfig:
    notional_fraction: float = 0.40
    derivative_collateral_fraction: float = 0.40
    maintenance_margin_rate: float = 0.05
    spot_fee_bps: float = 10.0
    spot_slippage_bps: float = 2.0
    perp_fee_bps: float = 5.5
    perp_slippage_bps: float = 2.0
    rebalance_days: int = 30

    def __post_init__(self) -> None:
        if not 0 < self.notional_fraction < 1:
            raise ValueError("notional_fraction must be in (0, 1)")
        if not 0 < self.derivative_collateral_fraction < 1:
            raise ValueError("derivative_collateral_fraction must be in (0, 1)")
        if self.notional_fraction + self.derivative_collateral_fraction > 1:
            raise ValueError("spot notional and derivative collateral exceed capital")
        if self.rebalance_days <= 0:
            raise ValueError("rebalance_days must be positive")


@dataclass(frozen=True, slots=True)
class CarryMetrics:
    return_usdt: float
    annualized_return: float
    max_drawdown: float
    sharpe: float
    funding_income: float
    positive_funding_income: float
    negative_funding_paid: float
    basis_pnl: float
    trading_costs: float
    active_settlements: int
    position_transitions: int
    rebalances: int
    positive_funding_share: float
    minimum_margin_ratio: float
    liquidation_triggered: bool
    maximum_absolute_coin_delta: float


@dataclass(frozen=True, slots=True)
class CarrySimulation:
    metrics: CarryMetrics
    returns: tuple[float, ...]
    equity: tuple[float, ...]


def default_carry_policies() -> list[CarryPolicy]:
    return [
        CarryPolicy("always_on"),
        CarryPolicy("prior_24h_positive", 3, 0.0),
        CarryPolicy("prior_72h_positive", 9, 0.0),
    ]


def build_carry_observations(
    market_data: CarryMarketData,
    spot_points: list[tuple[datetime, float]],
    maximum_age: timedelta = timedelta(hours=2),
) -> list[CarryObservation]:
    if not spot_points:
        raise ValueError("spot price series is empty")
    spot_points = sorted(spot_points)
    mark_points = sorted((item.ts, item.close) for item in market_data.marks)
    spot_times = [item[0] for item in spot_points]
    mark_times = [item[0] for item in mark_points]
    observations: list[CarryObservation] = []
    for funding in market_data.funding:
        spot_index = bisect.bisect_right(spot_times, funding.ts) - 1
        mark_index = bisect.bisect_right(mark_times, funding.ts) - 1
        if spot_index < 0 or mark_index < 0:
            continue
        spot_time, spot_price = spot_points[spot_index]
        mark_time, mark_price = mark_points[mark_index]
        if funding.ts - spot_time > maximum_age or funding.ts - mark_time > maximum_age:
            continue
        observations.append(CarryObservation(funding.ts, funding.rate, spot_price, mark_price))
    if len(observations) < 2:
        raise ValueError("insufficient aligned carry observations")
    return observations


def simulate_carry(
    observations: list[CarryObservation],
    policy: CarryPolicy,
    config: CarryConfig,
    cost_multiplier: float = 1.0,
) -> CarrySimulation:
    if len(observations) < 2:
        raise ValueError("carry simulation requires at least two observations")
    if any(right.ts <= left.ts for left, right in zip(observations, observations[1:], strict=False)):
        raise ValueError("carry observations must be strictly ordered")
    spot_cost_rate = (config.spot_fee_bps + config.spot_slippage_bps) * cost_multiplier / 10_000
    perp_cost_rate = (config.perp_fee_bps + config.perp_slippage_bps) * cost_multiplier / 10_000
    equity = 1.0
    curve = [equity]
    returns: list[float] = []
    quantity = 0.0
    funding_income = positive_funding = negative_funding = basis_pnl = trading_costs = 0.0
    transitions = rebalances = active_settlements = 0
    liquidation = False
    minimum_margin_ratio = math.inf
    short_margin = 0.0
    next_rebalance = observations[0].ts
    settled_rates: list[float] = []

    desired = _policy_active(policy, settled_rates)
    if desired:
        quantity, cost = _target_quantity(equity, observations[0], config, spot_cost_rate, perp_cost_rate)
        equity -= cost
        trading_costs += cost
        transitions += 1
        short_margin = equity * config.derivative_collateral_fraction
        next_rebalance = observations[0].ts + timedelta(days=config.rebalance_days)
    for previous, current in zip(observations, observations[1:], strict=False):
        before = equity
        if quantity > 0:
            spot_pnl = quantity * (current.spot_price - previous.spot_price)
            perp_pnl = quantity * (previous.mark_price - current.mark_price)
            funding = quantity * current.mark_price * current.funding_rate
            basis_pnl += spot_pnl + perp_pnl
            funding_income += funding
            positive_funding += max(funding, 0.0)
            negative_funding += abs(min(funding, 0.0))
            equity += spot_pnl + perp_pnl + funding
            short_margin += perp_pnl + funding
            active_settlements += 1
            requirement = config.maintenance_margin_rate * quantity * current.mark_price
            margin_ratio = short_margin / requirement if requirement > 0 else math.inf
            minimum_margin_ratio = min(minimum_margin_ratio, margin_ratio)
            liquidation = liquidation or short_margin <= requirement

        settled_rates.append(current.funding_rate)
        desired = _policy_active(policy, settled_rates)
        currently_active = quantity > 0
        if currently_active and not desired:
            cost = quantity * current.spot_price * spot_cost_rate + quantity * current.mark_price * perp_cost_rate
            equity -= cost
            trading_costs += cost
            quantity = 0.0
            short_margin = 0.0
            transitions += 1
        elif not currently_active and desired:
            quantity, cost = _target_quantity(equity, current, config, spot_cost_rate, perp_cost_rate)
            equity -= cost
            trading_costs += cost
            short_margin = equity * config.derivative_collateral_fraction
            next_rebalance = current.ts + timedelta(days=config.rebalance_days)
            transitions += 1
        elif currently_active and desired and current.ts >= next_rebalance:
            target_quantity = equity * config.notional_fraction / current.spot_price
            delta = abs(target_quantity - quantity)
            cost = delta * current.spot_price * spot_cost_rate + delta * current.mark_price * perp_cost_rate
            equity -= cost
            trading_costs += cost
            quantity = target_quantity
            short_margin = equity * config.derivative_collateral_fraction
            next_rebalance = current.ts + timedelta(days=config.rebalance_days)
            rebalances += 1
        returns.append(equity / before - 1.0 if before > 0 else -1.0)
        curve.append(equity)

    if quantity > 0:
        last = observations[-1]
        cost = quantity * last.spot_price * spot_cost_rate + quantity * last.mark_price * perp_cost_rate
        equity -= cost
        trading_costs += cost
        transitions += 1
        returns[-1] = equity / curve[-2] - 1.0
        curve[-1] = equity

    elapsed_days = max((observations[-1].ts - observations[0].ts).total_seconds() / 86400, 1.0)
    annualized = equity ** (365.0 / elapsed_days) - 1.0 if equity > 0 else -1.0
    positive_share = sum(item.funding_rate > 0 for item in observations[1:]) / (len(observations) - 1)
    metrics = CarryMetrics(
        return_usdt=equity - 1.0,
        annualized_return=annualized,
        max_drawdown=max_drawdown(curve),
        sharpe=sharpe(returns, 3 * 365),
        funding_income=funding_income,
        positive_funding_income=positive_funding,
        negative_funding_paid=negative_funding,
        basis_pnl=basis_pnl,
        trading_costs=trading_costs,
        active_settlements=active_settlements,
        position_transitions=transitions,
        rebalances=rebalances,
        positive_funding_share=positive_share,
        minimum_margin_ratio=minimum_margin_ratio if math.isfinite(minimum_margin_ratio) else 0.0,
        liquidation_triggered=liquidation,
        maximum_absolute_coin_delta=0.0,
    )
    return CarrySimulation(metrics, tuple(returns), tuple(curve))


def run_carry_research(
    observations: list[CarryObservation],
    report_path: Path,
    config: CarryConfig | None = None,
    policies: list[CarryPolicy] | None = None,
) -> dict[str, Any]:
    config = config or CarryConfig()
    policies = policies or default_carry_policies()
    full = {policy.name: simulate_carry(observations, policy, config) for policy in policies}
    ranking = sorted(policies, key=lambda item: full[item.name].metrics.return_usdt, reverse=True)
    best = ranking[0]
    observations_per_day = max(1, round(len(observations) / max((observations[-1].ts - observations[0].ts).days, 1)))
    folds = expanding_walk_forward(len(observations), 180 * observations_per_day, 60 * observations_per_day)
    fold_reports = []
    oos_returns: list[float] = []
    oos_factor = 1.0
    for number, fold in enumerate(folds, start=1):
        if fold.test_end - fold.test_start < 60 * observations_per_day:
            continue
        train = {
            policy.name: simulate_carry(observations[fold.train_start : fold.train_end], policy, config)
            for policy in policies
        }
        selected = max(policies, key=lambda item: train[item.name].metrics.return_usdt)
        test = simulate_carry(observations[fold.test_start : fold.test_end], selected, config)
        oos_factor *= 1.0 + test.metrics.return_usdt
        oos_returns.extend(test.returns)
        fold_reports.append(
            {
                "fold": number,
                "selected": selected.name,
                "train": [fold.train_start, fold.train_end],
                "test": [fold.test_start, fold.test_end],
                "oos": asdict(test.metrics),
            }
        )
    stress = [
        {
            "cost_multiplier": multiplier,
            "metrics": asdict(simulate_carry(observations, best, config, multiplier).metrics),
        }
        for multiplier in (1.0, 2.0, 3.0)
    ]
    oos_return = oos_factor - 1.0
    bootstrap = bootstrap_terminal_equity(oos_returns, paths=2000, seed=42)
    positive_oos_folds = sum(item["oos"]["return_usdt"] > 0 for item in fold_reports)
    research_criteria = {
        "at_least_360_days": observations[-1].ts - observations[0].ts >= timedelta(days=360),
        "oos_return_positive": oos_return > 0,
        "majority_oos_folds_positive": bool(fold_reports) and positive_oos_folds > len(fold_reports) / 2,
        "triple_cost_return_positive": stress[-1]["metrics"]["return_usdt"] > 0,
        "bootstrap_probability_loss_below_0_20": bootstrap.probability_loss < 0.20,
        "no_liquidation_proxy": not full[best.name].metrics.liquidation_triggered,
        "coin_delta_neutral": full[best.name].metrics.maximum_absolute_coin_delta == 0.0,
    }
    report = {
        "stage": "m7.5-carry",
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": {
            "observations": len(observations),
            "start": observations[0].ts.isoformat(),
            "end": observations[-1].ts.isoformat(),
        },
        "config": asdict(config),
        "policy_ranking": [
            {"policy": asdict(policy), "metrics": asdict(full[policy.name].metrics)} for policy in ranking
        ],
        "walk_forward": {
            "folds": fold_reports,
            "oos_return_usdt": oos_return,
            "positive_folds": positive_oos_folds,
        },
        "cost_stress": {"policy": best.name, "scenarios": stress},
        "bootstrap_oos": asdict(bootstrap),
        "research_gate": {"approved": all(research_criteria.values()), "criteria": research_criteria},
        "execution_gate": {
            "approved": False,
            "reason": "derivative execution, margin and reconciliation are not implemented",
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = report_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(report_path)
    return report


def _policy_active(policy: CarryPolicy, settled_rates: list[float]) -> bool:
    if policy.lookback_settlements == 0:
        return True
    if len(settled_rates) < policy.lookback_settlements:
        return False
    recent = settled_rates[-policy.lookback_settlements :]
    return sum(recent) / len(recent) > policy.minimum_average_rate


def _target_quantity(
    equity: float,
    observation: CarryObservation,
    config: CarryConfig,
    spot_cost_rate: float,
    perp_cost_rate: float,
) -> tuple[float, float]:
    quantity = equity * config.notional_fraction / observation.spot_price
    cost = quantity * observation.spot_price * spot_cost_rate
    cost += quantity * observation.mark_price * perp_cost_rate
    return quantity, cost
