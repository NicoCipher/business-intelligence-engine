"""
tests/test_semantic_eval_controls.py — ordinary pytest regression tests
for the Semantic Evaluation Baseline V1 corpus's PRESERVE cases ONLY.

Reviewed design: see the Semantic Evaluation Baseline V1 milestone.
Exactly five cases from tests/semantic_eval/corpus.py are classified
PRESERVE (desirable current behavior, safe to lock in): C1, C3, P1, P2,
S3. Every other case in that corpus (LIMITATION, UNRESOLVED) is
diagnostic-only and deliberately does NOT appear here — asserting a
LIMITATION case's current (defective) output as correct would block a
future fix from ever landing cleanly, and asserting a value for an
UNRESOLVED case would decide an open architectural question (does
actor/market belong in Problem identity?) through a test fixture
instead of through governance. See corpus.py's module docstring and
each case's own `rationale` for the full reasoning.

This file intentionally reuses the exact same per-layer dispatch
functions run_baseline.py uses (`_run_clustering`, `_run_canonicalization`,
`_run_scoring`), rather than re-implementing "how do I call
PatternDetector" a second time — a second, subtly different way of
invoking the same mechanism would be exactly the kind of duplicated
decision this project's architecture consistently avoids.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import database
from tests.semantic_eval.corpus import CORPUS, PRESERVE_CASE_IDS, Classification, Layer
from tests.semantic_eval.run_baseline import _run_canonicalization, _run_clustering, _run_scoring

_PRESERVE_CASES = {c.id: c for c in CORPUS if c.id in PRESERVE_CASE_IDS}


def test_preserve_case_ids_match_the_reviewed_design():
    """Guards against silent corpus drift -- if a case's classification
    ever changes, this file's scope must be revisited deliberately, not
    accidentally picked up by a loop."""
    assert PRESERVE_CASE_IDS == frozenset({"C1", "C3", "P1", "P2", "S3"})
    for case_id in PRESERVE_CASE_IDS:
        assert _PRESERVE_CASES[case_id].classification is Classification.PRESERVE


class TestClusteringPreserveCases:
    def test_c1_near_identical_phrasing_clusters_together(self):
        case = _PRESERVE_CASES["C1"]
        result = _run_clustering(case)
        assert result["clustered_together"] is True
        assert result["clustered_together"] == case.expected_cluster

    def test_c3_unrelated_topics_do_not_cluster(self):
        case = _PRESERVE_CASES["C3"]
        result = _run_clustering(case)
        assert result["clustered_together"] is False
        assert result["clustered_together"] == case.expected_cluster


class TestCanonicalizationPreserveCases:
    @pytest.fixture
    def fresh_db(self, tmp_path, monkeypatch):
        db_path = tmp_path / "test_semantic_eval_controls.db"
        monkeypatch.setattr(database, "DB_PATH", db_path)
        database.initialize()
        yield db_path

    def test_p1_same_entities_close_title_matches(self, fresh_db):
        case = _PRESERVE_CASES["P1"]
        with database.get_connection() as conn:
            result = _run_canonicalization(case, conn)
        assert result["matched"] is True
        assert result["matched"] == case.expected_match

    def test_p2_wording_drift_with_correct_entities_still_matches(self, fresh_db):
        case = _PRESERVE_CASES["P2"]
        with database.get_connection() as conn:
            result = _run_canonicalization(case, conn)
        assert result["matched"] is True
        assert result["matched"] == case.expected_match


class TestScoringPreserveCases:
    def test_s3_unambiguous_demand_language_triggers_demand_score(self):
        case = _PRESERVE_CASES["S3"]
        result = _run_scoring(case)
        assert result["score"] > 0
        assert "demand" in result["reason"].lower() or "solution" in result["reason"].lower()
