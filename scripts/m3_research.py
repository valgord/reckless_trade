from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

from research.backtests.nautilus_runner import run_nautilus_backtest, write_report
from research.experiments.m3_runner import run_m3_research, write_m3_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run M3 walk-forward and robustness research")
    parser.add_argument("--catalog", default="data/catalog")
    parser.add_argument("--config", default="configs/backtest/platform.yaml")
    parser.add_argument("--registry", default="data/runtime/experiment-registry.jsonl")
    parser.add_argument("--report", default="data/runtime/m3-research.json")
    parser.add_argument("--confirmation-report", default="data/runtime/m3-nautilus-confirmation.json")
    parser.add_argument("--skip-nautilus-confirmation", action="store_true")
    args = parser.parse_args()
    report = run_m3_research(
        Path(args.catalog),
        Path(args.config).resolve(),
        Path(args.registry),
    )
    if not args.skip_nautilus_confirmation:
        candidate = report["candidate_ranking"][0]["candidate"]
        confirmation = run_nautilus_backtest(
            Path(args.catalog),
            Path(args.config).resolve(),
            trade_notional=Decimal("1000"),
            enabled_strategies=tuple(candidate["enabled"]),
            min_hold_bars=int(candidate["min_hold_bars"]),
            allowed_regimes=tuple(candidate["allowed_regimes"]),
            regime_entry_bars=int(candidate["regime_entry_bars"]),
        )
        write_report(Path(args.confirmation_report), confirmation)
        fast_return = float(report["candidate_ranking"][0]["metrics"]["return_usdt"])
        delta = confirmation.strategy_return - fast_return
        report["nautilus_confirmation"] = {
            "candidate": candidate["name"],
            "fast_return_usdt": fast_return,
            "nautilus_return_usdt": confirmation.strategy_return,
            "return_delta": delta,
            "within_one_percentage_point": abs(delta) <= 0.01,
            "report": asdict(confirmation),
        }
        report["promotion"]["criteria"]["nautilus_confirmation_within_1pp"] = abs(delta) <= 0.01
        report["promotion"]["approved"] = all(report["promotion"]["criteria"].values())
    write_m3_report(Path(args.report), report)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
