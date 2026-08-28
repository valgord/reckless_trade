from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from storage.carry_scanner_history import read_carry_scan_history, record_carry_scan


def snapshot(updated_at: str, symbol: str = "BTCUSDT", eligible: bool = False) -> dict:
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
                "rank_score": 0.12,
                "reasons": [] if eligible else ["estimated_horizon_net_not_positive"],
                "funding": {
                    "current_rate": 0.001,
                    "historical_average_rate": 0.0008,
                    "positive_share": 0.9,
                },
                "estimate": {
                    "estimated_net_over_horizon_usdt": 0.12,
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
