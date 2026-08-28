from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class CarryAlertSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class CarryAlertConfig:
    stale_after_seconds: float = 180.0
    profit_review_usdt: float = 0.05
    maximum_loss_usdt: float = -2.0
    minimum_funding_settlements: int = 3

    def __post_init__(self) -> None:
        values = (self.stale_after_seconds, self.profit_review_usdt, self.maximum_loss_usdt)
        if any(not math.isfinite(value) for value in values):
            raise ValueError("carry alert thresholds must be finite")
        if self.stale_after_seconds <= 0 or self.profit_review_usdt < 0 or self.maximum_loss_usdt >= 0:
            raise ValueError("carry alert thresholds have invalid signs")
        if self.minimum_funding_settlements < 1:
            raise ValueError("minimum funding settlements must be positive")


@dataclass(frozen=True, slots=True)
class CarryAlert:
    code: str
    severity: CarryAlertSeverity
    message: str
    recommended_action: str
    confirmation_required: bool

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["severity"] = self.severity.value
        return payload


@dataclass(frozen=True, slots=True)
class CarryAlertDecision:
    state: str
    evidence_state: str
    alerts: tuple[CarryAlert, ...]
    operator_action: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "evidence_state": self.evidence_state,
            "alerts": [alert.as_dict() for alert in self.alerts],
            "operator_action": self.operator_action,
        }


def evaluate_carry_alerts(
    observer: dict[str, Any] | None,
    performance: dict[str, Any] | None,
    config: CarryAlertConfig,
    *,
    now: datetime | None = None,
) -> CarryAlertDecision:
    current = (now or datetime.now(tz=UTC)).astimezone(UTC)
    alerts: list[CarryAlert] = []

    _append_stale_alert(alerts, "observer", observer, config.stale_after_seconds, current)
    _append_stale_alert(alerts, "performance", performance, config.stale_after_seconds, current)

    phase = str((observer or {}).get("status", "missing"))
    if phase == "repair_required":
        alerts.append(
            CarryAlert(
                "leg_repair_required",
                CarryAlertSeverity.CRITICAL,
                "The Spot and perpetual quantities are no longer balanced.",
                "inspect_pair_and_prepare_risk_reducing_repair",
                True,
            )
        )
    elif phase == "close_required":
        alerts.append(
            CarryAlert(
                "risk_close_required",
                CarryAlertSeverity.CRITICAL,
                "The deterministic carry guard recommends closing both legs.",
                "review_and_confirm_pair_close",
                True,
            )
        )
    elif phase == "blocked":
        alerts.append(
            CarryAlert(
                "observer_blocked",
                CarryAlertSeverity.WARNING,
                "Carry reconciliation is blocked or incomplete.",
                "inspect_reconciliation_before_any_order",
                False,
            )
        )

    funding = (performance or {}).get("funding", {})
    performance_values = (performance or {}).get("performance", {})
    settlement_count = int(funding.get("settlement_count", 0) or 0)
    funding_income = float(funding.get("income_usdt", 0) or 0)
    estimated_net = performance_values.get("estimated_net_pnl_usdt")
    if funding_income < 0:
        alerts.append(
            CarryAlert(
                "negative_funding",
                CarryAlertSeverity.WARNING,
                f"Cumulative funding is negative ({funding_income:.6f} USDT).",
                "review_funding_regime_and_hold_decision",
                False,
            )
        )
    if estimated_net is not None:
        estimated_net = float(estimated_net)
        if estimated_net <= config.maximum_loss_usdt:
            alerts.append(
                CarryAlert(
                    "loss_limit_review",
                    CarryAlertSeverity.CRITICAL,
                    f"Estimated executable net PnL reached {estimated_net:.6f} USDT.",
                    "review_and_confirm_pair_close",
                    True,
                )
            )
        elif estimated_net >= config.profit_review_usdt and settlement_count >= config.minimum_funding_settlements:
            alerts.append(
                CarryAlert(
                    "profit_exit_review",
                    CarryAlertSeverity.INFO,
                    f"Estimated executable net PnL reached {estimated_net:.6f} USDT after sufficient settlements.",
                    "review_and_optionally_confirm_pair_close",
                    True,
                )
            )

    evidence_state = (
        "minimum_window_reached"
        if settlement_count >= config.minimum_funding_settlements
        else "collecting_funding_settlements"
    )
    actionable = [alert for alert in alerts if alert.confirmation_required]
    state = "action_required" if actionable else "attention" if alerts else "monitoring"
    operator_action = actionable[0].recommended_action if actionable else "continue_monitoring"
    return CarryAlertDecision(state, evidence_state, tuple(alerts), operator_action)


def _append_stale_alert(
    alerts: list[CarryAlert],
    name: str,
    payload: dict[str, Any] | None,
    stale_after_seconds: float,
    now: datetime,
) -> None:
    updated_at = (payload or {}).get("updated_at")
    if updated_at is None:
        age = None
    else:
        try:
            parsed = datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            age = max(0.0, (now - parsed.astimezone(UTC)).total_seconds())
        except ValueError:
            age = None
    if age is None or age > stale_after_seconds:
        detail = "missing" if age is None else f"{age:.0f}s old"
        alerts.append(
            CarryAlert(
                f"{name}_stale",
                CarryAlertSeverity.CRITICAL,
                f"Carry {name} state is {detail}.",
                "restore_monitoring_before_any_order",
                False,
            )
        )
