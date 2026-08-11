"""
tests/test_scoring_generalization.py — ADR-011: Domain-Generalized
Opportunity Scoring.

Covers what's actually new (not re-covered by test_scorer.py /
test_scoring_explanations.py, which already prove zero behavior change
for Business): OpportunityScores.dimensions as a domain-neutral dict,
domain-supplied weights/thresholds, OpportunityScorer accepting an
explicit DomainScoring (Tier-2 dispatch to a supplied compute_fn, and
the Tier-1 generic keyword fallback when no compute_fn is supplied), and
the api/opportunities.py fix that reads tier from the persisted scores
JSON instead of recomputing it from hardcoded thresholds.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import OpportunityScores, Signal
from domains.base import DomainScoring, ScoringDimension, ScoringThresholds
from opportunity_engine.scorer import OpportunityScorer


def _signal(text: str, source: str = "reddit", platform_score: int = 5, comment_count: int = 2) -> Signal:
    return Signal(
        source=source, source_id=f"id-{hash(text) % 10_000}",
        title=text, content="", platform_score=platform_score,
        comment_count=comment_count,
    )


class TestOpportunityScoresDimensions:
    def test_arbitrary_dimension_ids_accepted(self):
        """Not limited to Business's seven ids -- any domain's ids work."""
        s = OpportunityScores(dimensions={"severity": 9.0, "exploitability": 7.5})
        assert s.dimensions == {"severity": 9.0, "exploitability": 7.5}

    def test_composite_uses_supplied_weights_not_business_defaults(self):
        s = OpportunityScores(
            dimensions={"severity": 10.0, "exploitability": 0.0},
            weights={"severity": 0.8, "exploitability": 0.2},
        )
        assert s.composite() == 8.0

    def test_thresholds_are_domain_supplied(self):
        s = OpportunityScores(
            dimensions={"severity": 9.5},
            weights={"severity": 1.0},
            thresholds=(9.0, 5.0),
        )
        assert s.tier() == "gold"

        s2 = OpportunityScores(
            dimensions={"severity": 6.0},
            weights={"severity": 1.0},
            thresholds=(9.0, 5.0),
        )
        assert s2.tier() == "silver"

    def test_zero_context_construction_defaults_to_business_values(self):
        """No weights/thresholds supplied -> Business's current values,
        for any caller with no domain context (tests, from_dict on old rows)."""
        s = OpportunityScores(dimensions={"demand": 10, "competition": 10,
                                           "revenue_potential": 10, "confidence": 10,
                                           "execution_difficulty": 10,
                                           "time_to_revenue": 10, "risk": 10})
        assert s.composite() == 10.0
        assert s.tier() == "gold"

    def test_legacy_flat_kwarg_construction_and_dict_construction_are_equivalent(self):
        legacy = OpportunityScores(demand=7, competition=6, revenue_potential=5,
                                    execution_difficulty=4, time_to_revenue=3,
                                    risk=2, confidence=1)
        generalized = OpportunityScores(dimensions={
            "demand": 7, "competition": 6, "revenue_potential": 5,
            "execution_difficulty": 4, "time_to_revenue": 3,
            "risk": 2, "confidence": 1,
        })
        assert legacy.dimensions == generalized.dimensions
        assert legacy.composite() == generalized.composite()

    def test_property_setters_still_work_for_legacy_construction_pattern(self):
        """tests/test_explainer.py builds fixtures via post-construction
        attribute assignment (e.g. scores.demand = 9.0) -- must keep working
        since that file is unmodified by ADR-011."""
        s = OpportunityScores()
        s.demand = s.competition = s.revenue_potential = 9.0
        assert s.dimensions == {"demand": 9.0, "competition": 9.0, "revenue_potential": 9.0}

    def test_to_dict_from_dict_round_trip_with_non_business_dimension_ids(self):
        s = OpportunityScores(
            dimensions={"severity": 8.0, "exploitability": 6.0},
            weights={"severity": 0.6, "exploitability": 0.4},
            thresholds=(8.0, 5.0),
        )
        d = s.to_dict()
        assert d["severity"] == 8.0
        assert d["exploitability"] == 6.0
        assert "tier" in d and "composite" in d

        restored = OpportunityScores.from_dict(d)
        assert restored.dimensions == {"severity": 8.0, "exploitability": 6.0}
        # from_dict has no domain context -> falls back to Business
        # defaults, same as before this change for any persisted row.
        assert restored.weights != s.weights

    def test_to_dict_shape_unchanged_for_a_business_row(self):
        """Byte-compatibility check: a row shaped like one persisted
        before ADR-011 round-trips identically."""
        legacy_row = {
            "demand": 7.5, "competition": 6.0, "revenue_potential": 8.0,
            "execution_difficulty": 5.0, "time_to_revenue": 4.0,
            "risk": 7.0, "confidence": 6.5,
            "evidence_count": 3, "composite": 6.8, "tier": "silver",
            "explanations": {},
        }
        restored = OpportunityScores.from_dict(legacy_row)
        assert restored.demand == 7.5
        assert restored.evidence_count == 3
        re_serialized = restored.to_dict()
        assert re_serialized["demand"] == 7.5
        assert re_serialized["evidence_count"] == 3


class TestOpportunityScorerDomainDispatch:
    def test_default_scorer_uses_business_domain_scoring(self):
        scorer = OpportunityScorer()
        scores = scorer.score([_signal("i wish there was a tool, would pay, freelance b2b")])
        assert set(scores.dimensions.keys()) == {
            "demand", "competition", "revenue_potential",
            "execution_difficulty", "time_to_revenue", "risk", "confidence",
        }

    def test_explicit_domain_scoring_dispatches_to_its_compute_fn(self):
        def compute_severity(signals, blob):
            return (9.0, "always high for this test", "n/a")

        custom = DomainScoring(
            dimensions=[
                ScoringDimension(id="severity", label="Severity", description="",
                                  weight=1.0, compute_fn=compute_severity),
            ],
            thresholds=ScoringThresholds(high=8.0, medium=5.0),
        )
        scorer = OpportunityScorer(custom)
        scores = scorer.score([_signal("anything")])
        assert scores.dimensions == {"severity": 9.0}
        assert scores.tier() == "gold"

    def test_dimension_without_compute_fn_uses_generic_tier1_fallback(self):
        custom = DomainScoring(
            dimensions=[
                ScoringDimension(
                    id="urgency", label="Urgency", description="",
                    weight=1.0,
                    positive_keywords=frozenset(["critical", "urgent"]),
                    negative_keywords=frozenset(["low priority"]),
                    # no compute_fn -- must use the generic fallback
                ),
            ],
        )
        scorer = OpportunityScorer(custom)
        high = scorer.score([_signal("this is critical and urgent")])
        low = scorer.score([_signal("this is low priority, nothing else")])
        assert high.dimensions["urgency"] > 5.0
        assert low.dimensions["urgency"] < 5.0

    def test_empty_signals_returns_scores_with_domain_weights_still_set(self):
        custom = DomainScoring(
            dimensions=[ScoringDimension(id="x", label="X", description="", weight=1.0)],
        )
        scorer = OpportunityScorer(custom)
        scores = scorer.score([])
        assert scores.weights == {"x": 1.0}
        assert scores.composite() == 0.0


class TestApiTierReadsFromPersistedScores:
    """api/opportunities.py's _row_to_summary previously recomputed tier
    from composite_score against hardcoded 8.0/6.5 (ADR-011's fourth
    hardcode site) instead of trusting the tier already computed (using
    the correct domain's thresholds) and persisted at scoring time. This
    proves the fix: a deliberately mismatched row (composite_score would
    imply "gold" under the old hardcoded logic) must return the
    persisted tier, not a recomputed one.
    """

    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        import database
        db_path = tmp_path / "test_tier_fix.db"
        monkeypatch.setattr(database, "DB_PATH", db_path)
        monkeypatch.delenv("BIA_API_KEY", raising=False)
        database.initialize()

        import auth
        monkeypatch.setattr(auth, "API_KEY", "")

        from fastapi.testclient import TestClient
        from main import app
        with TestClient(app) as c:
            yield c

    def _seed(self, opp_id: str, composite_score: float, persisted_tier: str):
        import database
        import json
        with database.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO opportunities
                    (id, title, description, week_key, created_at, updated_at,
                     domain, composite_score, scores)
                VALUES (?, ?, ?, ?, datetime('now'), datetime('now'), ?, ?, ?)
                """,
                (opp_id, f"Opportunity {opp_id}", "desc", "2026-W28", "business",
                 composite_score, json.dumps({"tier": persisted_tier, "evidence_count": 1})),
            )
            conn.commit()

    def test_tier_comes_from_persisted_scores_not_recomputed_thresholds(self, client):
        # composite_score=8.5 would be "gold" under the old hardcoded
        # (>= 8.0) logic. The persisted scores JSON says "silver" (e.g.
        # a non-Business domain with a high=9.0 threshold). The fix must
        # return "silver".
        self._seed("opp-mismatch", composite_score=8.5, persisted_tier="silver")

        response = client.get("/api/v1/opportunities")

        assert response.status_code == 200
        body = response.json()
        opp = next(o for o in body["opportunities"] if o["id"] == "opp-mismatch")
        assert opp["tier"] == "silver"

    def test_missing_tier_in_scores_falls_back_to_bronze(self, client):
        import database
        with database.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO opportunities
                    (id, title, description, week_key, created_at, updated_at, domain)
                VALUES (?, ?, ?, ?, datetime('now'), datetime('now'), ?)
                """,
                ("opp-empty", "Opportunity opp-empty", "desc", "2026-W28", "business"),
            )
            conn.commit()

        response = client.get("/api/v1/opportunities")

        assert response.status_code == 200
        body = response.json()
        opp = next(o for o in body["opportunities"] if o["id"] == "opp-empty")
        assert opp["tier"] == "bronze"
