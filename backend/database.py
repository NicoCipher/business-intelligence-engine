"""
database.py — SQLite connection and schema management for BIA-OS

Design rationale:
  • SQLite with WAL mode allows concurrent readers while a writer is active.
    This matters because the collector and the API server run simultaneously.

  • Raw sqlite3 over SQLAlchemy: every query is explicit SQL. There are no
    lazy-load surprises, no N+1 query traps, no hidden session state.
    When this needs to scale to PostgreSQL, replace get_connection() only.

  • JSON columns for metadata: signal sources have different shapes. Rather
    than a column-per-field schema that requires migration for every new source,
    we store source-specific fields in a JSON metadata column. The structured
    columns (title, score, url) are the queryable, indexed core.

  • Foreign keys are enforced via PRAGMA. SQLite disables them by default,
    which would silently allow orphaned records. We always enable them.

Schema evolution:
  • schema_info table tracks applied version.
  • For Version 1, a simple version check suffices.
  • If/when migrations are needed, add an apply_migrations() function here.
"""

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from config import DB_PATH

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 3

# Full DDL. CREATE IF NOT EXISTS makes this idempotent — safe to call on
# every startup without worrying about duplicate table errors.
_SCHEMA_DDL = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ── Knowledge Graph: Entities ────────────────────────────────────────────
-- Nodes in the knowledge graph. A problem, market, technology, company,
-- skill, product, or regulation.

CREATE TABLE IF NOT EXISTS entities (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL,   -- problem|market|technology|company|skill|product|regulation
    name        TEXT NOT NULL,
    description TEXT DEFAULT '',
    metadata    TEXT DEFAULT '{}',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name COLLATE NOCASE);


-- ── Knowledge Graph: Relationships ───────────────────────────────────────
-- Directed edges between entities.
-- Examples: problem "solves" technology, technology "belongs_to" market.

CREATE TABLE IF NOT EXISTS relationships (
    id          TEXT PRIMARY KEY,
    from_id     TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    to_id       TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    type        TEXT NOT NULL,   -- solves|belongs_to|requires|competes_with|indicates
    weight      REAL DEFAULT 1.0,
    metadata    TEXT DEFAULT '{}',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rel_from   ON relationships(from_id);
CREATE INDEX IF NOT EXISTS idx_rel_to     ON relationships(to_id);
CREATE INDEX IF NOT EXISTS idx_rel_type   ON relationships(type);


-- ── Signal Store ─────────────────────────────────────────────────────────
-- Raw data collected from external sources. This is the system's memory
-- of what it observed, before any processing or interpretation.
--
-- The compound unique index on (source, source_id) prevents duplicate
-- collection of the same post on repeated runs.

CREATE TABLE IF NOT EXISTS signals (
    id            TEXT PRIMARY KEY,
    source        TEXT NOT NULL,   -- hn|reddit|rss|trends
    source_id     TEXT NOT NULL,   -- original ID in the source system
    url           TEXT DEFAULT '',
    title         TEXT NOT NULL,
    content       TEXT DEFAULT '',
    platform_score    INTEGER DEFAULT 0,  -- upvotes, HN points, etc.
    comment_count     INTEGER DEFAULT 0,
    entity_ids    TEXT DEFAULT '[]',   -- JSON: [uuid, ...]
    tags          TEXT DEFAULT '[]',   -- JSON: ["demand_signal", "ai", ...]
    raw_metadata  TEXT DEFAULT '{}',   -- JSON: source-specific fields
    collected_at  TEXT NOT NULL,
    processed     INTEGER DEFAULT 0,   -- 0=raw, 1=processed, 2=failed
    domain        TEXT NOT NULL DEFAULT 'business'  -- originating domain id
);
-- Dedup is scoped per domain: shared collectors (e.g. Hacker News) persist
-- one independent copy of the same source item for every active domain,
-- so each domain scores and stores its own row. See pipeline.py.
CREATE UNIQUE INDEX IF NOT EXISTS idx_signals_dedup     ON signals(source, source_id, domain);
CREATE        INDEX IF NOT EXISTS idx_signals_source    ON signals(source);
CREATE        INDEX IF NOT EXISTS idx_signals_collected ON signals(collected_at DESC);
CREATE        INDEX IF NOT EXISTS idx_signals_processed ON signals(processed);
CREATE        INDEX IF NOT EXISTS idx_signals_tags      ON signals(tags);  -- for full-text search on tags


-- ── Opportunities ─────────────────────────────────────────────────────────
-- A scored, evidence-backed opportunity detected from a cluster of signals.

CREATE TABLE IF NOT EXISTS opportunities (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    description     TEXT NOT NULL,
    signal_ids      TEXT DEFAULT '[]',  -- JSON: [uuid, ...]
    entity_ids      TEXT DEFAULT '[]',  -- JSON: [uuid, ...]
    scores          TEXT DEFAULT '{}',  -- JSON: OpportunityScores.to_dict()
    composite_score REAL DEFAULT 0.0,
    status          TEXT DEFAULT 'new', -- new|validated|dismissed|archived
    week_key        TEXT NOT NULL,      -- ISO week: '2026-W28'
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    domain          TEXT NOT NULL DEFAULT 'business'  -- originating domain id
);
CREATE INDEX IF NOT EXISTS idx_opp_composite ON opportunities(composite_score DESC);
CREATE INDEX IF NOT EXISTS idx_opp_status    ON opportunities(status);
CREATE INDEX IF NOT EXISTS idx_opp_week      ON opportunities(week_key DESC);


-- ── Weekly Reports ────────────────────────────────────────────────────────

-- One report per (week_key, domain) — each active domain gets its own
-- weekly briefing. The uniqueness constraint is a composite index rather
-- than an inline UNIQUE on week_key so multiple domains can each have a
-- report for the same week (see idx_reports_week_domain below).
CREATE TABLE IF NOT EXISTS reports (
    id           TEXT PRIMARY KEY,
    week_key     TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end   TEXT NOT NULL,
    content      TEXT DEFAULT '{}',   -- JSON: full report
    opp_count    INTEGER DEFAULT 0,
    signal_count INTEGER DEFAULT 0,
    created_at   TEXT NOT NULL,
    domain       TEXT NOT NULL DEFAULT 'business'  -- originating domain id
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_reports_week_domain ON reports(week_key, domain);


-- ── Schema Version ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS schema_info (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
"""


# ── Connection management ─────────────────────────────────────────────────

@contextmanager
def get_connection():
    """
    Yield a sqlite3 connection configured for this application.

    Usage:
        with get_connection() as conn:
            rows = conn.execute("SELECT * FROM signals").fetchall()

    - Rows are returned as sqlite3.Row objects (access by column name).
    - Uncommitted writes are rolled back automatically on exception.
    - The connection is always closed on exit, even on error.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        yield conn
    except sqlite3.Error:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize() -> None:
    """
    Create all tables and indexes if they do not exist.
    Apply any pending schema migrations.
    Safe to call on every startup — all operations are idempotent.
    """
    with get_connection() as conn:
        conn.executescript(_SCHEMA_DDL)

        current = conn.execute(
            "SELECT version FROM schema_info ORDER BY version DESC LIMIT 1"
        ).fetchone()

        current_version = current["version"] if current else 0

        if current_version < 2:
            _migrate_v2(conn)

        if current_version < 3:
            _migrate_v3(conn)

        if current_version < SCHEMA_VERSION:
            conn.execute(
                "INSERT OR REPLACE INTO schema_info (version, applied_at) VALUES (?, ?)",
                (SCHEMA_VERSION, _now())
            )
            conn.commit()
            logger.info(f"Database at schema version {SCHEMA_VERSION} — {DB_PATH}")
        else:
            logger.debug(f"Database already at schema version {current_version}")


def _migrate_v2(conn) -> None:
    """
    Migration v1 → v2: add domain column to signals, opportunities, reports.

    Adds TEXT NOT NULL DEFAULT 'business' so all existing rows are tagged
    as belonging to the business domain. Safe to run on a fresh database
    (the column already exists in the DDL) — PRAGMA table_info check prevents
    duplicate ALTER TABLE errors.
    """
    for table in ("signals", "opportunities", "reports"):
        existing_cols = {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if "domain" not in existing_cols:
            conn.execute(
                f"ALTER TABLE {table} "
                f"ADD COLUMN domain TEXT NOT NULL DEFAULT 'business'"
            )
            logger.info("Migration v2: added domain column to %s", table)
    conn.commit()


def _migrate_v3(conn) -> None:
    """
    Migration v2 → v3: make uniqueness domain-aware now that the pipeline
    actually iterates active domains (see pipeline.py).

    signals:
      Old dedup key was (source, source_id) — one row per source item,
      globally. That's wrong once multiple domains are active: a shared
      collector (Hacker News) must be able to persist one independent copy
      per active domain. Replace the unique index with
      (source, source_id, domain).

    reports:
      Old constraint was an inline UNIQUE on week_key alone, so a second
      domain's report for the same week would silently overwrite the
      first domain's report (INSERT OR REPLACE keys off week_key). SQLite
      can't drop an inline column-level UNIQUE without rebuilding the
      table, so we recreate it with a composite (week_key, domain) index.

    Both operations are idempotent — safe to run against a fresh database
    (where the final-shape DDL already matches) or an existing v2 database.
    """
    # ── signals: rebuild the dedup index to include domain ─────────────
    existing_indexes = {
        row["name"]
        for row in conn.execute("PRAGMA index_list(signals)").fetchall()
    }
    if "idx_signals_dedup" in existing_indexes:
        index_info = conn.execute(
            "PRAGMA index_info(idx_signals_dedup)"
        ).fetchall()
        columns = [row["name"] for row in index_info]
        if columns != ["source", "source_id", "domain"]:
            conn.execute("DROP INDEX idx_signals_dedup")
            conn.execute(
                "CREATE UNIQUE INDEX idx_signals_dedup "
                "ON signals(source, source_id, domain)"
            )
            logger.info(
                "Migration v3: rebuilt idx_signals_dedup as "
                "(source, source_id, domain)"
            )

    # ── reports: rebuild the table to drop the inline UNIQUE(week_key) ──
    reports_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'reports'"
    ).fetchone()
    if reports_sql and "week_key TEXT NOT NULL UNIQUE" in reports_sql["sql"]:
        conn.executescript("""
            CREATE TABLE reports_v3 (
                id           TEXT PRIMARY KEY,
                week_key     TEXT NOT NULL,
                period_start TEXT NOT NULL,
                period_end   TEXT NOT NULL,
                content      TEXT DEFAULT '{}',
                opp_count    INTEGER DEFAULT 0,
                signal_count INTEGER DEFAULT 0,
                created_at   TEXT NOT NULL,
                domain       TEXT NOT NULL DEFAULT 'business'
            );
            INSERT INTO reports_v3
                (id, week_key, period_start, period_end, content,
                 opp_count, signal_count, created_at, domain)
            SELECT id, week_key, period_start, period_end, content,
                   opp_count, signal_count, created_at, domain
            FROM reports;
            DROP TABLE reports;
            ALTER TABLE reports_v3 RENAME TO reports;
        """)
        logger.info("Migration v3: rebuilt reports table without inline UNIQUE(week_key)")

    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_reports_week_domain "
        "ON reports(week_key, domain)"
    )
    conn.commit()


# ── Helpers ───────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def encode_json(obj) -> str:
    """Encode a Python object to a JSON string. Handles datetimes via str()."""
    return json.dumps(obj, ensure_ascii=False, default=str)


def decode_json(s: str | None, default=None):
    """Safely decode a JSON string. Returns default on any parse error."""
    if not s:
        return default
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        logger.warning(f"JSON decode failed for: {s[:80]!r}")
        return default


def get_stats() -> dict:
    """Return a summary of database contents for health checks and the UI."""
    with get_connection() as conn:
        return {
            "signals":       conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0],
            "opportunities": conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0],
            "entities":      conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
            "reports":       conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0],
            "latest_signal": (
                conn.execute(
                    "SELECT collected_at FROM signals ORDER BY collected_at DESC LIMIT 1"
                ).fetchone() or [None]
            )[0],
        }
