from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import feedparser
import httpx


@dataclass(frozen=True, slots=True)
class NewsItem:
    source: str
    title: str
    body: str
    url: str
    published_at: datetime
    raw: dict[str, Any]


class FeedFetchError(RuntimeError):
    pass


def fetch_feed(url: str, timeout: float = 20.0) -> list[NewsItem]:
    response = httpx.get(
        url,
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": "reckless-trade-news-ingestion/0.1"},
    )
    response.raise_for_status()
    feed = feedparser.parse(response.content)
    if feed.bozo and not feed.entries:
        raise FeedFetchError(type(feed.bozo_exception).__name__)
    source = str(feed.feed.get("title", url))
    items: list[NewsItem] = []
    for entry in feed.entries:
        published = datetime.now(UTC)
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        if parsed:
            published = datetime(*parsed[:6], tzinfo=UTC)
        items.append(
            NewsItem(
                source=source,
                title=str(entry.get("title", "")),
                body=str(entry.get("summary", entry.get("description", ""))),
                url=str(entry.get("link", "")),
                published_at=published,
                raw=dict(entry),
            )
        )
    return items
