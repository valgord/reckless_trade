from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import exists, select

from domain.models import IntelligenceEvent
from intelligence.news.dedup import fingerprint
from storage.database import SessionLocal
from storage.models import Experiment, LlmAnalysis, NewsArticle, StrategyDecision


class AuditRepository:
    async def save_news(
        self,
        source: str,
        title: str,
        body: str,
        published_at: datetime,
        raw_metadata: dict | None = None,
        first_seen_at: datetime | None = None,
    ) -> str:
        key = fingerprint(title, body)
        async with SessionLocal() as session:
            existing = await session.scalar(select(NewsArticle).where(NewsArticle.fingerprint == key))
            if existing:
                return existing.id
            row = NewsArticle(
                source=source,
                fingerprint=key,
                title=title,
                body=body,
                published_at=published_at,
                first_seen_at=first_seen_at or datetime.now(UTC),
                raw_metadata=raw_metadata or {},
            )
            session.add(row)
            await session.commit()
            return row.id

    async def get_news(self, article_id: str) -> dict | None:
        async with SessionLocal() as session:
            row = await session.get(NewsArticle, article_id)
            if row is None:
                return None
            return {
                "article_id": row.id,
                "source": row.source,
                "title": row.title,
                "body": row.body,
                "published_at": row.published_at,
                "first_seen_at": row.first_seen_at,
                "raw_metadata": row.raw_metadata,
            }

    async def get_pending_news(self, model: str, prompt_hash: str, limit: int = 10) -> list[dict]:
        already_analysed = exists().where(
            LlmAnalysis.article_id == NewsArticle.id,
            LlmAnalysis.model == model,
            LlmAnalysis.prompt_hash == prompt_hash,
        )
        statement = (
            select(NewsArticle).where(~already_analysed).order_by(NewsArticle.first_seen_at).limit(max(1, limit))
        )
        async with SessionLocal() as session:
            rows = list((await session.scalars(statement)).all())
        return [
            {
                "article_id": row.id,
                "source": row.source,
                "title": row.title,
                "body": row.body,
                "published_at": row.published_at,
                "first_seen_at": row.first_seen_at,
                "raw_metadata": row.raw_metadata,
            }
            for row in rows
        ]

    async def save_llm_analysis(
        self,
        article_id: str,
        analysis_id: str,
        model: str,
        prompt_version: str,
        prompt_hash: str,
        started_at: datetime,
        completed_at: datetime,
        available_to_strategy_at: datetime,
        payload: dict,
    ) -> str:
        async with SessionLocal() as session:
            existing = await session.scalar(
                select(LlmAnalysis).where(
                    LlmAnalysis.article_id == article_id,
                    LlmAnalysis.model == model,
                    LlmAnalysis.prompt_hash == prompt_hash,
                )
            )
            if existing:
                return existing.id
            row = LlmAnalysis(
                id=analysis_id,
                article_id=article_id,
                model=model,
                prompt_version=prompt_version,
                prompt_hash=prompt_hash,
                started_at=started_at,
                completed_at=completed_at,
                available_to_strategy_at=available_to_strategy_at,
                direction=float(payload["direction"]),
                importance=float(payload["importance"]),
                confidence=float(payload["confidence"]),
                event_type=str(payload["event_type"]),
                assets=list(payload["assets"]),
                response=payload,
            )
            session.add(row)
            await session.commit()
            return row.id

    async def get_intelligence_events(
        self,
        event_ids: list[str] | None = None,
        as_of: datetime | None = None,
    ) -> list[IntelligenceEvent]:
        statement = select(LlmAnalysis, NewsArticle).join(NewsArticle, NewsArticle.id == LlmAnalysis.article_id)
        if event_ids is not None:
            if not event_ids:
                return []
            statement = statement.where(LlmAnalysis.id.in_(event_ids))
        if as_of is not None:
            statement = statement.where(LlmAnalysis.available_to_strategy_at <= as_of)
        async with SessionLocal() as session:
            rows = (await session.execute(statement)).all()
        events = [self._to_event(analysis, article) for analysis, article in rows]
        if event_ids is None:
            return sorted(events, key=lambda item: item.available_to_strategy_at)
        order = {event_id: index for index, event_id in enumerate(event_ids)}
        return sorted(events, key=lambda item: order.get(item.event_id, len(order)))

    async def get_llm_audit(self) -> dict:
        async with SessionLocal() as session:
            rows = list((await session.scalars(select(LlmAnalysis))).all())
        configurations: dict[str, int] = {}
        timing_violations = 0
        for row in rows:
            key = f"{row.model}:{row.prompt_version}:{row.prompt_hash}"
            configurations[key] = configurations.get(key, 0) + 1
            if row.completed_at < row.started_at or row.available_to_strategy_at < row.completed_at:
                timing_violations += 1
        return {
            "analysis_count": len(rows),
            "configurations": configurations,
            "timing_violations": timing_violations,
        }

    @staticmethod
    def _to_event(analysis: LlmAnalysis, article: NewsArticle) -> IntelligenceEvent:
        response = analysis.response or {}
        return IntelligenceEvent(
            event_id=analysis.id,
            source=article.source,
            title=article.title,
            summary=str(response.get("summary", "")),
            assets=tuple(analysis.assets),
            event_type=analysis.event_type,
            direction=analysis.direction,
            importance=analysis.importance,
            confidence=analysis.confidence,
            horizon_seconds=int(response.get("horizon_seconds", 3600)),
            published_at=article.published_at,
            first_seen_at=article.first_seen_at,
            analysis_completed_at=analysis.completed_at,
            available_to_strategy_at=analysis.available_to_strategy_at,
            analysis_started_at=analysis.started_at,
        )

    async def save_decision(
        self, ts_event: datetime, strategy: str, instrument: str, payload: dict, rationale: str = ""
    ) -> str:
        row = StrategyDecision(
            ts_event=ts_event, strategy=strategy, instrument=instrument, payload=payload, rationale=rationale
        )
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
