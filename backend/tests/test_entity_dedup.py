"""
tests/test_entity_dedup.py — Regression tests for issue 4: entity/
relationship deduplication.

Root cause covered: Entity.id and Relationship.id are random UUIDs with
no other unique constraint, so INSERT OR IGNORE never actually caught a
true duplicate — every extraction run added another row for the same
conceptual entity, and weight never accumulated as graph.py's docstring
claimed. Covers both the ongoing fix (unique indexes + upsert) and the
one-time migration that cleans up pre-existing duplicates.

Run with:
    cd backend && pytest tests/test_entity_dedup.py -v
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import database
from knowledge_graph import graph as kg
from knowledge_graph.extractor import EntityExtractor
from models import Entity, Relationship


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_entity_dedup.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    database.initialize()
    yield db_path


def _entity_count(type_, name) -> int:
    with database.get_connection() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM entities WHERE type = ? AND name = ?",
            (type_, name),
        ).fetchone()[0]


# ── Ongoing prevention: same entity extracted across multiple runs ───────

class TestEntityDeduplicationGoingForward:
    def test_same_entity_across_multiple_persist_calls_produces_one_row(self, fresh_db, make_signal):
        extractor = EntityExtractor()

        for i in range(5):
            sig = make_signal(title=f"Using Claude for a coding task number {i}")
            extractor.persist_results(extractor.extract_batch([sig]))

        assert _entity_count("technology", "Claude") == 1

    def test_same_entity_within_one_batch_produces_one_row(self, fresh_db, make_signal):
        extractor = EntityExtractor()
        signals = [make_signal(title=f"Using Claude for task {i}") for i in range(4)]
        extractor.persist_results(extractor.extract_batch(signals))
        assert _entity_count("technology", "Claude") == 1

    def test_unique_index_actually_exists(self, fresh_db):
        with database.get_connection() as conn:
            indexes = {r["name"] for r in conn.execute("PRAGMA index_list(entities)").fetchall()}
        assert "idx_entities_type_name_domain" in indexes


class TestRelationshipWeightAccumulation:
    def test_weight_accumulates_across_persist_calls_for_same_pair(self, fresh_db, make_signal):
        extractor = EntityExtractor()

        for i in range(3):
            sig = make_signal(title=f"Using Claude with Rust for task {i}")
            extractor.persist_results(extractor.extract_batch([sig]))

        pairs = kg.co_occurring_pairs(min_weight=0.0, limit=10)
        claude_rust = [
            p for p in pairs
            if {p["from"]["name"], p["to"]["name"]} == {"Claude", "Rust"}
        ]
        assert len(claude_rust) == 1, "must be exactly one relationship row, not one per run"
        assert claude_rust[0]["weight"] == pytest.approx(3.0)

    def test_weight_caps_at_ten(self, fresh_db, make_signal):
        extractor = EntityExtractor()
        for i in range(15):
            sig = make_signal(title=f"Using Claude with Rust for task {i}")
            extractor.persist_results(extractor.extract_batch([sig]))

        pairs = kg.co_occurring_pairs(min_weight=0.0, limit=10)
        claude_rust = [
            p for p in pairs
            if {p["from"]["name"], p["to"]["name"]} == {"Claude", "Rust"}
        ]
        assert claude_rust[0]["weight"] == pytest.approx(10.0)

    def test_unique_index_actually_exists(self, fresh_db):
        with database.get_connection() as conn:
            indexes = {r["name"] for r in conn.execute("PRAGMA index_list(relationships)").fetchall()}
        assert "idx_rel_from_to_type_domain" in indexes


# ── Migration: cleaning up pre-existing duplicates ────────────────────────

class TestKnowledgeGraphDomainScoping:
    """
    Regression coverage for the architecture review's flagged gap:
    entities/relationships had no domain column at all, so two domains'
    knowledge graphs were silently shared. These tests prove the fix
    directly — the same (type, name) entity independently exists per
    domain, and cross-domain data never appears in a domain-scoped query.
    """

    def test_same_entity_name_independent_per_domain(self, fresh_db, make_signal):
        extractor = EntityExtractor()
        biz_sig = make_signal(title="Using Claude for a business automation task", source="hn")
        sec_sig = make_signal(title="Using Claude for a security automation task", source="hn")

        extractor.persist_results(extractor.extract_batch([biz_sig]), domain="business")
        extractor.persist_results(extractor.extract_batch([sec_sig]), domain="cybersecurity")

        with database.get_connection() as conn:
            rows = conn.execute(
                "SELECT domain FROM entities WHERE type = 'technology' AND name = 'Claude'"
            ).fetchall()
        domains = {r["domain"] for r in rows}
        assert domains == {"business", "cybersecurity"}
        assert len(rows) == 2  # one row per domain, not merged into one

    def test_co_occurring_pairs_scoped_to_domain_excludes_other_domain(self, fresh_db, make_signal):
        extractor = EntityExtractor()
        biz_signals = [make_signal(title="Using Claude with Rust for business tooling", source="hn") for _ in range(3)]
        sec_signals = [make_signal(title="Using Claude with Rust for security tooling", source="hn") for _ in range(5)]

        extractor.persist_results(extractor.extract_batch(biz_signals), domain="business")
        extractor.persist_results(extractor.extract_batch(sec_signals), domain="cybersecurity")

        biz_pairs = kg.co_occurring_pairs(min_weight=0.0, limit=10, domain="business")
        biz_weight = next(
            (p["weight"] for p in biz_pairs if {p["from"]["name"], p["to"]["name"]} == {"Claude", "Rust"}),
            None,
        )
        assert biz_weight == pytest.approx(3.0), "business's weight must not include cybersecurity's 5 mentions"

    def test_weekly_entity_summary_scoped_to_domain(self, fresh_db, make_signal):
        extractor = EntityExtractor()
        biz_signals = [make_signal(title="Using Claude for business tasks", source="hn") for _ in range(2)]
        sec_signals = [make_signal(title="Using Claude for security tasks", source="hn") for _ in range(4)]

        extractor.persist_results(extractor.extract_batch(biz_signals), domain="business")
        extractor.persist_results(extractor.extract_batch(sec_signals), domain="cybersecurity")

        biz_summary = kg.weekly_entity_summary(domain="business")
        # "Claude" entity: 1 per domain (deduped within domain) -> business total_entities
        # must not be inflated by cybersecurity's separate Claude row.
        assert biz_summary["total_entities"] == 1

    def test_domain_none_preserves_old_all_domains_behavior(self, fresh_db, make_signal):
        """Backward compatibility: callers that don't specify domain still
        get the pre-v5 all-domains view, for direct/debugging use — but
        this is explicitly not what production report generation uses."""
        extractor = EntityExtractor()
        biz_sig = make_signal(title="Using Claude for a general task", source="hn")
        sec_sig = make_signal(title="Using Claude for a general task", source="hn")
        extractor.persist_results(extractor.extract_batch([biz_sig]), domain="business")
        extractor.persist_results(extractor.extract_batch([sec_sig]), domain="cybersecurity")

        with database.get_connection() as conn:
            claude_rows = conn.execute(
                "SELECT domain FROM entities WHERE type = 'technology' AND name = 'Claude'"
            ).fetchall()
        assert {r["domain"] for r in claude_rows} == {"business", "cybersecurity"}

        all_domains_pairs_or_summary = kg.weekly_entity_summary(domain=None)
        # domain=None must not filter anything out -- both domains' rows visible.
        assert all_domains_pairs_or_summary["total_entities"] >= 2

    def test_persist_results_defaults_to_business_domain(self, fresh_db, make_signal):
        """Existing callers that don't pass domain explicitly must keep
        working exactly as before v5."""
        extractor = EntityExtractor()
        sig = make_signal(title="Using Claude for a task", source="hn")
        extractor.persist_results(extractor.extract_batch([sig]))  # no domain arg

        with database.get_connection() as conn:
            row = conn.execute(
                "SELECT domain FROM entities WHERE type = 'technology' AND name = 'Claude'"
            ).fetchone()
        assert row["domain"] == "business"


class TestMigrationV4MergesExistingDuplicates:
    """
    These tests bypass the unique-index-enforced path entirely by
    inserting duplicate rows directly via raw SQL (simulating what a
    pre-v4 database, without the constraint, would already contain), then
    run the migration function directly to prove it cleans them up.
    """

    def _insert_raw_entity(self, conn, id_, type_, name, created_at):
        conn.execute(
            "INSERT INTO entities (id, type, name, description, metadata, created_at, updated_at) "
            "VALUES (?, ?, ?, '', '{}', ?, ?)",
            (id_, type_, name, created_at, created_at),
        )

    def _insert_raw_relationship(self, conn, id_, from_id, to_id, type_, weight, created_at):
        conn.execute(
            "INSERT INTO relationships (id, from_id, to_id, type, weight, metadata, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, '{}', ?, ?)",
            (id_, from_id, to_id, type_, weight, created_at, created_at),
        )

    def test_case_variant_duplicates_merged_into_one(self, fresh_db):
        # Bypass the unique index by dropping it temporarily, to simulate
        # a pre-v4 database state where duplicates could accumulate.
        with database.get_connection() as conn:
            conn.execute("DROP INDEX IF EXISTS idx_entities_type_name")
            conn.execute("DROP INDEX IF EXISTS idx_entities_type_name_domain")
            self._insert_raw_entity(conn, "e1", "technology", "AI", "2026-01-01T00:00:00Z")
            self._insert_raw_entity(conn, "e2", "technology", "AI", "2026-01-02T00:00:00Z")
            self._insert_raw_entity(conn, "e3", "technology", "ai", "2026-01-03T00:00:00Z")
            conn.commit()

            database._migrate_v4(conn)

            remaining = conn.execute(
                "SELECT id, name FROM entities WHERE type = 'technology' AND LOWER(name) = 'ai'"
            ).fetchall()
        assert len(remaining) == 1
        assert remaining[0]["id"] == "e1"  # earliest created_at wins

    def test_github_casing_variants_merged(self, fresh_db):
        with database.get_connection() as conn:
            conn.execute("DROP INDEX IF EXISTS idx_entities_type_name")
            conn.execute("DROP INDEX IF EXISTS idx_entities_type_name_domain")
            self._insert_raw_entity(conn, "g1", "technology", "Github", "2026-01-01T00:00:00Z")
            self._insert_raw_entity(conn, "g2", "technology", "GitHub", "2026-01-02T00:00:00Z")
            conn.commit()

            database._migrate_v4(conn)

            remaining = conn.execute(
                "SELECT id FROM entities WHERE type = 'technology' AND LOWER(name) = 'github'"
            ).fetchall()
        assert len(remaining) == 1

    def test_relationships_remapped_not_lost(self, fresh_db):
        """Merging entities must preserve the co-occurrence data by
        repointing relationships, not silently cascade-delete it."""
        with database.get_connection() as conn:
            conn.execute("DROP INDEX IF EXISTS idx_entities_type_name")
            conn.execute("DROP INDEX IF EXISTS idx_entities_type_name_domain")
            self._insert_raw_entity(conn, "ai1", "technology", "AI", "2026-01-01T00:00:00Z")
            self._insert_raw_entity(conn, "ai2", "technology", "AI", "2026-01-02T00:00:00Z")
            self._insert_raw_entity(conn, "rust1", "technology", "Rust", "2026-01-01T00:00:00Z")
            self._insert_raw_relationship(conn, "r1", "ai2", "rust1", "co-occurs", 2.0, "2026-01-02T00:00:00Z")
            conn.commit()

            database._migrate_v4(conn)

            rels = conn.execute("SELECT from_id, to_id, weight FROM relationships").fetchall()
        assert len(rels) == 1
        assert rels[0]["from_id"] == "ai1"  # remapped from ai2 to the canonical id
        assert rels[0]["weight"] == pytest.approx(2.0)

    def test_duplicate_relationships_after_remap_are_summed(self, fresh_db):
        """If two duplicate entities each had their own relationship to the
        same third entity, merging the entities creates a relationship
        collision — weights must be summed, not left as duplicate rows."""
        with database.get_connection() as conn:
            conn.execute("DROP INDEX IF EXISTS idx_entities_type_name")
            conn.execute("DROP INDEX IF EXISTS idx_entities_type_name_domain")
            conn.execute("DROP INDEX IF EXISTS idx_rel_from_to_type")
            conn.execute("DROP INDEX IF EXISTS idx_rel_from_to_type_domain")
            self._insert_raw_entity(conn, "ai1", "technology", "AI", "2026-01-01T00:00:00Z")
            self._insert_raw_entity(conn, "ai2", "technology", "AI", "2026-01-02T00:00:00Z")
            self._insert_raw_entity(conn, "rust1", "technology", "Rust", "2026-01-01T00:00:00Z")
            self._insert_raw_relationship(conn, "r1", "ai1", "rust1", "co-occurs", 3.0, "2026-01-01T00:00:00Z")
            self._insert_raw_relationship(conn, "r2", "ai2", "rust1", "co-occurs", 4.0, "2026-01-02T00:00:00Z")
            conn.commit()

            database._migrate_v4(conn)

            rels = conn.execute("SELECT from_id, to_id, weight FROM relationships").fetchall()
        assert len(rels) == 1
        assert rels[0]["weight"] == pytest.approx(7.0)

    def test_self_loop_relationships_removed_after_merge(self, fresh_db):
        """If two duplicate entities had a (bogus) relationship to each
        other, merging them creates a self-loop, which must be dropped."""
        with database.get_connection() as conn:
            conn.execute("DROP INDEX IF EXISTS idx_entities_type_name")
            conn.execute("DROP INDEX IF EXISTS idx_entities_type_name_domain")
            self._insert_raw_entity(conn, "ai1", "technology", "AI", "2026-01-01T00:00:00Z")
            self._insert_raw_entity(conn, "ai2", "technology", "AI", "2026-01-02T00:00:00Z")
            self._insert_raw_relationship(conn, "r1", "ai1", "ai2", "co-occurs", 1.0, "2026-01-01T00:00:00Z")
            conn.commit()

            database._migrate_v4(conn)

            rels = conn.execute("SELECT COUNT(*) c FROM relationships").fetchone()
        assert rels["c"] == 0

    def test_migration_is_idempotent(self, fresh_db):
        """Running the migration twice must not error or change the result."""
        with database.get_connection() as conn:
            conn.execute("DROP INDEX IF EXISTS idx_entities_type_name")
            conn.execute("DROP INDEX IF EXISTS idx_entities_type_name_domain")
            self._insert_raw_entity(conn, "e1", "technology", "AI", "2026-01-01T00:00:00Z")
            self._insert_raw_entity(conn, "e2", "technology", "AI", "2026-01-02T00:00:00Z")
            conn.commit()

            database._migrate_v4(conn)
            database._migrate_v4(conn)  # should be a no-op the second time

            remaining = conn.execute(
                "SELECT COUNT(*) c FROM entities WHERE type = 'technology' AND name = 'AI'"
            ).fetchone()
        assert remaining["c"] == 1

    def test_migration_runs_cleanly_on_fresh_database(self, fresh_db):
        """initialize() already ran _migrate_v4 once for this fixture (via
        the normal startup path) — must not have raised, and the schema
        must report version 4."""
        with database.get_connection() as conn:
            version = conn.execute(
                "SELECT version FROM schema_info ORDER BY version DESC LIMIT 1"
            ).fetchone()["version"]
        assert version == database.SCHEMA_VERSION == 5
