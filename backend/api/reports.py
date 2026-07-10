"""
api/reports.py — Weekly report endpoints

Routes:
  GET  /api/v1/reports                  list available reports (newest first)
  GET  /api/v1/reports/latest           latest generated report (most common call)
  GET  /api/v1/reports/{week_key}       specific week, e.g. 2026-W28
  POST /api/v1/reports/generate         generate report for current week (background)
"""

import logging
from fastapi import APIRouter, HTTPException, BackgroundTasks

import database
from database import decode_json
from report.generator import ReportGenerator

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("", response_model=dict)
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


@router.get("/latest", response_model=dict)
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


@router.get("/{week_key}", response_model=dict)
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


@router.post("/generate", response_model=dict)
async def generate_report(background_tasks: BackgroundTasks):
    """
    Trigger report generation for the current week.
    Returns immediately; generation runs in the background.
    """
    background_tasks.add_task(_generate_report_task)
    return {
        "status":  "generating",
        "message": "Report generation started. Poll GET /api/v1/reports/latest to check.",
    }


def _generate_report_task():
    """Background task: generate and persist the weekly report."""
    try:
        gen    = ReportGenerator()
        report = gen.generate()
        gen.persist(report)
        logger.info(f"Report generated for {report.week_key}: "
                    f"{report.opp_count} opps, {report.signal_count} signals")
    except Exception:
        logger.exception("Report generation failed")
