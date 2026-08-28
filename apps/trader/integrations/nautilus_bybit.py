from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Any


def build_bybit_client_configs(mode: str, instrument_ids: Iterable[str]):
    """Build the pinned Nautilus Bybit client configs without creating network clients."""
    if mode not in {"demo", "live"}:
        raise ValueError(f"Bybit live clients do not support mode {mode!r}")
    if mode == "live" and os.getenv("ALLOW_LIVE_TRADING", "false").lower() != "true":
        raise RuntimeError("Live trading is locked. Set ALLOW_LIVE_TRADING=true explicitly.")

    instrument_ids = tuple(instrument_ids)
    api_key_name = "BYBIT_DEMO_API_KEY" if mode == "demo" else "BYBIT_API_KEY"
    api_secret_name = "BYBIT_DEMO_API_SECRET" if mode == "demo" else "BYBIT_API_SECRET"
    api_key, api_secret = os.getenv(api_key_name), os.getenv(api_secret_name)
    if not api_key or not api_secret:
        raise RuntimeError(f"Missing {api_key_name}/{api_secret_name}")

    from nautilus_trader.adapters.bybit import (
        BybitDataClientConfig,
        BybitEnvironment,
        BybitExecClientConfig,
        BybitProductType,
    )
    from nautilus_trader.config import InstrumentProviderConfig
    from nautilus_trader.core import nautilus_pyo3
    from nautilus_trader.model.identifiers import InstrumentId

    environment = BybitEnvironment.DEMO if mode == "demo" else BybitEnvironment.MAINNET
    provider = InstrumentProviderConfig(
        load_ids=frozenset(InstrumentId.from_str(value) for value in instrument_ids),
    )
    product_types = []
    if any("-SPOT." in value for value in instrument_ids):
        product_types.append(BybitProductType.SPOT)
    if any("-LINEAR." in value for value in instrument_ids):
        product_types.append(BybitProductType.LINEAR)
    supported = all("-SPOT." in value or "-LINEAR." in value for value in instrument_ids)
    if not product_types or not supported:
        raise ValueError("Bybit instruments must use a supported SPOT or LINEAR product suffix")

    common = {
        "api_key": api_key,
        "api_secret": api_secret,
        "environment": environment,
        "instrument_provider": provider,
        "product_types": tuple(product_types),
    }
    execution = {}
    linear_symbols = [value.split(".", 1)[0] for value in instrument_ids if "-LINEAR." in value]
    if linear_symbols:
        execution = {
            "futures_leverages": {symbol: 1 for symbol in linear_symbols},
            "position_mode": {symbol: nautilus_pyo3.BybitPositionMode.MERGED_SINGLE for symbol in linear_symbols},
            "margin_mode": nautilus_pyo3.BybitMarginMode.ISOLATED_MARGIN,
        }
    return BybitDataClientConfig(**common), BybitExecClientConfig(**common, **execution)


def build_bybit_trading_node(
    mode: str = "demo",
    instrument_ids: Iterable[str] = ("BTCUSDT-SPOT.BYBIT",),
    *,
    strategies: Iterable[Any] = (),
    risk: dict[str, Any] | None = None,
):
    """Build a Bybit TradingNode with startup reconciliation enabled."""
    from nautilus_trader.adapters.bybit import BYBIT, BybitLiveDataClientFactory, BybitLiveExecClientFactory
    from nautilus_trader.common.config import LoggingConfig
    from nautilus_trader.live.config import LiveExecEngineConfig, LiveRiskEngineConfig
    from nautilus_trader.live.node import TradingNode, TradingNodeConfig

    instrument_ids = tuple(instrument_ids)
    data_config, exec_config = build_bybit_client_configs(mode, instrument_ids)
    risk = risk or {}
    max_notional = int(risk.get("max_order_notional_usdt", 10))
    if max_notional <= 0:
        raise ValueError("max_order_notional_usdt must be positive")
    config = TradingNodeConfig(
        data_clients={BYBIT: data_config},
        exec_clients={BYBIT: exec_config},
        exec_engine=LiveExecEngineConfig(
            reconciliation=True,
            generate_missing_orders=True,
            open_check_open_only=True,
        ),
        risk_engine=LiveRiskEngineConfig(
            bypass=False,
            max_order_submit_rate=str(risk.get("max_order_submit_rate", "1/00:01:00")),
            max_order_modify_rate=str(risk.get("max_order_modify_rate", "2/00:01:00")),
            max_notional_per_order={instrument_id: max_notional for instrument_id in instrument_ids},
        ),
        logging=LoggingConfig(log_level=os.getenv("NAUTILUS_LOG_LEVEL", "WARNING")),
    )
    node = TradingNode(config=config)
    for strategy in strategies:
        node.trader.add_strategy(strategy)
    node.add_data_client_factory(BYBIT, BybitLiveDataClientFactory)
    node.add_exec_client_factory(BYBIT, BybitLiveExecClientFactory)
    node.build()
    return node
