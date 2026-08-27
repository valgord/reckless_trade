from __future__ import annotations

import os


def build_bybit_trading_node(mode: str = "demo"):
    """Build the official Nautilus Bybit TradingNode. Imports are lazy so research/tests do not require Nautilus."""
    from nautilus_trader.adapters.bybit import BYBIT
    from nautilus_trader.adapters.bybit import BybitEnvironment
    from nautilus_trader.adapters.bybit import BybitLiveDataClientFactory
    from nautilus_trader.adapters.bybit import BybitLiveExecClientFactory
    from nautilus_trader.adapters.bybit import BybitProductType
    from nautilus_trader.live.node import TradingNode
    from nautilus_trader.live.node import TradingNodeConfig

    environment = BybitEnvironment.DEMO if mode == "demo" else BybitEnvironment.MAINNET
    api_key_name = "BYBIT_DEMO_API_KEY" if mode == "demo" else "BYBIT_API_KEY"
    api_secret_name = "BYBIT_DEMO_API_SECRET" if mode == "demo" else "BYBIT_API_SECRET"
    api_key, api_secret = os.getenv(api_key_name), os.getenv(api_secret_name)
    if not api_key or not api_secret:
        raise RuntimeError(f"Missing {api_key_name}/{api_secret_name}")
    client = {
        "api_key": api_key,
        "api_secret": api_secret,
        "base_url_http": None,
        "environment": environment,
        "product_types": [BybitProductType.SPOT],
    }
    config = TradingNodeConfig(data_clients={BYBIT: dict(client)}, exec_clients={BYBIT: dict(client)})
    node = TradingNode(config=config)
    node.add_data_client_factory(BYBIT, BybitLiveDataClientFactory)
    node.add_exec_client_factory(BYBIT, BybitLiveExecClientFactory)
    node.build()
    return node
