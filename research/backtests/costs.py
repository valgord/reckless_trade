from __future__ import annotations

from decimal import Decimal

from nautilus_trader.backtest.config import FeeModelConfig
from nautilus_trader.backtest.models import FeeModel
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.model.orders import Order


class AllInBpsFeeModelConfig(FeeModelConfig, frozen=True):
    total_bps: float


class AllInBpsFeeModel(FeeModel):
    """Charges configured fees, slippage and half-spread as one deterministic cost."""

    def __init__(self, config: AllInBpsFeeModelConfig) -> None:
        self.rate = Decimal(str(config.total_bps)) / Decimal("10000")

    def get_commission(
        self,
        order: Order,
        fill_qty: Quantity,
        fill_px: Price,
        instrument: Instrument,
    ) -> Money:
        del order
        notional = instrument.notional_value(fill_qty, fill_px, use_quote_for_inverse=False)
        return Money(notional.as_decimal() * self.rate, instrument.quote_currency)
