from __future__ import annotations

import os
from datetime import UTC, datetime

from fastapi import FastAPI
from pydantic import BaseModel

from intelligence.providers.null import NullIntelligenceProvider
from intelligence.providers.ollama import OllamaIntelligenceProvider
from storage.repositories import AuditRepository

app = FastAPI(title="Trading Intelligence API")
audit = AuditRepository()


class Article(BaseModel):
    source: str
    title: str
    body: str = ""
    published_at: str | None = None


def provider():
    if os.getenv("INTELLIGENCE_ENABLED", "false").lower() == "true":
        return OllamaIntelligenceProvider(
            os.getenv("OLLAMA_BASE_URL", "http://ollama:11434"), os.getenv("OLLAMA_MODEL", "qwen3:14b")
        )
    return NullIntelligenceProvider()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/analyse")
async def analyse(article: Article):
    article_data = article.model_dump()
    published_at = datetime.now(UTC)
    if article.published_at:
        published_at = datetime.fromisoformat(article.published_at.replace("Z", "+00:00"))
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=UTC)
    intelligence_provider = provider()
    result = await intelligence_provider.analyse(article_data)
    article_id = await audit.save_news(
        source=article.source,
        title=article.title,
        body=article.body,
        published_at=published_at,
    )
    if result is not None:
        await audit.save_llm_analysis(
            article_id=article_id,
            model=getattr(intelligence_provider, "model", "null"),
            prompt_version=getattr(intelligence_provider, "PROMPT_VERSION", "null"),
            started_at=result.first_seen_at,
            completed_at=result.analysis_completed_at,
            payload={
                "assets": result.assets,
                "direction": result.direction,
                "importance": result.importance,
                "confidence": result.confidence,
                "event_type": result.event_type,
                "summary": result.summary,
                "horizon_seconds": result.horizon_seconds,
            },
        )
    return {"result": result}
