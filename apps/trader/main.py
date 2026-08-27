from __future__ import annotations

import os
import signal
import threading

import structlog

from platform_core.logging import configure_logging
from platform_core.settings import load_settings


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
        if os.getenv("ENABLE_DEMO_STRATEGY", "false").lower() == "true":
            if settings.mode != "demo":
                raise RuntimeError("The Demo observer strategy cannot run outside Demo mode")
            from apps.trader.demo_strategy import build_demo_observer_strategy

            strategies.append(build_demo_observer_strategy(settings.raw))

        from apps.trader.integrations.nautilus_bybit import build_bybit_trading_node

        runtime = settings.raw.get("demo_runtime", {})
        node = build_bybit_trading_node(
            settings.mode,
            settings.instruments,
            strategies=strategies,
            risk=runtime.get("risk", {}),
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
