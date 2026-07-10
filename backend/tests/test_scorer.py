"""
tests/test_scorer.py — Test suite for OpportunityScorer

Tests are organised by dimension, then by composite and transparency.
Every test targets a specific documented behaviour from scorer.py's
docstring. If a test fails, the docstring is wrong or the code is wrong —
one of them must be fixed.

Run with:
    cd backend && pytest tests/test_scorer.py -v
"""

import pytest
from opportunity_engine.scorer import OpportunityScorer
from models import Signal, OpportunityScores
from config import SCORE_WEIGHTS


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def scorer():
    return OpportunityScorer()


# ── Empty input ───────────────────────────────────────────────────────────

class TestEmptyInput:
    def test_empty_list_returns_zero_scores(self, scorer):
        result = scorer.score([])
        assert result.demand == 0.0
        assert result.competition == 0.0
        assert result.confidence == 0.0
        assert result.evidence_count == 0

    def test_empty_list_composite_is_zero(self, scorer):
        result = scorer.score([])
        assert result.composite() == 0.0


# ── Evidence count ────────────────────────────────────────────────────────

class TestEvidenceCount:
    def test_evidence_count_matches_input_length(self, scorer, make_signal):
        for n in [1, 3, 7, 12]:
            signals = [make_signal() for _ in range(n)]
            result = scorer.score(signals)
            assert result.evidence_count == n, f"Expected {n}, got {result.evidence_count}"


# ── Demand dimension ──────────────────────────────────────────────────────

class TestDemandScoring:
    def test_more_signals_yields_higher_demand(self, scorer, make_signal):
        few  = [make_signal() for _ in range(2)]
        many = [make_signal() for _ in range(12)]
        assert scorer.score(many).demand > scorer.score(few).demand

    def test_demand_keywords_increase_score(self, scorer, make_signal):
        generic = [make_signal(title="Interesting discussion about tools") for _ in range(3)]
        demand  = [make_signal(title="Looking for alternatives to X — any recommendations?") for _ in range(3)]
        assert scorer.score(demand).demand > scorer.score(generic).demand

    def test_high_engagement_increases_demand(self, scorer, make_signal):
        low  = [make_signal(score=0,   comments=0)   for _ in range(4)]
        high = [make_signal(score=500, comments=200) for _ in range(4)]
        assert scorer.score(high).demand > scorer.score(low).demand

    def test_demand_bounded_zero_to_ten(self, scorer, demand_signals):
        result = scorer.score(demand_signals)
        assert 0.0 <= result.demand <= 10.0


# ── Competition dimension ─────────────────────────────────────────────────

class TestCompetitionScoring:
    def test_base_competition_is_moderate(self, scorer, make_signal):
        """Without explicit signals, competition defaults to ~5.5 (conservative)."""
        signals = [make_signal(title="Generic topic") for _ in range(3)]
        result  = scorer.score(signals)
        # Should be near the default base (5.5), not zero or ten
        assert 4.0 <= result.competition <= 8.0

    def test_low_competition_phrases_raise_score(self, scorer, make_signal):
        generic  = [make_signal(title="General topic") for _ in range(3)]
        gap_signals = [
            make_signal(title="Nothing like it exists — built this because no solution existed")
            for _ in range(3)
        ]
        assert scorer.score(gap_signals).competition > scorer.score(generic).competition

    def test_competition_bounded(self, scorer, demand_signals):
        assert 0.0 <= scorer.score(demand_signals).competition <= 10.0


# ── Revenue potential dimension ───────────────────────────────────────────

class TestRevenuePotentialScoring:
    def test_willingness_to_pay_phrases_increase_revenue(self, scorer, make_signal):
        no_pay  = [make_signal(title="Interesting community discussion") for _ in range(3)]
        pay_sig = [make_signal(title="I would pay $200/month for a tool that does X") for _ in range(3)]
        assert scorer.score(pay_sig).revenue_potential > scorer.score(no_pay).revenue_potential

    def test_b2b_context_increases_revenue(self, scorer, make_signal):
        consumer = [make_signal(title="Personal hobby project tool") for _ in range(3)]
        b2b      = [make_signal(title="Enterprise B2B SaaS for business teams") for _ in range(3)]
        assert scorer.score(b2b).revenue_potential > scorer.score(consumer).revenue_potential

    def test_minimum_floor_with_multiple_demand_signals(self, scorer, demand_signals):
        """3+ demand signals should produce at least a minimal revenue floor."""
        result = scorer.score(demand_signals)
        assert result.revenue_potential >= 1.5


# ── Execution difficulty (inverted) ──────────────────────────────────────

class TestExecutionDifficultyScoring:
    def test_easy_keywords_raise_score(self, scorer, make_signal):
        hard = [make_signal(title="Biotech clinical trial hardware semiconductor chip") for _ in range(3)]
        easy = [make_signal(title="Notion template newsletter writing consulting service") for _ in range(3)]
        assert scorer.score(easy).execution_difficulty > scorer.score(hard).execution_difficulty

    def test_score_stays_within_one_to_ten(self, scorer, make_signal):
        signals = [make_signal(title="PhD biotech hardware clinical trial chip FDA") for _ in range(3)]
        result  = scorer.score(signals)
        assert 1.0 <= result.execution_difficulty <= 10.0


# ── Risk (inverted) ───────────────────────────────────────────────────────

class TestRiskScoring:
    def test_risk_keywords_lower_score(self, scorer, make_signal):
        safe  = [make_signal(title="Niche productivity tool for freelancers") for _ in range(3)]
        risky = [make_signal(title="Google announced competing product; regulation banned it; bubble overhyped") for _ in range(3)]
        assert scorer.score(safe).risk > scorer.score(risky).risk

    def test_default_risk_is_moderate_low(self, scorer, make_signal):
        """No risk signals → default is 7.0 (moderate-low risk)."""
        signals = [make_signal(title="Completely neutral technical topic") for _ in range(3)]
        result  = scorer.score(signals)
        assert result.risk >= 5.0  # Should not be penalised for unknown risk

    def test_risk_bounded(self, scorer, demand_signals):
        assert 0.0 <= scorer.score(demand_signals).risk <= 10.0


# ── Confidence dimension ──────────────────────────────────────────────────

class TestConfidenceScoring:
    def test_multiple_sources_raise_confidence(
        self, scorer, single_source_signals, multi_source_signals
    ):
        single = scorer.score(single_source_signals).confidence
        multi  = scorer.score(multi_source_signals).confidence
        assert multi > single, (
            f"Multi-source ({multi:.2f}) should beat single-source ({single:.2f})"
        )

    def test_high_engagement_raises_confidence(self, scorer, make_signal):
        low_q  = [make_signal(score=0,   comments=0)   for _ in range(4)]
        high_q = [make_signal(score=800, comments=150) for _ in range(4)]
        assert scorer.score(high_q).confidence > scorer.score(low_q).confidence

    def test_single_signal_produces_low_confidence(self, scorer, make_signal):
        single = [make_signal(score=1000, comments=500)]
        result = scorer.score(single)
        # Even very high engagement on one signal should not yield high confidence
        assert result.confidence < 6.0

    def test_confidence_bounded(self, scorer, demand_signals):
        assert 0.0 <= scorer.score(demand_signals).confidence <= 10.0


# ── Composite score and tier ──────────────────────────────────────────────

class TestCompositeAndTier:
    def test_composite_within_zero_to_ten(self, scorer, demand_signals):
        composite = scorer.score(demand_signals).composite()
        assert 0.0 <= composite <= 10.0

    def test_all_tens_yields_composite_ten(self):
        scores = OpportunityScores(
            demand=10, competition=10, revenue_potential=10,
            execution_difficulty=10, time_to_revenue=10,
            risk=10, confidence=10,
        )
        assert scores.composite() == 10.0

    def test_all_zeros_yields_composite_zero(self):
        assert OpportunityScores().composite() == 0.0

    def test_tier_gold_at_eight_plus(self):
        scores = OpportunityScores(
            demand=10, competition=9, revenue_potential=9,
            execution_difficulty=9, time_to_revenue=9,
            risk=9, confidence=9,
        )
        assert scores.tier() == "gold"
        assert scores.composite() >= 8.0

    def test_tier_silver_between_6_5_and_8(self):
        scores = OpportunityScores(
            demand=7, competition=7, revenue_potential=7,
            execution_difficulty=7, time_to_revenue=7,
            risk=7, confidence=7,
        )
        tier = scores.tier()
        comp = scores.composite()
        assert tier == "silver"
        assert 6.5 <= comp < 8.0

    def test_tier_bronze_below_6_5(self):
        scores = OpportunityScores(
            demand=3, competition=3, revenue_potential=3,
            execution_difficulty=3, time_to_revenue=3,
            risk=3, confidence=3,
        )
        assert scores.tier() == "bronze"
        assert scores.composite() < 6.5

    def test_demand_signals_score_above_zero(self, scorer, demand_signals):
        """A realistic cluster of demand signals should produce a non-trivial score."""
        result = scorer.score(demand_signals)
        assert result.composite() > 3.0, (
            f"Realistic demand signals scored only {result.composite():.2f} — "
            f"scoring model may be too conservative"
        )


# ── Transparency guarantees ───────────────────────────────────────────────

class TestTransparency:
    def test_score_weights_sum_to_exactly_one(self):
        total = sum(SCORE_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9, (
            f"SCORE_WEIGHTS sum to {total}, not 1.0. "
            f"Edit config.py to fix the weights."
        )

    def test_to_dict_contains_all_dimensions(self, scorer, demand_signals):
        scores = scorer.score(demand_signals)
        d = scores.to_dict()
        required_keys = {
            "demand", "competition", "revenue_potential",
            "execution_difficulty", "time_to_revenue",
            "risk", "confidence", "evidence_count", "composite", "tier",
        }
        missing = required_keys - set(d.keys())
        assert not missing, f"to_dict() is missing keys: {missing}"

    def test_all_dimensions_bounded(self, scorer, demand_signals):
        result = scorer.score(demand_signals)
        dims = [
            "demand", "competition", "revenue_potential",
            "execution_difficulty", "time_to_revenue", "risk", "confidence",
        ]
        for dim in dims:
            val = getattr(result, dim)
            assert 0.0 <= val <= 10.0, (
                f"Dimension '{dim}' = {val:.2f} is outside [0, 10]. "
                f"The scorer has a bug in _{dim}()."
            )

    def test_from_dict_roundtrip(self, scorer, demand_signals):
        """Serialise to dict and deserialise — composite must be identical."""
        original = scorer.score(demand_signals)
        d = original.to_dict()
        restored = OpportunityScores.from_dict(d)
        assert abs(original.composite() - restored.composite()) < 0.01
