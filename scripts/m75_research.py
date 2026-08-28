from __future__ import annotations

import argparse
import json
from pathlib import Path

from research.experiments.m75_runner import run_m75_research


def main() -> None:
    parser = argparse.ArgumentParser(description="Run M7.5 fiat-alpha postmortem and carry research")
    parser.add_argument("--catalog", default="data/catalog")
    parser.add_argument("--config", default="configs/backtest/platform.yaml")
    parser.add_argument("--carry-data", default="data/carry/btcusdt.json")
    parser.add_argument("--m4-report", default="data/runtime/m4-research.json")
    parser.add_argument("--carry-report", default="data/runtime/m75-carry.json")
    parser.add_argument("--report", default="data/runtime/m75-research.json")
    args = parser.parse_args()
    report = run_m75_research(
        Path(args.catalog),
        Path(args.config),
        Path(args.carry_data),
        Path(args.m4_report),
        Path(args.report),
        Path(args.carry_report),
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
