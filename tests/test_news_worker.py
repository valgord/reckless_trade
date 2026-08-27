import asyncio
from contextlib import suppress
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx

from apps.news_worker import main as news_worker


def test_failed_news_delivery_is_retried(monkeypatch):
    item = SimpleNamespace(
        source="source",
        title="title",
        body="body",
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    monkeypatch.setenv("NEWS_RSS_URLS", "https://feed.example/rss")
    monkeypatch.setenv("INTELLIGENCE_URL", "https://intelligence.example/analyse")
    monkeypatch.setattr(news_worker, "fetch_feed", lambda url: [item])

    class FakeResponse:
        def __init__(self, failed):
            self.failed = failed

        def raise_for_status(self):
            if self.failed:
                raise httpx.HTTPError("temporary failure")

    class FakeClient:
        attempts = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, endpoint, json):
            self.attempts += 1
            return FakeResponse(self.attempts == 1)

    client = FakeClient()
    monkeypatch.setattr(news_worker.httpx, "AsyncClient", lambda timeout: client)
    seen = set()

    with suppress(httpx.HTTPError):
        asyncio.run(news_worker.process_once(seen))
    assert not seen
    assert asyncio.run(news_worker.process_once(seen)) == 1
    assert len(seen) == 1