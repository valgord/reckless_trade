from __future__ import annotations

from datetime import UTC, datetime

import pytest

from research.data.bybit_carry import fetch_bybit_carry_data


class Response:
    def __init__(self, rows):
        self.rows = rows

    def raise_for_status(self):
        return None

    def json(self):
        return {"retCode": 0, "retMsg": "OK", "result": {"list": self.rows}}


class Client:
    async def get(self, path, params):
        if path.endswith("funding/history"):
            return Response(
                [
                    {"fundingRateTimestamp": "1735718400000", "fundingRate": "0.0001"},
                    {"fundingRateTimestamp": "1735689600000", "fundingRate": "-0.0002"},
                ]
            )
        return Response(
            [
                ["1735718400000", "100", "102", "99", "101"],
                ["1735689600000", "98", "101", "97", "100"],
            ]
        )


@pytest.mark.asyncio
async def test_fetches_sorted_public_carry_data():
    data = await fetch_bybit_carry_data(
        "BTCUSDT",
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 1, 1, 9, tzinfo=UTC),
        client=Client(),
    )

    assert [item.rate for item in data.funding] == [-0.0002, 0.0001]
    assert [item.close for item in data.marks] == [100.0, 101.0]
    assert data.marks[0].ts == datetime(2025, 1, 1, 1, tzinfo=UTC)
