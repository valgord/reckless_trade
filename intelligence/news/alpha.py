from __future__ import annotations

from datetime import UTC, datetime

from domain.models import InstrumentKey, IntelligenceEvent, Signal


class NewsAlpha:
    def __init__(self, venue: str = "BYBIT", min_importance: float = 0.4, min_confidence: float = 0.5) -> None:
        self.venue = venue
        self.min_importance = min_importance
        self.min_confidence = min_confidence

    def generate(
        self, event: IntelligenceEvent, symbol_map: dict[str, str], now: datetime | None = None
    ) -> list[Signal]:
        now = now or datetime.now(UTC)
        if now < event.available_to_strategy_at:
            return []
        if event.importance < self.min_importance or event.confidence < self.min_confidence:
            return []
        strength = min(event.importance * abs(event.direction), 1.0)
        signals: list[Signal] = []
        for asset in event.assets:
            symbol = symbol_map.get(asset)
            if symbol:
                signals.append(
                    Signal(
                        "news_llm",
                        InstrumentKey(self.venue, symbol),
                        event.direction,
                        strength,
                        event.confidence,
                        event.horizon_seconds,
                        ts_event=event.available_to_strategy_at,
                        metadata={"event_id": event.event_id, "event_type": event.event_type},
                    )
                )
        return signals
