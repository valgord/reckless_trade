from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256

from sqlalchemy import select

from intelligence.news.dedup import fingerprint
from storage.database import SessionLocal
from storage.models import Experiment, LlmAnalysis, NewsArticle, StrategyDecision


class AuditRepository:
    async def save_news(self, source: str, title: str, body: str, published_at: datetime, raw_metadata: dict | None = None) -> str:
        key = fingerprint(title, body)
        async with SessionLocal() as session:
            existing = await session.scalar(select(NewsArticle).where(NewsArticle.fingerprint == key))
            if existing:
                return existing.id
            row = NewsArticle(source=source, fingerprint=key, title=title, body=body, published_at=published_at,
                              first_seen_at=datetime.now(timezone.utc), raw_metadata=raw_metadata or {})
            session.add(row)
            await session.commit()
            return row.id

    async def save_llm_analysis(self, article_id: str, model: str, prompt_version: str, started_at: datetime,
                                completed_at: datetime, payload: dict) -> str:
        prompt_hash = sha256(prompt_version.encode()).hexdigest()
        row = LlmAnalysis(article_id=article_id, model=model, prompt_version=prompt_version, prompt_hash=prompt_hash,
                          started_at=started_at, completed_at=completed_at, available_to_strategy_at=completed_at,
                          direction=float(payload.get("direction", 0.0)), importance=float(payload.get("importance", 0.0)),
                          confidence=float(payload.get("confidence", 0.0)), event_type=str(payload.get("event_type", "other")),
                          assets=list(payload.get("assets", [])), response=payload)
        async with SessionLocal() as session:
            session.add(row)
            await session.commit()
            return row.id

    async def save_decision(self, ts_event: datetime, strategy: str, instrument: str, payload: dict, rationale: str = "") -> str:
        row = StrategyDecision(ts_event=ts_event, strategy=strategy, instrument=instrument, payload=payload, rationale=rationale)
        async with SessionLocal() as session:
            session.add(row)
            await session.commit()
            return row.id

    async def save_experiment(self, **kwargs) -> str:
        row = Experiment(**kwargs)
        async with SessionLocal() as session:
            session.add(row)
            await session.commit()
            return row.id
