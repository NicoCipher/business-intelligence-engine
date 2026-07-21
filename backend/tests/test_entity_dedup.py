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
        assert "idx_entities_type_name" in indexes


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
        assert "idx_rel_from_to_type" in indexes


# ── Migration: cleaning up pre-existing duplicates ────────────────────────

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
            conn.execute("DROP INDEX IF EXISTS idx_rel_from_to_type")
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
        assert version == database.SCHEMA_VERSION == 4
