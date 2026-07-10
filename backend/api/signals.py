"""
api/signals.py — Signal feed endpoints

Routes:
  GET /api/v1/signals           recent signals, newest first
  GET /api/v1/signals/stats     collection statistics for the status panel

The signal feed is the system's live memory — everything observed, before
interpretation. It answers "what did the system see this week?"
"""

import logging
from typing import Optional

from fastapi import APIRouter, Query

import database
from database import decode_json, get_stats

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("", response_model=dict)
def list_signals(
    source: Optional[str] = Query(
        None,
        description="Filter by source: hn | reddit | rss | trends"
    ),
    tag: Optional[str] = Query(
        None,
        description="Filter by tag (e.g. demand_signal, complaint_signal)"
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """
    Return recent signals, newest first.

    The tag filter uses SQLite's LIKE on the JSON-stored tags array.
    This is not the most efficient approach for very large tables, but it
    is correct and simple. Add a full-text search index here when signal
    volume exceeds ~100k rows.
    """
    conditions = ["1=1"]
    params: dict = {}

    if source:
        conditions.append("source = :source")
        params["source"] = source

    if tag:
        # SQLite JSON stored as text: check if the tag string is in the tags column
        conditions.append("tags LIKE :tag_pattern")
        params["tag_pattern"] = f'%"{tag}"%'

    where = " AND ".join(conditions)
    params["limit"] = limit
    params["offset"] = offset

    with database.get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT id, source, title, url, platform_score,
                   comment_count, tags, collected_at, processed
            FROM   signals
            WHERE  {where}
            ORDER  BY collected_at DESC
            LIMIT  :limit OFFSET :offset
            """,
            params,
        ).fetchall()

        total = conn.execute(
            f"SELECT COUNT(*) FROM signals WHERE {where}",
            {k: v for k, v in params.items() if k not in ("limit", "offset")},
        ).fetchone()[0]

    items = [
        {
            "id":           row["id"],
            "source":       row["source"],
            "title":        row["title"],
            "url":          row["url"],
            "engagement":   row["platform_score"] + row["comment_count"],
            "tags":         decode_json(row["tags"], []),
            "collected_at": row["collected_at"],
            "processed":    bool(row["processed"]),
        }
        for row in rows
    ]

    return {
        "signals": items,
        "total":   total,
        "limit":   limit,
        "offset":  offset,
    }


@router.get("/stats", response_model=dict)
def get_signal_stats():
    """
    Return collection statistics for the dashboard status panel.

    This endpoint powers the live status indicators — how many signals,
    when was the last collection run, breakdown by source.
    """
    db_stats = get_stats()

    with database.get_connection() as conn:
        # Breakdown by source
        source_rows = conn.execute(
            "SELECT source, COUNT(*) as count FROM signals GROUP BY source"
        ).fetchall()
        by_source = {row["source"]: row["count"] for row in source_rows}

        # Signals in the last 7 days
        recent = conn.execute(
            """
            SELECT COUNT(*) FROM signals
            WHERE collected_at >= datetime('now', '-7 days')
            """
        ).fetchone()[0]

        # Tag distribution — top 10 most common tags
        # (Approximated by scanning tags column; precise but slow for large tables)
        tag_rows = conn.execute(
            """
            SELECT tags FROM signals
            WHERE collected_at >= datetime('now', '-7 days')
            """
        ).fetchall()

    tag_counts: dict[str, int] = {}
    for row in tag_rows:
        for tag in decode_json(row["tags"], []):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    return {
        "total_signals":    db_stats["signals"],
        "total_opps":       db_stats["opportunities"],
        "signals_this_week": recent,
        "latest_collection": db_stats["latest_signal"],
        "by_source":        by_source,
        "top_tags":         [{"tag": t, "count": c} for t, c in top_tags],
    }
