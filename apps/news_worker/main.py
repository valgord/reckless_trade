from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import structlog

from intelligence.news.dedup import fingerprint
from intelligence.news.ingestion import DurableNewsState, RawNewsArchive
from intelligence.news.rss import fetch_feed
from platform_core.logging import configure_logging
from storage.repositories import AuditRepository


async def process_once(
    seen: set[str],
    state: DurableNewsState | None = None,
    repository: Any | None = None,
    archive: RawNewsArchive | None = None,
    now: datetime | None = None,
) -> int:
    urls = [item.strip() for item in os.getenv("NEWS_RSS_URLS", "").split(",") if item.strip()]
    if not urls:
        return 0
    now = (now or datetime.now(UTC)).astimezone(UTC)
    minimum_interval = timedelta(seconds=max(int(os.getenv("NEWS_SOURCE_MIN_POLL_SECONDS", "60")), 1))
    endpoint = os.getenv("INTELLIGENCE_URL", "http://intelligence:8010/analyse")
    forward = os.getenv("NEWS_FORWARD_TO_INTELLIGENCE", "false").lower() == "true"
    store_database = os.getenv("NEWS_STORE_DATABASE", "false").lower() == "true"
    repository = repository or (AuditRepository() if store_database else None)
    archive = archive or RawNewsArchive(Path(os.getenv("NEWS_ARCHIVE_PATH", "data/news")))
    processed = 0

    async with httpx.AsyncClient(timeout=90) as client:
        for url in urls:
            if state and not state.can_poll(url, now, minimum_interval):
                continue
            if state:
                state.record_attempt(url, now)
            ingested = duplicates = 0
            try:
                items = await asyncio.to_thread(fetch_feed, url)
                for item in items:
                    key = fingerprint(item.title, item.body)
                    if key in seen:
                        duplicates += 1
                        continue
                    first_seen_at = datetime.now(UTC)
                    archive_path = archive.write(item, key, url, first_seen_at)
                    article_id = None
                    if repository is not None:
                        article_id = await repository.save_news(
                            source=item.source,
                            title=item.title,
                            body=item.body,
                            published_at=item.published_at,
                            first_seen_at=first_seen_at,
                            raw_metadata={
                                "url": item.url,
                                "feed_url": url,
                                "archive_path": str(archive_path),
                                "fingerprint": key,
                            },
                        )
                    if forward:
                        response = await client.post(
                            endpoint,
                            json={
                                "article_id": article_id,
                                "source": item.source,
                                "title": item.title,
                                "body": item.body,
                                "url": item.url,
                                "published_at": item.published_at.astimezone(UTC).isoformat(),
                                "first_seen_at": first_seen_at.isoformat(),
                                "raw_metadata": {"feed_url": url, "archive_path": str(archive_path)},
                            },
                        )
                        response.raise_for_status()
                    seen.add(key)
                    if state:
                        state.mark_delivered(key)
                    ingested += 1
                    processed += 1
                if state:
                    state.record_success(url, datetime.now(UTC), len(items), ingested, duplicates)
            except Exception as exc:
                if state:
                    state.record_failure(url, datetime.now(UTC), exc)
                continue
    return processed


async def run() -> None:
    configure_logging()
    log = structlog.get_logger("news-worker")
    state = DurableNewsState.load(Path(os.getenv("NEWS_STATE_PATH", "data/runtime/news-worker-state.json")))
    seen = set(state.delivered)
    interval = int(os.getenv("NEWS_POLL_SECONDS", "60"))
    while True:
        try:
            count = await process_once(seen, state=state) if os.getenv("NEWS_ENABLED", "false").lower() == "true" else 0
            if count:
                log.info("news_ingested", count=count)
        except Exception:
            log.exception("news_poll_failed")
        await asyncio.sleep(interval)


if __name__ == "__main__":
    asyncio.run(run())
