from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from prometheus_client import CONTENT_TYPE_LATEST, Gauge, generate_latest
from sqlalchemy import text
from starlette.responses import Response

from platform_core.settings import load_settings
from storage.database import engine

app = FastAPI(title="Trading Platform Control API", version="0.2.0")
READY = Gauge("trading_platform_ready", "Whether control plane dependencies are ready")


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
        return {"mode": settings.mode, "venue": settings.venue, "product_type": settings.product_type,
                "instruments": settings.instruments, "numeraire": settings.numeraire,
                "nautilus_node_enabled": os.getenv("RUN_NAUTILUS_NODE", "false").lower() == "true"}
    except Exception as exc:
        return {"mode": mode, "configuration_error": str(exc)}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
