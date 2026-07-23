"""
tests/test_detector_diagnose.py — Tests for PatternDetector.diagnose(),
the read-only twin of detect() that keeps rejected clusters with reasons.

Critically, these tests also confirm diagnose() has zero effect on
detect()/detect_and_persist() — the existing pipeline behaviour.

Run with:
    cd backend && pytest tests/test_detector_diagnose.py -v
"""

import pytest

from opportunity_engine.detector import PatternDetector, RejectedCluster, DetectionDiagnostics


@pytest.fixture
def detector():
    return PatternDetector()


class TestDiagnoseBasics:
    def test_empty_signals_returns_empty_diagnostics(self, detector):
        result = detector.diagnose([])
        assert result.accepted == []
        assert result.rejected == []
        assert isinstance(result, DetectionDiagnostics)

    def test_qualifying_cluster_appears_in_accepted(self, detector, make_signal):
        # Near-identical keyword-rich titles across two sources, with
        # willingness-to-pay + B2B language, so this reliably both
        # Jaccard-clusters together and scores above MIN_COMPOSITE_TO_PERSIST —
        # demand_signals (conftest) is intentionally worded more naturally
        # and doesn't always cluster into one group, so it isn't suitable here.
        qualifying = [
            make_signal(
                title="Looking for automated compliance tracking software for business teams",
                source="hn", score=200, comments=80,
            ),
            make_signal(
                title="I would pay for automated compliance tracking software for business teams",
                source="reddit", score=180, comments=60,
            ),
            make_signal(
                title="Any automated compliance tracking software for business teams out there?",
                source="hn", score=150, comments=40,
            ),
        ]
        result = detector.diagnose(qualifying, domain="business")
        assert len(result.accepted) >= 1
        assert result.accepted[0].domain == "business"

    def test_accepted_matches_detect_output(self, detector, demand_signals):
        """diagnose().accepted and detect() must agree — same clustering,
        same evaluation rules, just diagnose() also keeps the rejects."""
        detected = detector.detect(demand_signals, domain="business")
        diagnosed = detector.diagnose(demand_signals, domain="business").accepted
        assert len(detected) == len(diagnosed)
        assert [o.title for o in detected] == [o.title for o in diagnosed]
        assert [round(o.composite_score, 2) for o in detected] == \
               [round(o.composite_score, 2) for o in diagnosed]


class TestBusinessSignalGate:
    """
    Regression coverage for the core false-positive fix: a cluster with
    zero demand/complaint/willingness-to-pay evidence must never become
    an opportunity, regardless of how well-corroborated or high-engagement
    it is — this is what "reduce false positives" actually requires, not
    just narrative-layer filtering.
    """

    def test_well_corroborated_pure_news_is_rejected(self, detector, make_signal):
        """The exact failure mode this gate exists to prevent: a
        well-discussed announcement, cross-source, high engagement — none
        of which implies anyone wants or needs anything."""
        news_signals = [
            make_signal(title="OpenAI announced a major new feature today", score=500, comments=200)
            for _ in range(3)
        ] + [
            make_signal(title="OpenAI announced a major new feature today", score=400, comments=150, source="reddit")
            for _ in range(3)
        ]
        result = detector.diagnose(news_signals)
        assert result.accepted == [], "pure news must never be accepted as an opportunity"
        gated = [r for r in result.rejected if r.reason == "no_business_signal"]
        assert len(gated) > 0

    def test_detect_also_rejects_pure_news_not_just_diagnose(self, detector, make_signal):
        """detect()/detect_and_persist() must be gated identically to
        diagnose() — this is the actual persistence path."""
        news_signals = [
            make_signal(title="OpenAI announced a major new feature today", score=500, comments=200)
            for _ in range(3)
        ] + [
            make_signal(title="OpenAI announced a major new feature today", score=400, comments=150, source="reddit")
            for _ in range(3)
        ]
        result = detector.detect(news_signals)
        assert result == []

    def test_demand_language_alone_passes_the_gate(self, detector, make_signal):
        signals = [make_signal(title="Looking for a tool like this", score=10, comments=2) for _ in range(3)]
        assert detector._has_business_signal(signals) is True

    def test_complaint_language_alone_passes_the_gate(self, detector, make_signal):
        signals = [make_signal(title="This is broken and terrible", score=10, comments=2) for _ in range(3)]
        assert detector._has_business_signal(signals) is True

    def test_pay_language_alone_passes_the_gate(self, detector, make_signal):
        signals = [make_signal(title="I would pay for a fix", score=10, comments=2) for _ in range(3)]
        assert detector._has_business_signal(signals) is True

    def test_pure_announcement_fails_the_gate(self, detector, make_signal):
        signals = [make_signal(title="Company announced a new product launch", score=10, comments=2) for _ in range(3)]
        assert detector._has_business_signal(signals) is False

    def test_gate_checked_before_scoring_for_efficiency_and_correctness(self, detector, make_signal):
        """A gated cluster should carry no scores at all in diagnose() output
        — it was never scored, not scored-and-then-discarded."""
        news_signals = [
            make_signal(title="Company announced a new product launch", score=10, comments=2)
            for _ in range(3)
        ] + [
            make_signal(title="Company announced a new product launch", score=8, comments=1, source="reddit")
            for _ in range(3)
        ]
        result = detector.diagnose(news_signals)
        gated = [r for r in result.rejected if r.reason == "no_business_signal"]
        assert gated
        assert gated[0].scores is None


class TestRejectionReasons:
    def test_too_small_cluster_is_rejected_with_reason(self, detector, make_signal):
        single_signal = [make_signal(title="A totally unique one-off topic")]
        result = detector.diagnose(single_signal)
        assert result.accepted == []
        assert len(result.rejected) == 1
        assert result.rejected[0].reason == "too_small"
        assert "too_small" not in result.rejected[0].summary  # summary is prose, not the code
        assert result.rejected[0].scores is None

    def test_single_source_small_cluster_is_rejected(self, detector, make_signal):
        signals = [
            make_signal(title="Repeated single source topic discussion", source="hn")
            for _ in range(3)
        ]
        result = detector.diagnose(signals)
        assert result.accepted == []
        assert any(r.reason == "single_source" for r in result.rejected)

    def test_below_threshold_cluster_carries_scores(self, detector, make_signal):
        weak_signals = [
            make_signal(title="Looking for a minor product update tool", score=1, comments=0)
            for _ in range(3)
        ] + [
            make_signal(title="Looking for a minor product update tool", score=1, comments=0, source="reddit")
            for _ in range(3)
        ]
        result = detector.diagnose(weak_signals)
        below = [r for r in result.rejected if r.reason == "below_threshold"]
        assert below, "expected at least one below-threshold rejection"
        assert below[0].scores is not None
        assert below[0].scores.composite() < 5.0

    def test_rejected_clusters_are_rejected_cluster_instances(self, detector, make_signal):
        single = [make_signal()]
        result = detector.diagnose(single)
        assert all(isinstance(r, RejectedCluster) for r in result.rejected)


class TestDiagnoseDoesNotAffectDetect:
    def test_detect_unaffected_by_diagnose_being_called_first(self, detector, make_signal):
        """Calling diagnose() must not mutate detector state in a way that
        changes a subsequent detect() call."""
        qualifying = [
            make_signal(
                title="Looking for automated compliance tracking software for business teams",
                source="hn", score=200, comments=80,
            ),
            make_signal(
                title="I would pay for automated compliance tracking software for business teams",
                source="reddit", score=180, comments=60,
            ),
            make_signal(
                title="Any automated compliance tracking software for business teams out there?",
                source="hn", score=150, comments=40,
            ),
        ]
        detector.diagnose(qualifying)
        result = detector.detect(qualifying)
        assert len(result) >= 1

    def test_detect_and_persist_signature_unchanged(self, detector):
        import inspect
        sig = inspect.signature(detector.detect_and_persist)
        assert list(sig.parameters.keys()) == ["signals", "domain"]
