from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class CatalogUpdate:
    instrument_id: str
    bar_type: str
    fetched: int
    written: int
    total: int
    start: str
    end: str
    catalog_path: str


def parse_bar_interval(bar_spec: str) -> timedelta:
    parts = bar_spec.split("-")
    if len(parts) < 2:
        raise ValueError(f"Invalid bar specification {bar_spec!r}")
    step = int(parts[0])
    unit = parts[1]
    units = {"SECOND": "seconds", "MINUTE": "minutes", "HOUR": "hours", "DAY": "days"}
    if step <= 0 or unit not in units:
        raise ValueError(f"Unsupported bar interval {bar_spec!r}")
    return timedelta(**{units[unit]: step})


def validate_bar_series(bars: list[Any], interval: timedelta) -> None:
    if not bars:
        raise ValueError("No bars returned for the requested range")
    expected_ns = int(interval.total_seconds() * 1_000_000_000)
    timestamps = [int(bar.ts_event) for bar in bars]
    if timestamps != sorted(set(timestamps)):
        raise ValueError("Bars must be strictly ordered and unique")
    gaps = [
        (left, right) for left, right in zip(timestamps, timestamps[1:], strict=False) if right - left != expected_ns
    ]
    if gaps:
        raise ValueError(f"Historical bars contain {len(gaps)} time-grid gaps")


def last_completed_bar_end(now: datetime, interval: timedelta) -> datetime:
    now = now.astimezone(UTC)
    seconds = int(interval.total_seconds())
    epoch = int(now.timestamp())
    return datetime.fromtimestamp(epoch - epoch % seconds, tz=UTC)


async def update_bybit_catalog(
    catalog_path: Path,
    instrument_id: str,
    bar_spec: str,
    start: datetime,
    end: datetime,
) -> CatalogUpdate:
    from nautilus_trader.adapters.bybit.factories import get_cached_bybit_http_client
    from nautilus_trader.core import nautilus_pyo3
    from nautilus_trader.model.data import Bar
    from nautilus_trader.model.instruments import CurrencyPair
    from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

    interval = parse_bar_interval(bar_spec)
    start = start.astimezone(UTC)
    end = min(end.astimezone(UTC), last_completed_bar_end(datetime.now(UTC), interval))
    if start >= end:
        raise ValueError("Historical range must contain at least one completed bar")

    client = get_cached_bybit_http_client(
        environment=nautilus_pyo3.BybitEnvironment.MAINNET,
        api_key=None,
        api_secret=None,
        timeout_secs=30,
        max_retries=3,
        retry_delay_ms=500,
        retry_delay_max_ms=5_000,
    )
    product_type = nautilus_pyo3.BybitProductType.SPOT
    raw_symbol = instrument_id.split("-", 1)[0]
    pyo3_bar_type = nautilus_pyo3.BarType.from_str(f"{instrument_id}-{bar_spec}")
    try:
        instruments = await client.request_instruments(product_type, raw_symbol, None)
        pyo3_instrument = next((item for item in instruments if item.id.value == instrument_id), None)
        if pyo3_instrument is None:
            raise ValueError(f"Instrument {instrument_id} was not returned by Bybit")

        collected: dict[int, Any] = {}
        cursor_end = end
        while cursor_end > start:
            batch = await client.request_bars(
                product_type=product_type,
                bar_type=pyo3_bar_type,
                start=start,
                end=cursor_end,
                limit=1_000,
                timestamp_on_close=True,
            )
            if not batch:
                break
            for bar in batch:
                collected[int(bar.ts_event)] = bar
            earliest_ns = min(int(bar.ts_event) for bar in batch)
            earliest = datetime.fromtimestamp(earliest_ns / 1_000_000_000, tz=UTC)
            if earliest <= start or len(batch) < 1_000:
                break
            cursor_end = earliest - timedelta(microseconds=1)
    finally:
        client.cancel_all_requests()

    start_ns = int(start.timestamp() * 1_000_000_000)
    end_ns = int(end.timestamp() * 1_000_000_000)
    bars = Bar.from_pyo3_list([collected[key] for key in sorted(collected) if start_ns <= key <= end_ns])
    validate_bar_series(bars, interval)

    catalog_path.mkdir(parents=True, exist_ok=True)
    catalog = ParquetDataCatalog(str(catalog_path))
    existing_instruments = catalog.instruments(instrument_ids=[instrument_id])
    if not existing_instruments:
        catalog.write_data([CurrencyPair.from_pyo3(pyo3_instrument)])

    bar_type = f"{instrument_id}-{bar_spec}"
    existing = catalog.bars(bar_types=[bar_type])
    existing_timestamps = {int(bar.ts_event) for bar in existing}
    fresh = [bar for bar in bars if int(bar.ts_event) not in existing_timestamps]
    if fresh:
        catalog.write_data(fresh)

    total_bars = catalog.bars(bar_types=[bar_type])
    validate_bar_series(total_bars, interval)
    update = CatalogUpdate(
        instrument_id=instrument_id,
        bar_type=bar_type,
        fetched=len(bars),
        written=len(fresh),
        total=len(total_bars),
        start=datetime.fromtimestamp(total_bars[0].ts_event / 1_000_000_000, tz=UTC).isoformat(),
        end=datetime.fromtimestamp(total_bars[-1].ts_event / 1_000_000_000, tz=UTC).isoformat(),
        catalog_path=str(catalog_path),
    )
    manifest_symbol = raw_symbol.lower().replace("/", "-")
    manifest = catalog_path / f"bybit-{manifest_symbol}-bars.json"
    manifest.write_text(
        json.dumps({**asdict(update), "updated_at": datetime.now(UTC).isoformat()}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return update
