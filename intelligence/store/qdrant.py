from __future__ import annotations

from datetime import datetime

from domain.models import IntelligenceEvent


class QdrantSemanticEventStore:
    """Vector store adapter. Embedding creation is intentionally injected rather than coupled to Ollama."""

    def __init__(self, client, collection: str, embedder, audit_repository) -> None:
        self.client = client
        self.collection = collection
        self.embedder = embedder
        self.audit_repository = audit_repository

    async def upsert(self, event: IntelligenceEvent) -> None:
        from qdrant_client.models import PointStruct

        vector = await self.embedder.embed(f"{event.title}\n{event.summary}")
        payload = {
            "source": event.source,
            "title": event.title,
            "summary": event.summary,
            "assets": list(event.assets),
            "event_type": event.event_type,
            "direction": event.direction,
            "importance": event.importance,
            "confidence": event.confidence,
            "available_to_strategy_at": event.available_to_strategy_at.isoformat(),
        }
        self.client.upsert(
            collection_name=self.collection,
            points=[PointStruct(id=event.event_id, vector=vector, payload=payload)],
        )

    async def similar(
        self,
        event: IntelligenceEvent,
        as_of: datetime,
        limit: int = 10,
    ) -> list[IntelligenceEvent]:
        vector = await self.embedder.embed(f"{event.title}\n{event.summary}")
        response = self.client.query_points(
            collection_name=self.collection,
            query=vector,
            limit=limit,
            with_payload=False,
            with_vectors=False,
        )
        points = getattr(response, "points", response)
        event_ids = [str(point.id) for point in points if str(point.id) != event.event_id]
        # Qdrant chooses candidates only. PostgreSQL restores audited fields and enforces availability.
        return await self.audit_repository.get_intelligence_events(event_ids, as_of=as_of)
