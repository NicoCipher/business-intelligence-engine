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
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from config import DB_PATH

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 10

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
    type        TEXT NOT NULL,   -- problem|market|technology|skill|regulation (see knowledge_graph/schema.py ENTITY_TYPES for the authoritative list)
    name        TEXT NOT NULL,
    domain      TEXT NOT NULL DEFAULT 'business',
    description TEXT DEFAULT '',
    metadata    TEXT DEFAULT '{}',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    lifecycle_state       TEXT NOT NULL DEFAULT 'active',  -- active|dormant|archived — see knowledge_graph/decay.py
    lifecycle_updated_at  TEXT DEFAULT ''                   -- last time lifecycle_state itself changed (not last reference)
);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name COLLATE NOCASE);
-- NOTE: idx_entities_lifecycle is NOT created here — same reasoning as
-- idx_entities_domain below (this DDL block runs before any migration,
-- so an index on a migration-added column breaks pre-v8 databases).
-- _migrate_v8() creates it, unconditionally, outside any column-existence
-- guard (a fresh database, where the column already exists via this
-- CREATE TABLE, still needs the index — see that migration's docstring
-- for the earlier bug this exact mistake caused with idx_opp_problem).
-- NOTE: idx_entities_domain (like the UNIQUE(type, name, domain) index) is
-- created at the end of _migrate_v5(), not here. Same reasoning as the
-- UNIQUE index below: this DDL block runs unconditionally on every
-- initialize() call, before any migration — an existing pre-v5 database
-- doesn't have the domain column yet at that point, so an index
-- referencing it here would fail with "no such column: domain" before
-- _migrate_v5() ever gets the chance to add it. (This exact bug shipped
-- and was live for a while — see docs/PROBLEM_MEMORY_VALIDATION.md and
-- the CI investigation that found it.)
-- NOTE: the UNIQUE(type, name, domain) index is created at the end of
-- _migrate_v4()/_migrate_v5(), not here — same reasoning as before:
-- creating it unconditionally here would fail against any existing
-- database that still has duplicate rows before the migration cleans
-- them up.


-- ── Knowledge Graph: Relationships ───────────────────────────────────────
-- Directed edges between entities.
-- Examples: problem "solves" technology, technology "belongs_to" market.

CREATE TABLE IF NOT EXISTS relationships (
    id          TEXT PRIMARY KEY,
    from_id     TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    to_id       TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    type        TEXT NOT NULL,   -- solves|belongs_to|requires|competes_with|indicates
    weight      REAL DEFAULT 1.0,
    domain      TEXT NOT NULL DEFAULT 'business',
    metadata    TEXT DEFAULT '{}',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    lifecycle_state       TEXT NOT NULL DEFAULT 'active',
    lifecycle_updated_at  TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_rel_from   ON relationships(from_id);
-- NOTE: idx_rel_lifecycle is NOT created here — see idx_entities_lifecycle
-- above; _migrate_v8() creates it instead, unconditionally.
-- NOTE: idx_rel_domain is created at the end of _migrate_v5(), not here —
-- same reasoning as idx_entities_domain above (see that NOTE for the
-- full explanation of why an unconditional index on a migration-added
-- column here breaks pre-v5 databases).
-- NOTE: the UNIQUE(from_id, to_id, type, domain) index is created at the
-- end of _migrate_v5(), not here — same reasoning as idx_entities above.
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
-- NOTE: idx_signals_dedup is NOT created here. It references signals.domain,
-- which only exists after _migrate_v2() runs on a database older than v2 —
-- this DDL block runs unconditionally on every initialize() call, before
-- any migration, so creating it here would fail with "no such column:
-- domain" against any pre-v2 database, before _migrate_v2() ever gets the
-- chance to add it. _migrate_v3() (the migration that made this index
-- domain-aware in the first place) is responsible for guaranteeing it
-- exists in the correct shape, for both a pre-existing 2-column index and
-- a database with no such index at all yet.
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
    domain          TEXT NOT NULL DEFAULT 'business',  -- originating domain id
    problem_id      TEXT DEFAULT ''     -- canonical Problem this observation is linked to; see problems table below
);
CREATE INDEX IF NOT EXISTS idx_opp_composite ON opportunities(composite_score DESC);
CREATE INDEX IF NOT EXISTS idx_opp_status    ON opportunities(status);
CREATE INDEX IF NOT EXISTS idx_opp_week      ON opportunities(week_key DESC);
-- NOTE: idx_opp_problem is NOT created here — same reasoning as
-- idx_entities_domain above. It references opportunities.problem_id,
-- which only exists after _migrate_v6() runs on a database older than
-- v6; creating it in this unconditional pre-migration DDL block fails
-- with "no such column: problem_id" against any pre-v6 database.
-- _migrate_v6() already creates this index itself, after its own
-- ALTER TABLE call, in the correct order.


-- ── Problems ──────────────────────────────────────────────────────────────
-- The canonical, long-lived identity for a pain point (architecture review
-- §4/§5). An Opportunity is a dated, scored observation of one solution
-- angle against a Problem; the Problem is what persists across weeks and
-- accumulates history. problem_id on opportunities is a plain reference
-- (not an enforced FK, consistent with how entity_ids already works) —
-- see opportunity_engine/canonicalizer.py for how matching works.

CREATE TABLE IF NOT EXISTS problems (
    id          TEXT PRIMARY KEY,
    domain      TEXT NOT NULL DEFAULT 'business',
    title       TEXT NOT NULL,
    entity_ids  TEXT DEFAULT '[]',  -- JSON: accumulated union of entity ids across every linked opportunity
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    weeks_seen  INTEGER DEFAULT 1,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    -- Two INDEPENDENT current-state axes (schema v9) — see
    -- opportunity_engine/lifecycle.py and models.py's Problem docstring
    -- for why these are deliberately separate fields, not one combined
    -- enum: one field, one concept.
    lifecycle_state       TEXT NOT NULL DEFAULT 'new',      -- new|active|dormant|archived|reactivated — "is this operationally relevant"
    lifecycle_updated_at  TEXT DEFAULT '',                  -- last time lifecycle_state itself changed
    trend                 TEXT NOT NULL DEFAULT 'unknown',  -- unknown|growing|stable|declining — "how is its evidence cadence changing"
    trend_updated_at      TEXT DEFAULT ''                   -- last time trend itself changed
);
CREATE INDEX IF NOT EXISTS idx_problems_domain ON problems(domain);
-- NOTE: idx_problems_lifecycle / idx_problems_trend are NOT created here
-- — same reasoning as idx_entities_lifecycle above (this DDL block runs
-- before any migration, so an index on a migration-added column breaks
-- pre-v9 databases). _migrate_v9() creates both, unconditionally,
-- outside any column-existence guard.


-- ── Problem History ───────────────────────────────────────────────────────
-- Append-only event log for a Problem's timeline (schema v7). Problem
-- itself stores only current canonical state; this table stores the
-- complete evidence and change timeline as one row per event. See
-- models.py's ProblemHistoryEvent docstring for why this is normalized
-- rather than JSON arrays on the problems row.

CREATE TABLE IF NOT EXISTS problem_history (
    id             TEXT PRIMARY KEY,
    problem_id     TEXT NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
    domain         TEXT NOT NULL DEFAULT 'business',
    event_type     TEXT NOT NULL,   -- created|evidence_added|confidence_updated|status_changed|merged|split
    occurred_at    TEXT NOT NULL,
    week_key       TEXT DEFAULT '',
    opportunity_id TEXT DEFAULT '', -- the observation that triggered this event, if any (plain reference, not FK — consistent with opportunities.problem_id)
    metadata       TEXT DEFAULT '{}', -- JSON: event-type-specific payload
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_problem_history_problem  ON problem_history(problem_id);
CREATE INDEX IF NOT EXISTS idx_problem_history_type     ON problem_history(event_type);
CREATE INDEX IF NOT EXISTS idx_problem_history_occurred ON problem_history(occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_problem_history_domain   ON problem_history(domain);


-- ── Weekly Reports ────────────────────────────────────────────────────────

-- One report per (week_key, domain) — each active domain gets its own
-- weekly briefing. The uniqueness constraint is a composite index rather
-- than an inline UNIQUE on week_key so multiple domains can each have a
-- report for the same week (idx_reports_week_domain, created by
-- _migrate_v3() — see the NOTE just below the table definition).
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
-- NOTE: idx_reports_week_domain is NOT created here — same reasoning as
-- idx_signals_dedup above. It references reports.domain, which only
-- exists after _migrate_v2() runs on a database older than v2.
-- _migrate_v3() already creates this index itself, unconditionally, at
-- the end of its own function — after both _migrate_v2()'s ALTER TABLE
-- and its own table-rebuild step have guaranteed the domain column and
-- correct table shape exist.


-- ── Schema Version ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS schema_info (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);


-- ── Continuous Intelligence Engine: Collector State ─────────────────────────
-- Persisted per-(source, domain) scheduler state. Schema v10.
--
-- Why this table exists at all: BIA runs on GitHub Actions cron, not a
-- long-running server (see .github/workflows/collect.yml) -- there is no
-- process that could stay alive between collector runs to "remember" when
-- each source last ran or whether it's currently backed off. This table is
-- that memory, persisted where an ephemeral runner can't lose it. The
-- scheduler itself (which collectors are actually due on a given
-- invocation) is separate, later work -- this table is only the state it
-- will read and write.
--
-- (source, domain) composite key, not source alone: collectors are already
-- domain-scoped (pipeline.py calls RedditCollector/GitHubCollector/
-- TrendsCollector once per active domain, each with that domain's own
-- sources.reddit_sources/github_queries/trends_keywords). Only "business"
-- is a real active domain today, but a second domain scheduling
-- independently of Business's cadence is a real, foreseeable need this
-- key shape doesn't have to be revisited for later.
CREATE TABLE IF NOT EXISTS collector_state (
    source               TEXT NOT NULL,   -- matches BaseCollector.SOURCE_NAME (hn/reddit/rss/github/trends)
    domain               TEXT NOT NULL DEFAULT 'business',
    interval_minutes     INTEGER NOT NULL,
    priority             INTEGER NOT NULL DEFAULT 5,  -- 1 (highest) .. 10 (lowest) -- tie-breaking only, not a hard gate
    quota_per_period     INTEGER NOT NULL DEFAULT 0,   -- 0 = unlimited
    quota_period_minutes INTEGER NOT NULL DEFAULT 1440,
    quota_used           INTEGER NOT NULL DEFAULT 0,
    quota_reset_at       TEXT DEFAULT '',
    last_run_at          TEXT DEFAULT '',
    last_success_at      TEXT DEFAULT '',
    last_failure_at      TEXT DEFAULT '',
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    backoff_until        TEXT DEFAULT '',
    enabled              INTEGER NOT NULL DEFAULT 1,
    updated_at           TEXT NOT NULL,
    PRIMARY KEY (source, domain)
);


-- ── Continuous Intelligence Engine: Change Events ───────────────────────────
-- "Something meaningful happened" log -- the actual new detection logic
-- this table's producer (separate, later work) writes to. Foundation for
-- daily intelligence (query by date), real-time alerts (alert_rules below
-- reads this), and the weekly digest (reuses this alongside the existing
-- report pipeline). Append-only, same "never overwritten" principle as
-- problem_history -- a Problem's lifecycle_state/trend columns are current-
-- state, but every transition on either axis is also an immutable event
-- here (or in problem_history; this table is domain-agnostic across BOTH
-- Problems and Opportunities, problem_history is Problem-only).
CREATE TABLE IF NOT EXISTS change_events (
    id               TEXT PRIMARY KEY,
    domain           TEXT NOT NULL DEFAULT 'business',
    event_type       TEXT NOT NULL,   -- e.g. problem_trend_changed, problem_lifecycle_changed, opportunity_tier_crossed, new_opportunity
    entity_ref_type  TEXT NOT NULL,   -- 'problem' | 'opportunity'
    entity_ref_id    TEXT NOT NULL,
    previous_value   TEXT DEFAULT '',
    new_value        TEXT DEFAULT '',
    significance     TEXT NOT NULL DEFAULT 'normal',  -- 'normal' | 'high' -- coarse triage, not a new score
    detected_at      TEXT NOT NULL,
    metadata         TEXT DEFAULT '{}',
    created_at       TEXT NOT NULL
);


-- ── Continuous Intelligence Engine: Watchlists ──────────────────────────────
-- Foundation only -- data model + the join a future alert/digest reader
-- needs, no UI, no client/user table (none exists yet; client_id is an
-- opaque external identifier, matching auth.py's existing minimal,
-- single-operator-token model rather than inventing a users table this
-- migration has no mandate to design).
CREATE TABLE IF NOT EXISTS watchlists (
    id           TEXT PRIMARY KEY,
    client_id    TEXT NOT NULL,
    domain       TEXT NOT NULL DEFAULT 'business',
    target_type  TEXT NOT NULL,   -- 'problem' | 'entity' | 'keyword'
    target_id    TEXT NOT NULL,
    created_at   TEXT NOT NULL
);


-- ── Continuous Intelligence Engine: Alert Rules ─────────────────────────────
-- Foundation only -- subscription structure a future change-event reader
-- can query against. No delivery channel column (email/webhook/SMS) --
-- that's explicitly out of scope for this migration.
CREATE TABLE IF NOT EXISTS alert_rules (
    id                TEXT PRIMARY KEY,
    client_id         TEXT NOT NULL,
    domain            TEXT NOT NULL DEFAULT 'business',
    watchlist_id      TEXT DEFAULT '',   -- '' = domain-wide, not scoped to one watchlist item
    event_type        TEXT DEFAULT '',   -- '' = any change_events.event_type
    min_significance  TEXT NOT NULL DEFAULT 'normal',
    enabled           INTEGER NOT NULL DEFAULT 1,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);


-- ── Continuous Intelligence Engine: Operator State ──────────────────────────
-- Exactly one logical row (CHECK (id = 1) enforces this at the SQLite
-- level, not just by convention). Exists specifically because
-- change_events alone cannot answer "what's new since I last checked" --
-- a change log has no reference point for "since when" without
-- something to hold that timestamp. BIA is deliberately single-operator
-- (no users table, no OAuth, no per-user architecture) -- this is the
-- minimal state that fact requires, not a generic settings table. Do
-- not add preferences, identity, or session concepts here; if BIA ever
-- becomes multi-operator, this table's replacement is a new migration's
-- decision, not an extension of this one.
CREATE TABLE IF NOT EXISTS operator_state (
    id           INTEGER PRIMARY KEY CHECK (id = 1),
    last_seen_at TEXT DEFAULT '',
    updated_at   TEXT NOT NULL
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

        if current_version < 4:
            _migrate_v4(conn)

        if current_version < 5:
            _migrate_v5(conn)

        if current_version < 6:
            _migrate_v6(conn)

        if current_version < 7:
            _migrate_v7(conn)

        if current_version < 8:
            _migrate_v8(conn)

        if current_version < 9:
            _migrate_v9(conn)

        if current_version < 10:
            _migrate_v10(conn)

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

    idx_signals_dedup is no longer created by the unconditional DDL block
    (it references signals.domain, which doesn't exist pre-v2 — see the
    NOTE next to signals' indexes in _SCHEMA_DDL) — this function is the
    sole place that guarantees it exists, covering both "exists with the
    old 2-column shape" and "doesn't exist at all yet."
    """
    # ── signals: rebuild the dedup index to include domain ─────────────
    existing_indexes = {
        row["name"]
        for row in conn.execute("PRAGMA index_list(signals)").fetchall()
    }
    if "idx_signals_dedup" not in existing_indexes:
        conn.execute(
            "CREATE UNIQUE INDEX idx_signals_dedup "
            "ON signals(source, source_id, domain)"
        )
        logger.info("Migration v3: created idx_signals_dedup (source, source_id, domain)")
    else:
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


def _migrate_v4(conn) -> None:
    """
    Migration v3 → v4: real entity/relationship deduplication.

    Root cause: Entity.id and Relationship.id are random UUIDs
    (models.py), and neither table had a unique constraint on anything
    else. persist_results()'s "INSERT OR IGNORE ... (deduplicated by
    type + name)" could therefore never actually ignore a true duplicate
    — id never collides — so every extraction run added another row for
    the same conceptual entity ("AI", "AI", "AI", ...), and every
    co-occurrence added another weight=1.0 relationship row instead of
    the weight ever accumulating as graph.py's docstring claims.

    This migration is a one-time cleanup of existing duplicates. Going
    forward, the real fix is the unique indexes added in the DDL above
    (idx_entities_type_name, idx_rel_from_to_type) plus the upsert logic
    in extractor.py's persist_results() — this migration exists only to
    bring pre-v4 databases in line with what those enforce from here on.

    Steps, in dependency order:
      1. Group entities by (type, LOWER(TRIM(name))) — case-insensitive,
         since duplicates included casing drift (e.g. "Github" vs
         "GitHub"). Within each group, keep the earliest-created row as
         canonical (deterministic tie-break: earliest created_at, then
         lowest id).
      2. Repoint every relationship's from_id/to_id from a duplicate's id
         to its group's canonical id. This MUST happen before deleting
         the duplicate entities — they're referenced with
         ON DELETE CASCADE, so deleting first would silently destroy the
         co-occurrence data instead of preserving it under the survivor.
      3. Delete the now-unreferenced duplicate entity rows.
      4. Drop any relationship that became a self-loop (from_id == to_id)
         as a result of merging two entities that had previously been
         recorded as co-occurring with each other.
      5. Merge any relationships that now collide on
         (from_id, to_id, type) after remapping — keep one row, sum the
         others' weight into it (capped at 10.0, matching
         Relationship.__post_init__'s validated range), delete the rest.
      6. The unique indexes themselves are created unconditionally by the
         DDL at the top of this file (CREATE UNIQUE INDEX IF NOT EXISTS),
         so no explicit index-creation step is needed here — by the time
         this function runs, steps 1-5 have already made the data safe
         for those constraints to hold.

    Idempotent: safe to run against an already-migrated or fresh database
    (every step is a no-op when there's nothing left to merge).
    """
    # ── 1. Find duplicate entity groups ─────────────────────────────────
    rows = conn.execute(
        "SELECT id, type, name, created_at FROM entities ORDER BY created_at, id"
    ).fetchall()

    groups: dict[tuple[str, str], list[sqlite3.Row]] = {}
    for row in rows:
        key = (row["type"], row["name"].strip().lower())
        groups.setdefault(key, []).append(row)

    remap: dict[str, str] = {}   # duplicate entity id -> canonical entity id
    for key, group_rows in groups.items():
        if len(group_rows) <= 1:
            continue
        canonical = group_rows[0]   # already sorted by created_at, id
        for dup in group_rows[1:]:
            remap[dup["id"]] = canonical["id"]

    if remap:
        # ── 2. Repoint relationships to the canonical entity ────────────
        for dup_id, canonical_id in remap.items():
            conn.execute(
                "UPDATE relationships SET from_id = ? WHERE from_id = ?",
                (canonical_id, dup_id),
            )
            conn.execute(
                "UPDATE relationships SET to_id = ? WHERE to_id = ?",
                (canonical_id, dup_id),
            )

        # ── 3. Delete the now-redundant duplicate entities ──────────────
        conn.executemany(
            "DELETE FROM entities WHERE id = ?",
            [(dup_id,) for dup_id in remap.keys()],
        )
        logger.info(f"Migration v4: merged {len(remap)} duplicate entity row(s)")

    # ── 4. Drop relationships that became self-loops from merging ───────
    self_loops = conn.execute(
        "SELECT COUNT(*) FROM relationships WHERE from_id = to_id"
    ).fetchone()[0]
    if self_loops:
        conn.execute("DELETE FROM relationships WHERE from_id = to_id")
        logger.info(f"Migration v4: removed {self_loops} self-loop relationship(s)")

    # ── 5. Merge relationships that now collide on (from_id, to_id, type) ─
    dupe_rel_groups = conn.execute(
        """
        SELECT from_id, to_id, type, COUNT(*) as n, SUM(weight) as total_weight,
               MIN(id) as keep_id
        FROM   relationships
        GROUP  BY from_id, to_id, type
        HAVING COUNT(*) > 1
        """
    ).fetchall()

    for grp in dupe_rel_groups:
        merged_weight = min(10.0, grp["total_weight"])
        conn.execute(
            "UPDATE relationships SET weight = ? WHERE id = ?",
            (merged_weight, grp["keep_id"]),
        )
        conn.execute(
            "DELETE FROM relationships WHERE from_id = ? AND to_id = ? AND type = ? AND id != ?",
            (grp["from_id"], grp["to_id"], grp["type"], grp["keep_id"]),
        )
    if dupe_rel_groups:
        logger.info(f"Migration v4: merged {len(dupe_rel_groups)} duplicate relationship group(s)")

    # ── 6. Now safe to create the unique indexes ────────────────────────
    # Deliberately NOT in the unconditional DDL block at the top of this
    # file — creating them there would run on every startup, before this
    # migration's cleanup, and fail immediately against any pre-existing
    # duplicate rows. By this point steps 1-5 have already guaranteed the
    # data satisfies both constraints.
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_type_name ON entities(type, name)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_rel_from_to_type ON relationships(from_id, to_id, type)"
    )

    conn.commit()


def _migrate_v5(conn) -> None:
    """
    Migration v4 → v5: domain-scope the knowledge graph.

    Root cause: entities and relationships had no domain column at all —
    a single global graph shared across every domain. Invisible while
    only "business" ever had real data; would silently corrupt
    co_occurring_pairs()/weekly_entity_summary() the moment a second
    domain (e.g. the already-stubbed "cybersecurity") gets real signals,
    mixing both domains' entities into every ranking with no way to tell
    them apart.

    Steps:
      1. Add `domain` column to entities/relationships if not already
         present (ALTER TABLE ADD COLUMN with a DEFAULT — SQLite backfills
         existing rows with the default in place, no data rewrite needed).
         Default is 'business': the only domain that has ever had real
         data in this system, so every existing row is correctly
         classified by the default alone — no ambiguous backfill logic
         needed.
      2. Drop the old 2/3-column unique indexes from _migrate_v4 (they no
         longer match the intended uniqueness — two different domains
         should be allowed to independently have an entity with the same
         (type, name), which the old indexes would have incorrectly
         prevented).
      3. Create the new domain-aware unique indexes.

    Idempotent: safe to run against an already-migrated or fresh database.
    """
    entity_columns = {row["name"] for row in conn.execute("PRAGMA table_info(entities)").fetchall()}
    if "domain" not in entity_columns:
        conn.execute("ALTER TABLE entities ADD COLUMN domain TEXT NOT NULL DEFAULT 'business'")
        logger.info("Migration v5: added entities.domain (backfilled 'business')")

    rel_columns = {row["name"] for row in conn.execute("PRAGMA table_info(relationships)").fetchall()}
    if "domain" not in rel_columns:
        conn.execute("ALTER TABLE relationships ADD COLUMN domain TEXT NOT NULL DEFAULT 'business'")
        logger.info("Migration v5: added relationships.domain (backfilled 'business')")

    conn.execute("DROP INDEX IF EXISTS idx_entities_type_name")
    conn.execute("DROP INDEX IF EXISTS idx_rel_from_to_type")

    conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_domain ON entities(domain)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rel_domain ON relationships(domain)")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_type_name_domain "
        "ON entities(type, name, domain)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_rel_from_to_type_domain "
        "ON relationships(from_id, to_id, type, domain)"
    )

    conn.commit()


def _migrate_v6(conn) -> None:
    """
    Migration v5 → v6: canonical Problem identity (architecture review §4/§5).

    Adds the `problems` table — the long-lived pain-point identity that an
    Opportunity observation attaches to — and `opportunities.problem_id`.

    Backfill for existing (pre-v6) opportunities: each one becomes its own
    initial Problem root (a new Problem row with entity_ids=[] and the
    opportunity's own title/domain). This is an honest, explicitly-limited
    backfill, not a best-effort guess: pre-v6 opportunities never had
    entity_ids populated either (that field has been dead since it was
    added — see opportunity_engine/canonicalizer.py's docstring), so there
    is no real signature to retroactively match them against each other.
    Each old opportunity gets a stable identity going forward; it just
    doesn't get to benefit from canonicalization retroactively. New
    opportunities detected after this migration lands get real entity_ids
    and real matching.

    Idempotent: only backfills opportunities where problem_id is still
    empty, so re-running this is a no-op the second time.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS problems (
            id          TEXT PRIMARY KEY,
            domain      TEXT NOT NULL DEFAULT 'business',
            title       TEXT NOT NULL,
            entity_ids  TEXT DEFAULT '[]',
            first_seen  TEXT NOT NULL,
            last_seen   TEXT NOT NULL,
            weeks_seen  INTEGER DEFAULT 1,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_problems_domain ON problems(domain)")

    opp_columns = {row["name"] for row in conn.execute("PRAGMA table_info(opportunities)").fetchall()}
    if "problem_id" not in opp_columns:
        conn.execute("ALTER TABLE opportunities ADD COLUMN problem_id TEXT DEFAULT ''")
        logger.info("Migration v6: added opportunities.problem_id")

    # NOT nested inside the column-existence check above: on a fresh
    # database, problem_id already exists (it's in the DDL's own CREATE
    # TABLE), so that check is False and this index would never be
    # created if it lived inside it — exactly the bug that was found and
    # fixed for idx_entities_domain/idx_rel_domain in _migrate_v5 (see
    # that function for the same reasoning). IF NOT EXISTS makes this
    # safe to run unconditionally either way.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_opp_problem ON opportunities(problem_id)")

    unlinked = conn.execute(
        "SELECT id, title, domain, created_at FROM opportunities WHERE problem_id IS NULL OR problem_id = ''"
    ).fetchall()

    for opp in unlinked:
        problem_id = str(uuid.uuid4())
        now = opp["created_at"]
        conn.execute(
            """
            INSERT INTO problems (id, domain, title, entity_ids, first_seen, last_seen, weeks_seen, created_at, updated_at)
            VALUES (?, ?, ?, '[]', ?, ?, 1, ?, ?)
            """,
            (problem_id, opp["domain"], opp["title"], now, now, now, now),
        )
        conn.execute(
            "UPDATE opportunities SET problem_id = ? WHERE id = ?",
            (problem_id, opp["id"]),
        )

    if unlinked:
        logger.info(f"Migration v6: backfilled {len(unlinked)} opportunity(ies) with initial Problem roots")

    conn.commit()


def _migrate_v7(conn) -> None:
    """
    Migration v6 → v7: persistent Problem memory (problem_history table).

    Adds `problem_history` — the append-only event timeline for a Problem
    (models.py's ProblemHistoryEvent). Problem itself continues to store
    only current canonical state (title, entity_ids, first_seen, last_seen,
    weeks_seen); this table stores the full timeline as one row per event.
    Written going forward by opportunity_engine/canonicalizer.py's
    resolve_problem() — "created" when a new Problem is established,
    "evidence_added" when an existing one matches a new observation.

    Backfill for existing (pre-v7) problems: each gets exactly one
    synthetic "created" event, occurred_at = the problem's own first_seen,
    with metadata explicitly marked backfilled=True. This is an honest,
    explicitly-limited backfill, following the same principle _migrate_v6
    used for opportunities: pre-v7 problems were never tracked event-by-
    event, so there is no real per-week timeline to reconstruct — only
    weeks_seen (a count) survives, not which weeks. Fabricating one
    evidence_added event per counted week would misrepresent data that
    was never actually recorded. Each old Problem gets a truthful single
    origin marker instead; new events accumulate correctly from here on.

    Idempotent: only backfills problems that have zero existing
    problem_history rows, so re-running this is a no-op the second time.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS problem_history (
            id             TEXT PRIMARY KEY,
            problem_id     TEXT NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
            domain         TEXT NOT NULL DEFAULT 'business',
            event_type     TEXT NOT NULL,
            occurred_at    TEXT NOT NULL,
            week_key       TEXT DEFAULT '',
            opportunity_id TEXT DEFAULT '',
            metadata       TEXT DEFAULT '{}',
            created_at     TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_problem_history_problem  ON problem_history(problem_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_problem_history_type     ON problem_history(event_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_problem_history_occurred ON problem_history(occurred_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_problem_history_domain  ON problem_history(domain)")

    unbacked = conn.execute(
        """
        SELECT p.id, p.domain, p.title, p.first_seen
        FROM problems p
        LEFT JOIN problem_history h ON h.problem_id = p.id
        WHERE h.id IS NULL
        """
    ).fetchall()

    for problem in unbacked:
        conn.execute(
            """
            INSERT INTO problem_history
              (id, problem_id, domain, event_type, occurred_at, week_key, opportunity_id, metadata, created_at)
            VALUES (?, ?, ?, 'created', ?, '', '', ?, ?)
            """,
            (
                str(uuid.uuid4()),
                problem["id"],
                problem["domain"],
                problem["first_seen"],
                json.dumps({"title": problem["title"], "backfilled": True}),
                _now(),
            ),
        )

    if unbacked:
        logger.info(f"Migration v7: backfilled {len(unbacked)} problem(s) with an initial 'created' history event")

    conn.commit()


def _migrate_v8(conn) -> None:
    """
    Migration v7 → v8: knowledge-graph decay (lifecycle states).

    Adds `lifecycle_state` (active|dormant|archived — see
    knowledge_graph/decay.py) and `lifecycle_updated_at` to `entities` and
    `relationships`. Never deletes anything — decay is purely a state
    transition, always reversible by new evidence
    (knowledge_graph/extractor.py's persist_results() reactivates on
    re-encounter). Deliberately scoped to the knowledge graph only —
    Signal stays append-only/immutable and Opportunity stays immutable;
    neither gets a lifecycle here (that's out of scope — see
    docs/HANDOFF.md's roadmap, which keeps Problem/Opportunity lifecycle
    as a separate, future, explicitly-gated RFC decision).

    Backfill: every pre-v8 row gets lifecycle_state='active' (the DDL's
    own column default already handles this for the ALTER TABLE — SQLite
    backfills a NOT NULL DEFAULT value onto every existing row
    automatically) and lifecycle_updated_at = its own updated_at (the
    most honest available proxy for "when did this lifecycle state
    start" — it didn't really change at that moment, but there is no
    earlier truthful timestamp to use, and defaulting to the migration's
    own run-time would make every pre-existing row look like it *just*
    became active, which is worse).

    Index-creation placement is deliberately UNCONDITIONAL and OUTSIDE
    any column-existence guard in this function — this is not a stylistic
    choice, it's fixing the exact mistake that _migrate_v6() originally
    made with idx_opp_problem: nesting `CREATE INDEX` inside
    `if "problem_id" not in opp_columns` meant a FRESH database (where
    the column already exists via the DDL's own CREATE TABLE) never got
    the index at all, since that guard is always False there. IF NOT
    EXISTS makes running these indexes unconditionally safe regardless of
    whether the ALTER TABLE branch below actually ran.
    """
    entity_columns = {row["name"] for row in conn.execute("PRAGMA table_info(entities)").fetchall()}
    if "lifecycle_state" not in entity_columns:
        conn.execute("ALTER TABLE entities ADD COLUMN lifecycle_state TEXT NOT NULL DEFAULT 'active'")
        conn.execute("ALTER TABLE entities ADD COLUMN lifecycle_updated_at TEXT DEFAULT ''")
        conn.execute("UPDATE entities SET lifecycle_updated_at = updated_at WHERE lifecycle_updated_at = ''")
        logger.info("Migration v8: added entities.lifecycle_state / lifecycle_updated_at")

    rel_columns = {row["name"] for row in conn.execute("PRAGMA table_info(relationships)").fetchall()}
    if "lifecycle_state" not in rel_columns:
        conn.execute("ALTER TABLE relationships ADD COLUMN lifecycle_state TEXT NOT NULL DEFAULT 'active'")
        conn.execute("ALTER TABLE relationships ADD COLUMN lifecycle_updated_at TEXT DEFAULT ''")
        conn.execute("UPDATE relationships SET lifecycle_updated_at = updated_at WHERE lifecycle_updated_at = ''")
        logger.info("Migration v8: added relationships.lifecycle_state / lifecycle_updated_at")

    # Unconditional and outside both guards above — see docstring.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_lifecycle ON entities(lifecycle_state)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rel_lifecycle ON relationships(lifecycle_state)")

    conn.commit()


def _migrate_v9(conn) -> None:
    """
    Migration v8 → v9: Problem lifecycle & trend — two INDEPENDENT axes.

    Adds `lifecycle_state` (new|active|dormant|archived|reactivated —
    "is this operationally relevant") and `trend` (unknown|growing|
    stable|declining — "how is its evidence cadence changing") to
    `problems`, each with its own `_updated_at` companion. Deliberately
    two separate fields, not one combined state — see
    opportunity_engine/lifecycle.py's module docstring and models.py's
    Problem docstring for the full reasoning: one field should represent
    one concept, and a combined enum either explodes combinatorially or
    produces contradictory-reading states (a Problem that's "declining"
    but was also just reactivated, or "growing" while also newly
    dormant). A single-field trajectory_state design was the first one
    built here and was deliberately unwound in favor of this before
    anything shipped, once that cost became concrete rather than
    theoretical.

    Both are current-state fields, not history — every transition on
    either axis is also written to problem_history as a "status_changed"
    event (the event type schema v7 reserved for exactly this and left
    unused until now), tagged with which axis changed, so the full
    trajectory over time remains reconstructable even though these
    columns themselves are overwritten on each transition.

    Deliberately distinct from Opportunity.status (new|validated|
    dismissed|archived — a pre-existing, human-curated review field
    mutated via PATCH /opportunities/{id}/status, unrelated and never
    enforced): lifecycle_state/trend are system-derived from accumulated
    evidence, never human-set. The vocabularies happen to share "new"
    and "archived" — they are not the same concept.

    Backfill: every pre-v9 Problem gets lifecycle_state='new' and
    trend='unknown' (the DDL's own NOT NULL DEFAULTs handle this
    automatically for the ALTER TABLE), with both *_updated_at columns
    set to the row's own updated_at — the same honest-backfill reasoning
    used in every prior migration in this file: there's no earlier
    truthful timestamp for "when did this state start," and this
    backfill only needs to be a safe, honest starting point — the real
    lifecycle pass, run once after this migration, promptly reclassifies
    anything that actually has enough history to be active/dormant or a
    real trend.

    Index-creation placement is deliberately UNCONDITIONAL and OUTSIDE
    any column-existence guard — same fix already applied for
    idx_opp_problem (_migrate_v6) and idx_entities_lifecycle/
    idx_rel_lifecycle (_migrate_v8): nesting `CREATE INDEX` inside
    `if "lifecycle_state" not in problem_columns` would mean a FRESH
    database (where the column already exists via the DDL's own CREATE
    TABLE) never gets the index at all.
    """
    problem_columns = {row["name"] for row in conn.execute("PRAGMA table_info(problems)").fetchall()}
    if "lifecycle_state" not in problem_columns:
        conn.execute("ALTER TABLE problems ADD COLUMN lifecycle_state TEXT NOT NULL DEFAULT 'new'")
        conn.execute("ALTER TABLE problems ADD COLUMN lifecycle_updated_at TEXT DEFAULT ''")
        conn.execute("ALTER TABLE problems ADD COLUMN trend TEXT NOT NULL DEFAULT 'unknown'")
        conn.execute("ALTER TABLE problems ADD COLUMN trend_updated_at TEXT DEFAULT ''")
        conn.execute("UPDATE problems SET lifecycle_updated_at = updated_at WHERE lifecycle_updated_at = ''")
        conn.execute("UPDATE problems SET trend_updated_at = updated_at WHERE trend_updated_at = ''")
        logger.info("Migration v9: added problems.lifecycle_state / lifecycle_updated_at / trend / trend_updated_at")

    # Unconditional and outside the guard above — see docstring.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_problems_lifecycle ON problems(lifecycle_state)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_problems_trend ON problems(trend)")

    conn.commit()


def _migrate_v10(conn) -> None:
    """
    Migration v9 → v10: Continuous Intelligence Engine foundation --
    collector_state, change_events, watchlists, alert_rules,
    operator_state.

    All five are entirely new tables, not ALTER TABLE on existing ones --
    unlike v9, there is nothing to backfill from prior data, because none
    of these concepts existed before this migration. The CREATE TABLE
    statements below are redundant with _SCHEMA_DDL for a genuinely fresh
    database (idempotent via IF NOT EXISTS), but necessary here for a
    pre-v10 database being upgraded -- the same reasoning _migrate_v7()
    used for problem_history: redundant CREATEs make this migration safe
    to reason about and run standalone, not just as a side effect of
    _SCHEMA_DDL happening to run first in initialize().

    operator_state was added to v10 rather than deferred to its own
    migration: change_events alone cannot answer "what's new since I
    last checked" (its own stated purpose -- see that table's DDL
    comment) without a persisted reference point for "since when".
    BIA is deliberately single-operator (no users table, no OAuth, no
    per-user architecture) -- operator_state is the minimal state that
    fact requires: a single row, enforced by CHECK (id = 1), holding
    only last_seen_at. Not a settings table; do not add preferences,
    identity, or session concepts to it.

    collector_state seeding: every known collector (BaseCollector.
    SOURCE_NAME across hn/reddit/rss/github/trends) gets exactly one row
    for the 'business' domain, with interval_minutes reflecting each
    source's real, already-documented constraints -- not arbitrary
    defaults:
      hn      60 min, priority 3  -- shared/official API, cheap, matches
                                      the new hourly outer cron cadence
      reddit  120 min, priority 4 -- official API (PRAW), moderate cost
      rss     180 min, priority 5 -- feeds change slowly, no rate-limit
                                      pressure either way
      github  240 min, priority 4 -- official API but the Search
                                      endpoints' 30 req/min limit is the
                                      real constraint (see
                                      collectors/github_collector.py) --
                                      less frequent, not less careful
      trends  360 min, priority 7 -- unofficial, reverse-engineered, no
                                      documented rate limit at all (see
                                      collectors/trends_collector.py's
                                      own module docstring calling this
                                      "the least reliable source in the
                                      system") -- most conservative
                                      interval, lowest priority
    quota_per_period is 0 (unlimited) for all five: none of these sources
    has a real, documented daily cap distinct from its own per-request
    rate limit (already enforced inside each collector), so seeding a
    fabricated quota number here would be inventing a constraint that
    doesn't exist. The column exists, ready for a human to set a real
    cap later if one becomes necessary; this migration doesn't guess one.

    operator_state seeding: exactly one row, id=1, last_seen_at=''
    (never seen), inserted only if the table is currently empty -- same
    idempotency discipline as collector_state's seeding, checked
    separately since the two are independent conditions.

    Idempotent: collector_state seeding only runs if that table is
    completely empty, and operator_state seeding only runs if its own
    single row doesn't exist yet -- both checked independently, so
    re-running this migration (or calling initialize() again) never
    overwrites state a real scheduler run, or a real operator visit,
    has since written.

    Index-creation placement is deliberately UNCONDITIONAL and OUTSIDE
    the seeding step below -- same fix already applied for idx_opp_problem
    (_migrate_v6), idx_entities_lifecycle/idx_rel_lifecycle (_migrate_v8),
    and idx_problems_lifecycle/idx_problems_trend (_migrate_v9): nesting
    index creation inside a conditional would mean a fresh database
    (where _SCHEMA_DDL's own CREATE TABLE already ran) never gets the
    index at all.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS collector_state (
            source               TEXT NOT NULL,
            domain               TEXT NOT NULL DEFAULT 'business',
            interval_minutes     INTEGER NOT NULL,
            priority             INTEGER NOT NULL DEFAULT 5,
            quota_per_period     INTEGER NOT NULL DEFAULT 0,
            quota_period_minutes INTEGER NOT NULL DEFAULT 1440,
            quota_used           INTEGER NOT NULL DEFAULT 0,
            quota_reset_at       TEXT DEFAULT '',
            last_run_at          TEXT DEFAULT '',
            last_success_at      TEXT DEFAULT '',
            last_failure_at      TEXT DEFAULT '',
            consecutive_failures INTEGER NOT NULL DEFAULT 0,
            backoff_until        TEXT DEFAULT '',
            enabled              INTEGER NOT NULL DEFAULT 1,
            updated_at           TEXT NOT NULL,
            PRIMARY KEY (source, domain)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS change_events (
            id               TEXT PRIMARY KEY,
            domain           TEXT NOT NULL DEFAULT 'business',
            event_type       TEXT NOT NULL,
            entity_ref_type  TEXT NOT NULL,
            entity_ref_id    TEXT NOT NULL,
            previous_value   TEXT DEFAULT '',
            new_value        TEXT DEFAULT '',
            significance     TEXT NOT NULL DEFAULT 'normal',
            detected_at      TEXT NOT NULL,
            metadata         TEXT DEFAULT '{}',
            created_at       TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS watchlists (
            id           TEXT PRIMARY KEY,
            client_id    TEXT NOT NULL,
            domain       TEXT NOT NULL DEFAULT 'business',
            target_type  TEXT NOT NULL,
            target_id    TEXT NOT NULL,
            created_at   TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS alert_rules (
            id                TEXT PRIMARY KEY,
            client_id         TEXT NOT NULL,
            domain            TEXT NOT NULL DEFAULT 'business',
            watchlist_id      TEXT DEFAULT '',
            event_type        TEXT DEFAULT '',
            min_significance  TEXT NOT NULL DEFAULT 'normal',
            enabled           INTEGER NOT NULL DEFAULT 1,
            created_at        TEXT NOT NULL,
            updated_at        TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS operator_state (
            id           INTEGER PRIMARY KEY CHECK (id = 1),
            last_seen_at TEXT DEFAULT '',
            updated_at   TEXT NOT NULL
        )
        """
    )

    existing = conn.execute("SELECT COUNT(*) FROM collector_state").fetchone()[0]
    if existing == 0:
        now = _now()
        defaults = [
            # (source, interval_minutes, priority)
            ("hn",     60,  3),
            ("reddit", 120, 4),
            ("rss",    180, 5),
            ("github", 240, 4),
            ("trends", 360, 7),
        ]
        for source, interval_minutes, priority in defaults:
            conn.execute(
                """
                INSERT INTO collector_state
                    (source, domain, interval_minutes, priority, updated_at)
                VALUES (?, 'business', ?, ?, ?)
                """,
                (source, interval_minutes, priority, now),
            )
        logger.info(f"Migration v10: seeded collector_state for {len(defaults)} known collectors")

    # operator_state: exactly one row, seeded only if the table is
    # currently empty -- an INSERT OR IGNORE against the id=1 singleton
    # would be equally idempotent, but a fetch-then-conditional-insert
    # makes the "do not overwrite an existing last_seen_at" guarantee
    # explicit in the code rather than relying on OR IGNORE's silent
    # no-op to be understood as intentional by a future reader.
    has_operator_row = conn.execute("SELECT 1 FROM operator_state WHERE id = 1").fetchone()
    if has_operator_row is None:
        conn.execute(
            "INSERT INTO operator_state (id, last_seen_at, updated_at) VALUES (1, '', ?)",
            (_now(),),
        )
        logger.info("Migration v10: seeded operator_state singleton row")

    # Unconditional and outside both seeding guards above — see docstring.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_collector_state_domain ON collector_state(domain)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_collector_state_enabled ON collector_state(enabled)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_change_events_domain ON change_events(domain)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_change_events_entity ON change_events(entity_ref_type, entity_ref_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_change_events_detected_at ON change_events(detected_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_watchlists_client ON watchlists(client_id, domain)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_watchlists_target ON watchlists(target_type, target_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_alert_rules_client ON alert_rules(client_id, domain)")

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
            "signals":         conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0],
            "opportunities":   conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0],
            "entities":        conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
            "problems":        conn.execute("SELECT COUNT(*) FROM problems").fetchone()[0],
            "problem_history": conn.execute("SELECT COUNT(*) FROM problem_history").fetchone()[0],
            "reports":         conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0],
            "change_events":   conn.execute("SELECT COUNT(*) FROM change_events").fetchone()[0],
            "watchlists":      conn.execute("SELECT COUNT(*) FROM watchlists").fetchone()[0],
            "alert_rules":     conn.execute("SELECT COUNT(*) FROM alert_rules").fetchone()[0],
            "operator_last_seen_at": (
                conn.execute("SELECT last_seen_at FROM operator_state WHERE id = 1").fetchone() or [""]
            )[0] or None,
            "latest_signal": (
                conn.execute(
                    "SELECT collected_at FROM signals ORDER BY collected_at DESC LIMIT 1"
                ).fetchone() or [None]
            )[0],
        }
