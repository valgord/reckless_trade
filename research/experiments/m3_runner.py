from __future__ import annotations

import copy
import hashlib
import json
import math
import uuid
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from apps.trader.demo_strategy import DemoDecisionEngine
from domain.models import Bar as DomainBar
from domain.models import InstrumentKey
from research.backtests.simple_engine import CostModel
from research.validation.metrics import max_drawdown, profit_factor, sharpe, sortino
from research.validation.robustness import bootstrap_terminal_equity
from research.validation.selection import deflated_sharpe_probability, probability_of_backtest_overfitting
from research.validation.walk_forward import expanding_walk_forward

PERIODS_PER_DAY = 96
PERIODS_PER_YEAR = 365 * PERIODS_PER_DAY


@dataclass(frozen=True, slots=True)
class Candidate:
    name: str
    enabled: tuple[str, ...]
    min_hold_bars: int = 0
    allowed_regimes: tuple[str, ...] = ()
    regime_entry_bars: int = 1


@dataclass(frozen=True, slots=True)
class TrialMetrics:
    return_usdt: float
    buy_hold_return: float
    excess_vs_buy_hold: float
    return_in_btc: float
    max_drawdown: float
    sharpe: float
    sortino: float
    profit_factor: float
    trades: int
    turnover: float
    exposure: float
    regime_returns: dict[str, float]


@dataclass(slots=True)
class PreparedCandidate:
    candidate: Candidate
    targets: list[float]
    regimes: list[str]
    signal_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class Simulation:
    metrics: TrialMetrics
    returns: list[float]
    equity: list[float]


def default_candidates() -> list[Candidate]:
    all_models = ("trend_following", "mean_reversion", "momentum", "breakout")
    return [
        Candidate("baseline", all_models),
        Candidate("baseline_hold_4h", all_models, 16),
        Candidate("baseline_hold_12h", all_models, 48),
        Candidate("baseline_hold_1d", all_models, 96),
        Candidate("trend_only", ("trend_following",)),
        Candidate("momentum_only", ("momentum",)),
        Candidate("mean_reversion_only", ("mean_reversion",)),
        Candidate("breakout_only", ("breakout",)),
        Candidate("trend_momentum", ("trend_following", "momentum")),
        Candidate("trend_breakout", ("trend_following", "breakout")),
    ]


def default_m4_candidates() -> list[Candidate]:
    core = ("trend_following", "mean_reversion", "momentum", "breakout")
    trend_up = ("trend_up",)
    return [
        Candidate("m3_control_hold_1d", core, 96),
        Candidate("trend_gate_trend_confirm_1h", ("trend_following",), 96, trend_up, 4),
        Candidate("trend_gate_trend_confirm_4h", ("trend_following",), 96, trend_up, 16),
        Candidate("trend_gate_trend_confirm_12h", ("trend_following",), 96, trend_up, 48),
        Candidate("trend_gate_core_confirm_4h", core, 96, trend_up, 16),
        Candidate("trend_gate_core_confirm_12h", core, 96, trend_up, 48),
        Candidate("trend_gate_trend_momentum_4h", ("trend_following", "momentum"), 96, trend_up, 16),
        Candidate("trend_gate_trend_breakout_4h", ("trend_following", "breakout"), 96, trend_up, 16),
        Candidate("trend_gate_volatility_4h", ("volatility_breakout",), 96, trend_up, 16),
        Candidate(
            "trend_gate_core_volatility_4h",
            (*core, "volatility_breakout"),
            96,
            trend_up,
            16,
        ),
    ]


def prepare_candidate(
    bars: list[Any],
    base_config: dict[str, Any],
    candidate: Candidate,
    instrument: InstrumentKey,
    position_weight: float = 0.10,
) -> PreparedCandidate:
    config = copy.deepcopy(base_config)
    for name, values in config.get("strategies", {}).items():
        values["enabled"] = name in candidate.enabled
    engine = DemoDecisionEngine(config, instrument, max_bars=150)
    targets: list[float] = []
    regimes: list[str] = []
    signal_counts: Counter[str] = Counter()
    allowed_streak = 0
    for bar in bars:
        result = engine.on_bar(_domain_bar(bar, instrument))
        regime_allowed = not candidate.allowed_regimes or result["regime"] in candidate.allowed_regimes
        allowed_streak = allowed_streak + 1 if regime_allowed else 0
        entry_confirmed = allowed_streak >= candidate.regime_entry_bars
        targets.append(
            position_weight if entry_confirmed and result["target_weights"].get(instrument.canonical, 0.0) > 0 else 0.0
        )
        regimes.append(str(result["regime"]))
        signal_counts.update(result.get("signal_sources", []))
    return PreparedCandidate(candidate, targets, regimes, dict(signal_counts))


def simulate_candidate(
    prepared: PreparedCandidate,
    closes: list[float],
    start: int,
    end: int,
    costs: CostModel,
) -> Simulation:
    if start < 0 or end > len(closes) or end - start < 2:
        raise ValueError("simulation range must contain at least two bars")
    equity = [1.0]
    returns: list[float] = []
    position = 0.0
    bars_held = prepared.candidate.min_hold_bars
    trades = 0
    turnover = 0.0
    exposed = 0
    regime_factors: dict[str, float] = defaultdict(lambda: 1.0)

    for index in range(start, end - 1):
        desired = prepared.targets[index]
        traded = 0.0
        regime_allowed = (
            not prepared.candidate.allowed_regimes or prepared.regimes[index] in prepared.candidate.allowed_regimes
        )
        forced_regime_exit = position > 0 and not regime_allowed
        if desired != position and (forced_regime_exit or bars_held >= prepared.candidate.min_hold_bars):
            traded = abs(desired - position)
            turnover += traded
            trades += 1
            position = desired
            bars_held = 0
        else:
            bars_held += 1
        cost = traded * costs.one_way_rate
        price_return = closes[index + 1] / closes[index] - 1.0
        period_return = (1.0 - cost) * (1.0 + position * price_return) - 1.0
        returns.append(period_return)
        equity.append(equity[-1] * (1.0 + period_return))
        regime_factors[prepared.regimes[index]] *= 1.0 + period_return
        exposed += int(position > 0)

    one_way = costs.one_way_rate
    buy_hold = closes[end - 1] / closes[start] * (1.0 - one_way) - 1.0
    total_return = equity[-1] - 1.0
    metrics = TrialMetrics(
        return_usdt=total_return,
        buy_hold_return=buy_hold,
        excess_vs_buy_hold=total_return - buy_hold,
        return_in_btc=(1.0 + total_return) / (1.0 + buy_hold) - 1.0,
        max_drawdown=max_drawdown(equity),
        sharpe=sharpe(returns, PERIODS_PER_YEAR),
        sortino=sortino(returns, PERIODS_PER_YEAR),
        profit_factor=profit_factor(returns),
        trades=trades,
        turnover=turnover,
        exposure=exposed / len(returns),
        regime_returns={name: factor - 1.0 for name, factor in sorted(regime_factors.items())},
    )
    return Simulation(metrics, returns, equity)


def candidate_is_eligible(simulation: Simulation, periods: int, full_periods: int) -> bool:
    minimum_trades = max(2, math.ceil(12 * periods / full_periods))
    return simulation.metrics.trades >= minimum_trades and simulation.metrics.exposure >= 0.005


class ExperimentRegistry:
    def __init__(self, path: Path, run_id: str, config_hash: str) -> None:
        self.path = path
        self.run_id = run_id
        self.config_hash = config_hash
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.trials = 0

    def record(
        self,
        kind: str,
        candidate: Candidate,
        start: int,
        end: int,
        costs: CostModel,
        metrics: TrialMetrics,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "run_id": self.run_id,
            "trial_id": str(uuid.uuid4()),
            "recorded_at": datetime.now(UTC).isoformat(),
            "config_hash": self.config_hash,
            "kind": kind,
            "candidate": asdict(candidate),
            "range": {"start_index": start, "end_index": end},
            "costs": asdict(costs),
            "metrics": asdict(metrics),
            "metadata": metadata or {},
        }
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, sort_keys=True) + "\n")
        self.trials += 1


def run_m3_research(
    catalog_path: Path,
    platform_config_path: Path,
    registry_path: Path = Path("data/runtime/experiment-registry.jsonl"),
    instrument_id: str = "BTCUSDT-SPOT.BYBIT",
    bar_spec: str = "15-MINUTE-LAST-EXTERNAL",
    candidates: list[Candidate] | None = None,
    stage: str = "m3",
) -> dict[str, Any]:
    from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

    raw_text = platform_config_path.read_text(encoding="utf-8")
    config = yaml.safe_load(raw_text) or {}
    catalog = ParquetDataCatalog(str(catalog_path))
    bars = catalog.bars(bar_types=[f"{instrument_id}-{bar_spec}"])
    if len(bars) < PERIODS_PER_DAY * 120:
        raise ValueError("M3 requires at least 120 days of 15-minute bars")
    closes = [float(str(bar.close)) for bar in bars]
    raw_symbol = instrument_id.split("-", 1)[0]
    instrument = InstrumentKey("BYBIT", raw_symbol)
    candidates = candidates or default_candidates()
    position_weight = float(config.get("validation", {}).get("simulation_position_weight", 0.10))
    if not 0 < position_weight <= 1:
        raise ValueError("validation.simulation_position_weight must be in (0, 1]")
    prepared = [prepare_candidate(bars, config, candidate, instrument, position_weight) for candidate in candidates]

    cost_config = config.get("cost_model", {})
    base_costs = CostModel(
        float(cost_config.get("fees_bps", 10)),
        float(cost_config.get("slippage_bps", 2)),
        float(cost_config.get("spread_bps", 1)),
    )
    run_id = datetime.now(UTC).strftime(f"{stage}-%Y%m%dT%H%M%SZ")
    config_hash = hashlib.sha256(raw_text.encode()).hexdigest()
    registry = ExperimentRegistry(registry_path, run_id, config_hash)

    full: dict[str, Simulation] = {}
    for item in prepared:
        simulation = simulate_candidate(item, closes, 0, len(bars), base_costs)
        full[item.candidate.name] = simulation
        registry.record("full_sample", item.candidate, 0, len(bars), base_costs, simulation.metrics)
    eligible = [item for item in prepared if candidate_is_eligible(full[item.candidate.name], len(bars), len(bars))]
    if not eligible:
        raise ValueError("No candidate satisfies the minimum research activity requirement")
    ranking = sorted(
        prepared,
        key=lambda item: (
            candidate_is_eligible(full[item.candidate.name], len(bars), len(bars)),
            full[item.candidate.name].metrics.return_in_btc,
        ),
        reverse=True,
    )
    best = ranking[0]

    validation = config.get("validation", {})
    min_train = int(validation.get("min_train_days", 180)) * PERIODS_PER_DAY
    test_size = int(validation.get("test_days", 60)) * PERIODS_PER_DAY
    folds = expanding_walk_forward(len(bars), min_train, test_size)
    fold_reports: list[dict[str, Any]] = []
    oos_factor = btc_factor = 1.0
    oos_daily_returns: list[float] = []
    for number, fold in enumerate(folds, start=1):
        train_scores: dict[str, float] = {}
        for item in prepared:
            trial = simulate_candidate(item, closes, fold.train_start, fold.train_end, base_costs)
            train_scores[item.candidate.name] = (
                trial.metrics.return_in_btc
                if item in eligible and candidate_is_eligible(trial, fold.train_end - fold.train_start, len(bars))
                else -math.inf
            )
            registry.record(
                "walk_forward_train",
                item.candidate,
                fold.train_start,
                fold.train_end,
                base_costs,
                trial.metrics,
                {"fold": number},
            )
        selected_name = max(train_scores, key=train_scores.get)
        selected = next(item for item in prepared if item.candidate.name == selected_name)
        test = simulate_candidate(selected, closes, fold.test_start, fold.test_end, base_costs)
        registry.record(
            "walk_forward_oos",
            selected.candidate,
            fold.test_start,
            fold.test_end,
            base_costs,
            test.metrics,
            {"fold": number},
        )
        oos_factor *= 1 + test.metrics.return_usdt
        btc_factor *= 1 + test.metrics.buy_hold_return
        oos_daily_returns.extend(_compound_chunks(test.returns, PERIODS_PER_DAY))
        fold_reports.append(
            {
                "fold": number,
                "train": [fold.train_start, fold.train_end],
                "test": [fold.test_start, fold.test_end],
                "selected": selected_name,
                "train_return_in_btc": train_scores[selected_name],
                "oos": asdict(test.metrics),
            }
        )

    stress: list[dict[str, Any]] = []
    for fee_multiplier in validation.get("stress_fee_multiplier", [1.0, 1.5, 2.0]):
        for slippage_multiplier in validation.get("stress_slippage_multiplier", [1.0, 2.0, 4.0]):
            stressed = CostModel(
                base_costs.fee_bps * float(fee_multiplier),
                base_costs.slippage_bps * float(slippage_multiplier),
                base_costs.spread_bps,
            )
            trial = simulate_candidate(best, closes, 0, len(bars), stressed)
            registry.record("cost_stress", best.candidate, 0, len(bars), stressed, trial.metrics)
            stress.append(
                {
                    "fee_multiplier": float(fee_multiplier),
                    "slippage_multiplier": float(slippage_multiplier),
                    "return_usdt": trial.metrics.return_usdt,
                    "return_in_btc": trial.metrics.return_in_btc,
                }
            )

    blocks = 8
    block_returns: dict[str, list[float]] = {}
    for item in eligible:
        values = []
        for block in range(blocks):
            start = block * len(bars) // blocks
            end = (block + 1) * len(bars) // blocks
            values.append(simulate_candidate(item, closes, start, end, base_costs).metrics.return_usdt)
        block_returns[item.candidate.name] = values
    pbo = probability_of_backtest_overfitting(block_returns)
    best_daily = _compound_chunks(full[best.candidate.name].returns, PERIODS_PER_DAY)
    dsr = deflated_sharpe_probability(best_daily, len(eligible))
    bootstrap = bootstrap_terminal_equity(
        oos_daily_returns,
        paths=int(validation.get("bootstrap_paths", 2000)),
        seed=42,
    )
    oos_return = oos_factor - 1
    oos_buy_hold = btc_factor - 1
    oos_btc = oos_factor / btc_factor - 1
    worst_stress = min(item["return_usdt"] for item in stress)
    criteria = {
        "oos_return_positive": oos_return > 0,
        "oos_beats_btc": oos_btc > 0,
        "worst_stress_positive": worst_stress > 0,
        "dsr_at_least_0_95": dsr >= 0.95,
        "pbo_below_0_20": pbo < 0.20,
    }
    return {
        "stage": stage,
        "run_id": run_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "config_hash": config_hash,
        "instrument_id": instrument_id,
        "bar_type": f"{instrument_id}-{bar_spec}",
        "bars": len(bars),
        "start": _timestamp(bars[0]),
        "end": _timestamp(bars[-1]),
        "registry_path": str(registry_path),
        "trials_recorded": registry.trials,
        "candidate_ranking": [
            {
                "candidate": asdict(item.candidate),
                "metrics": asdict(full[item.candidate.name].metrics),
                "signal_counts": item.signal_counts,
                "qualified": candidate_is_eligible(full[item.candidate.name], len(bars), len(bars)),
            }
            for item in ranking
        ],
        "walk_forward": {
            "folds": fold_reports,
            "oos_return_usdt": oos_return,
            "oos_buy_hold_return": oos_buy_hold,
            "oos_return_in_btc": oos_btc,
        },
        "cost_stress": {"candidate": best.candidate.name, "scenarios": stress, "worst_return_usdt": worst_stress},
        "selection_risk": {
            "deflated_sharpe_probability": dsr,
            "probability_of_backtest_overfitting": pbo,
            "bootstrap_oos": asdict(bootstrap),
        },
        "promotion": {"approved": all(criteria.values()), "criteria": criteria},
    }


def write_m3_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(_json_safe(report), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _domain_bar(bar: Any, instrument: InstrumentKey) -> DomainBar:
    return DomainBar(
        instrument=instrument,
        ts_event=datetime.fromtimestamp(bar.ts_event / 1_000_000_000, tz=UTC),
        open=float(str(bar.open)),
        high=float(str(bar.high)),
        low=float(str(bar.low)),
        close=float(str(bar.close)),
        volume=float(str(bar.volume)),
    )


def _timestamp(bar: Any) -> str:
    return datetime.fromtimestamp(bar.ts_event / 1_000_000_000, tz=UTC).isoformat()


def _compound_chunks(returns: list[float], size: int) -> list[float]:
    result = []
    for start in range(0, len(returns), size):
        result.append(math.prod(1 + value for value in returns[start : start + size]) - 1)
    return result


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value
