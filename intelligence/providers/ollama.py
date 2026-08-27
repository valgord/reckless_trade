from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx

from domain.models import IntelligenceEvent


class OllamaIntelligenceProvider:
    PROMPT_VERSION = "news-v1"

    def __init__(self, base_url: str, model: str, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    async def analyse(self, article: dict[str, Any]) -> IntelligenceEvent | None:
        first_seen = datetime.now(timezone.utc)
        schema = {
            "assets": ["BTC"], "event_type": "other", "direction": 0.0, "importance": 0.0,
            "confidence": 0.0, "horizon_seconds": 3600, "summary": "",
        }
        prompt = (
            "Classify the financial/crypto news. Do not give trading instructions. Return ONLY valid JSON with keys "
            f"matching this schema: {json.dumps(schema)}. direction must be [-1,1], importance/confidence [0,1], "
            "horizon_seconds > 0. Assets must use uppercase tickers.\n"
            f"Source: {article.get('source', '')}\nTitle: {article.get('title', '')}\nBody: {article.get('body', '')}"
        )
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/api/generate", json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.0},
            })
            response.raise_for_status()
            payload = json.loads(response.json()["response"])
        now = datetime.now(timezone.utc)
        published = article.get("published_at", first_seen)
        if isinstance(published, str):
            published = datetime.fromisoformat(published.replace("Z", "+00:00"))
        assets = tuple(str(asset).upper() for asset in payload.get("assets", []))
        return IntelligenceEvent(
            event_id=str(uuid4()), source=str(article.get("source", "unknown")), title=str(article.get("title", "")),
            summary=str(payload.get("summary", "")), assets=assets, event_type=str(payload.get("event_type", "other")),
            direction=max(-1.0, min(1.0, float(payload.get("direction", 0.0)))),
            importance=max(0.0, min(1.0, float(payload.get("importance", 0.0)))),
            confidence=max(0.0, min(1.0, float(payload.get("confidence", 0.0)))),
            horizon_seconds=max(1, int(payload.get("horizon_seconds", 3600))), published_at=published,
            first_seen_at=first_seen, analysis_completed_at=now, available_to_strategy_at=now,
        )
