from __future__ import annotations

import os
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from intelligence.providers.null import NullIntelligenceProvider
from intelligence.providers.ollama import OllamaIntelligenceProvider
from storage.repositories import AuditRepository

app = FastAPI(title="Trading Intelligence API")
audit = AuditRepository()


class Article(BaseModel):
    article_id: str | None = None
    source: str
    title: str
    body: str = ""
    published_at: str | None = None
    first_seen_at: str | None = None
    url: str = ""
    raw_metadata: dict = Field(default_factory=dict)


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
    published_at = datetime.now(UTC)
    if article.published_at:
        published_at = datetime.fromisoformat(article.published_at.replace("Z", "+00:00"))
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=UTC)
    article_id = article.article_id
    if article_id is None:
        first_seen_at = datetime.now(UTC)
        if article.first_seen_at:
            first_seen_at = datetime.fromisoformat(article.first_seen_at.replace("Z", "+00:00"))
        article_id = await audit.save_news(
            source=article.source,
            title=article.title,
            body=article.body,
            published_at=published_at,
            first_seen_at=first_seen_at,
            raw_metadata={**article.raw_metadata, "url": article.url},
        )
    stored_article = await audit.get_news(article_id)
    if stored_article is None:
        raise HTTPException(status_code=404, detail="article_id does not exist")
    intelligence_provider = provider()
    result = await intelligence_provider.analyse(stored_article)
    if result is not None:
        await audit.save_llm_analysis(
            article_id=article_id,
            analysis_id=result.event_id,
            model=getattr(intelligence_provider, "model", "null"),
            prompt_version=getattr(intelligence_provider, "PROMPT_VERSION", "null"),
            prompt_hash=getattr(intelligence_provider, "prompt_hash", "null"),
            started_at=result.analysis_started_at or result.analysis_completed_at,
            completed_at=result.analysis_completed_at,
            available_to_strategy_at=result.available_to_strategy_at,
            payload={
                "assets": result.assets,
                "direction": result.direction,
                "importance": result.importance,
                "confidence": result.confidence,
                "event_type": result.event_type,
                "summary": result.summary,
                "horizon_seconds": result.horizon_seconds,
                "prompt_version": getattr(intelligence_provider, "PROMPT_VERSION", "null"),
                "prompt_hash": getattr(intelligence_provider, "prompt_hash", "null"),
                "model": getattr(intelligence_provider, "model", "null"),
            },
        )
    return {"result": result}
