from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from research.data.bybit_catalog import update_bybit_catalog


def utc_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


async def run(args: argparse.Namespace) -> None:
    end = utc_datetime(args.end) if args.end else datetime.now(UTC)
    start = utc_datetime(args.start) if args.start else end - timedelta(days=args.days)
    result = await update_bybit_catalog(
        Path(args.catalog),
        args.instrument,
        args.bar_spec,
        start,
        end,
    )
    print(json.dumps(asdict(result), indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Download completed Bybit bars into a Nautilus Parquet catalog")
    parser.add_argument("--catalog", default="data/catalog")
    parser.add_argument("--instrument", default="BTCUSDT-SPOT.BYBIT")
    parser.add_argument("--bar-spec", default="15-MINUTE-LAST-EXTERNAL")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--start")
    parser.add_argument("--end")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
