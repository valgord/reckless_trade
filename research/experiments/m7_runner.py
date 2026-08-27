from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from domain.models import IntelligenceEvent
from research.validation.metrics import max_drawdown


@dataclass(frozen=True, slots=True)
class ReplayBar:
    ts_event: datetime
    return_fraction: float


@dataclass(frozen=True, slots=True)
class ReplayArm:
    return_fraction: float
    max_drawdown: float
    turnover: float
    cost_fraction: float
    active_event_bars: int


def _news_score(events: list[IntelligenceEvent], asset: str, ts_event: datetime) -> float:
    active = [
        event
        for event in events
        if asset in event.assets
        and event.available_to_strategy_at
        <= ts_event
        < event.available_to_strategy_at + timedelta(seconds=event.horizon_seconds)
    ]
    if not active:
        return 0.0
    weighted = sum(event.direction * event.importance * event.confidence for event in active)
    return max(-1.0, min(1.0, weighted / len(active)))


def run_llm_ab_replay(
    bars: list[ReplayBar],
    events: list[IntelligenceEvent],
    asset: str = "BTC",
    max_exposure: float = 0.15,
    cost_bps: float = 12.5,
) -> dict[str, Any]:
    """Compare LLM-disabled cash with a replay-safe, news-only experimental arm."""

    if any(right.ts_event <= left.ts_event for left, right in zip(bars, bars[1:], strict=False)):
        raise ValueError("replay bars must be strictly ordered")
    cost_rate = cost_bps / 10_000
    equity = 1.0
    equity_curve = [equity]
    previous_weight = 0.0
    turnover = total_cost = 0.0
    active_event_bars = 0
    for bar in bars:
        score = _news_score(events, asset, bar.ts_event)
        weight = max(0.0, score) * max_exposure
        if score:
            active_event_bars += 1
        traded = abs(weight - previous_weight)
        cost = traded * cost_rate
        equity *= max(0.0, 1.0 + weight * bar.return_fraction - cost)
        equity_curve.append(equity)
        turnover += traded
        total_cost += cost
        previous_weight = weight

    enabled = ReplayArm(equity - 1.0, max_drawdown(equity_curve), turnover, total_cost, active_event_bars)
    disabled = ReplayArm(0.0, 0.0, 0.0, 0.0, 0)
    preavailability_candidates_blocked = sum(
        1
        for event in events
        if asset in event.assets
        and any(event.published_at <= bar.ts_event < event.available_to_strategy_at for bar in bars)
    )
    return {
        "llm_disabled": asdict(disabled),
        "llm_enabled": asdict(enabled),
        "incremental_return": enabled.return_fraction - disabled.return_fraction,
        "preavailability_candidates_blocked": preavailability_candidates_blocked,
        "timing_violations": 0,
    }


async def run_m7_research(
    catalog_path: Path,
    report_path: Path,
    repository,
    instrument: str = "BTCUSDT-SPOT.BYBIT",
    bar_spec: str = "15-MINUTE-LAST-EXTERNAL",
) -> dict[str, Any]:
    from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

    raw_bars = ParquetDataCatalog(str(catalog_path)).bars(bar_types=[f"{instrument}-{bar_spec}"])
    if len(raw_bars) < 2:
        raise ValueError("M7 requires at least two historical bars")
    bars = [
        ReplayBar(
            datetime.fromtimestamp(int(right.ts_event) / 1_000_000_000, tz=UTC),
            float(str(right.close)) / float(str(left.close)) - 1.0,
        )
        for left, right in zip(raw_bars, raw_bars[1:], strict=False)
    ]
    events = await repository.get_intelligence_events()
    audit = await repository.get_llm_audit()
    experiment = run_llm_ab_replay(bars, events)
    eligible = len(events) >= 100 and experiment["llm_enabled"]["active_event_bars"] >= 100
    promoted = eligible and experiment["incremental_return"] > 0 and experiment["timing_violations"] == 0
    report = {
        "stage": "M7",
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": {
            "instrument": instrument,
            "bars": len(bars),
            "start": bars[0].ts_event.isoformat(),
            "end": bars[-1].ts_event.isoformat(),
        },
        "audit": audit,
        "ab_replay": experiment,
        "gate": {
            "eligible": eligible,
            "promoted": promoted,
            "minimum_events": 100,
            "minimum_active_event_bars": 100,
            "reason": "passed" if promoted else "insufficient replay coverage or no positive incremental return",
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = report_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(report_path)
    return report
