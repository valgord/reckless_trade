from __future__ import annotations

import os

import structlog

from platform_core.logging import configure_logging
from platform_core.settings import load_settings


def main() -> None:
    configure_logging()
    log = structlog.get_logger("trader")
    settings = load_settings()
    log.info("trader_boot", mode=settings.mode, venue=settings.venue, instruments=settings.instruments,
             numeraire=settings.numeraire)
    if settings.mode in {"demo", "live"} and os.getenv("RUN_NAUTILUS_NODE", "false").lower() == "true":
        from apps.trader.integrations.nautilus_bybit import build_bybit_trading_node

        node = build_bybit_trading_node(settings.mode)
        log.info("nautilus_node_built", mode=settings.mode)
        node.run()
    else:
        log.info("nautilus_node_disabled", hint="Set RUN_NAUTILUS_NODE=true after credentials/config smoke tests")


if __name__ == "__main__":
    main()
