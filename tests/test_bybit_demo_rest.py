from __future__ import annotations

import hashlib
import hmac

from apps.trader.bybit_demo_rest import sign_bybit_query


def test_bybit_signature_uses_documented_payload_order() -> None:
    payload = "1710000000000demo-key5000category=linear&symbol=BTCUSDT"
    expected = hmac.new(b"demo-secret", payload.encode(), hashlib.sha256).hexdigest()

    assert (
        sign_bybit_query(
            "demo-secret",
            1_710_000_000_000,
            "demo-key",
            5_000,
            "category=linear&symbol=BTCUSDT",
        )
        == expected
    )
