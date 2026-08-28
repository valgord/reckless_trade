from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from research.backtests.nautilus_runner import build_run_config
from research.data.bybit_catalog import (
    bar_time_grid_gaps,
    last_completed_bar_end,
    parse_bar_interval,
    split_contiguous_bars,
    validate_bar_series,
)


def test_bar_interval_and_completed_boundary() -> None:
    interval = parse_bar_interval("15-MINUTE-LAST-EXTERNAL")
    now = datetime(2026, 8, 27, 12, 17, 42, tzinfo=UTC)

    assert interval == timedelta(minutes=15)
    assert last_completed_bar_end(now, interval) == datetime(2026, 8, 27, 12, 15, tzinfo=UTC)


def test_bar_validation_rejects_time_grid_gap() -> None:
    step = 15 * 60 * 1_000_000_000
    bars = [SimpleNamespace(ts_event=step), SimpleNamespace(ts_event=step * 3)]

    assert bar_time_grid_gaps(bars, timedelta(minutes=15)) == [(step, step * 3)]
    with pytest.raises(ValueError, match=r"time-grid gaps.*1 missing bars"):
        validate_bar_series(bars, timedelta(minutes=15))


def test_fresh_bars_are_split_around_existing_catalog_intervals() -> None:
    step = 15 * 60 * 1_000_000_000
    bars = [
        SimpleNamespace(ts_event=step),
        SimpleNamespace(ts_event=step * 2),
        SimpleNamespace(ts_event=step * 5),
        SimpleNamespace(ts_event=step * 6),
    ]

    segments = split_contiguous_bars(bars, timedelta(minutes=15))

    assert [[bar.ts_event for bar in segment] for segment in segments] == [
        [step, step * 2],
        [step * 5, step * 6],
    ]


def test_backtest_run_config_targets_catalog_bar_type() -> None:
    config = build_run_config(Path("data/catalog"), Path("configs/backtest/platform.yaml").resolve())

    assert config.venues[0].name == "BYBIT"
    assert config.venues[0].allow_cash_borrowing is False
    assert config.data[0].query["identifiers"] == ["BTCUSDT-SPOT.BYBIT-15-MINUTE-LAST-EXTERNAL"]
    assert config.engine.risk_engine.max_notional_per_order == {"BTCUSDT-SPOT.BYBIT": 1000}
    assert config.venues[0].fee_model.config == {"total_bps": 12.5}


def test_backtest_run_config_passes_research_execution_overrides() -> None:
    config = build_run_config(
        Path("data/catalog"),
        Path("configs/backtest/platform.yaml").resolve(),
        enabled_strategies=("trend_following",),
        min_hold_bars=96,
        allowed_regimes=("trend_up",),
        regime_entry_bars=16,
    )

    strategy = config.engine.strategies[0].config
    assert strategy["enabled_strategies"] == ["trend_following"]
    assert strategy["min_hold_bars"] == 96
    assert strategy["allowed_regimes"] == ["trend_up"]
    assert strategy["regime_entry_bars"] == 16
