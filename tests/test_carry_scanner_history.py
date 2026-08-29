from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from storage.carry_scanner_history import (
    read_carry_scan_history,
    record_carry_scan,
    summarize_carry_scan_history,
)


def snapshot(updated_at: str, symbol: str = "BTCUSDT", eligible: bool = False) -> dict:
    estimated_net = 0.12 if eligible else -0.12
    return {
        "status": "available",
        "updated_at": updated_at,
        "universe": {
            "common_symbol_count": 291,
            "scanned_symbol_count": 20,
            "eligible_symbol_count": int(eligible),
            "failed_symbol_count": 0,
        },
        "candidates": [
            {
                "symbol": symbol,
                "eligible": eligible,
                "rank_score": estimated_net,
                "reasons": [] if eligible else ["estimated_horizon_net_not_positive"],
                "funding": {
                    "current_rate": 0.001,
                    "historical_average_rate": 0.0008,
                    "positive_share": 0.9,
                },
                "estimate": {
                    "estimated_net_over_horizon_usdt": estimated_net,
                    "break_even_settlements": 12.5,
                },
            }
        ],
    }


def test_records_and_reads_compact_symbol_history(tmp_path: Path) -> None:
    path = tmp_path / "history.sqlite3"
    record_carry_scan(path, snapshot("2026-08-28T09:00:00+00:00"))
    record_carry_scan(path, snapshot("2026-08-28T09:05:00+00:00", eligible=True))

    result = read_carry_scan_history(path, symbol="btcusdt", limit=10)

    assert result["status"] == "available"
    assert result["symbol"] == "BTCUSDT"
    assert len(result["observations"]) == 2
    assert result["observations"][0]["eligible"] is True
    assert result["observations"][1]["reasons"] == ["estimated_horizon_net_not_positive"]


def test_history_retention_removes_old_runs(tmp_path: Path) -> None:
    path = tmp_path / "history.sqlite3"
    record_carry_scan(path, snapshot("2026-01-01T00:00:00+00:00"), retention_days=90)
    record_carry_scan(
        path,
        snapshot("2026-08-28T09:00:00+00:00"),
        retention_days=90,
        now=datetime(2026, 8, 28, 9, tzinfo=UTC),
    )

    result = read_carry_scan_history(path)

    assert [item["updated_at"] for item in result["observations"]] == ["2026-08-28T09:00:00+00:00"]


def test_missing_history_is_reported_without_creating_database(tmp_path: Path) -> None:
    path = tmp_path / "missing.sqlite3"

    result = read_carry_scan_history(path)

    assert result == {"status": "not_run", "symbol": None, "observations": []}
    assert not path.exists()


def test_summarizes_scanner_evidence_over_requested_window(tmp_path: Path) -> None:
    path = tmp_path / "history.sqlite3"
    record_carry_scan(path, snapshot("2026-08-27T08:59:00+00:00"))
    record_carry_scan(path, snapshot("2026-08-28T08:00:00+00:00"))
    record_carry_scan(path, snapshot("2026-08-28T09:00:00+00:00", eligible=True))

    result = summarize_carry_scan_history(
        path,
        symbol="btcusdt",
        lookback_hours=24,
        now=datetime(2026, 8, 28, 9, tzinfo=UTC),
    )

    assert result["status"] == "available"
    assert result["orders_enabled"] is False
    assert result["automatic_actions_enabled"] is False
    assert result["symbol"] == "BTCUSDT"
    assert result["window"]["run_count"] == 2
    assert result["window"]["runs_with_eligible_candidate"] == 1
    assert result["window"]["runs_with_eligible_candidate_share"] == 0.5
    assert len(result["symbols"]) == 1
    evidence = result["symbols"][0]
    assert evidence["observation_count"] == 2
    assert evidence["run_coverage_share"] == 1
    assert evidence["eligible_share"] == 0.5
    assert evidence["positive_current_funding_share"] == 1
    assert evidence["positive_estimated_net_share"] == 0.5


def test_summary_reports_empty_window_and_validates_lookback(tmp_path: Path) -> None:
    path = tmp_path / "history.sqlite3"
    record_carry_scan(path, snapshot("2026-08-28T09:00:00+00:00"))

    result = summarize_carry_scan_history(
        path,
        lookback_hours=1,
        now=datetime(2026, 8, 29, 9, tzinfo=UTC),
    )

    assert result["status"] == "not_run"
    assert result["window"]["run_count"] == 0
    with pytest.raises(ValueError, match="between 1 and 2160"):
        summarize_carry_scan_history(path, lookback_hours=0)
