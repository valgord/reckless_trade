from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from domain.models import InstrumentKey
from research.backtests.simple_engine import CostModel
from research.experiments.m3_runner import Candidate, prepare_candidate
from research.validation.metrics import max_drawdown, profit_factor, sharpe, sortino
from research.validation.robustness import bootstrap_terminal_equity
from research.validation.walk_forward import expanding_walk_forward
from trading.portfolio.risk_budget import InverseVolatilityRiskAllocator, RiskBudgetConfig

PERIODS_PER_DAY = 96
PERIODS_PER_YEAR = 365 * PERIODS_PER_DAY


@dataclass(frozen=True, slots=True)
class PortfolioPolicy:
    name: str
    method: str
    correlation_budget: bool = False


@dataclass(frozen=True, slots=True)
class PortfolioMetrics:
    return_usdt: float
    btc_buy_hold_return: float
    risk_matched_btc_return: float
    excess_vs_risk_matched_btc: float
    equal_weight_basket_return: float
    max_drawdown: float
    sharpe: float
    sortino: float
    profit_factor: float
    turnover: float
    rebalance_trades: int
    average_gross_exposure: float
    kill_switch_triggered: bool
    asset_return_contributions: dict[str, float]
    constraints_applied: dict[str, int]


@dataclass(frozen=True, slots=True)
class PortfolioSimulation:
    metrics: PortfolioMetrics
    returns: list[float]


def default_policies() -> list[PortfolioPolicy]:
    return [
        PortfolioPolicy("btc_signal_control", "btc_only"),
        PortfolioPolicy("equal_active", "equal"),
        PortfolioPolicy("inverse_volatility", "inverse_volatility"),
        PortfolioPolicy("inverse_volatility_correlation_budget", "inverse_volatility", True),
    ]


def simulate_portfolio(
    policy: PortfolioPolicy,
    symbols: list[str],
    closes: dict[str, np.ndarray],
    targets: dict[str, list[float]],
    start: int,
    end: int,
    costs: CostModel,
    risk_config: RiskBudgetConfig,
    rebalance_bars: int = PERIODS_PER_DAY,
    lookback_bars: int = 30 * PERIODS_PER_DAY,
    kill_drawdown: float = 0.10,
) -> PortfolioSimulation:
    if end - start < 2:
        raise ValueError("portfolio simulation requires at least two bars")
    allocator = InverseVolatilityRiskAllocator(risk_config)
    weights = {symbol: 0.0 for symbol in symbols}
    equity = [1.0]
    returns: list[float] = []
    peak = 1.0
    killed = False
    turnover = 0.0
    rebalance_trades = 0
    gross_sum = 0.0
    contribution_factors = {symbol: 1.0 for symbol in symbols}
    constraints: Counter[str] = Counter()

    asset_returns = {symbol: closes[symbol][1:] / closes[symbol][:-1] - 1.0 for symbol in symbols}
    for index in range(start, end - 1):
        current_drawdown = equity[-1] / peak - 1.0
        desired = dict(weights)
        forced_exit = {symbol for symbol in symbols if targets[symbol][index] <= 0 and weights[symbol] > 0}
        for symbol in forced_exit:
            desired[symbol] = 0.0

        should_rebalance = index == start or (index - start) % rebalance_bars == 0
        signal_entry = any(
            targets[symbol][index] > 0 and (index == 0 or targets[symbol][index - 1] <= 0) for symbol in symbols
        )
        if current_drawdown <= -abs(kill_drawdown):
            killed = True
            desired = {symbol: 0.0 for symbol in symbols}
        elif (should_rebalance or signal_entry) and not killed:
            active = {symbol for symbol in symbols if targets[symbol][index] > 0}
            desired, applied = _allocate(policy, symbols, active, closes, index, lookback_bars, allocator, risk_config)
            constraints.update(applied)

        traded = 0.0
        for symbol in symbols:
            delta = abs(desired[symbol] - weights[symbol])
            if delta >= 0.01 or symbol in forced_exit or killed:
                traded += delta
                weights[symbol] = desired[symbol]
        if traded > 0:
            rebalance_trades += 1
            turnover += traded
        period_asset = {symbol: weights[symbol] * float(asset_returns[symbol][index]) for symbol in symbols}
        period_return = (1.0 - traded * costs.one_way_rate) * (1.0 + sum(period_asset.values())) - 1.0
        returns.append(period_return)
        equity.append(equity[-1] * (1.0 + period_return))
        peak = max(peak, equity[-1])
        gross_sum += sum(weights.values())
        for symbol, value in period_asset.items():
            contribution_factors[symbol] *= 1.0 + value

    btc = symbols[0]
    btc_return = closes[btc][end - 1] / closes[btc][start] * (1 - costs.one_way_rate) - 1.0
    risk_matched_btc = risk_config.max_total_weight * (closes[btc][end - 1] / closes[btc][start] - 1.0)
    risk_matched_btc -= risk_config.max_total_weight * costs.one_way_rate
    equal_weight = (
        sum(
            risk_config.max_total_weight / len(symbols) * (closes[symbol][end - 1] / closes[symbol][start] - 1.0)
            for symbol in symbols
        )
        - risk_config.max_total_weight * costs.one_way_rate
    )
    total_return = equity[-1] - 1.0
    metrics = PortfolioMetrics(
        return_usdt=total_return,
        btc_buy_hold_return=float(btc_return),
        risk_matched_btc_return=float(risk_matched_btc),
        excess_vs_risk_matched_btc=float(total_return - risk_matched_btc),
        equal_weight_basket_return=float(equal_weight),
        max_drawdown=max_drawdown(equity),
        sharpe=sharpe(returns, PERIODS_PER_YEAR),
        sortino=sortino(returns, PERIODS_PER_YEAR),
        profit_factor=profit_factor(returns),
        turnover=turnover,
        rebalance_trades=rebalance_trades,
        average_gross_exposure=gross_sum / len(returns),
        kill_switch_triggered=killed,
        asset_return_contributions={symbol: contribution_factors[symbol] - 1.0 for symbol in symbols},
        constraints_applied=dict(sorted(constraints.items())),
    )
    return PortfolioSimulation(metrics, returns)


def run_m5_research(
    catalog_path: Path,
    platform_config_path: Path,
    report_path: Path = Path("data/runtime/m5-research.json"),
    instruments: tuple[str, ...] = (
        "BTCUSDT-SPOT.BYBIT",
        "ETHUSDT-SPOT.BYBIT",
        "SOLUSDT-SPOT.BYBIT",
    ),
    bar_spec: str = "15-MINUTE-LAST-EXTERNAL",
) -> dict[str, Any]:
    from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

    config = yaml.safe_load(platform_config_path.read_text(encoding="utf-8")) or {}
    catalog = ParquetDataCatalog(str(catalog_path))
    raw_bars = {instrument: catalog.bars(bar_types=[f"{instrument}-{bar_spec}"]) for instrument in instruments}
    if any(not bars for bars in raw_bars.values()):
        missing = [name for name, bars in raw_bars.items() if not bars]
        raise ValueError(f"catalog has no bars for {missing}")
    common = set.intersection(*[{int(bar.ts_event) for bar in bars} for bars in raw_bars.values()])
    if len(common) < 180 * PERIODS_PER_DAY:
        raise ValueError("M5 requires at least 180 aligned days")
    timestamps = sorted(common)
    aligned = {
        instrument: [bar for bar in raw_bars[instrument] if int(bar.ts_event) in common] for instrument in instruments
    }
    symbols = [instrument.split("-", 1)[0] for instrument in instruments]
    closes = {
        symbol: np.asarray([float(str(bar.close)) for bar in aligned[instrument]], dtype=float)
        for symbol, instrument in zip(symbols, instruments, strict=True)
    }

    alpha = Candidate(
        "m5_trend_regime",
        ("trend_following",),
        min_hold_bars=96,
        allowed_regimes=("trend_up",),
        regime_entry_bars=4,
    )
    targets = {}
    for symbol, instrument in zip(symbols, instruments, strict=True):
        prepared = prepare_candidate(
            aligned[instrument],
            config,
            alpha,
            InstrumentKey("BYBIT", symbol),
            position_weight=1.0,
        )
        targets[symbol] = _execution_states(prepared.targets, prepared.regimes, alpha)

    portfolio_config = config.get("m5_portfolio", {})
    risk_config = RiskBudgetConfig(
        max_total_weight=float(portfolio_config.get("max_total_weight", 0.30)),
        max_asset_weight=float(portfolio_config.get("max_asset_weight", 0.15)),
        max_correlated_pair_weight=float(portfolio_config.get("max_correlated_pair_weight", 0.20)),
        correlation_threshold=float(portfolio_config.get("correlation_threshold", 0.75)),
        max_venue_weight=float(portfolio_config.get("max_venue_weight", 0.30)),
    )
    cost_config = config.get("cost_model", {})
    costs = CostModel(
        float(cost_config.get("fees_bps", 10)),
        float(cost_config.get("slippage_bps", 2)),
        float(cost_config.get("spread_bps", 1)),
    )
    policies = default_policies()
    full = {
        policy.name: simulate_portfolio(policy, symbols, closes, targets, 0, len(timestamps), costs, risk_config)
        for policy in policies
    }
    ranking = sorted(
        policies,
        key=lambda policy: full[policy.name].metrics.excess_vs_risk_matched_btc,
        reverse=True,
    )
    best = ranking[0]

    validation = config.get("validation", {})
    folds = expanding_walk_forward(
        len(timestamps),
        int(validation.get("min_train_days", 180)) * PERIODS_PER_DAY,
        int(validation.get("test_days", 60)) * PERIODS_PER_DAY,
    )
    fold_reports = []
    oos_factor = benchmark_factor = 1.0
    oos_returns: list[float] = []
    for number, fold in enumerate(folds, start=1):
        train = {
            policy.name: simulate_portfolio(
                policy, symbols, closes, targets, fold.train_start, fold.train_end, costs, risk_config
            )
            for policy in policies
        }
        selected = max(policies, key=lambda policy: train[policy.name].metrics.excess_vs_risk_matched_btc)
        test = simulate_portfolio(
            selected, symbols, closes, targets, fold.test_start, fold.test_end, costs, risk_config
        )
        oos_factor *= 1 + test.metrics.return_usdt
        benchmark_factor *= 1 + test.metrics.risk_matched_btc_return
        oos_returns.extend(_compound_chunks(test.returns, PERIODS_PER_DAY))
        fold_reports.append(
            {
                "fold": number,
                "selected": selected.name,
                "train": [fold.train_start, fold.train_end],
                "test": [fold.test_start, fold.test_end],
                "oos": asdict(test.metrics),
            }
        )

    stress = []
    for multiplier in (1.0, 1.5, 2.0):
        stressed = CostModel(costs.fee_bps * multiplier, costs.slippage_bps * multiplier, costs.spread_bps)
        trial = simulate_portfolio(best, symbols, closes, targets, 0, len(timestamps), stressed, risk_config)
        stress.append({"cost_multiplier": multiplier, "return_usdt": trial.metrics.return_usdt})
    correlations = _daily_correlation(symbols, closes)
    bootstrap = bootstrap_terminal_equity(oos_returns, paths=int(validation.get("bootstrap_paths", 2000)), seed=42)
    oos_return = oos_factor - 1.0
    oos_benchmark = benchmark_factor - 1.0
    worst_stress = min(item["return_usdt"] for item in stress)
    criteria = {
        "oos_return_positive": oos_return > 0,
        "oos_beats_risk_matched_btc": oos_return > oos_benchmark,
        "worst_stress_positive": worst_stress > 0,
        "bootstrap_probability_loss_below_0_20": bootstrap.probability_loss < 0.20,
        "multi_asset_nautilus_confirmation": False,
    }
    report = {
        "stage": "m5",
        "run_id": datetime.now(UTC).strftime("m5-%Y%m%dT%H%M%SZ"),
        "generated_at": datetime.now(UTC).isoformat(),
        "instruments": list(instruments),
        "bars": len(timestamps),
        "start": datetime.fromtimestamp(timestamps[0] / 1_000_000_000, tz=UTC).isoformat(),
        "end": datetime.fromtimestamp(timestamps[-1] / 1_000_000_000, tz=UTC).isoformat(),
        "alpha": asdict(alpha),
        "risk_budget": asdict(risk_config),
        "daily_return_correlations": correlations,
        "policy_ranking": [
            {"policy": asdict(policy), "metrics": asdict(full[policy.name].metrics)} for policy in ranking
        ],
        "walk_forward": {
            "folds": fold_reports,
            "oos_return_usdt": oos_return,
            "oos_risk_matched_btc_return": oos_benchmark,
            "oos_excess": oos_return - oos_benchmark,
        },
        "cost_stress": {"policy": best.name, "scenarios": stress, "worst_return_usdt": worst_stress},
        "bootstrap_oos": asdict(bootstrap),
        "promotion": {"approved": all(criteria.values()), "criteria": criteria},
    }
    write_m5_report(report_path, report)
    return report


def write_m5_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _allocate(
    policy: PortfolioPolicy,
    symbols: list[str],
    active: set[str],
    closes: dict[str, np.ndarray],
    index: int,
    lookback: int,
    allocator: InverseVolatilityRiskAllocator,
    risk_config: RiskBudgetConfig,
) -> tuple[dict[str, float], tuple[str, ...]]:
    desired = {symbol: 0.0 for symbol in symbols}
    if policy.method == "btc_only":
        if symbols[0] in active:
            desired[symbols[0]] = min(0.10, risk_config.max_asset_weight)
        return desired, ()
    if policy.method == "equal":
        weight = min(risk_config.max_asset_weight, risk_config.max_total_weight / max(len(active), 1))
        for symbol in active:
            desired[symbol] = weight
        return desired, ()
    start = max(1, index - lookback)
    samples = np.column_stack(
        [closes[symbol][start : index + 1] / closes[symbol][start - 1 : index] - 1.0 for symbol in symbols]
    )
    volatilities = {
        symbol: float(np.std(samples[:, offset])) if len(samples) >= 2 else 1.0 for offset, symbol in enumerate(symbols)
    }
    matrix = np.corrcoef(samples, rowvar=False) if len(samples) >= 2 else np.eye(len(symbols))
    correlations = {
        left: {right: float(matrix[i, j]) for j, right in enumerate(symbols)} for i, left in enumerate(symbols)
    }
    if not policy.correlation_budget:
        correlations = {}
    result = allocator.allocate(active, volatilities, correlations, {symbol: "BYBIT" for symbol in symbols})
    desired.update(result.weights)
    return desired, result.constraints_applied


def _daily_correlation(symbols: list[str], closes: dict[str, np.ndarray]) -> dict[str, dict[str, float]]:
    daily = np.column_stack(
        [
            closes[symbol][PERIODS_PER_DAY::PERIODS_PER_DAY] / closes[symbol][:-PERIODS_PER_DAY:PERIODS_PER_DAY] - 1.0
            for symbol in symbols
        ]
    )
    matrix = np.corrcoef(daily, rowvar=False)
    return {left: {right: float(matrix[i, j]) for j, right in enumerate(symbols)} for i, left in enumerate(symbols)}


def _compound_chunks(returns: list[float], size: int) -> list[float]:
    return [
        math.prod(1 + value for value in returns[start : start + size]) - 1.0 for start in range(0, len(returns), size)
    ]


def _execution_states(raw_targets: list[float], regimes: list[str], candidate: Candidate) -> list[float]:
    position = 0.0
    bars_held = candidate.min_hold_bars
    states: list[float] = []
    for desired, regime in zip(raw_targets, regimes, strict=True):
        regime_allowed = not candidate.allowed_regimes or regime in candidate.allowed_regimes
        forced_exit = position > 0 and not regime_allowed
        if desired != position and (forced_exit or bars_held >= candidate.min_hold_bars):
            position = desired
            bars_held = 0
        else:
            bars_held += 1
        states.append(position)
    return states
