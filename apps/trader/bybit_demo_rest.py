from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any
from urllib.parse import urlencode

import httpx

BYBIT_DEMO_REST_URL = "https://api-demo.bybit.com"


class BybitDemoRestError(RuntimeError):
    pass


def sign_bybit_query(api_secret: str, timestamp_ms: int, api_key: str, recv_window_ms: int, query: str) -> str:
    payload = f"{timestamp_ms}{api_key}{recv_window_ms}{query}"
    return hmac.new(api_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


class BybitDemoReadClient:
    """Small GET-only client for Demo endpoints not exposed by the Nautilus adapter."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        base_url: str = BYBIT_DEMO_REST_URL,
        recv_window_ms: int = 5_000,
        timeout_seconds: float = 20.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.recv_window_ms = recv_window_ms
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(base_url=base_url, timeout=timeout_seconds)

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def get_public(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        response = await self.client.get(path, params=params)
        return self._validated(response)

    async def get_private(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        query = urlencode(sorted((key, str(value)) for key, value in params.items() if value is not None))
        timestamp_ms = int(time.time() * 1_000)
        headers = {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-TIMESTAMP": str(timestamp_ms),
            "X-BAPI-RECV-WINDOW": str(self.recv_window_ms),
            "X-BAPI-SIGN": sign_bybit_query(
                self.api_secret,
                timestamp_ms,
                self.api_key,
                self.recv_window_ms,
                query,
            ),
        }
        response = await self.client.get(f"{path}?{query}", headers=headers)
        return self._validated(response)

    async def get_private_pages(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        cursor = None
        while True:
            payload = await self.get_private(path, {**params, "cursor": cursor})
            result = payload.get("result", {})
            rows.extend(result.get("list", []))
            next_cursor = result.get("nextPageCursor")
            if not next_cursor or next_cursor == cursor:
                return rows
            cursor = next_cursor

    @staticmethod
    def _validated(response: httpx.Response) -> dict[str, Any]:
        response.raise_for_status()
        payload = response.json()
        if int(payload.get("retCode", -1)) != 0:
            raise BybitDemoRestError(f"Bybit Demo returned {payload.get('retCode')}: {payload.get('retMsg')}")
        return payload
