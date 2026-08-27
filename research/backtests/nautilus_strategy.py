from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import yaml
from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy

from apps.trader.demo_strategy import DemoDecisionEngine
from domain.models import Bar as DomainBar
from domain.models import InstrumentKey


class DomainPipelineBacktestConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType
    platform_config_path: str
    trade_notional: Decimal = Decimal("1000")
    enabled_strategies: tuple[str, ...] = ()
    min_hold_bars: int = 0
    allowed_regimes: tuple[str, ...] = ()
    regime_entry_bars: int = 1


class DomainPipelineBacktestStrategy(Strategy):
    """Long-only BacktestNode adapter for the engine-independent strategy pipeline."""

    def __init__(self, config: DomainPipelineBacktestConfig) -> None:
        super().__init__(config)
        raw = yaml.safe_load(Path(config.platform_config_path).read_text(encoding="utf-8")) or {}
        if config.enabled_strategies:
            for name, values in raw.get("strategies", {}).items():
                values["enabled"] = name in config.enabled_strategies
        raw_symbol = config.instrument_id.symbol.value.split("-", 1)[0]
        key = InstrumentKey(config.instrument_id.venue.value, raw_symbol)
        self.engine = DemoDecisionEngine(raw, key)
        self.instrument = None
        self.bars_since_trade = config.min_hold_bars
        self.allowed_regime_streak = 0

    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.config.instrument_id)
        if self.instrument is None:
            self.log.error(f"Could not find instrument for {self.config.instrument_id}")
            self.stop()
            return
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: Bar) -> None:
        if self.instrument is None:
            return
        decision = self.engine.on_bar(
            DomainBar(
                instrument=self.engine.instrument,
                ts_event=datetime.fromtimestamp(bar.ts_event / 1_000_000_000, tz=UTC),
                open=float(str(bar.open)),
                high=float(str(bar.high)),
                low=float(str(bar.low)),
                close=float(str(bar.close)),
                volume=float(str(bar.volume)),
            )
        )
        target = float(decision["target_weights"].get(self.engine.instrument.canonical, 0.0))
        regime_allowed = not self.config.allowed_regimes or decision["regime"] in self.config.allowed_regimes
        self.allowed_regime_streak = self.allowed_regime_streak + 1 if regime_allowed else 0
        if not regime_allowed or self.allowed_regime_streak < self.config.regime_entry_bars:
            target = 0.0
        if (
            target > 0
            and self.portfolio.is_flat(self.config.instrument_id)
            and self.bars_since_trade >= self.config.min_hold_bars
        ):
            quantity = self.instrument.make_qty(self.config.trade_notional / bar.close.as_decimal())
            if quantity <= 0:
                return
            order = self.order_factory.market(
                instrument_id=self.config.instrument_id,
                order_side=OrderSide.BUY,
                quantity=quantity,
                time_in_force=TimeInForce.IOC,
            )
            self.submit_order(order)
            self.bars_since_trade = 0
        elif (
            target == 0
            and self.portfolio.is_net_long(self.config.instrument_id)
            and (not regime_allowed or self.bars_since_trade >= self.config.min_hold_bars)
        ):
            self.close_all_positions(self.config.instrument_id, time_in_force=TimeInForce.IOC)
            self.bars_since_trade = 0
        else:
            self.bars_since_trade += 1

    def on_stop(self) -> None:
        self.cancel_all_orders(self.config.instrument_id)
        self.unsubscribe_bars(self.config.bar_type)
