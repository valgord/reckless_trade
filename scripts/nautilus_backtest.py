from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

from research.backtests.nautilus_runner import run_nautilus_backtest, write_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the domain pipeline through Nautilus BacktestNode")
    parser.add_argument("--catalog", default="data/catalog")
    parser.add_argument("--config", default="configs/backtest/platform.yaml")
    parser.add_argument("--instrument", default="BTCUSDT-SPOT.BYBIT")
    parser.add_argument("--bar-spec", default="15-MINUTE-LAST-EXTERNAL")
    parser.add_argument("--trade-notional", default="1000")
    parser.add_argument("--report", default="data/runtime/nautilus-backtest.json")
    parser.add_argument("--enabled-strategies", nargs="*", default=[])
    parser.add_argument("--min-hold-bars", type=int, default=0)
    parser.add_argument("--allowed-regimes", nargs="*", default=[])
    parser.add_argument("--regime-entry-bars", type=int, default=1)
    args = parser.parse_args()

    report = run_nautilus_backtest(
        Path(args.catalog),
        Path(args.config).resolve(),
        args.instrument,
        args.bar_spec,
        Decimal(args.trade_notional),
        tuple(args.enabled_strategies),
        args.min_hold_bars,
        tuple(args.allowed_regimes),
        args.regime_entry_bars,
    )
    write_report(Path(args.report), report)
    print(json.dumps(asdict(report), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
