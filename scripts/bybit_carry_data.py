from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from research.data.bybit_carry import fetch_bybit_carry_data, write_carry_data


def utc_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


async def run() -> None:
    parser = argparse.ArgumentParser(description="Download public Bybit funding and mark-price history")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--output", default="data/carry/btcusdt.json")
    args = parser.parse_args()
    end = utc_datetime(args.end) if args.end else datetime.now(UTC)
    start = utc_datetime(args.start) if args.start else end - timedelta(days=args.days)
    data = await fetch_bybit_carry_data(args.symbol, start, end)
    write_carry_data(Path(args.output), data)
    print(
        json.dumps(
            {
                "symbol": data.symbol,
                "funding_points": len(data.funding),
                "mark_points": len(data.marks),
                "start": data.funding[0].ts.isoformat(),
                "end": data.funding[-1].ts.isoformat(),
                "output": args.output,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    asyncio.run(run())
