from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from domain.models import InstrumentKey
from research.attribution.directional import attribute_directional_candidate
from research.backtests.simple_engine import CostModel
from research.data.bybit_carry import read_carry_data
from research.experiments.carry_runner import build_carry_observations, run_carry_research
from research.experiments.m3_runner import Candidate, prepare_candidate
from research.experiments.m5_runner import (
    _execution_states,
    default_policies,
    simulate_portfolio,
)
from trading.portfolio.risk_budget import RiskBudgetConfig


def run_m75_research(
    catalog_path: Path,
    config_path: Path,
    carry_data_path: Path,
    m4_report_path: Path,
    report_path: Path,
    carry_report_path: Path,
) -> dict[str, Any]:
    from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    catalog = ParquetDataCatalog(str(catalog_path))
    bar_spec = "15-MINUTE-LAST-EXTERNAL"
    btc_instrument = "BTCUSDT-SPOT.BYBIT"
    btc_bars = catalog.bars(bar_types=[f"{btc_instrument}-{bar_spec}"])
    if not btc_bars:
        raise ValueError("BTC Spot history is required")
    m4_report = json.loads(m4_report_path.read_text(encoding="utf-8"))
    m4_bars = _bars_in_report_window(btc_bars, m4_report)
    candidate_payload = m4_report["candidate_ranking"][0]["candidate"]
    m4_candidate = Candidate(
        name=candidate_payload["name"],
        enabled=tuple(candidate_payload["enabled"]),
        min_hold_bars=int(candidate_payload["min_hold_bars"]),
        allowed_regimes=tuple(candidate_payload["allowed_regimes"]),
        regime_entry_bars=int(candidate_payload["regime_entry_bars"]),
    )
    position_weight = float(config.get("validation", {}).get("simulation_position_weight", 0.10))
    prepared = prepare_candidate(
        m4_bars,
        config,
        m4_candidate,
        InstrumentKey("BYBIT", "BTCUSDT"),
        position_weight,
    )
    costs = _cost_model(config)
    m4_closes = [float(str(bar.close)) for bar in m4_bars]
    m4_attribution = attribute_directional_candidate(prepared, m4_closes, costs)
    m5_attribution = _attribute_m5(catalog, config, bar_spec, costs)

    carry_market = read_carry_data(carry_data_path)
    spot_points = [
        (datetime.fromtimestamp(int(bar.ts_event) / 1_000_000_000, tz=UTC), float(str(bar.close))) for bar in btc_bars
    ]
    observations = build_carry_observations(carry_market, spot_points)
    carry_report = run_carry_research(observations, carry_report_path)
    report = {
        "stage": "m7.5-fiat-alpha-discovery",
        "generated_at": datetime.now(UTC).isoformat(),
        "directional_postmortem": {
            "m4": m4_attribution,
            "m5": m5_attribution,
            "conclusion": _directional_conclusion(m4_attribution, m5_attribution),
        },
        "carry": carry_report,
        "next_action": _next_action(carry_report),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = report_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(report_path)
    return report


def _attribute_m5(catalog, config: dict[str, Any], bar_spec: str, costs: CostModel) -> dict[str, Any]:
    instruments = (
        "BTCUSDT-SPOT.BYBIT",
        "ETHUSDT-SPOT.BYBIT",
        "SOLUSDT-SPOT.BYBIT",
    )
    raw_bars = {instrument: catalog.bars(bar_types=[f"{instrument}-{bar_spec}"]) for instrument in instruments}
    common = set.intersection(*[{int(bar.ts_event) for bar in bars} for bars in raw_bars.values()])
    timestamps = sorted(common)
    aligned = {
        instrument: [bar for bar in raw_bars[instrument] if int(bar.ts_event) in common] for instrument in instruments
    }
    symbols = [instrument.split("-", 1)[0] for instrument in instruments]
    closes = {
        symbol: np.asarray([float(str(bar.close)) for bar in aligned[instrument]], dtype=float)
        for symbol, instrument in zip(symbols, instruments, strict=True)
    }
    candidate = Candidate(
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
            candidate,
            InstrumentKey("BYBIT", symbol),
            position_weight=1.0,
        )
        targets[symbol] = _execution_states(prepared.targets, prepared.regimes, candidate)
    portfolio_config = config.get("m5_portfolio", {})
    risk_config = RiskBudgetConfig(
        max_total_weight=float(portfolio_config.get("max_total_weight", 0.30)),
        max_asset_weight=float(portfolio_config.get("max_asset_weight", 0.15)),
        max_correlated_pair_weight=float(portfolio_config.get("max_correlated_pair_weight", 0.20)),
        correlation_threshold=float(portfolio_config.get("correlation_threshold", 0.75)),
        max_venue_weight=float(portfolio_config.get("max_venue_weight", 0.30)),
    )
    policy = next(item for item in default_policies() if item.name == "btc_signal_control")
    net = simulate_portfolio(policy, symbols, closes, targets, 0, len(timestamps), costs, risk_config)
    gross = simulate_portfolio(
        policy,
        symbols,
        closes,
        targets,
        0,
        len(timestamps),
        CostModel(0.0, 0.0, 0.0),
        risk_config,
    )
    return {
        "policy": asdict(policy),
        "gross_return_usdt": gross.metrics.return_usdt,
        "net_return_usdt": net.metrics.return_usdt,
        "cost_drag": gross.metrics.return_usdt - net.metrics.return_usdt,
        "gross_edge_positive": gross.metrics.return_usdt > 0,
        "profit_factor_net": net.metrics.profit_factor,
        "average_gross_exposure": net.metrics.average_gross_exposure,
        "turnover": net.metrics.turnover,
        "rebalance_trades": net.metrics.rebalance_trades,
        "asset_return_contributions": net.metrics.asset_return_contributions,
    }


def _cost_model(config: dict[str, Any]) -> CostModel:
    values = config.get("cost_model", {})
    return CostModel(
        float(values.get("fees_bps", 10)),
        float(values.get("slippage_bps", 2)),
        float(values.get("spread_bps", 1)),
    )


def _bars_in_report_window(bars: list, report: dict[str, Any]) -> list:
    start = datetime.fromisoformat(str(report["start"]).replace("Z", "+00:00"))
    end = datetime.fromisoformat(str(report["end"]).replace("Z", "+00:00"))
    selected = [
        bar for bar in bars if start.timestamp() * 1_000_000_000 <= int(bar.ts_event) <= end.timestamp() * 1_000_000_000
    ]
    if not selected:
        raise ValueError("BTC Spot catalog does not cover the M4 report window")
    return selected


def _directional_conclusion(m4: dict, m5: dict) -> str:
    if not m4["gross_edge_positive"] and not m5["gross_edge_positive"]:
        return "directional alpha is negative before costs; parameter tuning is not justified"
    return "some gross edge remains; inspect cost drag and regime concentration before further testing"


def _next_action(carry_report: dict) -> str:
    if carry_report["research_gate"]["approved"]:
        return "implement demo-only spot/perpetual execution and reconciliation, then run a long forward test"
    return "extend the dataset and reject or revise carry based on failed research criteria"
