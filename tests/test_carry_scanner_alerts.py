from __future__ import annotations

from trading.execution.carry_scanner_alerts import evaluate_scanner_transition


def scanner(updated_at: str, eligible: tuple[str, ...]) -> dict:
    return {
        "status": "available",
        "updated_at": updated_at,
        "candidates": [
            {"symbol": symbol, "eligible": symbol in eligible, "estimate": {}, "funding": {}}
            for symbol in ("BTCUSDT", "ETHUSDT")
        ],
    }


def test_first_snapshot_records_baseline_without_notification() -> None:
    event, state = evaluate_scanner_transition(scanner("t1", ("BTCUSDT",)), None)

    assert event == {"status": "baseline_recorded", "newly_eligible": []}
    assert state == {"schema_version": 1, "scanner_updated_at": "t1", "eligible_symbols": ["BTCUSDT"]}


def test_only_false_to_true_transition_is_reported() -> None:
    previous = {"schema_version": 1, "scanner_updated_at": "t1", "eligible_symbols": ["BTCUSDT"]}

    event, state = evaluate_scanner_transition(scanner("t2", ("ETHUSDT",)), previous)

    assert event["status"] == "newly_eligible"
    assert [candidate["symbol"] for candidate in event["newly_eligible"]] == ["ETHUSDT"]
    assert state["eligible_symbols"] == ["ETHUSDT"]


def test_same_scanner_snapshot_is_deduplicated() -> None:
    previous = {"schema_version": 1, "scanner_updated_at": "t1", "eligible_symbols": []}

    event, state = evaluate_scanner_transition(scanner("t1", ("ETHUSDT",)), previous)

    assert event == {"status": "unchanged", "newly_eligible": []}
    assert state is None
