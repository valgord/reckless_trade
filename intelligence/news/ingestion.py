from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

from intelligence.news.rss import NewsItem


def source_id(url: str) -> str:
    return sha256(url.strip().encode()).hexdigest()[:16]


@dataclass(slots=True)
class SourceHealth:
    source_id: str
    url: str
    last_attempt_at: str | None = None
    last_success_at: str | None = None
    last_error_at: str | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    fetched_total: int = 0
    ingested_total: int = 0
    duplicate_total: int = 0
    rate_limited_total: int = 0


@dataclass(slots=True)
class DurableNewsState:
    path: Path
    delivered: set[str] = field(default_factory=set)
    sources: dict[str, SourceHealth] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> DurableNewsState:
        if not path.exists():
            return cls(path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            sources = {key: SourceHealth(**value) for key, value in raw.get("sources", {}).items()}
            return cls(path, set(raw.get("delivered", [])), sources)
        except (OSError, json.JSONDecodeError, TypeError):
            return cls(path)

    def can_poll(self, url: str, now: datetime, minimum_interval: timedelta) -> bool:
        health = self._source(url)
        if not health.last_attempt_at:
            return True
        last = datetime.fromisoformat(health.last_attempt_at)
        if now - last >= minimum_interval:
            return True
        health.rate_limited_total += 1
        self.save()
        return False

    def record_attempt(self, url: str, now: datetime) -> None:
        self._source(url).last_attempt_at = now.astimezone(UTC).isoformat()
        self.save()

    def record_success(self, url: str, now: datetime, fetched: int, ingested: int, duplicates: int) -> None:
        health = self._source(url)
        health.last_success_at = now.astimezone(UTC).isoformat()
        health.last_error = None
        health.consecutive_failures = 0
        health.fetched_total += fetched
        health.ingested_total += ingested
        health.duplicate_total += duplicates
        self.save()

    def record_failure(self, url: str, now: datetime, error: Exception) -> None:
        health = self._source(url)
        health.last_error_at = now.astimezone(UTC).isoformat()
        health.last_error = type(error).__name__
        health.consecutive_failures += 1
        self.save()

    def mark_delivered(self, fingerprint: str) -> None:
        self.delivered.add(fingerprint)
        self.save()

    def public_status(self) -> dict[str, Any]:
        return {
            "status": "configured" if self.sources else "not_configured",
            "delivered_fingerprints": len(self.delivered),
            "sources": [asdict(self.sources[key]) for key in sorted(self.sources)],
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        payload = {
            "version": 1,
            "updated_at": datetime.now(UTC).isoformat(),
            "delivered": sorted(self.delivered),
            "sources": {key: asdict(value) for key, value in sorted(self.sources.items())},
        }
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    def _source(self, url: str) -> SourceHealth:
        key = source_id(url)
        if key not in self.sources:
            self.sources[key] = SourceHealth(key, url)
        return self.sources[key]


class RawNewsArchive:
    def __init__(self, root: Path) -> None:
        self.root = root

    def write(self, item: NewsItem, fingerprint: str, feed_url: str, first_seen_at: datetime) -> Path:
        day = first_seen_at.astimezone(UTC)
        path = self.root / "raw" / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}" / f"{fingerprint}.json"
        if path.exists():
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "fingerprint": fingerprint,
            "source_id": source_id(feed_url),
            "feed_url": feed_url,
            "article_url": item.url,
            "source": item.source,
            "title": item.title,
            "body": item.body,
            "published_at": item.published_at.astimezone(UTC).isoformat(),
            "first_seen_at": first_seen_at.astimezone(UTC).isoformat(),
            "raw_payload": item.raw,
        }
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        temporary.replace(path)
        return path
