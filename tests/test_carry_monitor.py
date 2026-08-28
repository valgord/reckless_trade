from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.trader.carry_monitor import CarryMonitorError, CarryPerformanceMonitor, _fee_in_usdt


class FakeClient:
    def __init__(self, executions: dict[str, list[dict]]) -> None:
        self.executions = executions

    async def get_private_pages(self, path: str, params: dict) -> list[dict]:
        assert path == "/v5/execution/list"
        return self.executions[params["category"]]


def execution(category: str, quantity: str, price: str, fee: str, currency: str, timestamp: str) -> dict:
    return {
        "category": category,
        "execQty": quantity,
        "execPrice": price,
        "execValue": str(float(quantity) * float(price)),
        "execFee": fee,
        "feeCurrency": currency,
        "execTime": timestamp,
    }


@pytest.mark.asyncio
async def test_recover_cycle_uses_actual_execution_prices_and_fees(tmp_path: Path) -> None:
    pair_path = tmp_path / "pair.json"
    pair_path.write_text(
        json.dumps({"status": "completed", "action": "open", "pair_id": "rt-carry-open-abc"}),
        encoding="utf-8",
    )
    client = FakeClient(
        {
            "spot": [execution("spot", "0.001", "80000", "0.000001", "BTC", "1000")],
            "linear": [execution("linear", "0.001", "79950", "0.0439725", "USDT", "1001")],
        }
    )
    monitor = CarryPerformanceMonitor(
        client,  # type: ignore[arg-type]
        pair_path=pair_path,
        observer_path=tmp_path / "observer.json",
        cycle_path=tmp_path / "cycle.json",
        status_path=tmp_path / "performance.json",
    )

    cycle = await monitor._recover_open_cycle()

    assert cycle.open_pair_id == "rt-carry-open-abc"
    assert cycle.spot.quantity == 0.001
    assert cycle.spot.average_price == 80000
    assert cycle.spot.fee_usdt == pytest.approx(0.08)
    assert cycle.perp.fee_usdt == pytest.approx(0.0439725)
    assert cycle.opened_at_ms == 1000


def test_unknown_fee_currency_is_not_silently_ignored() -> None:
    with pytest.raises(CarryMonitorError, match="cannot convert"):
        _fee_in_usdt(execution("spot", "1", "10", "0.1", "ETH", "1000"))
