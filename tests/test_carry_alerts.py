from __future__ import annotations

from datetime import UTC, datetime, timedelta

from trading.execution.carry_alerts import CarryAlertConfig, evaluate_carry_alerts

NOW = datetime(2026, 8, 28, 8, 0, tzinfo=UTC)


def observer(status: str = "hedged", age_seconds: float = 0) -> dict:
    return {"status": status, "updated_at": (NOW - timedelta(seconds=age_seconds)).isoformat()}


def performance(net: float = -0.25, settlements: int = 0, funding: float = 0, age_seconds: float = 0) -> dict:
    return {
        "updated_at": (NOW - timedelta(seconds=age_seconds)).isoformat(),
        "position_phase": "hedged",
        "funding": {"settlement_count": settlements, "income_usdt": funding},
        "performance": {"estimated_net_pnl_usdt": net},
    }


def test_healthy_pair_collects_evidence_without_requesting_action() -> None:
    decision = evaluate_carry_alerts(observer(), performance(), CarryAlertConfig(), now=NOW)

    assert decision.state == "monitoring"
    assert decision.evidence_state == "collecting_funding_settlements"
    assert decision.operator_action == "continue_monitoring"
    assert decision.alerts == ()


def test_repair_and_guarded_close_require_human_confirmation() -> None:
    repair = evaluate_carry_alerts(observer("repair_required"), performance(), CarryAlertConfig(), now=NOW)
    close = evaluate_carry_alerts(observer("close_required"), performance(), CarryAlertConfig(), now=NOW)

    assert repair.state == close.state == "action_required"
    assert repair.alerts[0].code == "leg_repair_required"
    assert close.alerts[0].code == "risk_close_required"
    assert repair.alerts[0].confirmation_required is True
    assert close.alerts[0].confirmation_required is True


def test_stale_monitor_is_critical_but_cannot_authorize_an_order() -> None:
    decision = evaluate_carry_alerts(
        observer(age_seconds=181),
        performance(age_seconds=181),
        CarryAlertConfig(stale_after_seconds=180),
        now=NOW,
    )

    assert {alert.code for alert in decision.alerts} == {"observer_stale", "performance_stale"}
    assert all(alert.severity == "critical" for alert in decision.alerts)
    assert all(alert.confirmation_required is False for alert in decision.alerts)


def test_profit_review_waits_for_minimum_funding_window() -> None:
    early = evaluate_carry_alerts(observer(), performance(net=0.1, settlements=2), CarryAlertConfig(), now=NOW)
    ready = evaluate_carry_alerts(observer(), performance(net=0.1, settlements=3), CarryAlertConfig(), now=NOW)

    assert early.alerts == ()
    assert ready.alerts[0].code == "profit_exit_review"
    assert ready.alerts[0].confirmation_required is True


def test_loss_limit_and_negative_funding_are_visible() -> None:
    decision = evaluate_carry_alerts(
        observer(),
        performance(net=-2.01, settlements=1, funding=-0.02),
        CarryAlertConfig(),
        now=NOW,
    )

    assert [alert.code for alert in decision.alerts] == ["negative_funding", "loss_limit_review"]
    assert decision.operator_action == "review_and_confirm_pair_close"
