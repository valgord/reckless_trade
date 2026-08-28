from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx


@dataclass(frozen=True, slots=True)
class FundingPoint:
    ts: datetime
    rate: float


@dataclass(frozen=True, slots=True)
class MarkPoint:
    ts: datetime
    close: float


@dataclass(frozen=True, slots=True)
class CarryMarketData:
    symbol: str
    funding: tuple[FundingPoint, ...]
    marks: tuple[MarkPoint, ...]


async def fetch_bybit_carry_data(
    symbol: str,
    start: datetime,
    end: datetime,
    base_url: str = "https://api.bybit.com",
    client: Any | None = None,
) -> CarryMarketData:
    start = start.astimezone(UTC)
    end = end.astimezone(UTC)
    if start >= end:
        raise ValueError("carry data range must be positive")
    owns_client = client is None
    client = client or httpx.AsyncClient(base_url=base_url, timeout=30.0)
    try:
        funding = await _fetch_funding(client, symbol, start, end)
        marks = await _fetch_marks(client, symbol, start, end)
    finally:
        if owns_client:
            await client.aclose()
    if not funding:
        raise ValueError("Bybit returned no funding history")
    if not marks:
        raise ValueError("Bybit returned no mark-price history")
    return CarryMarketData(symbol, tuple(funding), tuple(marks))


def write_carry_data(path: Path, data: CarryMarketData) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "symbol": data.symbol,
        "updated_at": datetime.now(UTC).isoformat(),
        "funding": [{"ts": item.ts.isoformat(), "rate": item.rate} for item in data.funding],
        "marks": [{"ts": item.ts.isoformat(), "close": item.close} for item in data.marks],
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_carry_data(path: Path) -> CarryMarketData:
    payload = json.loads(path.read_text(encoding="utf-8"))
    funding = tuple(FundingPoint(_parse_datetime(item["ts"]), float(item["rate"])) for item in payload["funding"])
    marks = tuple(MarkPoint(_parse_datetime(item["ts"]), float(item["close"])) for item in payload["marks"])
    return CarryMarketData(str(payload["symbol"]), funding, marks)


async def _fetch_funding(client: Any, symbol: str, start: datetime, end: datetime) -> list[FundingPoint]:
    start_ms = int(start.timestamp() * 1000)
    cursor_end = int(end.timestamp() * 1000)
    collected: dict[int, FundingPoint] = {}
    while cursor_end >= start_ms:
        response = await client.get(
            "/v5/market/funding/history",
            params={"category": "linear", "symbol": symbol, "endTime": cursor_end, "limit": 200},
        )
        rows = _result_rows(response)
        if not rows:
            break
        timestamps = []
        for row in rows:
            timestamp = int(row["fundingRateTimestamp"])
            timestamps.append(timestamp)
            if start_ms <= timestamp <= int(end.timestamp() * 1000):
                collected[timestamp] = FundingPoint(
                    datetime.fromtimestamp(timestamp / 1000, tz=UTC),
                    float(row["fundingRate"]),
                )
        earliest = min(timestamps)
        if earliest <= start_ms or earliest >= cursor_end:
            break
        cursor_end = earliest - 1
        await asyncio.sleep(0.03)
    return [collected[key] for key in sorted(collected)]


async def _fetch_marks(client: Any, symbol: str, start: datetime, end: datetime) -> list[MarkPoint]:
    interval = timedelta(hours=1)
    start_ms = int(start.timestamp() * 1000)
    query_start_ms = start_ms - int(interval.total_seconds() * 1000)
    cursor_end = int(end.timestamp() * 1000)
    collected: dict[int, MarkPoint] = {}
    while cursor_end >= query_start_ms:
        window_start = max(query_start_ms, cursor_end - int(interval.total_seconds() * 1000) * 999)
        response = await client.get(
            "/v5/market/mark-price-kline",
            params={
                "category": "linear",
                "symbol": symbol,
                "interval": "60",
                "start": window_start,
                "end": cursor_end,
                "limit": 1000,
            },
        )
        rows = _result_rows(response)
        if not rows:
            break
        timestamps = []
        for row in rows:
            candle_start = int(row[0])
            timestamp = candle_start + int(interval.total_seconds() * 1000)
            timestamps.append(candle_start)
            close = float(row[4])
            if close <= 0:
                raise ValueError("mark prices must be positive")
            if start_ms <= timestamp <= int(end.timestamp() * 1000):
                collected[timestamp] = MarkPoint(datetime.fromtimestamp(timestamp / 1000, tz=UTC), close)
        earliest = min(timestamps)
        if earliest <= query_start_ms or earliest >= cursor_end:
            break
        cursor_end = earliest - 1
        await asyncio.sleep(0.03)
    points = [collected[key] for key in sorted(collected)]
    if any(right.ts <= left.ts for left, right in zip(points, points[1:], strict=False)):
        raise ValueError("mark-price timestamps must be strictly increasing")
    return points


def _result_rows(response: Any) -> list:
    response.raise_for_status()
    payload = response.json()
    if int(payload.get("retCode", -1)) != 0:
        raise ValueError(f"Bybit error {payload.get('retCode')}: {payload.get('retMsg', 'unknown')}")
    return list(payload.get("result", {}).get("list", []))


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
