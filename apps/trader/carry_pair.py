from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import uuid4

import yaml

from apps.trader.bybit_smoke import create_demo_client
from trading.execution.carry import (
    CarryOwnership,
    evaluate_pair_fills,
    read_carry_ownership,
    write_carry_ownership,
)

CARRY_PAIR_CONFIRMATION = "I_UNDERSTAND_THIS_PLACES_DEMO_CARRY_ORDERS"


class CarryPairError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CarryPairOptions:
    action: str
    config_path: Path
    status_path: Path
    confirmation: str | None
    timeout_seconds: float = 12.0


def validate_pair_confirmation(value: str | None) -> None:
    if value != CARRY_PAIR_CONFIRMATION:
        raise CarryPairError(f"Demo carry pair is locked; confirmation must be {CARRY_PAIR_CONFIRMATION}")


class CarryPairTypes:
    def __init__(self) -> None:
        from nautilus_trader.core import nautilus_pyo3

        self.module = nautilus_pyo3
        self.spot = nautilus_pyo3.BybitProductType.SPOT
        self.linear = nautilus_pyo3.BybitProductType.LINEAR
        self.account_type = nautilus_pyo3.BybitAccountType.UNIFIED
        self.account_id = nautilus_pyo3.AccountId("BYBIT-UNIFIED")

    def ticker_params(self, product_type: Any, symbol: str):
        return self.module.BybitTickersParams(product_type, symbol)

    def client_order_id(self, value: str):
        return self.module.ClientOrderId(value)

    def quantity(self, value: Decimal):
        return self.module.Quantity.from_decimal(value)

    @property
    def market(self):
        return self.module.OrderType.MARKET

    @property
    def ioc(self):
        return self.module.TimeInForce.IOC

    @property
    def buy(self):
        return self.module.OrderSide.BUY

    @property
    def sell(self):
        return self.module.OrderSide.SELL

    @property
    def isolated(self):
        return self.module.BybitMarginMode.ISOLATED_MARGIN

    @property
    def one_way(self):
        return self.module.BybitPositionMode.MERGED_SINGLE


class CarryPairExecutor:
    def __init__(self, client: Any, types: CarryPairTypes, config: dict[str, Any], timeout_seconds: float) -> None:
        self.client = client
        self.types = types
        self.config = config
        self.timeout_seconds = timeout_seconds
        self.spot_text = str(config.get("spot_instrument", "BTCUSDT-SPOT.BYBIT"))
        self.perp_text = str(config.get("perp_instrument", "BTCUSDT-LINEAR.BYBIT"))
        self.symbol = self.spot_text.split("-", 1)[0]
        self.ownership_path = Path(config.get("ownership_path", "data/runtime/carry-ownership.json"))

    async def execute(self, action: str) -> dict[str, Any]:
        if action not in {"open", "close"}:
            raise CarryPairError("carry pair action must be open or close")
        await self._validate_writable_key()
        spot, perp, spot_price, perp_price = await self._market_context()
        ownership = read_carry_ownership(self.ownership_path)
        await self._configure_derivative_account()
        await self._validate_no_open_orders(spot.id, perp.id)
        position_quantity = await self._perp_position_quantity(perp.id)

        if action == "open":
            if ownership != CarryOwnership() or abs(position_quantity) > 1e-12:
                raise CarryPairError("carry ownership or perpetual position is already non-flat")
            quantity = self._open_quantity(spot, perp, spot_price, perp_price)
            sides = (self.types.buy, self.types.sell)
            reduce_only = (False, False)
        else:
            quantity = self._close_quantity(ownership, position_quantity)
            sides = (self.types.sell, self.types.buy)
            reduce_only = (False, True)

        pair_id = f"rt-carry-{action}-{uuid4().hex[:10]}"
        spot_id = self.types.client_order_id(f"{pair_id}-s")
        perp_id = self.types.client_order_id(f"{pair_id}-p")
        await asyncio.gather(
            self._submit(spot.id, self.types.spot, spot_id, sides[0], quantity, reduce_only[0]),
            self._submit(perp.id, self.types.linear, perp_id, sides[1], quantity, reduce_only[1]),
            return_exceptions=True,
        )
        spot_filled, perp_filled = await asyncio.gather(
            self._wait_filled(spot.id, self.types.spot, spot_id),
            self._wait_filled(perp.id, self.types.linear, perp_id),
        )
        fill_decision = evaluate_pair_fills(float(quantity), spot_filled, perp_filled)
        if not fill_decision.complete:
            unwind = await self._unwind(
                action,
                spot.id,
                perp.id,
                Decimal(str(fill_decision.spot_unwind_quantity)),
                Decimal(str(fill_decision.perp_unwind_quantity)),
                pair_id,
            )
            raise CarryPairError(
                f"pair did not fill atomically; spot={spot_filled:g}, perp={perp_filled:g}, unwind={unwind}"
            )

        next_ownership = CarryOwnership(float(quantity), -float(quantity)) if action == "open" else CarryOwnership()
        write_carry_ownership(self.ownership_path, next_ownership)
        return {
            "status": "completed",
            "action": action,
            "pair_id": pair_id,
            "quantity": str(quantity),
            "spot_price_reference": str(spot_price),
            "perp_price_reference": str(perp_price),
            "spot_filled": spot_filled,
            "perp_filled": perp_filled,
            "ownership": {
                "spot_quantity": next_ownership.spot_quantity,
                "perp_quantity": next_ownership.perp_quantity,
            },
        }

    async def _validate_writable_key(self) -> None:
        details = await self.client.get_account_details()
        if bool(details.read_only):
            raise CarryPairError("Bybit Demo API key is read-only; order permission is required")

    async def _market_context(self) -> tuple[Any, Any, Decimal, Decimal]:
        spot_items, perp_items = await asyncio.gather(
            self.client.request_instruments(self.types.spot, self.symbol, None),
            self.client.request_instruments(self.types.linear, self.symbol, None),
        )
        spot = next((item for item in spot_items if item.id.value == self.spot_text), None)
        perp = next((item for item in perp_items if item.id.value == self.perp_text), None)
        if spot is None or perp is None:
            raise CarryPairError("Spot or Linear instrument was not discovered")
        spot_tickers, perp_tickers = await asyncio.gather(
            self.client.request_tickers(self.types.ticker_params(self.types.spot, self.symbol)),
            self.client.request_tickers(self.types.ticker_params(self.types.linear, self.symbol)),
        )
        spot_ticker = next((item for item in spot_tickers if item.symbol == self.symbol), None)
        perp_ticker = next((item for item in perp_tickers if item.symbol == self.symbol), None)
        if spot_ticker is None or perp_ticker is None:
            raise CarryPairError("Spot or Linear ticker was not returned")
        return spot, perp, Decimal(spot_ticker.ask1_price), Decimal(perp_ticker.bid1_price)

    def _open_quantity(self, spot: Any, perp: Any, spot_price: Decimal, perp_price: Decimal) -> Decimal:
        minimum = max(
            spot.min_quantity.as_decimal() if spot.min_quantity else Decimal(0),
            perp.min_quantity.as_decimal() if perp.min_quantity else Decimal(0),
        )
        increment = max(spot.size_increment.as_decimal(), perp.size_increment.as_decimal())
        quantity = max(minimum, increment)
        cap = Decimal(str(self.config.get("target_notional_usdt", 100)))
        if max(quantity * spot_price, quantity * perp_price) > cap:
            raise CarryPairError("minimum equal-quantity pair exceeds the configured carry cap")
        return quantity

    @staticmethod
    def _close_quantity(ownership: CarryOwnership, position_quantity: float) -> Decimal:
        if ownership.spot_quantity <= 0 or ownership.perp_quantity >= 0:
            raise CarryPairError("ownership ledger contains no open carry pair")
        if abs(ownership.spot_quantity - abs(ownership.perp_quantity)) > 1e-12:
            raise CarryPairError("ownership ledger legs are not equal")
        if abs(position_quantity - ownership.perp_quantity) > 1e-12:
            raise CarryPairError("reconciled perpetual position does not match ownership ledger")
        return Decimal(str(ownership.spot_quantity))

    async def _configure_derivative_account(self) -> None:
        await self._setting(self.client.set_margin_mode(self.types.isolated))
        await self._setting(self.client.switch_mode(self.types.linear, self.types.one_way, symbol=self.symbol))
        await self._setting(self.client.set_leverage(self.types.linear, self.symbol, "1", "1"))

    @staticmethod
    async def _setting(call) -> None:
        try:
            await call
        except Exception as exc:
            message = str(exc).lower()
            if "not been modified" not in message and "110043" not in message and "110025" not in message:
                raise

    async def _validate_no_open_orders(self, spot_id: Any, perp_id: Any) -> None:
        reports = await asyncio.gather(
            self.client.request_order_status_reports(self.types.account_id, self.types.spot, spot_id, open_only=True),
            self.client.request_order_status_reports(self.types.account_id, self.types.linear, perp_id, open_only=True),
        )
        if any(reports):
            raise CarryPairError("open Spot or Linear orders must be reconciled before pair execution")

    async def _perp_position_quantity(self, perp_id: Any) -> float:
        reports = await self.client.request_position_status_reports(
            self.types.account_id,
            self.types.linear,
            perp_id,
        )
        return sum(
            -float(str(report.quantity)) if report.is_short else float(str(report.quantity))
            for report in reports
            if not report.is_flat
        )

    async def _submit(
        self,
        instrument_id: Any,
        product_type: Any,
        client_order_id: Any,
        side: Any,
        quantity: Decimal,
        reduce_only: bool,
    ) -> Any:
        return await self.client.submit_order(
            self.types.account_id,
            product_type,
            instrument_id,
            client_order_id,
            side,
            self.types.market,
            self.types.quantity(quantity),
            time_in_force=self.types.ioc,
            reduce_only=reduce_only,
        )

    async def _wait_filled(
        self,
        instrument_id: Any,
        product_type: Any,
        client_order_id: Any,
    ) -> float:
        deadline = monotonic() + self.timeout_seconds
        filled = 0.0
        while monotonic() < deadline:
            reports, fills = await asyncio.gather(
                self.client.request_order_status_reports(
                    self.types.account_id,
                    product_type,
                    instrument_id,
                    open_only=False,
                ),
                self.client.request_fill_reports(
                    self.types.account_id,
                    product_type,
                    instrument_id,
                ),
            )
            report = next(
                (
                    item
                    for item in reports
                    if _identifier_value(item.client_order_id) == _identifier_value(client_order_id)
                ),
                None,
            )
            fill_total = sum(
                float(str(item.last_qty))
                for item in fills
                if _identifier_value(item.client_order_id) == _identifier_value(client_order_id)
            )
            filled = max(filled, fill_total)
            if report is not None:
                filled = max(filled, float(str(report.filled_qty)))
                if not report.is_open:
                    return filled
            await asyncio.sleep(0.25)
        return filled

    async def _unwind(
        self,
        action: str,
        spot_id: Any,
        perp_id: Any,
        spot_quantity: Decimal,
        perp_quantity: Decimal,
        pair_id: str,
    ) -> dict[str, Any]:
        calls = []
        identifiers = []
        if spot_quantity > 0:
            identifier = self.types.client_order_id(f"{pair_id}-us")
            side = self.types.sell if action == "open" else self.types.buy
            calls.append(self._submit(spot_id, self.types.spot, identifier, side, spot_quantity, False))
            identifiers.append(("spot", spot_id, self.types.spot, identifier, spot_quantity))
        if perp_quantity > 0:
            identifier = self.types.client_order_id(f"{pair_id}-up")
            side = self.types.buy if action == "open" else self.types.sell
            calls.append(self._submit(perp_id, self.types.linear, identifier, side, perp_quantity, action == "open"))
            identifiers.append(("perp", perp_id, self.types.linear, identifier, perp_quantity))
        if calls:
            await asyncio.gather(*calls, return_exceptions=True)
        result: dict[str, Any] = {}
        complete = True
        for name, instrument_id, product_type, identifier, expected in identifiers:
            result[name] = await self._wait_filled(instrument_id, product_type, identifier)
            complete = complete and abs(result[name] - float(expected)) <= max(float(expected) * 1e-9, 1e-12)
        result["complete"] = complete
        return result


def _identifier_value(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


def write_pair_status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


async def run(options: CarryPairOptions) -> int:
    result: dict[str, Any] = {"environment": "demo", "action": options.action, "orders_requested": False}
    client = None
    try:
        validate_pair_confirmation(options.confirmation)
        api_key = os.getenv("BYBIT_DEMO_API_KEY")
        api_secret = os.getenv("BYBIT_DEMO_API_SECRET")
        if not api_key or not api_secret:
            raise CarryPairError("BYBIT_DEMO_API_KEY and BYBIT_DEMO_API_SECRET are required")
        platform = yaml.safe_load(options.config_path.read_text(encoding="utf-8")) or {}
        config = platform.get("carry_runtime", {})
        client = create_demo_client(api_key, api_secret)
        result["orders_requested"] = True
        result.update(
            await CarryPairExecutor(client, CarryPairTypes(), config, options.timeout_seconds).execute(options.action)
        )
        return_code = 0
    except Exception as exc:
        result.update({"status": "failed", "error_type": type(exc).__name__, "error": str(exc)})
        return_code = 2
    finally:
        if client is not None:
            client.cancel_all_requests()
        write_pair_status(options.status_path, result)
        print(json.dumps(result, indent=2, sort_keys=True))
    return return_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Open or close one strictly gated Bybit Demo carry pair")
    parser.add_argument("action", choices=("open", "close"))
    parser.add_argument("--config", type=Path, default=Path("configs/demo/platform.yaml"))
    parser.add_argument("--status-path", type=Path, default=Path("data/runtime/carry-pair.json"))
    parser.add_argument("--timeout-seconds", type=float, default=12.0)
    args = parser.parse_args()
    return asyncio.run(
        run(
            CarryPairOptions(
                action=args.action,
                config_path=args.config,
                status_path=args.status_path,
                confirmation=os.getenv("BYBIT_DEMO_CARRY_CONFIRMATION"),
                timeout_seconds=args.timeout_seconds,
            )
        )
    )


if __name__ == "__main__":
    sys.exit(main())
