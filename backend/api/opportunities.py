"""
api/opportunities.py — Opportunity API endpoints

Routes:
  GET  /api/v1/opportunities                list, sorted by composite score
  GET  /api/v1/opportunities/{id}           single opportunity with evidence
  PATCH /api/v1/opportunities/{id}/status   update lifecycle status (protected)

No business logic lives here. These handlers:
  1. Parse and validate request parameters (Pydantic handles this)
  2. Query the database
  3. Shape the response

If a route grows complex, extract a service function in opportunity_engine/
and call it from here. Routes stay thin.
"""

import logging
from typing import Optional, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

import auth
import database
from database import decode_json

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Request / Response schemas ─────────────────────────────────────────────
# Real, enforced models -- wired via response_model= below, not
# response_model=dict. FastAPI validates every response against these
# and generates an accurate OpenAPI schema from them.

class StatusUpdate(BaseModel):
    status: Literal["validated", "dismissed", "archived"]


class OpportunitySummary(BaseModel):
    """Lightweight representation for list views."""
    id: str
    title: str
    description: str
    composite_score: float
    tier: str
    status: str
    week_key: str
    domain: str
    evidence_count: int
    scores: dict
    created_at: str


class OpportunityDetail(OpportunitySummary):
    """Full representation including evidence signals."""
    signal_ids: list[str]
    evidence: list[dict]


class OpportunityListResponse(BaseModel):
    opportunities: list[OpportunitySummary]
    total: int
    limit: int
    offset: int


class StatusUpdateResponse(BaseModel):
    id: str
    status: str


# ── Routes ────────────────────────────────────────────────────────────────

@router.get("", response_model=OpportunityListResponse)
def list_opportunities(
    status: Optional[str] = Query(
        None,
        description="Filter by status: new | validated | dismissed | archived"
    ),
    week: Optional[str] = Query(
        None,
        description="Filter by ISO week key, e.g. 2026-W28"
    ),
    domain: Optional[str] = Query(
        None,
        description="Filter by domain id, e.g. business | cybersecurity"
    ),
    min_score: float = Query(
        0.0, ge=0.0, le=10.0,
        description="Minimum composite score (0–10)"
    ),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """
    Return opportunities ranked by composite score, highest first.

    The response includes summary-level scores but not full signal evidence.
    Use GET /{id} to retrieve the complete evidence chain for a single
    opportunity.

    The domain filter is an unvalidated equality match against the stored
    `domain` column (same treatment as `status`/`week`) -- an unknown
    domain id returns an empty list rather than an error, consistent with
    every other filter on this endpoint. No dedicated index exists on
    `domain` alone yet (see database.py); acceptable at V1 scale, same
    tolerance already applied to the tag LIKE-scan in signals.py.
    """
    conditions = ["composite_score >= :min_score"]
    params: dict = {"min_score": min_score}

    if status:
        conditions.append("status = :status")
        params["status"] = status

    if week:
        conditions.append("week_key = :week")
        params["week"] = week

    if domain:
        conditions.append("domain = :domain")
        params["domain"] = domain

    where = " AND ".join(conditions)
    params["limit"] = limit
    params["offset"] = offset

    with database.get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT id, title, description, composite_score, status,
                   week_key, domain, scores, created_at
            FROM   opportunities
            WHERE  {where}
            ORDER  BY composite_score DESC
            LIMIT  :limit OFFSET :offset
            """,
            params,
        ).fetchall()

        total = conn.execute(
            f"SELECT COUNT(*) FROM opportunities WHERE {where}",
            {k: v for k, v in params.items() if k not in ("limit", "offset")},
        ).fetchone()[0]

    items = [_row_to_summary(row) for row in rows]

    return {
        "opportunities": items,
        "total":  total,
        "limit":  limit,
        "offset": offset,
    }


@router.get("/{opp_id}", response_model=OpportunityDetail)
def get_opportunity(opp_id: str):
    """
    Return a single opportunity with its full evidence chain.

    The evidence field contains the signals that formed this opportunity,
    ordered by engagement (platform_score + comment_count) descending.
    This makes the "why" immediately visible in the response.
    """
    with database.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM opportunities WHERE id = ?", (opp_id,)
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Opportunity not found")

        result = _row_to_summary(row)
        result["signal_ids"] = decode_json(row["signal_ids"], [])

        # Fetch evidence signals — only the columns the frontend needs
        signal_ids = result["signal_ids"]
        evidence = []
        if signal_ids:
            placeholders = ",".join("?" * len(signal_ids))
            sigs = conn.execute(
                f"""
                SELECT id, source, title, url, platform_score,
                       comment_count, tags, collected_at
                FROM   signals
                WHERE  id IN ({placeholders})
                ORDER  BY (platform_score + comment_count) DESC
                """,
                signal_ids,
            ).fetchall()
            evidence = [
                {
                    "id":            s["id"],
                    "source":        s["source"],
                    "title":         s["title"],
                    "url":           s["url"],
                    "engagement":    s["platform_score"] + s["comment_count"],
                    "tags":          decode_json(s["tags"], []),
                    "collected_at":  s["collected_at"],
                }
                for s in sigs
            ]

        result["evidence"] = evidence

    return result


@router.patch("/{opp_id}/status", response_model=StatusUpdateResponse)
def update_status(
    opp_id: str,
    body: StatusUpdate,
    actor: auth.Actor = Depends(auth.get_current_actor),
):
    """
    Update an opportunity's lifecycle status. Protected -- requires a
    valid API key when BIA_API_KEY is configured (see auth.py).

    Valid transitions:
      new → validated  (human confirmed this is worth pursuing)
      new → dismissed  (human determined this is not worth pursuing)
      any → archived   (moving to long-term storage)

    We do not enforce transition rules in Version 1 — any status can
    transition to any other. Add a state machine here if needed.
    """
    with database.get_connection() as conn:
        result = conn.execute(
            """
            UPDATE opportunities
               SET status = ?, updated_at = datetime('now', 'utc')
             WHERE id = ?
            """,
            (body.status, opp_id),
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        conn.commit()

    logger.info(f"Opportunity {opp_id} status → {body.status} (by {actor})")
    return {"id": opp_id, "status": body.status}


# ── Helpers ───────────────────────────────────────────────────────────────

def _row_to_summary(row) -> dict:
    """Convert a database row to an API summary dict."""
    scores = decode_json(row["scores"], {})
    # Tier is read from the persisted scores JSON (written by
    # OpportunityScores.to_dict() at scoring time, using whichever
    # domain's thresholds actually applied) rather than recomputed here
    # from composite_score against literal thresholds. Recomputing with
    # hardcoded 8.0/6.5 was ADR-011's fourth hardcode site: it silently
    # ignored a non-Business domain's own ScoringThresholds. "bronze"
    # fallback matches explainer/opportunity.py's existing convention
    # for a missing/legacy tier value.
    tier = scores.get("tier", "bronze")
    return {
        "id":              row["id"],
        "title":           row["title"],
        "description":     row["description"],
        "composite_score": round(row["composite_score"], 2),
        "tier":            tier,
        "status":          row["status"],
        "week_key":        row["week_key"],
        "domain":          row["domain"],
        "scores":          scores,
        "evidence_count":  scores.get("evidence_count", 0),
        "created_at":      row["created_at"],
    }
