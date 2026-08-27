from __future__ import annotations

from domain.models import IntelligenceEvent


class QdrantSemanticEventStore:
    """Vector store adapter. Embedding creation is intentionally injected rather than coupled to Ollama."""

    def __init__(self, client, collection: str, embedder) -> None:
        self.client = client
        self.collection = collection
        self.embedder = embedder

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
        self.client.upsert(self.collection, [PointStruct(id=event.event_id, vector=vector, payload=payload)])

    async def similar(self, event: IntelligenceEvent, limit: int = 10) -> list[IntelligenceEvent]:
        # Qdrant payloads are intentionally not promoted directly into domain events here because historical timing fields
        # must come from the relational audit store. This method is wired when the full event repository is available.
        return []
