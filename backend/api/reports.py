"""
api/reports.py — Weekly report endpoints

Routes:
  GET  /api/v1/reports                  list available reports (newest first)
  GET  /api/v1/reports/latest           latest generated report (most common call)
  GET  /api/v1/reports/{week_key}       specific week, e.g. 2026-W28
  POST /api/v1/reports/generate         generate report for current week (background, protected)
"""

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

import auth
import config
import database
import locking
import persistence
from database import decode_json
from report.generator import ReportGenerator

logger = logging.getLogger(__name__)
router = APIRouter()

REPORT_LOCK_PATH = config.DATA_DIR / "report.lock"


# ── Response models ─────────────────────────────────────────────────────
# Real, enforced models (not response_model=dict) -- FastAPI validates
# every response against these and generates an accurate OpenAPI schema
# from them, rather than documenting "dict" for every route.

class ReportSummary(BaseModel):
    week_key: str
    period_start: str
    period_end: str
    opp_count: int
    signal_count: int
    created_at: str


class ReportListResponse(BaseModel):
    reports: list[ReportSummary]
    total: int


class ReportDetail(BaseModel):
    id: str
    week_key: str
    domain: str
    period_start: str
    period_end: str
    opp_count: int
    signal_count: int
    created_at: str
    content: dict[str, Any]


class GenerateReportResponse(BaseModel):
    status: str
    message: str


@router.get("", response_model=ReportListResponse)
def list_reports(limit: int = 10):
    """Return a list of available weekly reports, newest first."""
    with database.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT week_key, period_start, period_end,
                   opp_count, signal_count, created_at
            FROM   reports
            ORDER  BY week_key DESC
            LIMIT  ?
            """,
            (limit,),
        ).fetchall()

    return {
        "reports": [dict(row) for row in rows],
        "total":   len(rows),
    }


@router.get("/latest", response_model=ReportDetail)
def get_latest_report():
    """
    Return the most recently generated report.
    This is what the frontend polls to display the intelligence briefing.
    """
    with database.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM reports ORDER BY week_key DESC LIMIT 1"
        ).fetchone()

    if not row:
        raise HTTPException(
            status_code=404,
            detail="No reports generated yet. POST /api/v1/reports/generate to create one."
        )

    result = dict(row)
    result["content"] = decode_json(result.get("content"), {})
    return result


@router.get("/{week_key}", response_model=ReportDetail)
def get_report(week_key: str):
    """Return the report for a specific ISO week, e.g. 2026-W28."""
    with database.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM reports WHERE week_key = ?",
            (week_key,)
        ).fetchone()

    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"No report found for week {week_key}."
        )

    result = dict(row)
    result["content"] = decode_json(result.get("content"), {})
    return result


@router.post("/generate", response_model=GenerateReportResponse)
async def generate_report(
    background_tasks: BackgroundTasks,
    actor: auth.Actor = Depends(auth.get_current_actor),
):
    """
    Trigger report generation for the current week.
    Returns immediately; generation runs in the background.

    Returns 409 if a report generation is already in progress.
    """
    if locking.is_locked(REPORT_LOCK_PATH):
        raise HTTPException(status_code=409, detail="A report generation is already in progress")

    logger.info(f"Report generation triggered by {actor}")
    background_tasks.add_task(_generate_report_task)
    return {
        "status":  "generating",
        "message": "Report generation started. Poll GET /api/v1/reports/latest to check.",
    }


def _generate_report_task():
    """
    Background task: generate and persist the weekly report.

    Guarded by an exclusive file lock (locking.py), matching the same
    protection main.py's pipeline trigger uses -- report generation also
    writes to SQLite and is reachable via the same kind of double-click/
    retry as the pipeline endpoint. On success, snapshots the database
    to durable storage (persistence.push()).
    """
    try:
        with locking.exclusive_lock(REPORT_LOCK_PATH):
            gen    = ReportGenerator()
            report = gen.generate()
            gen.persist(report)
            logger.info(f"Report generated for {report.week_key}: "
                        f"{report.opp_count} opps, {report.signal_count} signals")
            persistence.push()
    except locking.LockBusyError:
        logger.warning("Report generation skipped -- another generation is already in progress")
    except Exception:
        logger.exception("Report generation failed")
