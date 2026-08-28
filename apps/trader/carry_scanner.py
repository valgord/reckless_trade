from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from apps.trader.bybit_demo_rest import BYBIT_PUBLIC_REST_URL, BybitPublicRestClient
from apps.trader.demo_strategy import write_runtime_status
from storage.carry_scanner_history import record_carry_scan
from trading.execution.carry_scanner import CarryScannerConfig, evaluate_carry_candidate


class CarryScannerError(RuntimeError):
    pass


class BybitCarryScanner:
    def __init__(
        self,
        client: BybitPublicRestClient,
        *,
        config: CarryScannerConfig,
        maximum_symbols: int = 20,
        funding_history_limit: int = 21,
        symbols: tuple[str, ...] = (),
        status_path: Path,
        history_path: Path | None = None,
        history_retention_days: int = 90,
    ) -> None:
        if maximum_symbols < 1 or funding_history_limit < 1:
            raise ValueError("scanner symbol and history limits must be positive")
        self.client = client
        self.config = config
        self.maximum_symbols = maximum_symbols
        self.funding_history_limit = min(funding_history_limit, 200)
        self.symbols = symbols
        self.status_path = status_path
        self.history_path = history_path
        self.history_retention_days = history_retention_days
        self._funding_semaphore = asyncio.Semaphore(5)

    async def refresh(self) -> dict[str, Any]:
        spot_tickers_payload, perp_tickers_payload, spot_instruments_payload, perp_instruments = await asyncio.gather(
            self.client.get_public("/v5/market/tickers", {"category": "spot"}),
            self.client.get_public("/v5/market/tickers", {"category": "linear"}),
            self.client.get_public("/v5/market/instruments-info", {"category": "spot"}),
            self.client.get_public_pages(
                "/v5/market/instruments-info",
                {"category": "linear", "status": "Trading", "limit": 1000},
            ),
        )
        spot_tickers = _by_symbol(spot_tickers_payload)
        perp_tickers = _by_symbol(perp_tickers_payload)
        spot_instruments = _by_symbol(spot_instruments_payload)
        perp_instruments = {
            str(row["symbol"]): row
            for row in perp_instruments
            if row.get("quoteCoin") == "USDT"
            and row.get("settleCoin") == "USDT"
            and row.get("contractType") == "LinearPerpetual"
            and row.get("status") == "Trading"
            and row.get("isPreListing") is not True
        }
        common = set(spot_tickers) & set(perp_tickers) & set(spot_instruments) & set(perp_instruments)
        if self.symbols:
            common &= set(self.symbols)
        ranked_symbols = sorted(
            common,
            key=lambda symbol: min(
                _float_or_zero(spot_tickers[symbol].get("turnover24h")),
                _float_or_zero(perp_tickers[symbol].get("turnover24h")),
            ),
            reverse=True,
        )[: self.maximum_symbols]
        if not ranked_symbols:
            raise CarryScannerError("Bybit returned no common USDT Spot/Linear symbols")

        history_results = await asyncio.gather(
            *(self._funding_history(symbol) for symbol in ranked_symbols),
            return_exceptions=True,
        )
        candidates = []
        failures = []
        for symbol, funding_result in zip(ranked_symbols, history_results, strict=True):
            if isinstance(funding_result, BaseException):
                failures.append(
                    {"symbol": symbol, "error_type": type(funding_result).__name__, "error": str(funding_result)}
                )
                continue
            try:
                candidates.append(
                    evaluate_carry_candidate(
                        symbol,
                        spot_tickers[symbol],
                        perp_tickers[symbol],
                        spot_instruments[symbol],
                        perp_instruments[symbol],
                        funding_result,
                        self.config,
                    )
                )
            except (TypeError, ValueError) as exc:
                failures.append({"symbol": symbol, "error_type": type(exc).__name__, "error": str(exc)})
        candidates.sort(key=lambda item: (item.eligible, item.rank_score), reverse=True)
        payload = {
            "schema_version": 1,
            "status": "available",
            "source": "bybit_public",
            "orders_enabled": False,
            "automatic_actions_enabled": False,
            "selection_policy": "observation_only_no_execution",
            "config": {
                "maximum_symbols": self.maximum_symbols,
                "funding_history_limit": self.funding_history_limit,
                **asdict(self.config),
            },
            "universe": {
                "common_symbol_count": len(common),
                "scanned_symbol_count": len(ranked_symbols),
                "eligible_symbol_count": sum(item.eligible for item in candidates),
                "failed_symbol_count": len(failures),
            },
            "candidates": [item.as_dict() for item in candidates],
            "failures": failures,
            "updated_at": datetime.now(tz=UTC).isoformat(),
        }
        if self.history_path is not None:
            record_carry_scan(self.history_path, payload, retention_days=self.history_retention_days)
            payload["history"] = {"persisted": True, "retention_days": self.history_retention_days}
        write_runtime_status(self.status_path, payload)
        return payload

    async def _funding_history(self, symbol: str) -> list[float]:
        async with self._funding_semaphore:
            payload = await self.client.get_public(
                "/v5/market/funding/history",
                {"category": "linear", "symbol": symbol, "limit": self.funding_history_limit},
            )
        return [float(row["fundingRate"]) for row in payload.get("result", {}).get("list", [])]


def _by_symbol(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row["symbol"]): row
        for row in payload.get("result", {}).get("list", [])
        if row.get("symbol") and row.get("status", "Trading") == "Trading"
    }


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _symbols_from_env() -> tuple[str, ...]:
    return tuple(value.strip().upper() for value in os.getenv("CARRY_SCANNER_SYMBOLS", "").split(",") if value.strip())


async def run(watch: bool, poll_seconds: float) -> int:
    client = BybitPublicRestClient(base_url=os.getenv("CARRY_SCANNER_REST_URL", BYBIT_PUBLIC_REST_URL))
    scanner = BybitCarryScanner(
        client,
        config=CarryScannerConfig(
            target_notional_usdt=float(os.getenv("CARRY_SCANNER_TARGET_NOTIONAL_USDT", "100")),
            horizon_settlements=int(os.getenv("CARRY_SCANNER_HORIZON_SETTLEMENTS", "3")),
            minimum_turnover_24h_usdt=float(os.getenv("CARRY_SCANNER_MIN_TURNOVER_24H_USDT", "10000000")),
            minimum_funding_samples=int(os.getenv("CARRY_SCANNER_MIN_FUNDING_SAMPLES", "6")),
            minimum_positive_funding_share=float(os.getenv("CARRY_SCANNER_MIN_POSITIVE_SHARE", "0.6")),
        ),
        maximum_symbols=int(os.getenv("CARRY_SCANNER_MAX_SYMBOLS", "20")),
        funding_history_limit=int(os.getenv("CARRY_SCANNER_FUNDING_HISTORY_LIMIT", "21")),
        symbols=_symbols_from_env(),
        status_path=Path(os.getenv("CARRY_SCANNER_STATUS_PATH", "data/runtime/carry-scanner.json")),
        history_path=Path(os.getenv("CARRY_SCANNER_HISTORY_DB", "data/carry/scanner-history.sqlite3")),
        history_retention_days=int(os.getenv("CARRY_SCANNER_HISTORY_RETENTION_DAYS", "90")),
    )
    try:
        while True:
            try:
                result = await scanner.refresh()
                print(json.dumps(result, indent=2, sort_keys=True), flush=True)
            except Exception as exc:
                error = {
                    "status": "failed",
                    "source": "bybit_public",
                    "orders_enabled": False,
                    "automatic_actions_enabled": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "updated_at": datetime.now(tz=UTC).isoformat(),
                }
                write_runtime_status(scanner.status_path, error)
                print(json.dumps(error, indent=2, sort_keys=True), flush=True)
                if not watch:
                    return 2
            if not watch:
                return 0
            await asyncio.sleep(poll_seconds)
    finally:
        await client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only multi-pair Bybit carry scanner")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=300.0)
    args = parser.parse_args()
    if args.poll_seconds <= 0:
        parser.error("--poll-seconds must be positive")
    return asyncio.run(run(args.watch, args.poll_seconds))


if __name__ == "__main__":
    sys.exit(main())
