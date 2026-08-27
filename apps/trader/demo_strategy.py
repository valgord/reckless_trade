from __future__ import annotations

import json
from collections import deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from domain.models import Bar as DomainBar
from domain.models import InstrumentKey
from trading.alpha.models import PriceSeriesContext
from trading.regimes.simple import VolatilityTrendRegimeProvider
from trading.strategy.factory import build_alpha_models, build_pipeline


class DemoDecisionEngine:
    """Runs the engine-independent strategy pipeline for one Demo instrument."""

    def __init__(self, platform_config: dict[str, Any], instrument: InstrumentKey, max_bars: int = 500) -> None:
        self.instrument = instrument
        self.closes: deque[float] = deque(maxlen=max_bars)
        self.volumes: deque[float] = deque(maxlen=max_bars)
        self.alpha_models = build_alpha_models(platform_config)
        self.pipeline = build_pipeline(platform_config)
        regime = platform_config.get("regime", {})
        self.regime_provider = VolatilityTrendRegimeProvider(
            vol_high=float(regime.get("vol_high", 0.03)),
            trend_threshold=float(regime.get("trend_threshold", 0.02)),
        )
        self.numeraire = str(platform_config.get("objective", {}).get("numeraire", "BTC"))

    def on_bar(self, bar: DomainBar) -> dict[str, Any]:
        self.closes.append(bar.close)
        self.volumes.append(bar.volume)
        context = PriceSeriesContext(self.instrument, list(self.closes), list(self.volumes))
        signals = [signal for model in self.alpha_models for signal in model.generate(context)]
        regime = self.regime_provider.regime(context.returns)
        decision = self.pipeline.decide(signals, self.numeraire, regime)
        return {
            "accepted": decision.accepted,
            "bar_count": len(self.closes),
            "close": str(bar.close),
            "last_bar_at": bar.ts_event.isoformat(),
            "raw_signal_count": len(decision.raw_signals),
            "signal_sources": [signal.source for signal in decision.raw_signals],
            "aggregated_signal_count": len(decision.aggregated_signals),
            "regime": decision.regime.value,
            "risk_errors": list(decision.risk_errors),
            "target_weights": decision.target.weights,
        }


def write_runtime_status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def build_demo_observer_strategy(platform_config: dict[str, Any]):
    from nautilus_trader.config import PositiveInt, StrategyConfig
    from nautilus_trader.model.data import Bar, BarType
    from nautilus_trader.model.identifiers import InstrumentId
    from nautilus_trader.trading.strategy import Strategy

    trading = platform_config.get("trading", {})
    instruments = trading.get("instruments", [])
    if len(instruments) != 1:
        raise ValueError("Demo observer currently requires exactly one instrument")

    instrument_text = str(instruments[0])
    bar_spec = str(trading.get("bar_type", "15-MINUTE-LAST-EXTERNAL"))
    runtime = platform_config.get("demo_runtime", {})

    class DemoObserverConfig(StrategyConfig, frozen=True):
        instrument_id: InstrumentId
        bar_type: BarType
        status_path: str
        historical_days: PositiveInt = 2
        max_bars: PositiveInt = 500

    class DemoObserverStrategy(Strategy):
        def __init__(self, config: DemoObserverConfig) -> None:
            super().__init__(config)
            venue, symbol = instrument_text.rsplit(".", 1)
            self.engine = DemoDecisionEngine(
                platform_config,
                InstrumentKey(symbol, venue.split("-")[0]),
                max_bars=config.max_bars,
            )
            self.status_path = Path(config.status_path)

        def on_start(self) -> None:
            instrument = self.cache.instrument(self.config.instrument_id)
            if instrument is None:
                self.log.error(f"Could not find instrument for {self.config.instrument_id}")
                self.stop()
                return
            write_runtime_status(
                self.status_path,
                {
                    "status": "running",
                    "mode": "demo",
                    "orders_enabled": False,
                    "strategy": "domain_pipeline_observer",
                    "instrument": instrument_text,
                    "bar_type": str(self.config.bar_type),
                    "awaiting_bars": True,
                    "started_at": self._clock.utc_now().isoformat(),
                },
            )
            self.request_bars(
                self.config.bar_type,
                start=self._clock.utc_now() - timedelta(days=self.config.historical_days),
                callback=lambda _: self.subscribe_bars(self.config.bar_type),
            )

        def on_bar(self, bar: Bar) -> None:
            self._process_bar(bar, source="live")

        def on_historical_data(self, data: Any) -> None:
            if isinstance(data, Bar):
                self._process_bar(data, source="historical")

        def _process_bar(self, bar: Bar, source: str) -> None:
            ts_event = datetime.fromtimestamp(bar.ts_event / 1_000_000_000, tz=UTC)
            result = self.engine.on_bar(
                DomainBar(
                    instrument=self.engine.instrument,
                    ts_event=ts_event,
                    open=float(str(bar.open)),
                    high=float(str(bar.high)),
                    low=float(str(bar.low)),
                    close=float(str(bar.close)),
                    volume=float(str(bar.volume)),
                )
            )
            write_runtime_status(
                self.status_path,
                {
                    "status": "running",
                    "mode": "demo",
                    "orders_enabled": False,
                    "strategy": "domain_pipeline_observer",
                    "instrument": instrument_text,
                    "bar_type": str(self.config.bar_type),
                    "awaiting_bars": False,
                    "bar_source": source,
                    "decision": result,
                },
            )

        def on_stop(self) -> None:
            self.unsubscribe_bars(self.config.bar_type)

    return DemoObserverStrategy(
        DemoObserverConfig(
            instrument_id=InstrumentId.from_str(instrument_text),
            bar_type=BarType.from_str(f"{instrument_text}-{bar_spec}"),
            status_path=str(runtime.get("status_path", "data/runtime/demo-strategy.json")),
            historical_days=int(runtime.get("historical_days", 2)),
            max_bars=int(runtime.get("max_bars", 500)),
        )
    )
