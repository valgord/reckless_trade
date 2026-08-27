from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import feedparser


@dataclass(frozen=True, slots=True)
class NewsItem:
    source: str
    title: str
    body: str
    url: str
    published_at: datetime
    raw: dict[str, Any]


def fetch_feed(url: str) -> list[NewsItem]:
    feed = feedparser.parse(url)
    source = str(feed.feed.get("title", url))
    items: list[NewsItem] = []
    for entry in feed.entries:
        published = datetime.now(timezone.utc)
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        if parsed:
            published = datetime(*parsed[:6], tzinfo=timezone.utc)
        items.append(NewsItem(
            source=source,
            title=str(entry.get("title", "")),
            body=str(entry.get("summary", entry.get("description", ""))),
            url=str(entry.get("link", "")),
            published_at=published,
            raw=dict(entry),
        ))
    return items
