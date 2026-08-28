from __future__ import annotations

from typing import Any


def evaluate_scanner_transition(
    scanner: dict[str, Any] | None,
    previous_state: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if not scanner or scanner.get("status") != "available" or not scanner.get("updated_at"):
        return {"status": "scanner_unavailable", "newly_eligible": []}, None
    current_candidates = {
        str(candidate["symbol"]): candidate
        for candidate in scanner.get("candidates") or []
        if candidate.get("eligible") is True and candidate.get("symbol")
    }
    next_state = {
        "schema_version": 1,
        "scanner_updated_at": str(scanner["updated_at"]),
        "eligible_symbols": sorted(current_candidates),
    }
    if previous_state is None:
        return {"status": "baseline_recorded", "newly_eligible": []}, next_state
    if previous_state.get("scanner_updated_at") == scanner.get("updated_at"):
        return {"status": "unchanged", "newly_eligible": []}, None
    previous_symbols = {str(symbol) for symbol in previous_state.get("eligible_symbols") or []}
    newly_eligible = [
        current_candidates[symbol] for symbol in sorted(set(current_candidates).difference(previous_symbols))
    ]
    return {
        "status": "newly_eligible" if newly_eligible else "state_updated",
        "scanner_updated_at": str(scanner["updated_at"]),
        "newly_eligible": newly_eligible,
    }, next_state
