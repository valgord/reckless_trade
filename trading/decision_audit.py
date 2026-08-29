from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class AlgorithmAction(StrEnum):
    OBSERVE = "observe"
    HOLD = "hold"
    OPEN = "open"
    CLOSE = "close"
    REDUCE = "reduce"
    REBALANCE = "rebalance"
    BLOCK = "block"


class ExecutionStatus(StrEnum):
    NOT_REQUESTED = "not_requested"
    BLOCKED = "blocked"
    PLANNED = "planned"
    SUBMITTED = "submitted"
    FILLED = "filled"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class AlgorithmDecisionAudit:
    action: AlgorithmAction
    summary: str
    confidence: float
    strategy_summary: str
    news_summary: str
    news_event_ids: tuple[str, ...] = ()
    risk_checks: tuple[str, ...] = ()
    automatic_execution: bool = False
    execution_status: ExecutionStatus = ExecutionStatus.NOT_REQUESTED
    order_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.summary.strip():
            raise ValueError("algorithm decision summary cannot be empty")
        if not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("algorithm decision confidence must be between zero and one")
        if self.execution_status == ExecutionStatus.FILLED and not self.order_ids:
            raise ValueError("a filled algorithm decision must reference at least one order")

    def as_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "decision": {
                "action": self.action.value,
                "summary": self.summary,
                "confidence": self.confidence,
            },
            "analysis": {
                "strategy_summary": self.strategy_summary,
                "news_summary": self.news_summary,
                "news_event_ids": list(self.news_event_ids),
            },
            "risk": {"checks": list(self.risk_checks)},
            "execution": {
                "automatic": self.automatic_execution,
                "status": self.execution_status.value,
                "order_ids": list(self.order_ids),
            },
        }
