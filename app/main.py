"""NetPulse FastAPI application entrypoint."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import SessionLocal, init_db
from .monitor.engine import engine
from .routers import auth, dashboard, devices, events, metrics, system

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("netpulse")

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting %s", settings.app_name)

    # --- security guardrails ---
    if settings.secret_key in ("dev-insecure-secret-change-me", "", "change-me-to-a-long-random-string"):
        log.warning(
            "SECRET_KEY is using an insecure default. Set a strong SECRET_KEY in .env "
            "(python -c \"import secrets; print(secrets.token_urlsafe(48))\")"
        )
    if settings.is_sqlite and settings.database_url.endswith("./netpulse.db") and settings.cookie_secure:
        log.info("Running SQLite in the project directory with secure cookies enabled.")

    await init_db()
    async with SessionLocal() as db:
        await auth.ensure_first_admin(db)
    await engine.start()
    try:
        yield
    finally:
        await engine.stop()
        log.info("%s stopped", settings.app_name)


app = FastAPI(
    title=settings.app_name,
    description="Free & open-source network monitoring (Ping / SNMP / TCP / HTTP).",
    version="1.0.0",
    lifespan=lifespan,
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(dashboard.router)
app.include_router(auth.router)
app.include_router(devices.router)
app.include_router(metrics.router)
app.include_router(events.router)
app.include_router(system.router)


@app.get("/health", tags=["meta"])
async def health():
    return JSONResponse({"status": "ok", "app": settings.app_name})
