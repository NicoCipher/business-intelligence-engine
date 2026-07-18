"""
main.py — FastAPI application for BIA-OS Version 1

Responsibilities:
  - Configure logging
  - Initialise the database on startup
  - Mount all API routers
  - Provide a health endpoint and a pipeline trigger endpoint
  - Configure CORS for the local React dev server

What does NOT live here:
  - Business logic (that's in opportunity_engine/)
  - Data collection (that's in collectors/)
  - Database queries (that's in api/*)

Running locally:
  uvicorn main:app --reload --host 127.0.0.1 --port 8000

The --reload flag watches for file changes and restarts automatically.
Do not use --reload in production.
"""

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware

import database
from config import API_HOST, API_PORT
from api import opportunities, signals, reports
from domains.registry import DomainRegistry

# ── Logging ───────────────────────────────────────────────────────────────
# Structured logging from day one. Every module uses getLogger(__name__),
# which automatically creates a hierarchy we can filter at any level.

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("bia-os")


# ── Lifespan ──────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Run startup tasks before the server begins accepting requests,
    and cleanup tasks after the last request is served.

    Startup:
      - Initialise SQLite schema (idempotent — safe on every restart)

    Shutdown:
      - Nothing required yet. Add connection pool teardown here if
        we ever move to a server database.
    """
    logger.info("BIA-OS starting up…")
    database.initialize()
    DomainRegistry.discover_and_register()

    stats = database.get_stats()
    logger.info(
        f"Database ready — "
        f"{stats['signals']} signals, "
        f"{stats['opportunities']} opportunities"
    )

    yield   # Server is live between here and the next line

    logger.info("BIA-OS shutting down.")


# ── Application ───────────────────────────────────────────────────────────

app = FastAPI(
    title="BIA-OS API",
    description=(
        "Business Intelligence Autonomous Operating System — Version 1.\n\n"
        "Collects signals from public data sources, detects opportunity patterns, "
        "and returns scored, evidence-backed recommendations."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",      # Swagger UI
    redoc_url="/api/redoc",    # ReDoc
    openapi_url="/api/openapi.json",
)

# CORS: allow the local React dev server to call this API.
# In production, replace the origins list with your actual domain.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",    # Create React App
        "http://localhost:5173",    # Vite
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type"],
    allow_credentials=False,
)


# ── Routers ───────────────────────────────────────────────────────────────

app.include_router(
    opportunities.router,
    prefix="/api/v1/opportunities",
    tags=["opportunities"],
)
app.include_router(
    signals.router,
    prefix="/api/v1/signals",
    tags=["signals"],
)
app.include_router(
    reports.router,
    prefix="/api/v1/reports",
    tags=["reports"],
)


# ── Utility endpoints ─────────────────────────────────────────────────────

@app.get("/api/v1/health", tags=["system"])
def health():
    """
    Returns 200 when the server is running.
    The React frontend polls this to display the connection status badge.
    """
    stats = database.get_stats()
    return {
        "status":  "ok",
        "version": "1.0.0",
        "db":      stats,
    }


@app.post("/api/v1/pipeline/run", tags=["system"])
async def run_pipeline(background_tasks: BackgroundTasks):
    """
    Trigger a full collection + detection cycle in the background.

    Returns immediately. The pipeline runs asynchronously.
    Poll GET /api/v1/signals/stats to see when new signals arrive.

    In production, replace this with a scheduled cron job or GitHub Action.
    This endpoint exists for manual triggering during development.
    """
    background_tasks.add_task(_run_pipeline_task)
    return {"status": "pipeline started", "message": "Collection running in background"}


async def _run_pipeline_task():
    """
    Full pipeline: collect → detect → persist.

    Runs in a background task. Errors are logged but do not crash the server.
    """
    import asyncio
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _pipeline_sync)


def _pipeline_sync():
    """Synchronous pipeline execution (runs in thread pool via run_in_executor)."""
    from collectors.hn_collector import HNCollector
    from collectors.reddit_collector import RedditCollector
    from opportunity_engine.detector import PatternDetector
    import database as db

    logger.info("Pipeline run started")
    all_signals = []

    for CollectorClass in [HNCollector, RedditCollector]:
        try:
            collector = CollectorClass()
            collected = collector.collect()
            count = collector.persist(collected)
            all_signals.extend(collected)
            logger.info(f"{CollectorClass.SOURCE_NAME}: {count} new signals")
        except Exception:
            logger.exception(f"Collector {CollectorClass.__name__} failed")

    if len(all_signals) >= 2:
        detector = PatternDetector()
        new_opps = detector.detect_and_persist(all_signals)
        logger.info(f"Pipeline complete — {new_opps} new opportunities detected")
    else:
        logger.info("Not enough signals for pattern detection this run")
