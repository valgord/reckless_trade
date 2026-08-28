from __future__ import annotations

import asyncio
import json
import os
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from apps.trader.bybit_demo_rest import BybitDemoReadClient
from apps.trader.demo_strategy import write_runtime_status
from trading.execution.carry import CarryOwnership, write_carry_ownership

PAIR_LINK = re.compile(r"^(rt-carry-open-[0-9a-f]{10})-([sp])$")


class CarryRecoveryError(RuntimeError):
    pass


def select_open_pair(spot_rows: list[dict[str, Any]], perp_rows: list[dict[str, Any]]) -> tuple[str, float]:
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: {"s": [], "p": []})
    for expected_leg, rows in (("s", spot_rows), ("p", perp_rows)):
        for row in rows:
            match = PAIR_LINK.fullmatch(str(row.get("orderLinkId", "")))
            if match and match.group(2) == expected_leg:
                grouped[match.group(1)][expected_leg].append(row)

    complete = [(pair_id, legs) for pair_id, legs in grouped.items() if legs["s"] and legs["p"]]
    if len(complete) != 1:
        message = f"expected exactly one completed open pair in execution history, found {len(complete)}"
        raise CarryRecoveryError(message)
    pair_id, legs = complete[0]
    if any(str(row.get("side", "")).lower() != "buy" for row in legs["s"]):
        raise CarryRecoveryError("recovered Spot executions are not buys")
    if any(str(row.get("side", "")).lower() != "sell" for row in legs["p"]):
        raise CarryRecoveryError("recovered Linear executions are not sells")
    spot_quantity = sum(float(row["execQty"]) for row in legs["s"])
    perp_quantity = sum(float(row["execQty"]) for row in legs["p"])
    tolerance = max(spot_quantity * 1e-9, 1e-12)
    if spot_quantity <= 0 or abs(spot_quantity - perp_quantity) > tolerance:
        raise CarryRecoveryError("recovered carry legs do not have equal positive quantities")
    return pair_id, spot_quantity


def validate_observer(observer: dict[str, Any], quantity: float) -> None:
    snapshot = observer.get("snapshot") or {}
    if observer.get("reconciliation_complete") is not True:
        raise CarryRecoveryError("carry observer reconciliation is incomplete")
    if int(snapshot.get("open_orders", -1)) != 0:
        raise CarryRecoveryError("open orders must be reconciled before recovery")
    perp_quantity = float(snapshot.get("perp_quantity", 0) or 0)
    tolerance = max(quantity * 1e-9, 1e-12)
    if abs(perp_quantity + quantity) > tolerance:
        raise CarryRecoveryError("current Linear short does not match recovered pair quantity")
    if float(observer.get("account_btc_total", 0) or 0) + tolerance < quantity:
        raise CarryRecoveryError("current BTC balance does not cover recovered Spot quantity")


async def recover() -> dict[str, Any]:
    api_key = os.getenv("BYBIT_DEMO_API_KEY")
    api_secret = os.getenv("BYBIT_DEMO_API_SECRET")
    if not api_key or not api_secret:
        raise CarryRecoveryError("Bybit Demo credentials are required")
    pair_path = Path(os.getenv("CARRY_PAIR_STATUS_PATH", "data/runtime/carry-pair.json"))
    ownership_path = Path(os.getenv("CARRY_OWNERSHIP_PATH", "data/runtime/carry-ownership.json"))
    observer_path = Path(os.getenv("CARRY_STATUS_PATH", "data/runtime/carry-observer.json"))
    if pair_path.exists() or ownership_path.exists():
        raise CarryRecoveryError("refusing to overwrite an existing carry pair or ownership journal")
    if not observer_path.exists():
        raise CarryRecoveryError("carry observer status is missing")
    observer = json.loads(observer_path.read_text(encoding="utf-8"))

    client = BybitDemoReadClient(api_key, api_secret)
    try:
        spot_rows, perp_rows = await asyncio.gather(
            client.get_private_pages(
                "/v5/execution/list", {"category": "spot", "symbol": "BTCUSDT", "limit": 100}
            ),
            client.get_private_pages(
                "/v5/execution/list", {"category": "linear", "symbol": "BTCUSDT", "limit": 100}
            ),
        )
    finally:
        await client.close()

    pair_id, quantity = select_open_pair(spot_rows, perp_rows)
    validate_observer(observer, quantity)
    recovered_at = datetime.now(tz=UTC).isoformat()
    write_carry_ownership(ownership_path, CarryOwnership(quantity, -quantity))
    pair = {
        "status": "completed",
        "action": "open",
        "pair_id": pair_id,
        "quantity": str(quantity),
        "spot_instrument": "BTCUSDT-SPOT.BYBIT",
        "perp_instrument": "BTCUSDT-LINEAR.BYBIT",
        "spot_filled": quantity,
        "perp_filled": quantity,
        "ownership": {"spot_quantity": quantity, "perp_quantity": -quantity},
        "recovered_from": "bybit_demo_execution_history",
        "recovered_at": recovered_at,
        "orders_submitted": False,
    }
    try:
        write_runtime_status(pair_path, pair)
    except Exception:
        ownership_path.unlink(missing_ok=True)
        raise
    return pair


def main() -> None:
    result = asyncio.run(recover())
    print(
        json.dumps(
            {
                "status": result["status"],
                "pair_id": result["pair_id"],
                "quantity": result["quantity"],
                "orders_submitted": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
