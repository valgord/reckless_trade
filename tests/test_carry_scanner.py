from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.trader.carry_scanner import BybitCarryScanner
from trading.execution.carry_scanner import CarryScannerConfig, evaluate_carry_candidate


def spot_ticker(symbol: str = "AAAUSDT", turnover: str = "50000000") -> dict:
    return {
        "symbol": symbol,
        "ask1Price": "100.1",
        "ask1Size": "10",
        "bid1Price": "100",
        "bid1Size": "10",
        "turnover24h": turnover,
    }


def perp_ticker(symbol: str = "AAAUSDT", funding: str = "0.003", turnover: str = "60000000") -> dict:
    return {
        "symbol": symbol,
        "bid1Price": "101",
        "bid1Size": "10",
        "ask1Price": "101.1",
        "ask1Size": "10",
        "markPrice": "101",
        "fundingRate": funding,
        "nextFundingTime": "123456789",
        "turnover24h": turnover,
    }


def spot_instrument(symbol: str = "AAAUSDT") -> dict:
    return {
        "symbol": symbol,
        "status": "Trading",
        "baseCoin": symbol.removesuffix("USDT"),
        "quoteCoin": "USDT",
        "lotSizeFilter": {"minOrderAmt": "5", "minOrderQty": "0.01"},
    }


def perp_instrument(symbol: str = "AAAUSDT") -> dict:
    return {
        "symbol": symbol,
        "status": "Trading",
        "baseCoin": symbol.removesuffix("USDT"),
        "quoteCoin": "USDT",
        "settleCoin": "USDT",
        "contractType": "LinearPerpetual",
        "isPreListing": False,
        "fundingInterval": "480",
        "lotSizeFilter": {"minNotionalValue": "5", "minOrderQty": "0.01"},
    }


def test_candidate_estimate_is_transparent_and_eligible() -> None:
    candidate = evaluate_carry_candidate(
        "AAAUSDT",
        spot_ticker(),
        perp_ticker(),
        spot_instrument(),
        perp_instrument(),
        [0.003] * 10,
        CarryScannerConfig(),
    )

    assert candidate.eligible is True
    assert candidate.reasons == ()
    assert candidate.funding["positive_share"] == 1
    assert candidate.estimate["roundtrip_fees_usdt"] > 0
    assert candidate.estimate["estimated_net_over_horizon_usdt"] > 0
    assert candidate.liquidity["top_book_capacity_usdt"] >= 100


def test_candidate_rejects_negative_unstable_and_illiquid_funding() -> None:
    candidate = evaluate_carry_candidate(
        "AAAUSDT",
        spot_ticker(turnover="100"),
        perp_ticker(funding="-0.001", turnover="100"),
        spot_instrument(),
        perp_instrument(),
        [-0.001, 0.001],
        CarryScannerConfig(),
    )

    assert candidate.eligible is False
    assert {
        "current_funding_not_positive",
        "insufficient_funding_history",
        "positive_funding_share_below_threshold",
        "spot_turnover_below_threshold",
        "perp_turnover_below_threshold",
        "estimated_horizon_net_not_positive",
    }.issubset(candidate.reasons)


class FakePublicClient:
    async def get_public(self, path: str, params: dict) -> dict:
        if path.endswith("tickers") and params["category"] == "spot":
            return {"result": {"list": [spot_ticker()]}}
        if path.endswith("tickers") and params["category"] == "linear":
            return {"result": {"list": [perp_ticker()]}}
        if path.endswith("instruments-info"):
            return {"result": {"list": [spot_instrument()]}}
        if path.endswith("funding/history"):
            return {"result": {"list": [{"fundingRate": "0.003"}] * 10}}
        raise AssertionError((path, params))

    async def get_public_pages(self, path: str, params: dict) -> list[dict]:
        assert path.endswith("instruments-info")
        assert params["category"] == "linear"
        return [perp_instrument()]


@pytest.mark.asyncio
async def test_scanner_is_public_read_only_and_persists_ranked_output(tmp_path: Path) -> None:
    status_path = tmp_path / "scanner.json"
    scanner = BybitCarryScanner(
        FakePublicClient(),  # type: ignore[arg-type]
        config=CarryScannerConfig(),
        maximum_symbols=5,
        funding_history_limit=10,
        status_path=status_path,
    )

    result = await scanner.refresh()

    assert result["status"] == "available"
    assert result["source"] == "bybit_public"
    assert result["orders_enabled"] is False
    assert result["automatic_actions_enabled"] is False
    assert result["universe"]["eligible_symbol_count"] == 1
    assert result["candidates"][0]["symbol"] == "AAAUSDT"
    assert json.loads(status_path.read_text())["selection_policy"] == "observation_only_no_execution"
