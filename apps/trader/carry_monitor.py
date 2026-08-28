from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from apps.trader.bybit_demo_rest import BybitDemoReadClient
from apps.trader.demo_strategy import write_runtime_status
from trading.execution.carry_performance import CarryEntryLeg, calculate_carry_performance


class CarryMonitorError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CarryCycle:
    open_pair_id: str
    symbol: str
    opened_at_ms: int
    spot: CarryEntryLeg
    perp: CarryEntryLeg

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "state": "open",
            "open_pair_id": self.open_pair_id,
            "symbol": self.symbol,
            "opened_at_ms": self.opened_at_ms,
            "opened_at": datetime.fromtimestamp(self.opened_at_ms / 1_000, tz=UTC).isoformat(),
            "spot": asdict(self.spot),
            "perp": asdict(self.perp),
        }


def read_cycle(path: Path) -> CarryCycle | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or payload.get("state") != "open":
        raise CarryMonitorError("unsupported carry cycle journal")
    return CarryCycle(
        open_pair_id=str(payload["open_pair_id"]),
        symbol=str(payload["symbol"]),
        opened_at_ms=int(payload["opened_at_ms"]),
        spot=CarryEntryLeg(**payload["spot"]),
        perp=CarryEntryLeg(**payload["perp"]),
    )


class CarryPerformanceMonitor:
    def __init__(
        self,
        client: BybitDemoReadClient,
        *,
        pair_path: Path,
        observer_path: Path,
        cycle_path: Path,
        status_path: Path,
    ) -> None:
        self.client = client
        self.pair_path = pair_path
        self.observer_path = observer_path
        self.cycle_path = cycle_path
        self.status_path = status_path

    async def refresh(self) -> dict[str, Any]:
        cycle = read_cycle(self.cycle_path)
        if cycle is None:
            cycle = await self._recover_open_cycle()
            write_runtime_status(self.cycle_path, cycle.as_dict())

        spot_quote, perp_quote, funding_rows = await asyncio.gather(
            self._ticker("spot", cycle.symbol),
            self._ticker("linear", cycle.symbol),
            self._funding_rows(cycle),
        )
        spot_exit = float(spot_quote["bid1Price"])
        perp_exit = float(perp_quote["ask1Price"])
        funding_income = sum(float(row.get("funding") or 0) for row in funding_rows)
        performance = calculate_carry_performance(
            cycle.spot,
            cycle.perp,
            spot_exit,
            perp_exit,
            funding_income,
        )
        observer = self._read_optional_json(self.observer_path)
        now_ms = int(datetime.now(tz=UTC).timestamp() * 1_000)
        payload = {
            "status": "monitoring",
            "mode": "demo",
            "orders_enabled": False,
            "cycle": cycle.as_dict(),
            "position_phase": (observer or {}).get("status"),
            "market": {
                "spot_exit_bid": spot_exit,
                "perp_exit_ask": perp_exit,
                "spot_last": float(spot_quote["lastPrice"]),
                "perp_mark": float(perp_quote["markPrice"]),
            },
            "funding": {
                "settlement_count": len(funding_rows),
                "income_usdt": funding_income,
                "last_settlement_at": self._latest_timestamp(funding_rows),
            },
            "performance": performance.as_dict(),
            "held_seconds": max(0.0, (now_ms - cycle.opened_at_ms) / 1_000),
            "updated_at": datetime.now(tz=UTC).isoformat(),
        }
        write_runtime_status(self.status_path, payload)
        return payload

    async def _recover_open_cycle(self) -> CarryCycle:
        pair = self._read_required_json(self.pair_path)
        if pair.get("status") != "completed" or pair.get("action") != "open":
            raise CarryMonitorError("no completed open carry pair is available")
        pair_id = str(pair["pair_id"])
        symbol = str(pair.get("spot_instrument", "BTCUSDT-SPOT.BYBIT")).split("-", 1)[0]
        spot_rows, perp_rows = await asyncio.gather(
            self.client.get_private_pages(
                "/v5/execution/list",
                {"category": "spot", "orderLinkId": f"{pair_id}-s", "limit": 100},
            ),
            self.client.get_private_pages(
                "/v5/execution/list",
                {"category": "linear", "orderLinkId": f"{pair_id}-p", "limit": 100},
            ),
        )
        spot, spot_time = self._entry_leg(spot_rows, "spot")
        perp, perp_time = self._entry_leg(perp_rows, "linear")
        if abs(spot.quantity - perp.quantity) > max(spot.quantity * 1e-9, 1e-12):
            raise CarryMonitorError("recovered carry entry legs have unequal quantities")
        return CarryCycle(pair_id, symbol, min(spot_time, perp_time), spot, perp)

    @staticmethod
    def _entry_leg(rows: list[dict[str, Any]], category: str) -> tuple[CarryEntryLeg, int]:
        if not rows:
            raise CarryMonitorError(f"no {category} executions found for the open pair")
        quantity = sum(float(row["execQty"]) for row in rows)
        value = sum(float(row["execQty"]) * float(row["execPrice"]) for row in rows)
        if quantity <= 0:
            raise CarryMonitorError(f"invalid {category} execution quantity")
        average_price = value / quantity
        fee_usdt = sum(_fee_in_usdt(row) for row in rows)
        fee_rate = fee_usdt / max(sum(float(row["execValue"]) for row in rows), 1e-12)
        return CarryEntryLeg(quantity, average_price, fee_usdt, fee_rate), min(int(row["execTime"]) for row in rows)

    async def _ticker(self, category: str, symbol: str) -> dict[str, Any]:
        payload = await self.client.get_public(
            "/v5/market/tickers",
            {"category": category, "symbol": symbol},
        )
        rows = payload.get("result", {}).get("list", [])
        if not rows:
            raise CarryMonitorError(f"no {category} ticker returned")
        return rows[0]

    async def _funding_rows(self, cycle: CarryCycle) -> list[dict[str, Any]]:
        now_ms = int(datetime.now(tz=UTC).timestamp() * 1_000)
        rows: list[dict[str, Any]] = []
        start = cycle.opened_at_ms
        maximum_window_ms = 7 * 24 * 60 * 60 * 1_000
        while start <= now_ms:
            end = min(now_ms, start + maximum_window_ms)
            page = await self.client.get_private_pages(
                "/v5/account/transaction-log",
                {
                    "accountType": "UNIFIED",
                    "category": "linear",
                    "currency": "USDT",
                    "startTime": start,
                    "endTime": end,
                    "limit": 50,
                },
            )
            rows.extend(
                row
                for row in page
                if row.get("symbol") == cycle.symbol
                and row.get("type") == "SETTLEMENT"
                and int(row["transactionTime"]) >= cycle.opened_at_ms
            )
            if end == now_ms:
                break
            start = end + 1
        return list(
            {(str(row["id"]), str(row["transactionTime"]), str(row.get("funding"))): row for row in rows}.values()
        )

    @staticmethod
    def _latest_timestamp(rows: list[dict[str, Any]]) -> str | None:
        if not rows:
            return None
        value = max(int(row["transactionTime"]) for row in rows)
        return datetime.fromtimestamp(value / 1_000, tz=UTC).isoformat()

    @staticmethod
    def _read_required_json(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise CarryMonitorError(f"required runtime file is missing: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _read_optional_json(path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))


def _fee_in_usdt(row: dict[str, Any]) -> float:
    fee = float(row["execFee"])
    currency = str(row.get("feeCurrency") or ("USDT" if row.get("category") == "linear" else ""))
    if currency == "USDT":
        return fee
    if currency == "BTC":
        return fee * float(row["execPrice"])
    raise CarryMonitorError(f"cannot convert {currency or 'unknown'} execution fee to USDT")


async def run(watch: bool, poll_seconds: float) -> int:
    api_key = os.getenv("BYBIT_DEMO_API_KEY")
    api_secret = os.getenv("BYBIT_DEMO_API_SECRET")
    if not api_key or not api_secret:
        raise CarryMonitorError("BYBIT_DEMO_API_KEY and BYBIT_DEMO_API_SECRET are required")
    client = BybitDemoReadClient(api_key, api_secret)
    monitor = CarryPerformanceMonitor(
        client,
        pair_path=Path(os.getenv("CARRY_PAIR_STATUS_PATH", "data/runtime/carry-pair.json")),
        observer_path=Path(os.getenv("CARRY_STATUS_PATH", "data/runtime/carry-observer.json")),
        cycle_path=Path(os.getenv("CARRY_CYCLE_PATH", "data/runtime/carry-cycle.json")),
        status_path=Path(os.getenv("CARRY_PERFORMANCE_PATH", "data/runtime/carry-performance.json")),
    )
    try:
        while True:
            try:
                result = await monitor.refresh()
                print(json.dumps(result, indent=2, sort_keys=True), flush=True)
            except Exception as exc:
                error = {
                    "status": "failed",
                    "mode": "demo",
                    "orders_enabled": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "updated_at": datetime.now(tz=UTC).isoformat(),
                }
                write_runtime_status(monitor.status_path, error)
                print(json.dumps(error, indent=2, sort_keys=True), flush=True)
                if not watch:
                    return 2
            if not watch:
                return 0
            await asyncio.sleep(poll_seconds)
    finally:
        await client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Bybit Demo carry performance monitor")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=60.0)
    args = parser.parse_args()
    if args.poll_seconds <= 0:
        parser.error("--poll-seconds must be positive")
    return asyncio.run(run(args.watch, args.poll_seconds))


if __name__ == "__main__":
    sys.exit(main())
