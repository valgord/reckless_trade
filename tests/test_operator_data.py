from __future__ import annotations

import json
from pathlib import Path

from apps.control_api.operator_data import article_preview, merge_news_feed, prepare_stored_news, read_archived_news


def test_article_preview_uses_html_parser_and_finds_image() -> None:
    text, image = article_preview('<style>hidden</style><p>Market <strong>moved</strong>.</p><img src="https://x.test/a.jpg">')

    assert text == "Market moved ."
    assert image == "https://x.test/a.jpg"


def test_reads_archived_news_as_pending_analysis(tmp_path: Path) -> None:
    path = tmp_path / "raw" / "2026" / "08" / "29" / "news.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "fingerprint": "fp-1",
                "source": "Example",
                "title": "BTC headline",
                "article_url": "https://example.test/news",
                "published_at": "2026-08-29T08:00:00+00:00",
                "first_seen_at": "2026-08-29T08:01:00+00:00",
                "body": "<p>Material news.</p>",
                "raw_payload": {"media_content": [{"url": "https://example.test/news.jpg"}]},
            }
        ),
        encoding="utf-8",
    )

    result = read_archived_news(tmp_path)

    assert len(result) == 1
    assert result[0]["analysis_status"] == "pending"
    assert result[0]["excerpt"] == "Material news."
    assert result[0]["image_url"] == "https://example.test/news.jpg"


def test_stored_analysis_replaces_matching_raw_archive_item() -> None:
    archived = [{"fingerprint": "fp-1", "first_seen_at": "2026-08-29T08:01:00+00:00", "analysis": None}]
    stored = prepare_stored_news(
        [
            {
                "fingerprint": "fp-1",
                "first_seen_at": "2026-08-29T08:01:00+00:00",
                "body": "<p>Stored body.</p>",
                "analysis": {"summary": "Analysed."},
            }
        ]
    )

    result = merge_news_feed(stored, archived, limit=10)

    assert len(result) == 1
    assert result[0]["analysis_status"] == "available"
    assert result[0]["excerpt"] == "Stored body."
