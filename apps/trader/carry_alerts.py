from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from apps.trader.demo_strategy import write_runtime_status
from intelligence.providers.carry_advisor import OllamaCarryAdvisor
from trading.execution.carry_alerts import CarryAlertConfig, evaluate_carry_alerts


class CarryAlertsWorker:
    def __init__(self, *, observer_path: Path, performance_path: Path, status_path: Path) -> None:
        self.observer_path = observer_path
        self.performance_path = performance_path
        self.status_path = status_path
        self.config = CarryAlertConfig(
            stale_after_seconds=float(os.getenv("CARRY_ALERT_STALE_SECONDS", "180")),
            profit_review_usdt=float(os.getenv("CARRY_ALERT_PROFIT_REVIEW_USDT", "0.05")),
            maximum_loss_usdt=float(os.getenv("CARRY_ALERT_MAXIMUM_LOSS_USDT", "-2")),
            minimum_funding_settlements=int(os.getenv("CARRY_ALERT_MIN_FUNDING_SETTLEMENTS", "3")),
        )
        self.llm_enabled = os.getenv("CARRY_ALERT_LLM_ENABLED", "false").lower() == "true"
        self.webhook_url = os.getenv("CARRY_ALERT_WEBHOOK_URL")

    async def refresh(self) -> dict[str, Any]:
        observer = _read_optional_json(self.observer_path)
        performance = _read_optional_json(self.performance_path)
        decision = evaluate_carry_alerts(observer, performance, self.config)
        fingerprint = _fingerprint(decision.as_dict(), performance)
        previous = _read_optional_json(self.status_path)
        advisory = await self._advisory(decision.as_dict(), performance, previous, fingerprint)
        changed = previous is None or previous.get("fingerprint") != fingerprint
        payload = {
            "status": decision.state,
            "mode": "demo",
            "orders_enabled": False,
            "automatic_actions_enabled": False,
            "confirmation_policy": "explicit_one_shot_pair_command",
            "decision": decision.as_dict(),
            "fingerprint": fingerprint,
            "llm_advisory": advisory,
            "webhook_configured": bool(self.webhook_url),
            "updated_at": datetime.now(tz=UTC).isoformat(),
        }
        write_runtime_status(self.status_path, payload)
        if changed and self.webhook_url:
            await self._notify(payload)
        return payload

    async def _advisory(
        self,
        decision: dict[str, Any],
        performance: dict[str, Any] | None,
        previous: dict[str, Any] | None,
        fingerprint: str,
    ) -> dict[str, Any]:
        if not self.llm_enabled:
            return {"status": "disabled"}
        if previous and previous.get("fingerprint") == fingerprint:
            cached = previous.get("llm_advisory")
            if isinstance(cached, dict):
                return cached
        advisor = OllamaCarryAdvisor(
            os.getenv("OLLAMA_BASE_URL", "http://ollama:11434"),
            os.getenv("OLLAMA_MODEL", "qwen3:14b"),
        )
        try:
            return await advisor.analyse(
                {
                    "decision": decision,
                    "funding": (performance or {}).get("funding"),
                    "performance": (performance or {}).get("performance"),
                    "position_phase": (performance or {}).get("position_phase"),
                }
            )
        except Exception as exc:
            return {"status": "unavailable", "error_type": type(exc).__name__}

    async def _notify(self, payload: dict[str, Any]) -> None:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(self.webhook_url, json=payload)
                response.raise_for_status()
        except Exception:
            return


def _read_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _fingerprint(decision: dict[str, Any], performance: dict[str, Any] | None) -> str:
    stable = {
        "alerts": [
            {
                "code": item["code"],
                "severity": item["severity"],
                "recommended_action": item["recommended_action"],
            }
            for item in decision["alerts"]
        ],
        "evidence_state": decision["evidence_state"],
        "settlement_count": ((performance or {}).get("funding") or {}).get("settlement_count", 0),
    }
    return hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def run(watch: bool, poll_seconds: float) -> int:
    worker = CarryAlertsWorker(
        observer_path=Path(os.getenv("CARRY_STATUS_PATH", "data/runtime/carry-observer.json")),
        performance_path=Path(os.getenv("CARRY_PERFORMANCE_PATH", "data/runtime/carry-performance.json")),
        status_path=Path(os.getenv("CARRY_ALERT_STATUS_PATH", "data/runtime/carry-alerts.json")),
    )
    while True:
        result = await worker.refresh()
        print(json.dumps(result, indent=2, sort_keys=True), flush=True)
        if not watch:
            return 0
        await asyncio.sleep(poll_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic carry alerts with optional local LLM explanation")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    args = parser.parse_args()
    if args.poll_seconds <= 0:
        parser.error("--poll-seconds must be positive")
    return asyncio.run(run(args.watch, args.poll_seconds))


if __name__ == "__main__":
    sys.exit(main())
