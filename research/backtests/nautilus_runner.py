from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True, slots=True)
class NautilusBacktestReport:
    instrument_id: str
    bar_type: str
    bars: int
    start: str
    end: str
    first_close: float
    last_close: float
    buy_hold_return: float
    strategy_return: float
    excess_return_vs_buy_hold: float
    strategy_return_in_btc: float
    total_orders: int
    total_positions: int
    elapsed_time: float
    summary: dict[str, Any]
    stats_pnls: dict[str, Any]
    stats_returns: dict[str, Any]
    cost_assumptions: dict[str, float]


def build_run_config(
    catalog_path: Path,
    platform_config_path: Path,
    instrument_id: str = "BTCUSDT-SPOT.BYBIT",
    bar_spec: str = "15-MINUTE-LAST-EXTERNAL",
    trade_notional: Decimal = Decimal("1000"),
    total_cost_bps: float = 12.5,
    enabled_strategies: tuple[str, ...] = (),
    min_hold_bars: int = 0,
    allowed_regimes: tuple[str, ...] = (),
    regime_entry_bars: int = 1,
):
    from nautilus_trader.config import (
        BacktestDataConfig,
        BacktestEngineConfig,
        BacktestRunConfig,
        BacktestVenueConfig,
        ImportableFeeModelConfig,
        ImportableFillModelConfig,
        ImportableStrategyConfig,
        LoggingConfig,
        RiskEngineConfig,
    )
    from nautilus_trader.model.data import Bar

    strategy = ImportableStrategyConfig(
        strategy_path="research.backtests.nautilus_strategy:DomainPipelineBacktestStrategy",
        config_path="research.backtests.nautilus_strategy:DomainPipelineBacktestConfig",
        config={
            "instrument_id": instrument_id,
            "bar_type": f"{instrument_id}-{bar_spec}",
            "platform_config_path": str(platform_config_path),
            "trade_notional": str(trade_notional),
            "enabled_strategies": list(enabled_strategies),
            "min_hold_bars": min_hold_bars,
            "allowed_regimes": list(allowed_regimes),
            "regime_entry_bars": regime_entry_bars,
        },
    )
    return BacktestRunConfig(
        venues=[
            BacktestVenueConfig(
                name="BYBIT",
                oms_type="NETTING",
                account_type="CASH",
                base_currency=None,
                starting_balances=["10000 USDT"],
                fill_model=ImportableFillModelConfig(
                    fill_model_path="nautilus_trader.backtest.models:FillModel",
                    config_path="nautilus_trader.backtest.config:FillModelConfig",
                    config={"prob_fill_on_limit": 1.0, "prob_slippage": 0.0, "random_seed": 42},
                ),
                fee_model=ImportableFeeModelConfig(
                    fee_model_path="research.backtests.costs:AllInBpsFeeModel",
                    config_path="research.backtests.costs:AllInBpsFeeModelConfig",
                    config={"total_bps": total_cost_bps},
                ),
                bar_execution=True,
                allow_cash_borrowing=False,
            )
        ],
        data=[
            BacktestDataConfig(
                catalog_path=str(catalog_path),
                data_cls=Bar,
                bar_types=[f"{instrument_id}-{bar_spec}"],
            )
        ],
        engine=BacktestEngineConfig(
            strategies=[strategy],
            logging=LoggingConfig(bypass_logging=True),
            risk_engine=RiskEngineConfig(
                bypass=False,
                max_notional_per_order={instrument_id: int(trade_notional)},
            ),
        ),
        raise_exception=True,
        dispose_on_completion=False,
    )


def run_nautilus_backtest(
    catalog_path: Path,
    platform_config_path: Path,
    instrument_id: str = "BTCUSDT-SPOT.BYBIT",
    bar_spec: str = "15-MINUTE-LAST-EXTERNAL",
    trade_notional: Decimal = Decimal("1000"),
    enabled_strategies: tuple[str, ...] = (),
    min_hold_bars: int = 0,
    allowed_regimes: tuple[str, ...] = (),
    regime_entry_bars: int = 1,
) -> NautilusBacktestReport:
    from nautilus_trader.backtest.node import BacktestNode
    from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

    catalog = ParquetDataCatalog(str(catalog_path))
    bar_type = f"{instrument_id}-{bar_spec}"
    bars = catalog.bars(bar_types=[bar_type])
    if len(bars) < 2:
        raise ValueError(f"Catalog has insufficient data for {bar_type}")

    raw = yaml.safe_load(platform_config_path.read_text(encoding="utf-8")) or {}
    costs = raw.get("cost_model", {})
    total_cost_bps = (
        float(costs.get("fees_bps", 10)) + float(costs.get("slippage_bps", 2)) + float(costs.get("spread_bps", 1)) / 2
    )
    run_config = build_run_config(
        catalog_path,
        platform_config_path,
        instrument_id,
        bar_spec,
        trade_notional,
        total_cost_bps,
        enabled_strategies,
        min_hold_bars,
        allowed_regimes,
        regime_entry_bars,
    )
    node = BacktestNode(configs=[run_config])
    try:
        result = node.run()[0]
    finally:
        node.dispose()
    first_close = float(str(bars[0].close))
    last_close = float(str(bars[-1].close))
    one_way_cost = total_cost_bps / 10_000
    buy_hold_return = (last_close / first_close) * (1 - one_way_cost) - 1
    strategy_return = float(result.stats_pnls.get("USDT", {}).get("PnL% (total)", 0.0)) / 100
    return NautilusBacktestReport(
        instrument_id=instrument_id,
        bar_type=bar_type,
        bars=len(bars),
        start=datetime.fromtimestamp(bars[0].ts_event / 1_000_000_000, tz=UTC).isoformat(),
        end=datetime.fromtimestamp(bars[-1].ts_event / 1_000_000_000, tz=UTC).isoformat(),
        first_close=first_close,
        last_close=last_close,
        buy_hold_return=buy_hold_return,
        strategy_return=strategy_return,
        excess_return_vs_buy_hold=strategy_return - buy_hold_return,
        strategy_return_in_btc=(1 + strategy_return) / (1 + buy_hold_return) - 1,
        total_orders=result.total_orders,
        total_positions=result.total_positions,
        elapsed_time=result.elapsed_time,
        summary=_json_safe(result.summary),
        stats_pnls=_json_safe(result.stats_pnls),
        stats_returns=_json_safe(result.stats_returns),
        cost_assumptions={
            "fees_bps": float(costs.get("fees_bps", 10)),
            "slippage_bps": float(costs.get("slippage_bps", 2)),
            "spread_bps": float(costs.get("spread_bps", 1)),
        },
    )


def write_report(path: Path, report: NautilusBacktestReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(report), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value
    return str(value)
