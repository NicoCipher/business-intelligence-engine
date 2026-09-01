"""
main.py — FastAPI application for BIA-OS Version 1

Responsibilities:
  - Configure logging
  - Restore the database from durable storage if needed, then initialise it
  - Mount all API routers
  - Provide a health endpoint and a pipeline trigger endpoint
  - Configure CORS for the local React dev server
  - Apply cross-cutting security middleware (body size limits, headers)

What does NOT live here:
  - Business logic (that's in opportunity_engine/)
  - Data collection (that's in collectors/)
  - Database queries (that's in api/*)
  - Auth logic (that's in auth.py)
  - Locking logic (that's in locking.py)
  - Durable persistence logic (that's in persistence.py)

V1 is kept private by design (no public network exposure) -- see the
accepted V1 security review. Auth (auth.py) is real and enforced on
every mutating endpoint regardless, as defense-in-depth today and the
primary boundary the moment network isolation is ever lifted.

Running locally:
  uvicorn main:app --reload --host 127.0.0.1 --port 8000

The --reload flag watches for file changes and restarts automatically.
Do not use --reload in production.
"""

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, BackgroundTasks, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import auth
import config
import database
import locking
import persistence
from config import API_HOST, API_PORT
from api import opportunities, signals, reports, problems, changes, operator_state, collectors
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

PIPELINE_LOCK_PATH = config.DATA_DIR / "pipeline.lock"
REPORT_LOCK_PATH = config.DATA_DIR / "report.lock"


# ── Lifespan ──────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Run startup tasks before the server begins accepting requests,
    and cleanup tasks after the last request is served.

    Startup:
      - Restore the database from durable storage if this is a cold
        start (persistence.pull() -- never overwrites a live database)
      - Initialise SQLite schema (idempotent — safe on every restart)

    Shutdown:
      - Nothing required yet. Add connection pool teardown here if
        we ever move to a server database.
    """
    logger.info("BIA-OS starting up…")
    persistence.pull()
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
    allow_headers=["Content-Type", "Authorization"],
    allow_credentials=False,
)

# Security middleware: request body size limits and defensive headers.
# See middleware.py for why these exist and what they don't replace
# (frontend-side safe rendering of Signal-derived text).
from middleware import BodySizeLimitMiddleware, SecurityHeadersMiddleware  # noqa: E402
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(BodySizeLimitMiddleware)


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
app.include_router(
    problems.router,
    prefix="/api/v1/problems",
    tags=["problems"],
)
app.include_router(
    changes.router,
    prefix="/api/v1/changes",
    tags=["changes"],
)
app.include_router(
    operator_state.router,
    prefix="/api/v1/operator-state",
    tags=["operator-state"],
)
app.include_router(
    collectors.router,
    prefix="/api/v1/system",
    tags=["system"],
)


# ── Utility endpoints ─────────────────────────────────────────────────────

@app.get("/api/v1/health", tags=["system"])
def health():
    """
    Returns 200 when the server is running.
    The React frontend polls this to display the connection status badge.

    Deliberately unauthenticated -- a health check needs to work even
    for monitoring tooling that predates or sits outside any API key
    configuration. It reveals no sensitive data.
    """
    stats = database.get_stats()
    return {
        "status":  "ok",
        "version": "1.0.0",
        "db":      stats,
    }


@app.post("/api/v1/pipeline/run", tags=["system"])
async def run_pipeline(
    background_tasks: BackgroundTasks,
    actor: auth.Actor = Depends(auth.get_current_actor),
):
    """
    Trigger a full collection + detection cycle in the background.

    Returns immediately. The pipeline runs asynchronously.
    Poll GET /api/v1/signals/stats to see when new signals arrive.

    Returns 409 if a pipeline run is already in progress -- checked
    here for immediate feedback; _pipeline_sync's own lock is the real,
    race-free guarantee (see locking.py).

    In production, replace this with a scheduled cron job or GitHub Action.
    This endpoint exists for manual triggering during development.
    """
    if locking.is_locked(PIPELINE_LOCK_PATH):
        raise HTTPException(status_code=409, detail="A pipeline run is already in progress")

    logger.info(f"Pipeline run triggered by {actor}")
    background_tasks.add_task(_run_pipeline_task)
    return {"status": "pipeline started", "message": "Collection running in background"}


async def _run_pipeline_task():
    """
    Full pipeline: collect → extract → detect → (report), per active domain.

    Runs in a background task. Errors are logged but do not crash the server.
    """
    import asyncio
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _pipeline_sync)


def _pipeline_sync():
    """
    Synchronous pipeline execution (runs in thread pool via run_in_executor).

    Delegates entirely to pipeline.run_full_pipeline() — the same function
    collect.py's CLI entry point calls. There is no pipeline logic here;
    this function only exists to bridge FastAPI's background-task/executor
    machinery to the synchronous pipeline implementation.

    Guarded by an exclusive file lock (locking.py) so a second concurrent
    trigger can never write to SQLite at the same time as this one --
    previously a real, silent failure mode (a lock-collision exception
    that a narrow except clause didn't catch). Any exception is now
    caught broadly and logged with a full traceback, never swallowed.
    On success, the database is snapshotted to durable storage
    (persistence.push()).
    """
    from pipeline import run_full_pipeline

    try:
        with locking.exclusive_lock(PIPELINE_LOCK_PATH):
            logger.info("Pipeline run started")
            try:
                result = run_full_pipeline(generate_report=False)
            except Exception:
                logger.exception("Pipeline run failed")
                return

            for d in result.domains:
                logger.info(
                    f"[{d.domain_id}] {d.signals_persisted} new signals, "
                    f"{d.opportunities_detected} new opportunities"
                )
            logger.info(
                f"Pipeline complete — {result.total_signals} total signals, "
                f"{result.total_opportunities} total opportunities across "
                f"{len(result.domains)} domain(s)"
            )
            persistence.push()
    except locking.LockBusyError:
        logger.warning("Pipeline run skipped -- another run is already in progress")
