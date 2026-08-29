from __future__ import annotations

import pytest

from trading.decision_audit import AlgorithmAction, AlgorithmDecisionAudit, ExecutionStatus


def test_algorithm_decision_produces_stable_human_audit_payload() -> None:
    decision = AlgorithmDecisionAudit(
        action=AlgorithmAction.HOLD,
        summary="Funding remains positive and no risk guard fired.",
        confidence=0.78,
        strategy_summary="The pair remains delta neutral.",
        news_summary="No material negative BTC news was detected.",
        news_event_ids=("event-1",),
        risk_checks=("delta_within_limit", "monitor_fresh"),
    )

    payload = decision.as_payload()

    assert payload["schema_version"] == 1
    assert payload["decision"] == {
        "action": "hold",
        "summary": "Funding remains positive and no risk guard fired.",
        "confidence": 0.78,
    }
    assert payload["analysis"]["news_event_ids"] == ["event-1"]
    assert payload["execution"] == {
        "automatic": False,
        "status": "not_requested",
        "order_ids": [],
    }


def test_algorithm_decision_rejects_ambiguous_execution_audit() -> None:
    with pytest.raises(ValueError, match="between zero and one"):
        AlgorithmDecisionAudit(
            AlgorithmAction.OBSERVE,
            "Observe.",
            1.2,
            "Strategy summary.",
            "News summary.",
        )
    with pytest.raises(ValueError, match="reference at least one order"):
        AlgorithmDecisionAudit(
            AlgorithmAction.OPEN,
            "Open.",
            0.9,
            "Strategy summary.",
            "News summary.",
            automatic_execution=False,
            execution_status=ExecutionStatus.FILLED,
        )
