from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

ORDER_SMOKE_CONFIRMATION = "I_UNDERSTAND_THIS_PLACES_A_DEMO_ORDER"
DEFAULT_INSTRUMENT_ID = "BTCUSDT-SPOT.BYBIT"


class SmokeCheckError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SmokeOptions:
    public_only: bool = False
    place_order: bool = False
    instrument_id: str = DEFAULT_INSTRUMENT_ID


class NautilusBybitTypes:
    """Small type boundary which keeps the smoke workflow independently testable."""

    def __init__(self) -> None:
        from nautilus_trader.core import nautilus_pyo3

        self.module = nautilus_pyo3
        self.product_type = nautilus_pyo3.BybitProductType.SPOT
        self.account_type = nautilus_pyo3.BybitAccountType.UNIFIED

    def ticker_params(self, symbol: str):
        return self.module.BybitTickersParams(self.product_type, symbol)

    def account_id(self):
        return self.module.AccountId("BYBIT-UNIFIED")

    def client_order_id(self, value: str):
        return self.module.ClientOrderId(value)

    def quantity(self, value: Decimal):
        return self.module.Quantity.from_decimal(value)

    def price(self, value: Decimal):
        return self.module.Price.from_decimal(value)

    @property
    def buy_side(self):
        return self.module.OrderSide.BUY

    @property
    def limit_order(self):
        return self.module.OrderType.LIMIT

    @property
    def gtc(self):
        return self.module.TimeInForce.GTC


def validate_order_confirmation(value: str | None) -> None:
    if value != ORDER_SMOKE_CONFIRMATION:
        raise SmokeCheckError(
            "Order smoke is locked. Set BYBIT_DEMO_ORDER_SMOKE_CONFIRMATION=" + ORDER_SMOKE_CONFIRMATION,
        )


def create_demo_client(api_key: str | None, api_secret: str | None):
    from nautilus_trader.adapters.bybit.factories import get_cached_bybit_http_client
    from nautilus_trader.core.nautilus_pyo3 import BybitEnvironment

    return get_cached_bybit_http_client(
        environment=BybitEnvironment.DEMO,
        api_key=api_key,
        api_secret=api_secret,
        timeout_secs=30,
        max_retries=2,
        retry_delay_ms=500,
        retry_delay_max_ms=2_000,
    )


class BybitDemoSmoke:
    def __init__(self, client: Any, instrument_id: str = DEFAULT_INSTRUMENT_ID, types: Any | None = None) -> None:
        self.client = client
        self.instrument_id = instrument_id
        self.types = types or NautilusBybitTypes()

    async def run(self, options: SmokeOptions) -> dict[str, Any]:
        instrument, ticker, public = await self._check_public()
        result: dict[str, Any] = {"public": public}
        if options.public_only:
            return result

        result.update(await self._check_private(instrument))
        if options.place_order:
            result["order_smoke"] = await self._submit_and_cancel(instrument, ticker)
        return result

    async def _check_public(self) -> tuple[Any, Any, dict[str, Any]]:
        raw_symbol = self.instrument_id.split("-", 1)[0]
        instruments = await self.client.request_instruments(self.types.product_type, raw_symbol, None)
        instrument = next((item for item in instruments if item.id.value == self.instrument_id), None)
        if instrument is None:
            raise SmokeCheckError(f"Instrument {self.instrument_id} was not discovered")

        tickers = await self.client.request_tickers(self.types.ticker_params(raw_symbol))
        ticker = next((item for item in tickers if item.symbol == raw_symbol), None)
        if ticker is None:
            raise SmokeCheckError(f"Ticker {raw_symbol} was not returned")
        return (
            instrument,
            ticker,
            {
                "instrument": instrument.id.value,
                "price_precision": instrument.price_precision,
                "size_precision": instrument.size_precision,
                "last_price": ticker.last_price,
                "bid": ticker.bid1_price,
                "ask": ticker.ask1_price,
            },
        )

    async def _check_private(self, instrument: Any) -> dict[str, Any]:
        details = await self.client.get_account_details()
        account_id = self.types.account_id()
        state = await self.client.request_account_state(self.types.account_type, account_id)
        open_orders = await self.client.request_order_status_reports(
            account_id,
            self.types.product_type,
            instrument.id,
            open_only=True,
        )
        return {
            "account": {
                "authenticated": True,
                "read_only_key": bool(details.read_only),
                "account_type": str(state.account_type),
                "balance_count": len(state.balances),
            },
            "reconciliation": {
                "queried": True,
                "open_order_count": len(open_orders),
            },
        }

    async def _submit_and_cancel(self, instrument: Any, ticker: Any) -> dict[str, Any]:
        bid = Decimal(ticker.bid1_price)
        price_increment = instrument.price_increment.as_decimal()
        size_increment = instrument.size_increment.as_decimal()
        price = (bid * Decimal("0.90") / price_increment).to_integral_value(rounding=ROUND_FLOOR) * price_increment
        min_notional = instrument.min_notional.as_decimal() if instrument.min_notional else Decimal("1")
        max_notional = Decimal(os.getenv("BYBIT_DEMO_ORDER_SMOKE_MAX_NOTIONAL", "10"))
        target_notional = max(min_notional, Decimal("1"))
        if target_notional > max_notional:
            raise SmokeCheckError(f"Venue minimum notional {target_notional} exceeds smoke cap {max_notional}")
        quantity = (target_notional / price / size_increment).to_integral_value(rounding=ROUND_CEILING) * size_increment
        if instrument.min_quantity:
            quantity = max(quantity, instrument.min_quantity.as_decimal())
        actual_notional = price * quantity
        if actual_notional > max_notional:
            raise SmokeCheckError(f"Rounded order notional {actual_notional} exceeds smoke cap {max_notional}")

        account_id = self.types.account_id()
        client_order_id = self.types.client_order_id(f"rt-smoke-{uuid4().hex[:12]}")
        submit_attempted = False
        submit_report = None
        cancel_report = None
        submit_error = None
        cancel_error = None
        cancel_verified_by_reconciliation = False
        try:
            submit_attempted = True
            submit_report = await self.client.submit_order(
                account_id,
                self.types.product_type,
                instrument.id,
                client_order_id,
                self.types.buy_side,
                self.types.limit_order,
                self.types.quantity(quantity),
                time_in_force=self.types.gtc,
                price=self.types.price(price),
                post_only=True,
            )
        except Exception as exc:
            submit_error = exc
        finally:
            if submit_attempted:
                try:
                    cancel_report = await self.client.cancel_order(
                        account_id,
                        self.types.product_type,
                        instrument.id,
                        client_order_id=client_order_id,
                    )
                except Exception as exc:
                    cancel_error = exc

        if cancel_error is not None:
            try:
                open_orders = await self.client.request_order_status_reports(
                    account_id,
                    self.types.product_type,
                    instrument.id,
                    open_only=True,
                )
                cancel_verified_by_reconciliation = self._order_absent_from_reports(
                    client_order_id,
                    open_orders,
                )
            except Exception:
                cancel_verified_by_reconciliation = False
            if cancel_verified_by_reconciliation:
                cancel_error = None

        if submit_error is not None:
            cancel_outcome = "succeeded" if cancel_report is not None else f"failed: {cancel_error}"
            raise SmokeCheckError(
                f"Submit outcome is unknown for {client_order_id.value}; cancellation {cancel_outcome}",
            ) from submit_error
        if cancel_error is not None:
            raise SmokeCheckError(
                f"Order {client_order_id.value} was submitted but cancellation failed: {cancel_error}",
            ) from cancel_error

        return {
            "submitted": submit_report is not None,
            "cancelled": cancel_report is not None or cancel_verified_by_reconciliation,
            "client_order_id": client_order_id.value,
            "price": str(price),
            "quantity": str(quantity),
            "notional": str(actual_notional),
            "submit_status": str(submit_report.order_status) if submit_report else None,
            "cancel_status": (
                str(cancel_report.order_status)
                if cancel_report
                else "NOT_OPEN"
                if cancel_verified_by_reconciliation
                else None
            ),
        }

    @staticmethod
    def _order_absent_from_reports(client_order_id: Any, reports: list[Any]) -> bool:
        if not reports:
            return True

        target = client_order_id.value
        for report in reports:
            report_id = getattr(report, "client_order_id", None)
            value = getattr(report_id, "value", report_id)
            if value is None:
                return False
            if value == target:
                return False
        return True


def write_status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


async def run(options: SmokeOptions, status_path: Path) -> int:
    api_key = os.getenv("BYBIT_DEMO_API_KEY")
    api_secret = os.getenv("BYBIT_DEMO_API_SECRET")
    result: dict[str, Any] = {
        "checked_at": datetime.now(UTC).isoformat(),
        "environment": "demo",
        "instrument": options.instrument_id,
        "public_only": options.public_only,
        "order_requested": options.place_order,
    }
    try:
        if not options.public_only and (not api_key or not api_secret):
            raise SmokeCheckError("BYBIT_DEMO_API_KEY and BYBIT_DEMO_API_SECRET are required")
        if options.place_order:
            validate_order_confirmation(os.getenv("BYBIT_DEMO_ORDER_SMOKE_CONFIRMATION"))
        client = create_demo_client(
            None if options.public_only else api_key,
            None if options.public_only else api_secret,
        )
        result.update(await BybitDemoSmoke(client, options.instrument_id).run(options))
        result["status"] = "passed"
        return_code = 0
    except Exception as exc:
        result.update({"status": "failed", "error_type": type(exc).__name__, "error": str(exc)})
        return_code = 2
    finally:
        client = locals().get("client")
        if client is not None:
            client.cancel_all_requests()
        write_status(status_path, result)
        print(json.dumps(result, indent=2, sort_keys=True))
    return return_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Bybit Demo integration smoke test")
    parser.add_argument("--public-only", action="store_true", help="Skip authenticated account checks")
    parser.add_argument("--order-smoke", action="store_true", help="Submit and immediately cancel a Demo order")
    parser.add_argument("--instrument", default=DEFAULT_INSTRUMENT_ID)
    parser.add_argument(
        "--status-path",
        type=Path,
        default=Path(os.getenv("BYBIT_SMOKE_STATUS_PATH", "data/runtime/bybit-smoke.json")),
    )
    args = parser.parse_args()
    if args.public_only and args.order_smoke:
        parser.error("--public-only and --order-smoke cannot be combined")
    return asyncio.run(
        run(
            SmokeOptions(public_only=args.public_only, place_order=args.order_smoke, instrument_id=args.instrument),
            args.status_path,
        ),
    )


if __name__ == "__main__":
    sys.exit(main())
