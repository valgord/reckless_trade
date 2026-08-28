from __future__ import annotations

from pathlib import Path
from typing import Any

from apps.trader.demo_strategy import write_runtime_status
from trading.execution.carry import (
    CarryAccountSnapshot,
    CarryExecutionGuard,
    CarryGuardConfig,
    CarryOwnership,
    read_carry_ownership,
)


def build_carry_observer_strategy(platform_config: dict[str, Any]):
    from nautilus_trader.config import StrategyConfig
    from nautilus_trader.model.data import QuoteTick
    from nautilus_trader.model.identifiers import InstrumentId
    from nautilus_trader.model.objects import Currency
    from nautilus_trader.trading.strategy import Strategy

    runtime = platform_config.get("carry_runtime", {})
    spot_text = str(runtime.get("spot_instrument", "BTCUSDT-SPOT.BYBIT"))
    perp_text = str(runtime.get("perp_instrument", "BTCUSDT-LINEAR.BYBIT"))
    guard_config = CarryGuardConfig(
        target_notional_usdt=float(runtime.get("target_notional_usdt", 10)),
        minimum_free_reserve_usdt=float(runtime.get("minimum_free_reserve_usdt", 10)),
        maintenance_margin_rate=float(runtime.get("maintenance_margin_rate", 0.05)),
        minimum_margin_ratio=float(runtime.get("minimum_margin_ratio", 3.0)),
        maximum_quantity_mismatch_fraction=float(runtime.get("maximum_quantity_mismatch_fraction", 0.02)),
    )

    class CarryObserverConfig(StrategyConfig, frozen=True):
        spot_instrument_id: InstrumentId
        perp_instrument_id: InstrumentId
        status_path: str
        ownership_path: str

    class CarryObserverStrategy(Strategy):
        def __init__(self, config: CarryObserverConfig) -> None:
            super().__init__(config)
            self.guard = CarryExecutionGuard(guard_config, spot_text, perp_text)
            self.status_path = Path(config.status_path)
            self.ownership_path = Path(config.ownership_path)
            self.ownership = CarryOwnership()
            self.prices: dict[str, float] = {}
            self.reconciliation_complete = False
            self.minimum_quantity = 0.0
            self.quantity_increment = 0.0

        def on_start(self) -> None:
            try:
                self.ownership = read_carry_ownership(self.ownership_path)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self._write_status("blocked", {"reasons": [f"invalid ownership ledger: {type(exc).__name__}"]})
                self.stop()
                return
            missing = [
                str(instrument_id)
                for instrument_id in (self.config.spot_instrument_id, self.config.perp_instrument_id)
                if self.cache.instrument(instrument_id) is None
            ]
            if missing:
                self._write_status("blocked", {"reasons": [f"missing instruments: {', '.join(missing)}"]})
                self.stop()
                return
            instruments = (
                self.cache.instrument(self.config.spot_instrument_id),
                self.cache.instrument(self.config.perp_instrument_id),
            )
            self.minimum_quantity = max(
                (float(str(instrument.min_quantity)) if instrument.min_quantity is not None else 0.0)
                for instrument in instruments
            )
            self.quantity_increment = max(
                (float(str(instrument.size_increment)) if instrument.size_increment is not None else 0.0)
                for instrument in instruments
            )
            self.reconciliation_complete = True
            self.subscribe_quote_ticks(self.config.spot_instrument_id)
            self.subscribe_quote_ticks(self.config.perp_instrument_id)
            self._evaluate()

        def on_quote_tick(self, tick: QuoteTick) -> None:
            self.prices[str(tick.instrument_id)] = (float(str(tick.bid_price)) + float(str(tick.ask_price))) / 2
            self._evaluate()

        def on_stop(self) -> None:
            self.unsubscribe_quote_ticks(self.config.spot_instrument_id)
            self.unsubscribe_quote_ticks(self.config.perp_instrument_id)

        def _evaluate(self) -> None:
            account_btc_total = self._total_balance(Currency.from_str("BTC"))
            ownership_covered = account_btc_total + 1e-12 >= self.ownership.spot_quantity
            spot_quantity = self.ownership.spot_quantity
            perp_quantity = self._position_quantity(self.config.perp_instrument_id)
            free_usdt = self._free_balance(Currency.from_str("USDT"))
            snapshot = CarryAccountSnapshot(
                reconciliation_complete=self.reconciliation_complete and ownership_covered,
                spot_quantity=spot_quantity,
                perp_quantity=perp_quantity,
                spot_price=self.prices.get(spot_text),
                perp_price=self.prices.get(perp_text),
                free_usdt=free_usdt,
                open_orders=len(self.cache.orders_open(venue=self.config.spot_instrument_id.venue)),
                minimum_quantity=self.minimum_quantity,
                quantity_increment=self.quantity_increment,
            )
            decision = self.guard.evaluate(snapshot)
            self._write_status(decision.phase.value, decision.as_dict(), snapshot, account_btc_total)

        def _position_quantity(self, instrument_id: InstrumentId) -> float:
            return sum(float(position.signed_qty) for position in self.cache.positions(instrument_id=instrument_id))

        def _free_balance(self, currency: Currency) -> float:
            values = []
            for account in self.cache.accounts():
                balance = account.balance_free(currency)
                if balance is not None:
                    values.append(balance.as_double())
            return max(values, default=0.0)

        def _total_balance(self, currency: Currency) -> float:
            values = []
            for account in self.cache.accounts():
                balance = account.balance_total(currency)
                if balance is not None:
                    values.append(balance.as_double())
            return max(values, default=0.0)

        def _write_status(
            self,
            status: str,
            decision: dict[str, Any],
            snapshot: CarryAccountSnapshot | None = None,
            account_btc_total: float | None = None,
        ) -> None:
            write_runtime_status(
                self.status_path,
                {
                    "status": status,
                    "mode": "demo",
                    "strategy": "delta_neutral_carry_observer",
                    "orders_enabled": False,
                    "execution_gate": "locked",
                    "spot_instrument": spot_text,
                    "perp_instrument": perp_text,
                    "reconciliation_complete": (
                        snapshot.reconciliation_complete if snapshot else self.reconciliation_complete
                    ),
                    "ownership": {
                        "spot_quantity": self.ownership.spot_quantity,
                        "perp_quantity": self.ownership.perp_quantity,
                        "ledger_path": str(self.ownership_path),
                    },
                    "account_btc_total": account_btc_total,
                    "snapshot": {
                        "spot_quantity": snapshot.spot_quantity,
                        "perp_quantity": snapshot.perp_quantity,
                        "spot_price": snapshot.spot_price,
                        "perp_price": snapshot.perp_price,
                        "free_usdt": snapshot.free_usdt,
                        "open_orders": snapshot.open_orders,
                        "minimum_quantity": snapshot.minimum_quantity,
                        "quantity_increment": snapshot.quantity_increment,
                    }
                    if snapshot
                    else None,
                    "guard": decision,
                    "updated_at": self._clock.utc_now().isoformat(),
                },
            )

    return CarryObserverStrategy(
        CarryObserverConfig(
            spot_instrument_id=InstrumentId.from_str(spot_text),
            perp_instrument_id=InstrumentId.from_str(perp_text),
            status_path=str(runtime.get("status_path", "data/runtime/carry-observer.json")),
            ownership_path=str(runtime.get("ownership_path", "data/runtime/carry-ownership.json")),
        )
    )
