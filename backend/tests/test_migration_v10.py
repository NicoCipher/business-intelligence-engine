"""
tests/test_migration_v10.py — Regression tests for schema v10:
Continuous Intelligence Engine foundation (collector_state,
change_events, watchlists, alert_rules).

Unlike every migration from v2 through v9, all four v10 tables are
entirely new -- there is no ALTER TABLE on an existing table, and
therefore no pre-existing data to backfill. What still needs the same
two-failure-mode coverage this project's DDL-ordering bug class has
actually produced before (see test_migration_v8.py's docstring for the
full history): a pre-v10 database (a real v9 database, upgraded), and a
fresh database (index creation must not be nested inside a conditional
that a fresh database, whose tables already exist via _SCHEMA_DDL,
would never enter).

Run with:
    cd backend && pytest tests/test_migration_v10.py -v
"""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import database


def _seed_pre_v10_database(db_path):
    """A genuine v9 database -- schema_info says 9, none of the four
    v10 tables exist yet. Minimal on purpose: v10 doesn't touch any
    existing table, so there's nothing else that needs to be present
    for this migration's own behavior to be exercised correctly."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE schema_info (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
        INSERT INTO schema_info (version, applied_at) VALUES (9, '2026-01-01T00:00:00Z');
        """
    )
    conn.commit()
    conn.close()


@pytest.fixture
def pre_v10_db(tmp_path, monkeypatch):
    db_path = tmp_path / "pre_v10.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    _seed_pre_v10_database(db_path)
    yield db_path


_NEW_TABLES = ("collector_state", "change_events", "watchlists", "alert_rules", "operator_state")

_NEW_INDEXES = (
    "idx_collector_state_domain", "idx_collector_state_enabled",
    "idx_change_events_domain", "idx_change_events_entity", "idx_change_events_detected_at",
    "idx_watchlists_client", "idx_watchlists_target",
    "idx_alert_rules_client",
)

_KNOWN_COLLECTORS = {"hn", "reddit", "rss", "github", "trends"}


class TestInitializeAgainstPreV10Database:
    def test_initialize_does_not_raise(self, pre_v10_db):
        database.initialize()

    def test_migrates_to_current_version(self, pre_v10_db):
        database.initialize()
        with database.get_connection() as conn:
            version = conn.execute(
                "SELECT version FROM schema_info ORDER BY version DESC LIMIT 1"
            ).fetchone()["version"]
        assert version == database.SCHEMA_VERSION == 11

    @pytest.mark.parametrize("table", _NEW_TABLES)
    def test_new_table_created(self, pre_v10_db, table):
        database.initialize()
        with database.get_connection() as conn:
            names = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
        assert table in names

    @pytest.mark.parametrize("index", _NEW_INDEXES)
    def test_new_index_created(self, pre_v10_db, index):
        database.initialize()
        with database.get_connection() as conn:
            names = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()}
        assert index in names

    def test_collector_state_seeded_for_every_known_collector(self, pre_v10_db):
        database.initialize()
        with database.get_connection() as conn:
            rows = conn.execute("SELECT source FROM collector_state").fetchall()
        assert {r["source"] for r in rows} == _KNOWN_COLLECTORS

    def test_seeded_rows_scoped_to_business_domain(self, pre_v10_db):
        database.initialize()
        with database.get_connection() as conn:
            rows = conn.execute("SELECT domain FROM collector_state").fetchall()
        assert all(r["domain"] == "business" for r in rows)

    def test_seeded_rows_enabled_by_default(self, pre_v10_db):
        database.initialize()
        with database.get_connection() as conn:
            rows = conn.execute("SELECT enabled FROM collector_state").fetchall()
        assert all(r["enabled"] == 1 for r in rows)

    def test_seeded_rows_have_no_run_history_yet(self, pre_v10_db):
        """A freshly-migrated collector_state row must read as "never
        run" -- the scheduler (separate, later work) needs this to
        correctly treat every collector as due on its first check."""
        database.initialize()
        with database.get_connection() as conn:
            rows = conn.execute(
                "SELECT last_run_at, consecutive_failures, backoff_until FROM collector_state"
            ).fetchall()
        assert all(r["last_run_at"] == "" for r in rows)
        assert all(r["consecutive_failures"] == 0 for r in rows)
        assert all(r["backoff_until"] == "" for r in rows)

    def test_quota_per_period_defaults_to_unlimited(self, pre_v10_db):
        """No seeded collector has a real documented daily cap distinct
        from its own already-enforced per-request rate limit -- 0 means
        unlimited, not an oversight."""
        database.initialize()
        with database.get_connection() as conn:
            rows = conn.execute("SELECT quota_per_period FROM collector_state").fetchall()
        assert all(r["quota_per_period"] == 0 for r in rows)

    def test_trends_has_the_most_conservative_interval(self, pre_v10_db):
        """trends_collector.py's own module docstring calls Trends "the
        least reliable source in the system" -- collector_state's
        seeded defaults must reflect that, not treat every source
        identically."""
        database.initialize()
        with database.get_connection() as conn:
            rows = {r["source"]: r["interval_minutes"] for r in conn.execute(
                "SELECT source, interval_minutes FROM collector_state"
            ).fetchall()}
        assert rows["trends"] > rows["github"] > rows["reddit"] > rows["hn"]

    def test_idempotent_on_repeated_initialize_calls(self, pre_v10_db):
        database.initialize()
        database.initialize()
        with database.get_connection() as conn:
            version = conn.execute(
                "SELECT version FROM schema_info ORDER BY version DESC LIMIT 1"
            ).fetchone()["version"]
            count = conn.execute("SELECT COUNT(*) FROM collector_state").fetchone()[0]
        assert version == database.SCHEMA_VERSION
        assert count == 5  # not duplicated by the second initialize() call

    def test_seeding_does_not_overwrite_real_scheduler_state(self, pre_v10_db):
        """If a real scheduler run has already written state (e.g. via
        a partial migration or manual seed), re-running initialize()
        must not clobber it -- seeding only fires when the table is
        completely empty."""
        database.initialize()
        with database.get_connection() as conn:
            conn.execute(
                "UPDATE collector_state SET consecutive_failures = 3 WHERE source = 'github'"
            )
            conn.commit()

        database.initialize()  # second call must not re-seed over this

        with database.get_connection() as conn:
            failures = conn.execute(
                "SELECT consecutive_failures FROM collector_state WHERE source = 'github'"
            ).fetchone()["consecutive_failures"]
        assert failures == 3

    def test_operator_state_seeded_on_v9_to_v10_upgrade(self, pre_v10_db):
        """The v9->v10 upgrade path must create AND seed operator_state,
        not just create an empty table -- a real pre-v10 database has
        never had this concept, so there's nothing to backfill from,
        only a fresh singleton row to seed, same as a brand new database."""
        database.initialize()
        with database.get_connection() as conn:
            row = conn.execute("SELECT * FROM operator_state WHERE id = 1").fetchone()
        assert row is not None
        assert row["last_seen_at"] == ""
        assert row["updated_at"] != ""


class TestFreshDatabaseGetsIndexesToo:
    """The idx_opp_problem failure mode, checked again for v10's eight
    new indexes -- see test_migration_v8.py's docstring for the full
    history of this specific bug class."""

    @pytest.fixture
    def fresh_db(self, tmp_path, monkeypatch):
        db_path = tmp_path / "fresh.db"
        monkeypatch.setattr(database, "DB_PATH", db_path)
        database.initialize()
        yield db_path

    @pytest.mark.parametrize("index", _NEW_INDEXES)
    def test_fresh_database_has_index(self, fresh_db, index):
        with database.get_connection() as conn:
            names = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()}
        assert index in names

    def test_fresh_database_also_gets_seeded_collector_state(self, fresh_db):
        """Confirms seeding isn't accidentally gated behind the
        pre-v10-only migration path -- a brand new database must reach
        the same seeded state as an upgraded one."""
        with database.get_connection() as conn:
            rows = conn.execute("SELECT source FROM collector_state").fetchall()
        assert {r["source"] for r in rows} == _KNOWN_COLLECTORS

    def test_fresh_database_change_events_table_usable(self, fresh_db):
        with database.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO change_events
                    (id, domain, event_type, entity_ref_type, entity_ref_id, detected_at, created_at)
                VALUES ('ce1', 'business', 'problem_trend_changed', 'problem', 'p1',
                        '2026-08-15T00:00:00Z', '2026-08-15T00:00:00Z')
                """
            )
            conn.commit()
            row = conn.execute("SELECT * FROM change_events WHERE id = 'ce1'").fetchone()
        assert row["event_type"] == "problem_trend_changed"
        assert row["significance"] == "normal"  # DEFAULT applied correctly

    def test_fresh_database_watchlists_table_usable(self, fresh_db):
        with database.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO watchlists (id, client_id, domain, target_type, target_id, created_at)
                VALUES ('w1', 'client-abc', 'business', 'problem', 'p1', '2026-08-15T00:00:00Z')
                """
            )
            conn.commit()
            row = conn.execute("SELECT * FROM watchlists WHERE id = 'w1'").fetchone()
        assert row["client_id"] == "client-abc"

    def test_fresh_database_alert_rules_table_usable(self, fresh_db):
        with database.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO alert_rules (id, client_id, domain, created_at, updated_at)
                VALUES ('r1', 'client-abc', 'business', '2026-08-15T00:00:00Z', '2026-08-15T00:00:00Z')
                """
            )
            conn.commit()
            row = conn.execute("SELECT * FROM alert_rules WHERE id = 'r1'").fetchone()
        assert row["enabled"] == 1          # DEFAULT applied correctly
        assert row["min_significance"] == "normal"  # DEFAULT applied correctly

    def test_collector_state_primary_key_is_source_and_domain(self, fresh_db):
        """A second domain must be able to schedule independently of
        Business's cadence without a schema change -- proves the
        composite key actually allows a second row for the same
        source under a different domain."""
        with database.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO collector_state (source, domain, interval_minutes, updated_at)
                VALUES ('github', 'test_other_domain', 30, '2026-08-15T00:00:00Z')
                """
            )
            conn.commit()
            count = conn.execute(
                "SELECT COUNT(*) FROM collector_state WHERE source = 'github'"
            ).fetchone()[0]
        assert count == 2  # 'business' (seeded) + 'test_other_domain' (just inserted)


class TestGetStatsIncludesNewTables:
    @pytest.fixture
    def fresh_db(self, tmp_path, monkeypatch):
        db_path = tmp_path / "fresh.db"
        monkeypatch.setattr(database, "DB_PATH", db_path)
        database.initialize()
        yield db_path

    def test_get_stats_includes_all_three_new_counts(self, fresh_db):
        stats = database.get_stats()
        assert stats["change_events"] == 0
        assert stats["watchlists"] == 0
        assert stats["alert_rules"] == 0

    def test_get_stats_reports_operator_last_seen_as_none_when_unseen(self, fresh_db):
        stats = database.get_stats()
        assert stats["operator_last_seen_at"] is None

    def test_get_stats_reports_operator_last_seen_once_set(self, fresh_db):
        with database.get_connection() as conn:
            conn.execute(
                "UPDATE operator_state SET last_seen_at = '2026-08-15T12:00:00Z' WHERE id = 1"
            )
            conn.commit()
        stats = database.get_stats()
        assert stats["operator_last_seen_at"] == "2026-08-15T12:00:00Z"


class TestSingleOperatorConstraintsHold:
    """
    Guard-rail tests for the explicit architectural constraint stated
    when this schema was reviewed: BIA is deliberately single-operator.
    No multi-user auth, no OAuth, no users table, no tenants, no
    per-user architecture in this migration.

    These test the ABSENCE of something rather than a behavior -- an
    unusual shape for a test, but the same category as
    test_domain_system.py's test_scoring_dimensions_self_contained
    (which scans source text for a forbidden coupling). The risk this
    guards against is real: watchlists/alert_rules both have a
    client_id column, and "client" is exactly the kind of name that
    invites an FK to a users table to get added later without anyone
    deciding that on purpose. These tests make the current, deliberate
    absence explicit and would fail the moment someone adds one.
    """

    @pytest.fixture
    def fresh_db(self, tmp_path, monkeypatch):
        db_path = tmp_path / "fresh.db"
        monkeypatch.setattr(database, "DB_PATH", db_path)
        database.initialize()
        yield db_path

    def test_no_users_tenants_or_operators_table_exists(self, fresh_db):
        with database.get_connection() as conn:
            names = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
        assert not (names & {"users", "user", "tenants", "tenant", "operators", "accounts"})

    @pytest.mark.parametrize("table", _NEW_TABLES)
    def test_new_tables_have_no_foreign_keys(self, fresh_db, table):
        """client_id (watchlists, alert_rules) and watchlist_id
        (alert_rules) are deliberately opaque, unconstrained TEXT --
        not FKs to a users/watchlists identity table. This is what
        preserves a future multi-tenant migration path without
        building it prematurely (per the explicit instruction this
        schema was reviewed against): today client_id is just a
        string; a future migration could add a real users table and
        backfill an FK without this migration having guessed its shape."""
        with database.get_connection() as conn:
            fks = conn.execute(f"PRAGMA foreign_key_list({table})").fetchall()
        assert fks == []

    @pytest.mark.parametrize("table", ("watchlists", "alert_rules"))
    def test_no_user_or_tenant_id_column(self, fresh_db, table):
        with database.get_connection() as conn:
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        assert not (cols & {"user_id", "tenant_id", "account_id", "org_id"})

    def test_client_id_is_plain_unconstrained_text(self, fresh_db):
        """Proves watchlists/alert_rules accept any string as client_id
        right now -- no CHECK constraint, no enum, nothing that would
        need to change shape once a real identity concept exists later."""
        with database.get_connection() as conn:
            conn.execute(
                "INSERT INTO watchlists (id, client_id, target_type, target_id, created_at) "
                "VALUES ('w1', 'literally-any-string-works', 'problem', 'p1', '2026-08-15T00:00:00Z')"
            )
            conn.commit()
            row = conn.execute("SELECT client_id FROM watchlists WHERE id = 'w1'").fetchone()
        assert row["client_id"] == "literally-any-string-works"

    def test_alert_rules_has_no_delivery_channel_column(self, fresh_db):
        """Persistence foundation only, per the explicit scope this
        migration was given -- no email/webhook/sms/phone column.
        Delivery is deliberately not built yet."""
        with database.get_connection() as conn:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(alert_rules)").fetchall()}
        assert not (cols & {"email", "webhook_url", "webhook", "phone", "sms", "endpoint", "delivery_channel"})

    def test_operator_state_table_now_exists(self, fresh_db):
        """Superseded assertion: an earlier revision of this test file
        checked that operator_state did NOT exist yet, documenting that
        its absence was a pending recommendation rather than a decision.
        That recommendation was approved and operator_state was added to
        this same v10 migration (not deferred to v11) — see
        TestOperatorState below for its own dedicated coverage. This
        test now confirms the table exists, replacing the old assertion
        rather than just deleting it, so the history of that decision
        stays visible in the test file itself."""
        with database.get_connection() as conn:
            names = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
        assert "operator_state" in names


class TestOperatorState:
    """
    Dedicated coverage for operator_state, added to schema v10 (not a
    separate v11) because change_events cannot answer "what's new since
    I last checked" -- its own stated purpose -- without a persisted
    reference point for "since when". Covers exactly the six points
    raised when this table was approved: creation on a fresh database,
    correct v9->v10 upgrade (see
    TestInitializeAgainstPreV10Database.test_operator_state_seeded_on_v9_to_v10_upgrade
    for that half), the singleton constraint, idempotent initialization,
    seed behavior not overwriting an existing last_seen_at, and no
    regression in the other four v10 tables (covered by every other
    class in this file continuing to pass unchanged).
    """

    @pytest.fixture
    def fresh_db(self, tmp_path, monkeypatch):
        db_path = tmp_path / "fresh.db"
        monkeypatch.setattr(database, "DB_PATH", db_path)
        database.initialize()
        yield db_path

    def test_table_created_on_fresh_database(self, fresh_db):
        with database.get_connection() as conn:
            names = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
        assert "operator_state" in names

    def test_fresh_database_seeds_exactly_one_row(self, fresh_db):
        with database.get_connection() as conn:
            rows = conn.execute("SELECT * FROM operator_state").fetchall()
        assert len(rows) == 1
        assert rows[0]["id"] == 1

    def test_seeded_row_starts_with_empty_last_seen_at(self, fresh_db):
        """Never seen yet -- '' not NULL, matching every other
        never-happened-yet TEXT column convention in this schema
        (last_run_at, backoff_until, etc. all default to '' not NULL)."""
        with database.get_connection() as conn:
            row = conn.execute("SELECT last_seen_at FROM operator_state WHERE id = 1").fetchone()
        assert row["last_seen_at"] == ""

    def test_seeded_row_has_a_real_updated_at(self, fresh_db):
        with database.get_connection() as conn:
            row = conn.execute("SELECT updated_at FROM operator_state WHERE id = 1").fetchone()
        assert row["updated_at"] != ""

    def test_singleton_constraint_rejects_a_second_row(self, fresh_db):
        """CHECK (id = 1) enforced at the SQLite level, not just by
        convention -- attempting id=2 must raise IntegrityError, not
        silently succeed or be caught only by application code."""
        with database.get_connection() as conn:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO operator_state (id, last_seen_at, updated_at) "
                    "VALUES (2, '', '2026-08-15T00:00:00Z')"
                )

    def test_singleton_constraint_rejects_id_zero(self, fresh_db):
        with database.get_connection() as conn:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO operator_state (id, last_seen_at, updated_at) "
                    "VALUES (0, '', '2026-08-15T00:00:00Z')"
                )

    def test_idempotent_initialize_does_not_duplicate_the_row(self, fresh_db):
        database.initialize()
        database.initialize()
        with database.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM operator_state").fetchone()[0]
        assert count == 1

    def test_reinitialize_does_not_overwrite_existing_last_seen_at(self, fresh_db):
        """The exact requirement: once a real operator visit has set
        last_seen_at, re-running initialize() (e.g. on the next
        ephemeral GitHub Actions runner) must not reset it back to ''."""
        with database.get_connection() as conn:
            conn.execute(
                "UPDATE operator_state SET last_seen_at = '2026-08-15T09:00:00Z', "
                "updated_at = '2026-08-15T09:00:00Z' WHERE id = 1"
            )
            conn.commit()

        database.initialize()  # must not re-seed over this
        database.initialize()  # and again, for good measure

        with database.get_connection() as conn:
            row = conn.execute("SELECT last_seen_at FROM operator_state WHERE id = 1").fetchone()
        assert row["last_seen_at"] == "2026-08-15T09:00:00Z"

    def test_can_be_updated_like_any_normal_row(self, fresh_db):
        """Confirms this is ordinary mutable state (unlike append-only
        change_events/problem_history) -- an UPDATE against id=1 is the
        expected way a future scheduler run marks a new visit, not an
        INSERT."""
        with database.get_connection() as conn:
            conn.execute(
                "UPDATE operator_state SET last_seen_at = '2026-08-15T10:00:00Z', "
                "updated_at = '2026-08-15T10:00:00Z' WHERE id = 1"
            )
            conn.commit()
            row = conn.execute("SELECT * FROM operator_state WHERE id = 1").fetchone()
        assert row["last_seen_at"] == "2026-08-15T10:00:00Z"

    def test_no_regression_in_the_other_four_v10_tables(self, fresh_db):
        """Adding operator_state must not have disturbed the four
        tables approved and verified in the prior review -- re-checked
        directly here as a single, explicit assertion, in addition to
        every other class in this file continuing to pass unchanged."""
        with database.get_connection() as conn:
            names = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
        assert {"collector_state", "change_events", "watchlists", "alert_rules"} <= names
        with database.get_connection() as conn:
            collector_count = conn.execute("SELECT COUNT(*) FROM collector_state").fetchone()[0]
        assert collector_count == 5  # unchanged seeding behavior
