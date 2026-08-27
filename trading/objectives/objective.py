from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Objective:
    numeraire: str = "BTC"
    benchmark: str = "BUY_AND_HOLD_BTC"
    maximize: str = "terminal_numeraire"
