from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True, slots=True)
class PlatformSettings:
    mode: str
    venue: str
    product_type: str
    instruments: tuple[str, ...]
    numeraire: str
    benchmark: str
    live_allowed: bool
    config_path: Path
    raw: dict[str, Any]

    @property
    def is_live(self) -> bool:
        return self.mode == "live"


def load_settings(mode: str | None = None, root: Path | None = None) -> PlatformSettings:
    selected = (mode or os.getenv("TRADING_MODE", "demo")).lower()
    if selected not in {"backtest", "demo", "live"}:
        raise ValueError(f"Unsupported TRADING_MODE={selected!r}")
    root = root or Path(os.getenv("PLATFORM_ROOT", Path.cwd()))
    path = root / "configs" / selected / "platform.yaml"
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    trading = raw.get("trading", {})
    objective = raw.get("objective", {})
    venue = str(trading.get("venue", "BYBIT"))
    product_type = str(trading.get("product_type", "SPOT"))
    instruments = tuple(str(x) for x in trading.get("instruments", ["BTCUSDT-SPOT.BYBIT"]))
    live_allowed = os.getenv("ALLOW_LIVE_TRADING", "false").lower() == "true"
    if selected == "live" and not live_allowed:
        raise RuntimeError("Live trading is locked. Set ALLOW_LIVE_TRADING=true explicitly.")
    return PlatformSettings(
        mode=selected,
        venue=venue,
        product_type=product_type,
        instruments=instruments,
        numeraire=str(objective.get("numeraire", "BTC")),
        benchmark=str(objective.get("benchmark", "BUY_AND_HOLD_BTC")),
        live_allowed=live_allowed,
        config_path=path,
        raw=raw,
    )
