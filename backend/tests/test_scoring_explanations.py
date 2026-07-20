"""
tests/test_scoring_explanations.py — Tests for OpportunityScorer's
per-dimension explanations (scorer.py's "no black boxes" goal 2 upgrade).

These are separate from test_scorer.py, which covers the numeric behaviour
of each dimension and must keep passing unchanged. This file only tests
the new reason/evidence layer added alongside those numbers.

Run with:
    cd backend && pytest tests/test_scoring_explanations.py -v
"""

import pytest
from opportunity_engine.scorer import OpportunityScorer
from models import OpportunityScores, DimensionExplanation


@pytest.fixture
def scorer():
    return OpportunityScorer()


_ALL_DIMENSIONS = [
    "demand", "competition", "revenue_potential",
    "execution_difficulty", "time_to_revenue", "risk", "confidence",
]


class TestExplanationsPresent:
    def test_every_dimension_has_an_explanation(self, scorer, demand_signals):
        result = scorer.score(demand_signals)
        missing = [d for d in _ALL_DIMENSIONS if d not in result.explanations]
        assert not missing, f"Missing explanations for: {missing}"

    def test_explanations_are_dimension_explanation_instances(self, scorer, demand_signals):
        result = scorer.score(demand_signals)
        for dim in _ALL_DIMENSIONS:
            assert isinstance(result.explanations[dim], DimensionExplanation)

    def test_reason_and_evidence_are_non_empty_strings(self, scorer, demand_signals):
        result = scorer.score(demand_signals)
        for dim in _ALL_DIMENSIONS:
            exp = result.explanations[dim]
            assert isinstance(exp.reason, str) and exp.reason.strip()
            assert isinstance(exp.evidence, str) and exp.evidence.strip()

    def test_explanation_score_matches_dimension_score(self, scorer, demand_signals):
        """The score stored on the explanation must equal the dimension's own value —
        the explanation should never be able to drift from the number it describes."""
        result = scorer.score(demand_signals)
        for dim in _ALL_DIMENSIONS:
            assert result.explanations[dim].score == getattr(result, dim)

    def test_empty_signals_produce_no_explanations(self, scorer):
        result = scorer.score([])
        assert result.explanations == {}


class TestExplanationContentReflectsEvidence:
    """The reason text should actually change when the underlying evidence changes —
    otherwise it's just a label, not an explanation."""

    def test_demand_evidence_mentions_keyword_count(self, scorer, make_signal):
        signals = [
            make_signal(title="Looking for alternatives to X — any recommendations?")
            for _ in range(3)
        ]
        result = scorer.score(signals)
        exp = result.explanations["demand"]
        assert "demand-keyword match" in exp.evidence

    def test_low_competition_reason_differs_from_default_reason(self, scorer, make_signal):
        generic = [make_signal(title="General topic") for _ in range(3)]
        gap = [
            make_signal(title="Nothing like it exists — built this because no solution existed")
            for _ in range(3)
        ]
        generic_reason = scorer.score(generic).explanations["competition"].reason
        gap_reason = scorer.score(gap).explanations["competition"].reason
        assert generic_reason != gap_reason
        assert "market gap" in gap_reason.lower() or "underserved" in gap_reason.lower() or "gap" in gap_reason.lower()

    def test_single_source_confidence_reason_flags_single_source(
        self, scorer, single_source_signals
    ):
        result = scorer.score(single_source_signals)
        reason = result.explanations["confidence"].reason.lower()
        assert "single source" in reason or "single" in reason

    def test_multi_source_confidence_reason_mentions_corroboration(
        self, scorer, multi_source_signals
    ):
        result = scorer.score(multi_source_signals)
        reason = result.explanations["confidence"].reason.lower()
        assert "corroborat" in reason or "independent" in reason

    def test_time_to_revenue_reason_differs_by_category(self, scorer, make_signal):
        service = [make_signal(title="Freelance consulting service for X") for _ in range(3)]
        platform = [make_signal(title="A community marketplace platform for X") for _ in range(3)]
        service_reason = scorer.score(service).explanations["time_to_revenue"].reason
        platform_reason = scorer.score(platform).explanations["time_to_revenue"].reason
        assert service_reason != platform_reason


class TestSerialisationRoundtrip:
    def test_to_dict_includes_explanations(self, scorer, demand_signals):
        result = scorer.score(demand_signals)
        d = result.to_dict()
        assert "explanations" in d
        assert set(d["explanations"].keys()) == set(_ALL_DIMENSIONS)
        for dim in _ALL_DIMENSIONS:
            exp = d["explanations"][dim]
            assert set(exp.keys()) == {"score", "reason", "evidence"}

    def test_from_dict_restores_explanations(self, scorer, demand_signals):
        original = scorer.score(demand_signals)
        restored = OpportunityScores.from_dict(original.to_dict())
        for dim in _ALL_DIMENSIONS:
            assert restored.explanations[dim].reason == original.explanations[dim].reason
            assert restored.explanations[dim].evidence == original.explanations[dim].evidence
            assert restored.explanations[dim].score == original.explanations[dim].score

    def test_composite_unaffected_by_explanations(self, scorer, demand_signals):
        """Adding explanations must not change the composite score itself."""
        original = scorer.score(demand_signals)
        restored = OpportunityScores.from_dict(original.to_dict())
        assert original.composite() == restored.composite()

    def test_legacy_dict_without_explanations_still_loads(self):
        """A pre-upgrade persisted row (no 'explanations' key) must still deserialise."""
        legacy = {
            "demand": 7.0, "competition": 6.0, "revenue_potential": 5.0,
            "execution_difficulty": 6.0, "time_to_revenue": 5.5,
            "risk": 7.0, "confidence": 6.0, "evidence_count": 4,
        }
        restored = OpportunityScores.from_dict(legacy)
        assert restored.explanations == {}
        assert restored.composite() > 0.0


class TestBackwardCompatibility:
    def test_plain_numeric_construction_still_works(self):
        """Existing test_scorer.py-style construction must keep working unchanged."""
        scores = OpportunityScores(
            demand=10, competition=9, revenue_potential=9,
            execution_difficulty=9, time_to_revenue=9, risk=9, confidence=9,
        )
        assert scores.explanations == {}
        assert scores.tier() == "gold"
