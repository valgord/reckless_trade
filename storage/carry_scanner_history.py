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
