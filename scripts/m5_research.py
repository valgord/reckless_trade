from __future__ import annotations

import argparse
import json
from pathlib import Path

from research.experiments.m5_runner import run_m5_research


def main() -> None:
    parser = argparse.ArgumentParser(description="Run M5 multi-asset portfolio research")
    parser.add_argument("--catalog", default="data/catalog")
    parser.add_argument("--config", default="configs/backtest/platform.yaml")
    parser.add_argument("--report", default="data/runtime/m5-research.json")
    args = parser.parse_args()
    report = run_m5_research(Path(args.catalog), Path(args.config).resolve(), Path(args.report))
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
