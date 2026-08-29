from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


class _ArticlePreviewParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.image_url: str | None = None
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._ignored_depth += 1
        if tag == "img" and self.image_url is None:
            attributes = dict(attrs)
            self.image_url = attributes.get("src")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth and data.strip():
            self.text.append(data.strip())


def article_preview(body: str, maximum_length: int = 360) -> tuple[str, str | None]:
    parser = _ArticlePreviewParser()
    parser.feed(body)
    text = " ".join(parser.text)
    if len(text) > maximum_length:
        text = text[: maximum_length - 1].rstrip() + "..."
    return text, parser.image_url


def read_archived_news(root: Path, *, limit: int = 30) -> list[dict[str, Any]]:
    if limit < 1 or limit > 100:
        raise ValueError("operator news limit must be between 1 and 100")
    if not root.exists():
        return []
    candidates = sorted(root.glob("raw/**/*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    items: list[dict[str, Any]] = []
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        excerpt, body_image = article_preview(str(payload.get("body", "")))
        raw_payload = payload.get("raw_payload") or {}
        media = raw_payload.get("media_content") or []
        media_image = media[0].get("url") if media and isinstance(media[0], dict) else None
        items.append(
            {
                "article_id": None,
                "fingerprint": payload.get("fingerprint"),
                "source": payload.get("source", "Unknown source"),
                "title": payload.get("title", "Untitled"),
                "article_url": payload.get("article_url", ""),
                "image_url": media_image or body_image,
                "published_at": payload.get("published_at"),
                "first_seen_at": payload.get("first_seen_at"),
                "excerpt": excerpt,
                "analysis": None,
                "analysis_status": "pending",
            }
        )
        if len(items) >= limit:
            break
    return items


def prepare_stored_news(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prepared = []
    for item in items:
        excerpt, image_url = article_preview(str(item.pop("body", "")))
        item["excerpt"] = excerpt
        item["image_url"] = item.get("image_url") or image_url
        item["analysis_status"] = "available" if item.get("analysis") else "pending"
        prepared.append(item)
    return prepared


def merge_news_feed(
    stored: list[dict[str, Any]], archived: list[dict[str, Any]], *, limit: int
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in archived:
        key = str(item.get("fingerprint") or item.get("article_url") or item.get("title"))
        merged[key] = item
    for item in stored:
        key = str(item.get("fingerprint") or item.get("article_url") or item.get("title"))
        merged[key] = item
    return sorted(
        merged.values(),
        key=lambda item: str(item.get("first_seen_at") or item.get("published_at") or ""),
        reverse=True,
    )[:limit]
