from __future__ import annotations

import os
import signal
import threading

import structlog

from platform_core.logging import configure_logging
from platform_core.settings import load_settings


def runtime_risk_config(platform_config: dict, carry_enabled: bool) -> dict:
    risk = dict(platform_config.get("demo_runtime", {}).get("risk", {}))
    if carry_enabled:
        risk.update(platform_config.get("carry_runtime", {}).get("risk", {}))
    return risk


def main() -> None:
    configure_logging()
    log = structlog.get_logger("trader")
    settings = load_settings()
    log.info(
        "trader_boot",
        mode=settings.mode,
        venue=settings.venue,
        instruments=settings.instruments,
        numeraire=settings.numeraire,
    )
    if settings.mode in {"demo", "live"} and os.getenv("RUN_NAUTILUS_NODE", "false").lower() == "true":
        strategies = []
        instrument_ids = list(settings.instruments)
        if os.getenv("ENABLE_DEMO_STRATEGY", "false").lower() == "true":
            if settings.mode != "demo":
                raise RuntimeError("The Demo observer strategy cannot run outside Demo mode")
            from apps.trader.demo_strategy import build_demo_observer_strategy

            strategies.append(build_demo_observer_strategy(settings.raw))
        if os.getenv("ENABLE_CARRY_OBSERVER", "false").lower() == "true":
            if settings.mode != "demo":
                raise RuntimeError("The carry observer cannot run outside Demo mode")
            from apps.trader.carry_observer import build_carry_observer_strategy

            carry_runtime = settings.raw.get("carry_runtime", {})
            carry_instruments = (
                str(carry_runtime.get("spot_instrument", "BTCUSDT-SPOT.BYBIT")),
                str(carry_runtime.get("perp_instrument", "BTCUSDT-LINEAR.BYBIT")),
            )
            instrument_ids.extend(value for value in carry_instruments if value not in instrument_ids)
            strategies.append(build_carry_observer_strategy(settings.raw))

        from apps.trader.integrations.nautilus_bybit import build_bybit_trading_node

        carry_enabled = os.getenv("ENABLE_CARRY_OBSERVER", "false").lower() == "true"
        risk_config = runtime_risk_config(settings.raw, carry_enabled)
        node = build_bybit_trading_node(
            settings.mode,
            instrument_ids,
            strategies=strategies,
            risk=risk_config,
        )
        log.info("nautilus_node_built", mode=settings.mode, strategy_count=len(strategies))
        node.run()
    else:
        log.info("nautilus_node_disabled", hint="Set RUN_NAUTILUS_NODE=true after credentials/config smoke tests")
        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        stop.wait()


if __name__ == "__main__":
    main()
