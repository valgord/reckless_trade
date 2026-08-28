from __future__ import annotations

import json
import os
import subprocess
import sys
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.control_api.main import (
    backtest_status,
    bybit_status,
    carry_runtime_status,
    m3_research_status,
    m4_research_status,
    m5_research_status,
    m7_research_status,
    m75_research_status,
    news_ingestion_status,
)
from apps.trader import bybit_smoke
from apps.trader.bybit_smoke import (
    ORDER_SMOKE_CONFIRMATION,
    BybitDemoSmoke,
    SmokeCheckError,
    SmokeOptions,
    validate_order_confirmation,
)
from apps.trader.integrations.nautilus_bybit import build_bybit_client_configs


class DecimalValue:
    def __init__(self, value: str) -> None:
        self.value = Decimal(value)

    def as_decimal(self) -> Decimal:
        return self.value


class FakeBybitClient:
    def __init__(
        self,
        *,
        submit_fails: bool = False,
        cancel_fails: bool = False,
        cancel_lookup_misses: bool = False,
    ) -> None:
        self.instrument = SimpleNamespace(
            id=SimpleNamespace(value="BTCUSDT-SPOT.BYBIT"),
            price_precision=2,
            size_precision=6,
            price_increment=DecimalValue("0.01"),
            size_increment=DecimalValue("0.000001"),
            min_notional=DecimalValue("1"),
            min_quantity=DecimalValue("0.000001"),
        )
        self.ticker = SimpleNamespace(
            symbol="BTCUSDT",
            last_price="100000.00",
            bid1_price="99999.00",
            ask1_price="100001.00",
        )
        self.submit_fails = submit_fails
        self.cancel_fails = cancel_fails
        self.cancel_lookup_misses = cancel_lookup_misses
        self.submit_calls = 0
        self.cancel_calls = 0
        self.requests_cancelled = False

    async def request_instruments(self, *args):
        return [self.instrument]

    async def request_tickers(self, *args):
        return [self.ticker]

    async def get_account_details(self):
        return SimpleNamespace(read_only=0)

    async def request_account_state(self, *args):
        return SimpleNamespace(account_type="CASH", balances=[object(), object()])

    async def request_order_status_reports(self, *args, **kwargs):
        if self.cancel_calls and self.cancel_lookup_misses:
            return []
        return [object()]

    async def submit_order(self, *args, **kwargs):
        self.submit_calls += 1
        if self.submit_fails:
            raise TimeoutError("submit timed out")
        return SimpleNamespace(order_status="ACCEPTED")

    async def cancel_order(self, *args, **kwargs):
        self.cancel_calls += 1
        if self.cancel_fails:
            raise RuntimeError("cancel failed")
        if self.cancel_lookup_misses:
            raise RuntimeError("Order lookup failed after cancellation: No order returned after cancellation")
        return SimpleNamespace(order_status="CANCELED")

    def cancel_all_requests(self):
        self.requests_cancelled = True


class FakeBybitTypes:
    product_type = "SPOT"
    account_type = "UNIFIED"
    buy_side = "BUY"
    limit_order = "LIMIT"
    gtc = "GTC"

    @staticmethod
    def ticker_params(symbol):
        return symbol

    @staticmethod
    def account_id():
        return SimpleNamespace(value="BYBIT-UNIFIED")

    @staticmethod
    def client_order_id(value):
        return SimpleNamespace(value=value)

    @staticmethod
    def quantity(value):
        return value

    @staticmethod
    def price(value):
        return value


def smoke(client):
    return BybitDemoSmoke(client, types=FakeBybitTypes())


def test_builds_typed_demo_client_configs(monkeypatch):
    script = """
from apps.trader.integrations.nautilus_bybit import build_bybit_client_configs
data, execution = build_bybit_client_configs('demo', ['BTCUSDT-SPOT.BYBIT'])
assert type(data).__name__ == 'BybitDataClientConfig'
assert type(execution).__name__ == 'BybitExecClientConfig'
assert tuple(str(value) for value in data.product_types) == ('Spot',)
assert {value.value for value in data.instrument_provider.load_ids} == {'BTCUSDT-SPOT.BYBIT'}
"""
    env = os.environ.copy()
    env.update({"BYBIT_DEMO_API_KEY": "key", "BYBIT_DEMO_API_SECRET": "secret"})
    result = subprocess.run([sys.executable, "-c", script], env=env, text=True, capture_output=True, timeout=10)

    assert result.returncode == 0, result.stderr


def test_builds_mixed_spot_and_linear_demo_client_configs():
    script = """
from apps.trader.integrations.nautilus_bybit import build_bybit_client_configs
data, execution = build_bybit_client_configs(
    'demo',
    ['BTCUSDT-SPOT.BYBIT', 'BTCUSDT-LINEAR.BYBIT'],
)
assert tuple(str(value) for value in data.product_types) == ('Spot', 'Linear')
assert {value.value for value in data.instrument_provider.load_ids} == {
    'BTCUSDT-SPOT.BYBIT', 'BTCUSDT-LINEAR.BYBIT'
}
assert tuple(str(value) for value in execution.product_types) == ('Spot', 'Linear')
assert execution.futures_leverages == {'BTCUSDT-LINEAR': 1}
assert str(execution.position_mode['BTCUSDT-LINEAR']) == 'MERGED_SINGLE'
assert str(execution.margin_mode) == 'ISOLATED_MARGIN'
"""
    env = os.environ.copy()
    env.update({"BYBIT_DEMO_API_KEY": "key", "BYBIT_DEMO_API_SECRET": "secret"})

    result = subprocess.run([sys.executable, "-c", script], env=env, text=True, capture_output=True, timeout=10)

    assert result.returncode == 0, result.stderr


def test_trading_node_accepts_instrument_scoped_notional_limit():
    script = """
from apps.trader.integrations.nautilus_bybit import build_bybit_trading_node
from nautilus_trader.model.identifiers import InstrumentId
node = build_bybit_trading_node(
    'demo',
    ['BTCUSDT-SPOT.BYBIT'],
    risk={'max_order_notional_usdt': 10},
)
limit = node.kernel.risk_engine.max_notional_per_order(InstrumentId.from_str('BTCUSDT-SPOT.BYBIT'))
assert limit == 10
node.dispose()
"""
    env = os.environ.copy()
    env.update({"BYBIT_DEMO_API_KEY": "key", "BYBIT_DEMO_API_SECRET": "secret"})
    result = subprocess.run([sys.executable, "-c", script], env=env, text=True, capture_output=True, timeout=20)

    assert result.returncode == 0, result.stderr


def test_live_client_config_has_an_independent_gate(monkeypatch):
    monkeypatch.setenv("BYBIT_API_KEY", "key")
    monkeypatch.setenv("BYBIT_API_SECRET", "secret")
    monkeypatch.delenv("ALLOW_LIVE_TRADING", raising=False)

    with pytest.raises(RuntimeError, match="Live trading is locked"):
        build_bybit_client_configs("live", ["BTCUSDT-SPOT.BYBIT"])


@pytest.mark.asyncio
async def test_demo_smoke_checks_public_private_and_reconciliation():
    result = await smoke(FakeBybitClient()).run(SmokeOptions())

    assert result["public"]["instrument"] == "BTCUSDT-SPOT.BYBIT"
    assert result["account"] == {
        "authenticated": True,
        "read_only_key": False,
        "account_type": "CASH",
        "balance_count": 2,
    }
    assert result["reconciliation"] == {"queried": True, "open_order_count": 1}


def test_order_smoke_requires_exact_confirmation():
    with pytest.raises(SmokeCheckError, match="Order smoke is locked"):
        validate_order_confirmation("yes")
    validate_order_confirmation(ORDER_SMOKE_CONFIRMATION)


@pytest.mark.asyncio
async def test_public_smoke_never_passes_credentials_to_client(monkeypatch, tmp_path):
    client = FakeBybitClient()
    received = None

    def create_client(api_key, api_secret):
        nonlocal received
        received = (api_key, api_secret)
        return client

    monkeypatch.setenv("BYBIT_DEMO_API_KEY", "configured-key")
    monkeypatch.setenv("BYBIT_DEMO_API_SECRET", "configured-secret")
    monkeypatch.setattr(bybit_smoke, "create_demo_client", create_client)
    monkeypatch.setattr(bybit_smoke, "NautilusBybitTypes", FakeBybitTypes)

    return_code = await bybit_smoke.run(SmokeOptions(public_only=True), tmp_path / "status.json")

    assert return_code == 0
    assert received == (None, None)
    assert client.requests_cancelled is True


@pytest.mark.asyncio
async def test_order_smoke_submits_small_order_and_cancels(monkeypatch):
    monkeypatch.setenv("BYBIT_DEMO_ORDER_SMOKE_MAX_NOTIONAL", "2")
    client = FakeBybitClient()
    result = await smoke(client)._submit_and_cancel(client.instrument, client.ticker)

    assert client.submit_calls == 1
    assert client.cancel_calls == 1
    assert result["submitted"] is True
    assert result["cancelled"] is True
    assert Decimal(result["notional"]) <= Decimal("2")


@pytest.mark.asyncio
async def test_order_smoke_surfaces_failed_cancellation():
    client = FakeBybitClient(cancel_fails=True)

    with pytest.raises(SmokeCheckError, match="was submitted but cancellation failed"):
        await smoke(client)._submit_and_cancel(client.instrument, client.ticker)
    assert client.cancel_calls == 1


@pytest.mark.asyncio
async def test_order_smoke_accepts_missing_order_after_cancellation():
    client = FakeBybitClient(cancel_lookup_misses=True)

    result = await smoke(client)._submit_and_cancel(client.instrument, client.ticker)

    assert client.cancel_calls == 1
    assert result["cancelled"] is True
    assert result["cancel_status"] == "NOT_OPEN"


@pytest.mark.asyncio
async def test_order_smoke_cancels_after_unknown_submit_outcome():
    client = FakeBybitClient(submit_fails=True)

    with pytest.raises(SmokeCheckError, match="Submit outcome is unknown"):
        await smoke(client)._submit_and_cancel(client.instrument, client.ticker)
    assert client.cancel_calls == 1


@pytest.mark.asyncio
async def test_order_smoke_rechecks_cap_after_quantity_rounding(monkeypatch):
    monkeypatch.setenv("BYBIT_DEMO_ORDER_SMOKE_MAX_NOTIONAL", "2")
    client = FakeBybitClient()
    client.instrument.min_quantity = DecimalValue("1")

    with pytest.raises(SmokeCheckError, match="Rounded order notional"):
        await smoke(client)._submit_and_cancel(client.instrument, client.ticker)
    assert client.submit_calls == 0


def test_control_api_reads_sanitized_smoke_status(monkeypatch, tmp_path):
    path = tmp_path / "bybit-smoke.json"
    path.write_text(json.dumps({"status": "passed", "account": {"balance_count": 2}}), encoding="utf-8")
    monkeypatch.setenv("BYBIT_SMOKE_STATUS_PATH", str(path))
    monkeypatch.setenv("BYBIT_DEMO_API_KEY", "key")
    monkeypatch.setenv("BYBIT_DEMO_API_SECRET", "secret")

    result = bybit_status()

    assert result["credentials_configured"] is True
    assert result["order_smoke_locked"] is True
    assert result["last_smoke"]["status"] == "passed"


def test_control_api_reads_backtest_report(monkeypatch, tmp_path):
    path = tmp_path / "backtest.json"
    path.write_text(json.dumps({"strategy_return": -0.1, "total_orders": 12}), encoding="utf-8")
    monkeypatch.setenv("NAUTILUS_BACKTEST_REPORT_PATH", str(path))

    result = backtest_status()

    assert result == {"status": "available", "report": {"strategy_return": -0.1, "total_orders": 12}}


def test_control_api_reads_locked_carry_observer_status(monkeypatch, tmp_path):
    path = tmp_path / "carry.json"
    performance_path = tmp_path / "carry-performance.json"
    path.write_text(json.dumps({"status": "hedged", "orders_enabled": False}), encoding="utf-8")
    performance_path.write_text(
        json.dumps({"status": "monitoring", "performance": {"estimated_net_pnl_usdt": 0.01}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CARRY_STATUS_PATH", str(path))
    monkeypatch.setenv("CARRY_PERFORMANCE_PATH", str(performance_path))
    monkeypatch.setenv("ENABLE_CARRY_OBSERVER", "true")

    result = carry_runtime_status()

    assert result["observer_enabled"] is True
    assert result["orders_enabled"] is False
    assert result["execution_gate"] == "one_shot_confirmation_required"
    assert result["last_status"]["status"] == "hedged"
    assert result["performance"]["performance"]["estimated_net_pnl_usdt"] == 0.01


def test_control_api_reads_m3_research_report(monkeypatch, tmp_path):
    path = tmp_path / "m3.json"
    path.write_text(json.dumps({"promotion": {"approved": False}, "trials_recorded": 63}), encoding="utf-8")
    monkeypatch.setenv("M3_RESEARCH_REPORT_PATH", str(path))

    result = m3_research_status()

    assert result["status"] == "available"
    assert result["report"]["promotion"]["approved"] is False


def test_control_api_reads_m4_research_report(monkeypatch, tmp_path):
    path = tmp_path / "m4.json"
    path.write_text(json.dumps({"stage": "m4", "promotion": {"approved": False}}), encoding="utf-8")
    monkeypatch.setenv("M4_RESEARCH_REPORT_PATH", str(path))

    result = m4_research_status()

    assert result["status"] == "available"
    assert result["report"]["stage"] == "m4"


def test_control_api_reads_m5_research_report(monkeypatch, tmp_path):
    path = tmp_path / "m5.json"
    path.write_text(json.dumps({"stage": "m5", "promotion": {"approved": False}}), encoding="utf-8")
    monkeypatch.setenv("M5_RESEARCH_REPORT_PATH", str(path))

    result = m5_research_status()

    assert result["status"] == "available"
    assert result["report"]["stage"] == "m5"


def test_control_api_reads_m7_research_report(monkeypatch, tmp_path):
    path = tmp_path / "m7.json"
    path.write_text(json.dumps({"stage": "M7", "gate": {"promoted": False}}), encoding="utf-8")
    monkeypatch.setenv("M7_RESEARCH_REPORT_PATH", str(path))

    result = m7_research_status()

    assert result["status"] == "available"
    assert result["report"]["gate"]["promoted"] is False


def test_control_api_reads_m75_research_report(monkeypatch, tmp_path):
    path = tmp_path / "m75.json"
    path.write_text(json.dumps({"stage": "m7.5-fiat-alpha-discovery", "research_gate": True}), encoding="utf-8")
    monkeypatch.setenv("M75_RESEARCH_REPORT_PATH", str(path))

    result = m75_research_status()

    assert result["status"] == "available"
    assert result["report"]["stage"] == "m7.5-fiat-alpha-discovery"


def test_control_api_reads_news_ingestion_health(monkeypatch, tmp_path):
    state_path = tmp_path / "news-state.json"
    state_path.write_text(json.dumps({"delivered": ["a"], "sources": {}, "version": 1}), encoding="utf-8")
    monkeypatch.setenv("NEWS_STATE_PATH", str(state_path))
    monkeypatch.setenv("NEWS_ARCHIVE_PATH", str(tmp_path / "news"))

    result = news_ingestion_status()

    assert result["delivered_fingerprints"] == 1
    assert result["archived_articles"] == 0
