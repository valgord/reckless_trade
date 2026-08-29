from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


def record_carry_scan(
    path: Path,
    payload: dict[str, Any],
    *,
    retention_days: int = 90,
    now: datetime | None = None,
) -> None:
    if retention_days < 1:
        raise ValueError("carry scanner history retention must be positive")
    if payload.get("status") != "available" or not payload.get("updated_at"):
        raise ValueError("only available carry scanner snapshots can be recorded")
    path.parent.mkdir(parents=True, exist_ok=True)
    cutoff = (now or datetime.now(tz=UTC)) - timedelta(days=retention_days)
    updated_at = str(payload["updated_at"])
    universe = payload.get("universe") or {}
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS carry_scan_runs (
                updated_at TEXT PRIMARY KEY,
                common_symbol_count INTEGER NOT NULL,
                scanned_symbol_count INTEGER NOT NULL,
                eligible_symbol_count INTEGER NOT NULL,
                failed_symbol_count INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS carry_scan_candidates (
                updated_at TEXT NOT NULL,
                rank_position INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                eligible INTEGER NOT NULL,
                rank_score REAL NOT NULL,
                current_funding REAL NOT NULL,
                average_funding REAL NOT NULL,
                positive_share REAL NOT NULL,
                estimated_net_usdt REAL NOT NULL,
                break_even_settlements REAL,
                reasons_json TEXT NOT NULL,
                PRIMARY KEY (updated_at, symbol),
                FOREIGN KEY (updated_at) REFERENCES carry_scan_runs(updated_at) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS ix_carry_scan_candidates_symbol_time
                ON carry_scan_candidates(symbol, updated_at DESC);
            """
        )
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT OR REPLACE INTO carry_scan_runs VALUES (?, ?, ?, ?, ?)
            """,
            (
                updated_at,
                int(universe.get("common_symbol_count", 0)),
                int(universe.get("scanned_symbol_count", 0)),
                int(universe.get("eligible_symbol_count", 0)),
                int(universe.get("failed_symbol_count", 0)),
            ),
        )
        connection.execute("DELETE FROM carry_scan_candidates WHERE updated_at = ?", (updated_at,))
        for rank, candidate in enumerate(payload.get("candidates") or [], start=1):
            funding = candidate.get("funding") or {}
            estimate = candidate.get("estimate") or {}
            connection.execute(
                """
                INSERT INTO carry_scan_candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    updated_at,
                    rank,
                    str(candidate["symbol"]),
                    int(bool(candidate.get("eligible"))),
                    float(candidate.get("rank_score", 0)),
                    float(funding.get("current_rate", 0)),
                    float(funding.get("historical_average_rate", 0)),
                    float(funding.get("positive_share", 0)),
                    float(estimate.get("estimated_net_over_horizon_usdt", 0)),
                    estimate.get("break_even_settlements"),
                    json.dumps(candidate.get("reasons") or [], separators=(",", ":")),
                ),
            )
        connection.execute("DELETE FROM carry_scan_runs WHERE updated_at < ?", (cutoff.isoformat(),))


def read_carry_scan_history(path: Path, *, symbol: str | None = None, limit: int = 100) -> dict[str, Any]:
    if limit < 1 or limit > 500:
        raise ValueError("carry scanner history limit must be between 1 and 500")
    if not path.exists():
        return {"status": "not_run", "symbol": symbol, "observations": []}
    query = """
        SELECT updated_at, rank_position, symbol, eligible, rank_score, current_funding,
               average_funding, positive_share, estimated_net_usdt, break_even_settlements, reasons_json
        FROM carry_scan_candidates
    """
    parameters: list[Any] = []
    if symbol:
        query += " WHERE symbol = ?"
        parameters.append(symbol.upper())
    query += " ORDER BY updated_at DESC, rank_position ASC LIMIT ?"
    parameters.append(limit)
    uri = f"file:{path.resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        rows = connection.execute(query, parameters).fetchall()
    return {
        "status": "available",
        "symbol": symbol.upper() if symbol else None,
        "observations": [
            {
                "updated_at": row[0],
                "rank_position": row[1],
                "symbol": row[2],
                "eligible": bool(row[3]),
                "rank_score": row[4],
                "current_funding": row[5],
                "average_funding": row[6],
                "positive_share": row[7],
                "estimated_net_usdt": row[8],
                "break_even_settlements": row[9],
                "reasons": json.loads(row[10]),
            }
            for row in rows
        ],
    }


def summarize_carry_scan_history(
    path: Path,
    *,
    symbol: str | None = None,
    lookback_hours: int = 168,
    now: datetime | None = None,
) -> dict[str, Any]:
    if lookback_hours < 1 or lookback_hours > 24 * 90:
        raise ValueError("carry scanner summary lookback must be between 1 and 2160 hours")
    normalized_symbol = symbol.upper() if symbol else None
    if not path.exists():
        return _empty_summary(normalized_symbol, lookback_hours)

    cutoff = (now or datetime.now(tz=UTC)) - timedelta(hours=lookback_hours)
    uri = f"file:{path.resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        run_row = connection.execute(
            """
            SELECT MIN(updated_at), MAX(updated_at), COUNT(*),
                   COALESCE(SUM(CASE WHEN eligible_symbol_count > 0 THEN 1 ELSE 0 END), 0)
            FROM carry_scan_runs
            WHERE julianday(updated_at) >= julianday(?)
            """,
            (cutoff.isoformat(),),
        ).fetchone()
        run_count = int(run_row[2])
        if run_count == 0:
            return _empty_summary(normalized_symbol, lookback_hours)

        query = """
            SELECT symbol,
                   COUNT(*) AS observation_count,
                   SUM(CASE WHEN eligible = 1 THEN 1 ELSE 0 END) AS eligible_count,
                   SUM(CASE WHEN current_funding > 0 THEN 1 ELSE 0 END) AS positive_funding_count,
                   AVG(current_funding) AS average_current_funding,
                   AVG(average_funding) AS average_historical_funding,
                   SUM(CASE WHEN estimated_net_usdt > 0 THEN 1 ELSE 0 END) AS positive_net_count,
                   AVG(estimated_net_usdt) AS average_estimated_net_usdt,
                   MIN(estimated_net_usdt) AS minimum_estimated_net_usdt,
                   MAX(estimated_net_usdt) AS maximum_estimated_net_usdt,
                   AVG(break_even_settlements) AS average_break_even_settlements
            FROM carry_scan_candidates
            WHERE julianday(updated_at) >= julianday(?)
        """
        parameters: list[Any] = [cutoff.isoformat()]
        if normalized_symbol:
            query += " AND symbol = ?"
            parameters.append(normalized_symbol)
        query += """
            GROUP BY symbol
            ORDER BY eligible_count DESC, positive_net_count DESC,
                     average_estimated_net_usdt DESC, observation_count DESC, symbol ASC
        """
        rows = connection.execute(query, parameters).fetchall()

    symbols = []
    for row in rows:
        observation_count = int(row[1])
        eligible_count = int(row[2])
        positive_funding_count = int(row[3])
        positive_net_count = int(row[6])
        symbols.append(
            {
                "symbol": row[0],
                "observation_count": observation_count,
                "run_coverage_share": observation_count / run_count,
                "eligible_count": eligible_count,
                "eligible_share": eligible_count / observation_count,
                "positive_current_funding_count": positive_funding_count,
                "positive_current_funding_share": positive_funding_count / observation_count,
                "average_current_funding": row[4],
                "average_historical_funding": row[5],
                "positive_estimated_net_count": positive_net_count,
                "positive_estimated_net_share": positive_net_count / observation_count,
                "average_estimated_net_usdt": row[7],
                "minimum_estimated_net_usdt": row[8],
                "maximum_estimated_net_usdt": row[9],
                "average_break_even_settlements": row[10],
            }
        )

    runs_with_eligible = int(run_row[3])
    return {
        "status": "available",
        "source": "carry_scanner_history",
        "orders_enabled": False,
        "automatic_actions_enabled": False,
        "symbol": normalized_symbol,
        "lookback_hours": lookback_hours,
        "window": {
            "first_updated_at": run_row[0],
            "last_updated_at": run_row[1],
            "run_count": run_count,
            "runs_with_eligible_candidate": runs_with_eligible,
            "runs_with_eligible_candidate_share": runs_with_eligible / run_count,
        },
        "symbols": symbols,
    }


def _empty_summary(symbol: str | None, lookback_hours: int) -> dict[str, Any]:
    return {
        "status": "not_run",
        "source": "carry_scanner_history",
        "orders_enabled": False,
        "automatic_actions_enabled": False,
        "symbol": symbol,
        "lookback_hours": lookback_hours,
        "window": {
            "first_updated_at": None,
            "last_updated_at": None,
            "run_count": 0,
            "runs_with_eligible_candidate": 0,
            "runs_with_eligible_candidate_share": 0.0,
        },
        "symbols": [],
    }
