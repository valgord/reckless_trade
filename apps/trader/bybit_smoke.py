from __future__ import annotations

import os
import sys


def main() -> int:
    missing = [name for name in ("BYBIT_DEMO_API_KEY", "BYBIT_DEMO_API_SECRET") if not os.getenv(name)]
    if missing:
        print("Bybit Demo credentials are not configured:", ", ".join(missing))
        return 2
    try:
        from nautilus_trader.adapters.bybit import BybitEnvironment, BybitProductType
    except Exception as exc:
        print(f"NautilusTrader import failed: {exc}")
        return 3
    print("NautilusTrader import OK")
    print("Environment:", BybitEnvironment.DEMO)
    print("Product:", BybitProductType.SPOT)
    print("Instrument target: BTCUSDT-SPOT.BYBIT")
    print("Credentials found. Ready for live adapter wiring/reconciliation smoke test.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
