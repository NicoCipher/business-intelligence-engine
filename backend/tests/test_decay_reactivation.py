"""
tests/test_decay_reactivation.py — Two things schema v8 changed that
deserve their own focused coverage, separate from test_decay.py's
pure-logic and run_decay_pass() tests:

  1. Reactivation on new evidence — knowledge_graph/extractor.py's
     persist_results() is the ONLY reactivation path (decay only ever
     moves state forward; this is what moves it back). Also covers the
     updated_at recency-tracking gap that was fixed alongside this: a
     re-encountered entity used to never have its updated_at touched at
     all (INSERT OR IGNORE did nothing on conflict).

  2. Lifecycle-aware matching — opportunity_engine/canonicalizer.py's
     find_match() now weights entity-Jaccard by lifecycle state instead
     of counting every entity id equally. Confirms the two-layer
     eligibility rule (active=full, dormant=reduced, archived=excluded)
     actually changes matching outcomes, not just that the weighting
     function exists in isolation (that's covered in test_decay.py).

Run with:
    cd backend && pytest tests/test_decay_reactivation.py -v
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import database
from knowledge_graph.extractor import EntityExtractor
from opportunity_engine import canonicalizer


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_decay_reactivation.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    database.initialize()
    yield db_path


def _set_lifecycle(conn, table, id_, state):
    conn.execute(f"UPDATE {table} SET lifecycle_state = ? WHERE id = ?", (state, id_))
    conn.commit()


def _get_entity(conn, type_, name, domain="business"):
    return conn.execute(
        "SELECT * FROM entities WHERE type = ? AND name = ? COLLATE NOCASE AND domain = ?",
        (type_, name, domain),
    ).fetchone()


class TestEntityReactivation:
    def test_dormant_entity_reactivates_on_re_encounter(self, fresh_db, make_signal):
        extractor = EntityExtractor()
        sig = make_signal(title="We need better compliance tracking")
        extractor.persist_results(extractor.extract_batch([sig]))

        with database.get_connection() as conn:
            entity = _get_entity(conn, "problem", "compliance")
            _set_lifecycle(conn, "entities", entity["id"], "dormant")

        extractor.persist_results(extractor.extract_batch([sig]))

        with database.get_connection() as conn:
            entity = _get_entity(conn, "problem", "compliance")
        assert entity["lifecycle_state"] == "active"

    def test_archived_entity_reactivates_on_re_encounter(self, fresh_db, make_signal):
        extractor = EntityExtractor()
        sig = make_signal(title="We need better compliance tracking")
        extractor.persist_results(extractor.extract_batch([sig]))

        with database.get_connection() as conn:
            entity = _get_entity(conn, "problem", "compliance")
            _set_lifecycle(conn, "entities", entity["id"], "archived")

        extractor.persist_results(extractor.extract_batch([sig]))

        with database.get_connection() as conn:
            entity = _get_entity(conn, "problem", "compliance")
        assert entity["lifecycle_state"] == "active"

    def test_updated_at_bumps_on_re_encounter_not_just_first_insert(self, fresh_db, make_signal):
        """The recency-tracking gap this whole feature depended on fixing:
        before schema v8, INSERT OR IGNORE meant a re-encountered
        entity's updated_at never changed after its first insert."""
        extractor = EntityExtractor()
        sig = make_signal(title="We need better compliance tracking")
        extractor.persist_results(extractor.extract_batch([sig]))

        with database.get_connection() as conn:
            first_updated_at = _get_entity(conn, "problem", "compliance")["updated_at"]

        import time
        time.sleep(0.01)
        extractor.persist_results(extractor.extract_batch([sig]))

        with database.get_connection() as conn:
            second_updated_at = _get_entity(conn, "problem", "compliance")["updated_at"]

        assert second_updated_at > first_updated_at

    def test_lifecycle_updated_at_only_changes_on_an_actual_state_change(self, fresh_db, make_signal):
        """Re-encountering an already-active entity should bump
        updated_at (recency) but NOT lifecycle_updated_at (state hasn't
        actually changed) -- otherwise "how long has this been active"
        would be meaningless."""
        extractor = EntityExtractor()
        sig = make_signal(title="We need better compliance tracking")
        extractor.persist_results(extractor.extract_batch([sig]))

        with database.get_connection() as conn:
            first_lifecycle_updated_at = _get_entity(conn, "problem", "compliance")["lifecycle_updated_at"]

        import time
        time.sleep(0.01)
        extractor.persist_results(extractor.extract_batch([sig]))

        with database.get_connection() as conn:
            second_lifecycle_updated_at = _get_entity(conn, "problem", "compliance")["lifecycle_updated_at"]

        assert first_lifecycle_updated_at == second_lifecycle_updated_at

    def test_first_insert_is_active_by_default(self, fresh_db, make_signal):
        extractor = EntityExtractor()
        sig = make_signal(title="We need better compliance tracking")
        extractor.persist_results(extractor.extract_batch([sig]))
        with database.get_connection() as conn:
            entity = _get_entity(conn, "problem", "compliance")
        assert entity["lifecycle_state"] == "active"

    def test_entities_inserted_count_still_correct_with_upsert(self, fresh_db, make_signal):
        """Confirms the switch from INSERT OR IGNORE to an upsert didn't
        break the entities_inserted counter: a true first insert counts,
        a re-encounter does not."""
        extractor = EntityExtractor()
        sig = make_signal(title="We need better compliance tracking")
        counts1 = extractor.persist_results(extractor.extract_batch([sig]))
        counts2 = extractor.persist_results(extractor.extract_batch([sig]))
        assert counts1["entities_inserted"] == 1
        assert counts2["entities_inserted"] == 0


class TestRelationshipReactivation:
    def test_dormant_relationship_reactivates_on_re_encounter(self, fresh_db, make_signal):
        extractor = EntityExtractor()
        sig = make_signal(title="AI regulation affects the healthcare market")
        extractor.persist_results(extractor.extract_batch([sig]))

        with database.get_connection() as conn:
            rel = conn.execute("SELECT * FROM relationships LIMIT 1").fetchone()
            assert rel is not None, "fixture signal should produce at least one relationship"
            _set_lifecycle(conn, "relationships", rel["id"], "dormant")

        extractor.persist_results(extractor.extract_batch([sig]))

        with database.get_connection() as conn:
            rel = conn.execute("SELECT * FROM relationships WHERE id = ?", (rel["id"],)).fetchone()
        assert rel["lifecycle_state"] == "active"


class TestLifecycleAwareMatching:
    """
    find_match() (opportunity_engine/canonicalizer.py) now weights
    entity-Jaccard by lifecycle state. These tests confirm the weighting
    actually changes match outcomes, using real `entities` rows (not the
    bare synthetic ids most of test_canonicalizer.py uses, which
    deliberately exercise the "no lifecycle info -> full weight" default
    instead).
    """

    def _insert_problem(self, conn, id_, title, entity_ids, domain="business"):
        import json
        from models import _now
        conn.execute(
            """
            INSERT INTO problems (id, domain, title, entity_ids, first_seen, last_seen, weeks_seen, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (id_, domain, title, json.dumps(entity_ids), _now(), _now(), _now(), _now()),
        )

    def _insert_entity_with_state(self, conn, id_, state, domain="business"):
        from models import _now
        conn.execute(
            """
            INSERT INTO entities (id, type, name, domain, created_at, updated_at, lifecycle_state, lifecycle_updated_at)
            VALUES (?, 'technology', ?, ?, ?, ?, ?, ?)
            """,
            (id_, id_, domain, _now(), _now(), state, _now()),
        )

    def test_archived_entities_excluded_prevent_a_match_that_would_otherwise_qualify(self, fresh_db):
        with database.get_connection() as conn:
            self._insert_entity_with_state(conn, "e1", "archived")
            self._insert_entity_with_state(conn, "e2", "archived")
            self._insert_problem(conn, "p1", "Old problem", ["e1", "e2"])
            conn.commit()

            # Identical entity signature -- would be a perfect 1.0 plain
            # Jaccard match, but both entities are archived.
            match = canonicalizer.find_match(["e1", "e2"], "Old problem", "business", conn)
        assert match is None

    def test_active_entities_still_match_normally(self, fresh_db):
        with database.get_connection() as conn:
            self._insert_entity_with_state(conn, "e1", "active")
            self._insert_entity_with_state(conn, "e2", "active")
            self._insert_problem(conn, "p1", "Old problem", ["e1", "e2"])
            conn.commit()

            match = canonicalizer.find_match(["e1", "e2"], "Old problem", "business", conn)
        assert match is not None
        assert match["problem_id"] == "p1"

    def test_dormant_entities_match_at_reduced_score_not_full(self, fresh_db):
        """
        Identical entity sets aren't a useful test here -- weighting every
        member equally (even at a reduced weight) doesn't change a ratio
        between two IDENTICAL sets, since the weight cancels out
        (intersection and union scale together). The weighting only
        actually changes the score with a PARTIAL overlap, where some
        entities are unique to one side and don't get the same discount.
        """
        with database.get_connection() as conn:
            self._insert_entity_with_state(conn, "shared_active", "active")
            self._insert_entity_with_state(conn, "unique_active", "active")
            self._insert_problem(conn, "p_active", "Shared problem pattern", ["shared_active", "unique_active"])
            conn.commit()
            # New opportunity shares one entity, has one unique of its own.
            active_match = canonicalizer.find_match(
                ["shared_active", "unrelated-synthetic-1"], "Shared problem pattern", "business", conn,
            )

            self._insert_entity_with_state(conn, "shared_dormant", "dormant")
            self._insert_entity_with_state(conn, "unique_dormant", "active")
            self._insert_problem(conn, "p_dormant", "Shared problem pattern", ["shared_dormant", "unique_dormant"])
            conn.commit()
            dormant_match = canonicalizer.find_match(
                ["shared_dormant", "unrelated-synthetic-2"], "Shared problem pattern", "business", conn,
            )

        assert active_match is not None
        assert dormant_match is not None
        assert dormant_match["match_score"] < active_match["match_score"]

    def test_unknown_entity_ids_default_to_full_weight_backward_compat(self, fresh_db):
        """Entity ids with no corresponding `entities` row at all (the
        norm throughout the rest of test_canonicalizer.py) must behave
        exactly as before schema v8 -- full weight, no penalty."""
        with database.get_connection() as conn:
            self._insert_problem(conn, "p1", "Old problem", ["synthetic-e1", "synthetic-e2"])
            conn.commit()
            match = canonicalizer.find_match(["synthetic-e1", "synthetic-e2"], "Old problem", "business", conn)
        assert match is not None
        assert match["match_score"] == 1.0  # entity_j=1.0 (both unknown -> full weight) * 0.7 + title_j=1.0 * 0.3

    def test_mixed_known_and_unknown_entity_ids(self, fresh_db):
        """One archived (known, excluded), one with no row at all (default
        full weight) -- confirms the two rules compose correctly rather
        than one silently overriding the other."""
        with database.get_connection() as conn:
            self._insert_entity_with_state(conn, "e1", "archived")
            self._insert_problem(conn, "p1", "Unrelated title text", ["e1", "synthetic-e2"])
            conn.commit()
            # e1 excluded (weight 0), synthetic-e2 defaults to full weight
            # and is present on both sides -> should still match on that
            # one surviving shared entity.
            match = canonicalizer.find_match(["e1", "synthetic-e2"], "Unrelated title text", "business", conn)
        assert match is not None
