from __future__ import annotations

import asyncio
import os
from datetime import UTC

import httpx
import structlog

from intelligence.news.dedup import fingerprint
from intelligence.news.rss import fetch_feed
from platform_core.logging import configure_logging


async def process_once(seen: set[str]) -> int:
    urls = [item.strip() for item in os.getenv("NEWS_RSS_URLS", "").split(",") if item.strip()]
    if not urls:
        return 0
    endpoint = os.getenv("INTELLIGENCE_URL", "http://intelligence:8010/analyse")
    processed = 0
    async with httpx.AsyncClient(timeout=90) as client:
        for url in urls:
            for item in await asyncio.to_thread(fetch_feed, url):
                key = fingerprint(item.title, item.body)
                if key in seen:
                    continue
                payload = {
                    "source": item.source,
                    "title": item.title,
                    "body": item.body,
                    "published_at": item.published_at.astimezone(UTC).isoformat(),
                }
                response = await client.post(endpoint, json=payload)
                response.raise_for_status()
                seen.add(key)
                processed += 1
    return processed


async def run() -> None:
    configure_logging()
    log = structlog.get_logger("news-worker")
    seen: set[str] = set()
    interval = int(os.getenv("NEWS_POLL_SECONDS", "60"))
    while True:
        try:
            count = await process_once(seen) if os.getenv("NEWS_ENABLED", "false").lower() == "true" else 0
            if count:
                log.info("news_processed", count=count)
        except Exception:
            log.exception("news_poll_failed")
        await asyncio.sleep(interval)


if __name__ == "__main__":
    asyncio.run(run())
