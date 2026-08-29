from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from fastapi import FastAPI, Query
from prometheus_client import CONTENT_TYPE_LATEST, Gauge, generate_latest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import FileResponse, Response
from starlette.staticfiles import StaticFiles

from apps.control_api.operator_data import merge_news_feed, prepare_stored_news, read_archived_news
from intelligence.news.ingestion import DurableNewsState
from platform_core.settings import load_settings
from storage.carry_scanner_history import read_carry_scan_history, summarize_carry_scan_history
from storage.database import engine
from storage.repositories import AuditRepository

app = FastAPI(title="Trading Platform Control API", version="0.2.0")
STATIC_ROOT = Path(__file__).with_name("static")
app.mount("/operator-assets", StaticFiles(directory=STATIC_ROOT), name="operator-assets")
READY = Gauge("trading_platform_ready", "Whether control plane dependencies are ready")
audit = AuditRepository()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> dict[str, str]:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        READY.set(1)
        return {"status": "ready", "database": "ok"}
    except Exception as exc:
        READY.set(0)
        return {"status": "degraded", "database": type(exc).__name__}


@app.get("/status")
def status() -> dict:
    mode = os.getenv("TRADING_MODE", "demo")
    try:
        settings = load_settings(mode, Path(os.getenv("PLATFORM_ROOT", "/app")))
        return {
            "mode": settings.mode,
            "venue": settings.venue,
            "product_type": settings.product_type,
            "instruments": settings.instruments,
            "numeraire": settings.numeraire,
            "nautilus_node_enabled": os.getenv("RUN_NAUTILUS_NODE", "false").lower() == "true",
            "carry_observer_enabled": os.getenv("ENABLE_CARRY_OBSERVER", "false").lower() == "true",
        }
    except Exception as exc:
        return {"mode": mode, "configuration_error": str(exc)}


@app.get("/integrations/bybit")
def bybit_status() -> dict:
    status_path = Path(os.getenv("BYBIT_SMOKE_STATUS_PATH", "/app/data/runtime/bybit-smoke.json"))
    result = {
        "environment": "demo",
        "credentials_configured": bool(os.getenv("BYBIT_DEMO_API_KEY")) and bool(os.getenv("BYBIT_DEMO_API_SECRET")),
        "order_smoke_locked": os.getenv("BYBIT_DEMO_ORDER_SMOKE_CONFIRMATION")
        != "I_UNDERSTAND_THIS_PLACES_A_DEMO_ORDER",
        "last_smoke": None,
    }
    if status_path.exists():
        try:
            result["last_smoke"] = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            result["status_error"] = type(exc).__name__
    return result


@app.get("/runtime/demo-strategy")
def demo_strategy_status() -> dict:
    status_path = Path(os.getenv("DEMO_STRATEGY_STATUS_PATH", "/app/data/runtime/demo-strategy.json"))
    result = {
        "node_enabled": os.getenv("RUN_NAUTILUS_NODE", "false").lower() == "true",
        "strategy_enabled": os.getenv("ENABLE_DEMO_STRATEGY", "false").lower() == "true",
        "orders_enabled": False,
        "last_status": None,
    }
    if status_path.exists():
        try:
            result["last_status"] = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            result["status_error"] = type(exc).__name__
    return result


@app.get("/runtime/carry")
def carry_runtime_status() -> dict:
    status_path = Path(os.getenv("CARRY_STATUS_PATH", "/app/data/runtime/carry-observer.json"))
    pair_status_path = Path(os.getenv("CARRY_PAIR_STATUS_PATH", "/app/data/runtime/carry-pair.json"))
    performance_path = Path(os.getenv("CARRY_PERFORMANCE_PATH", "/app/data/runtime/carry-performance.json"))
    alerts_path = Path(os.getenv("CARRY_ALERT_STATUS_PATH", "/app/data/runtime/carry-alerts.json"))
    scanner_path = Path(os.getenv("CARRY_SCANNER_STATUS_PATH", "/app/data/runtime/carry-scanner.json"))
    result = {
        "observer_enabled": os.getenv("ENABLE_CARRY_OBSERVER", "false").lower() == "true",
        "orders_enabled": False,
        "execution_gate": "one_shot_confirmation_required",
        "last_status": None,
        "last_pair": None,
        "performance": None,
        "alerts": None,
        "scanner": None,
    }
    if status_path.exists():
        try:
            result["last_status"] = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            result["status_error"] = type(exc).__name__
    if pair_status_path.exists():
        try:
            result["last_pair"] = json.loads(pair_status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            result["pair_status_error"] = type(exc).__name__
    if performance_path.exists():
        try:
            result["performance"] = json.loads(performance_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            result["performance_status_error"] = type(exc).__name__
    if alerts_path.exists():
        try:
            result["alerts"] = json.loads(alerts_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            result["alerts_status_error"] = type(exc).__name__
    if scanner_path.exists():
        try:
            result["scanner"] = json.loads(scanner_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            result["scanner_status_error"] = type(exc).__name__
    return result


@app.get("/runtime/carry-scanner")
def carry_scanner_runtime_status() -> dict:
    path = Path(os.getenv("CARRY_SCANNER_STATUS_PATH", "/app/data/runtime/carry-scanner.json"))
    if not path.exists():
        return {"status": "not_run", "orders_enabled": False, "automatic_actions_enabled": False}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "status": "invalid",
            "orders_enabled": False,
            "automatic_actions_enabled": False,
            "status_error": type(exc).__name__,
        }


@app.get("/runtime/carry-scanner/history")
def carry_scanner_history(symbol: str | None = None, limit: int = 100) -> dict:
    path = Path(os.getenv("CARRY_SCANNER_HISTORY_DB", "/app/data/carry/scanner-history.sqlite3"))
    try:
        return read_carry_scan_history(path, symbol=symbol, limit=limit)
    except (OSError, ValueError, sqlite3.Error) as exc:
        return {"status": "invalid", "symbol": symbol, "observations": [], "status_error": type(exc).__name__}


@app.get("/runtime/carry-scanner/summary")
def carry_scanner_summary(symbol: str | None = None, hours: int = 168) -> dict:
    path = Path(os.getenv("CARRY_SCANNER_HISTORY_DB", "/app/data/carry/scanner-history.sqlite3"))
    try:
        return summarize_carry_scan_history(path, symbol=symbol, lookback_hours=hours)
    except (OSError, ValueError, sqlite3.Error) as exc:
        return {
            "status": "invalid",
            "symbol": symbol,
            "lookback_hours": hours,
            "symbols": [],
            "status_error": type(exc).__name__,
        }


@app.get("/operator", include_in_schema=False)
def operator_console() -> FileResponse:
    return FileResponse(STATIC_ROOT / "operator.html")


@app.get("/operator/api/decisions")
async def operator_decisions(limit: int = Query(default=30, ge=1, le=100)) -> dict:
    try:
        decisions = await audit.get_recent_decisions(limit)
        return {"status": "available", "decisions": decisions}
    except (SQLAlchemyError, ValueError) as exc:
        return {"status": "degraded", "decisions": [], "status_error": type(exc).__name__}


@app.get("/operator/api/news")
async def operator_news(limit: int = Query(default=30, ge=1, le=100)) -> dict:
    archive_path = Path(os.getenv("NEWS_ARCHIVE_PATH", "/app/data/news"))
    archived = read_archived_news(archive_path, limit=limit)
    database_error = None
    try:
        stored = prepare_stored_news(await audit.get_recent_news_with_analysis(limit))
    except (SQLAlchemyError, ValueError) as exc:
        stored = []
        database_error = type(exc).__name__
    result = {
        "status": "available" if database_error is None else "degraded",
        "items": merge_news_feed(stored, archived, limit=limit),
        "analysis_enabled": os.getenv("INTELLIGENCE_ENABLED", "false").lower() == "true",
    }
    if database_error:
        result["status_error"] = database_error
    return result


@app.get("/research/backtest")
def backtest_status() -> dict:
    report_path = Path(os.getenv("NAUTILUS_BACKTEST_REPORT_PATH", "/app/data/runtime/nautilus-backtest.json"))
    if not report_path.exists():
        return {"status": "not_run", "report": None}
    try:
        return {"status": "available", "report": json.loads(report_path.read_text(encoding="utf-8"))}
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "invalid", "report": None, "status_error": type(exc).__name__}


@app.get("/research/m3")
def m3_research_status() -> dict:
    report_path = Path(os.getenv("M3_RESEARCH_REPORT_PATH", "/app/data/runtime/m3-research.json"))
    if not report_path.exists():
        return {"status": "not_run", "report": None}
    try:
        return {"status": "available", "report": json.loads(report_path.read_text(encoding="utf-8"))}
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "invalid", "report": None, "status_error": type(exc).__name__}


@app.get("/research/m4")
def m4_research_status() -> dict:
    report_path = Path(os.getenv("M4_RESEARCH_REPORT_PATH", "/app/data/runtime/m4-research.json"))
    if not report_path.exists():
        return {"status": "not_run", "report": None}
    try:
        return {"status": "available", "report": json.loads(report_path.read_text(encoding="utf-8"))}
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "invalid", "report": None, "status_error": type(exc).__name__}


@app.get("/research/m5")
def m5_research_status() -> dict:
    report_path = Path(os.getenv("M5_RESEARCH_REPORT_PATH", "/app/data/runtime/m5-research.json"))
    if not report_path.exists():
        return {"status": "not_run", "report": None}
    try:
        return {"status": "available", "report": json.loads(report_path.read_text(encoding="utf-8"))}
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "invalid", "report": None, "status_error": type(exc).__name__}


@app.get("/research/m7")
def m7_research_status() -> dict:
    report_path = Path(os.getenv("M7_RESEARCH_REPORT_PATH", "/app/data/runtime/m7-research.json"))
    if not report_path.exists():
        return {"status": "not_run", "report": None}
    try:
        return {"status": "available", "report": json.loads(report_path.read_text(encoding="utf-8"))}
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "invalid", "report": None, "status_error": type(exc).__name__}


@app.get("/research/m75")
def m75_research_status() -> dict:
    report_path = Path(os.getenv("M75_RESEARCH_REPORT_PATH", "/app/data/runtime/m75-research.json"))
    if not report_path.exists():
        return {"status": "not_run", "report": None}
    try:
        return {"status": "available", "report": json.loads(report_path.read_text(encoding="utf-8"))}
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "invalid", "report": None, "status_error": type(exc).__name__}


@app.get("/intelligence/news")
def news_ingestion_status() -> dict:
    state_path = Path(os.getenv("NEWS_STATE_PATH", "/app/data/runtime/news-worker-state.json"))
    archive_path = Path(os.getenv("NEWS_ARCHIVE_PATH", "/app/data/news"))
    result = DurableNewsState.load(state_path).public_status()
    result.update(
        {
            "enabled": os.getenv("NEWS_ENABLED", "false").lower() == "true",
            "forward_to_intelligence": os.getenv("NEWS_FORWARD_TO_INTELLIGENCE", "false").lower() == "true",
            "archived_articles": sum(1 for _ in archive_path.glob("raw/**/*.json")) if archive_path.exists() else 0,
        }
    )
    return result


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
