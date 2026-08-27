import json
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from apps.news_worker import main as news_worker
from intelligence.news.ingestion import DurableNewsState, RawNewsArchive


@pytest.mark.asyncio
async def test_failed_news_delivery_is_retried(monkeypatch, tmp_path):
    item = SimpleNamespace(
        source="source",
        title="title",
        body="body",
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
        url="https://feed.example/article",
        raw={"id": "article-1"},
    )

    monkeypatch.setenv("NEWS_RSS_URLS", "https://feed.example/rss")
    monkeypatch.setenv("INTELLIGENCE_URL", "https://intelligence.example/analyse")
    monkeypatch.setenv("NEWS_FORWARD_TO_INTELLIGENCE", "true")
    monkeypatch.setenv("NEWS_STORE_DATABASE", "false")
    monkeypatch.setattr(news_worker, "fetch_feed", lambda url: [item])

    async def run_inline(function, *args):
        return function(*args)

    monkeypatch.setattr(news_worker.asyncio, "to_thread", run_inline)

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
        await news_worker.process_once(seen, archive=RawNewsArchive(tmp_path / "news"))
    assert not seen
    assert await news_worker.process_once(seen, archive=RawNewsArchive(tmp_path / "news")) == 1
    assert len(seen) == 1


def test_raw_archive_preserves_provenance_and_is_idempotent(tmp_path):
    first_seen = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)
    item = SimpleNamespace(
        source="Example",
        title="Bitcoin update",
        body="Body",
        url="https://example.test/article",
        published_at=datetime(2026, 1, 2, 3, 0, tzinfo=UTC),
        raw={"guid": "abc"},
    )
    archive = RawNewsArchive(tmp_path / "news")

    first = archive.write(item, "fingerprint", "https://example.test/rss", first_seen)
    second = archive.write(item, "fingerprint", "https://example.test/rss", first_seen)
    payload = json.loads(first.read_text(encoding="utf-8"))

    assert first == second
    assert payload["feed_url"] == "https://example.test/rss"
    assert payload["article_url"] == item.url
    assert payload["first_seen_at"] == first_seen.isoformat()
    assert payload["raw_payload"] == {"guid": "abc"}


def test_durable_source_health_enforces_poll_interval(tmp_path):
    path = tmp_path / "state.json"
    now = datetime(2026, 1, 1, tzinfo=UTC)
    state = DurableNewsState.load(path)
    url = "https://example.test/rss"

    assert state.can_poll(url, now, timedelta(seconds=60))
    state.record_attempt(url, now)
    assert not state.can_poll(url, now, timedelta(seconds=60))
    state.record_success(url, now, fetched=3, ingested=2, duplicates=1)
    reloaded = DurableNewsState.load(path)

    assert reloaded.public_status()["sources"][0]["fetched_total"] == 3
    assert reloaded.public_status()["sources"][0]["rate_limited_total"] == 1
