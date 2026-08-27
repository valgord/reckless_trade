from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any

from domain.models import IntelligenceEvent, MarketRegime, PortfolioTarget, Signal


class AlphaModel(ABC):
    @abstractmethod
    def generate(self, context: Any) -> list[Signal]: ...


class SignalAggregator(ABC):
    @abstractmethod
    def aggregate(self, signals: Iterable[Signal]) -> list[Signal]: ...


class PortfolioConstructor(ABC):
    @abstractmethod
    def construct(self, signals: Iterable[Signal], numeraire: str) -> PortfolioTarget: ...


class RiskPolicy(ABC):
    @abstractmethod
    def validate_target(self, target: PortfolioTarget) -> tuple[bool, list[str]]: ...


class RegimeProvider(ABC):
    @abstractmethod
    def regime(self, context: Any) -> MarketRegime: ...


class IntelligenceProvider(ABC):
    @abstractmethod
    async def analyse(self, article: dict[str, Any]) -> IntelligenceEvent | None: ...


class SemanticEventStore(ABC):
    @abstractmethod
    async def upsert(self, event: IntelligenceEvent) -> None: ...

    @abstractmethod
    async def similar(self, event: IntelligenceEvent, limit: int = 10) -> list[IntelligenceEvent]: ...
