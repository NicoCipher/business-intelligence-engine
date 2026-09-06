"""
tests/test_detector_greenhouse_containment.py — Regression coverage for the
Greenhouse origination containment (temporary, see detector.py's
_ORIGINATION_EXCLUDED_SOURCES note). Proves only the contract: Greenhouse
text cannot originate an Opportunity by itself, but can still corroborate
one that other evidence qualifies. Does not re-test clustering, scoring,
or canonicalization, which this change doesn't touch.

Run with:
    cd backend && pytest tests/test_detector_greenhouse_containment.py -v
"""

import pytest

from opportunity_engine.detector import PatternDetector


# Near-duplicate Greenhouse job-posting template reused across five
# companies -- dense in the exact vocabulary _has_business_signal() treats
# as a demand proxy ("looking for" a hire, "enterprise", "b2b", salary
# figures), and pre-fix reliably originated an Opportunity on that alone.
_GREENHOUSE_TEMPLATE = (
    "We are hiring an Enterprise Solutions Engineer to support our B2B SaaS platform. "
    "You will help enterprise clients integrate our commercial product, working closely "
    "with our sales and customer success teams to solve integration problems for business "
    "customers. Salary range ${lo} - {hi} per year, plus equity. We are looking for someone "
    "passionate about helping customers succeed with our enterprise software."
)
_SALARY_RANGES = [(120, 160), (110, 150), (130, 170), (100, 140), (125, 165)]

# Shares clustering vocabulary with the template above, but carries none of
# its qualifying keywords -- used to test containment against a non-empty
# but still non-qualifying non-Greenhouse signal.
_NO_EVIDENCE_CONTENT = (
    "Acme Corp clients integrate commercial product features while customer success "
    "teams solve integration problems for business customers who help improving "
    "software solutions engineer support workflows."
)

# Same shared vocabulary, but a genuine demand signal ("any alternative",
# "can't find").
_GENUINE_DEMAND_CONTENT = (
    "Any alternative for clients integrate commercial product features? Our customer "
    "success teams solve integration problems for business customers manually and we "
    "can't find a solutions engineer support tool that helps."
)


@pytest.fixture
def detector():
    return PatternDetector()


@pytest.fixture
def greenhouse_job_cluster(make_signal):
    """Five near-duplicate Greenhouse job postings for the same role,
    across five companies -- single-source cluster of 5."""
    return [
        make_signal(
            title="Enterprise Solutions Engineer",
            content=_GREENHOUSE_TEMPLATE.format(lo=lo, hi=hi),
            source="greenhouse_jobs",
        )
        for lo, hi in _SALARY_RANGES
    ]


class TestGreenhouseCannotOriginateAlone:
    """A: five Greenhouse job postings alone must not originate an
    Opportunity, despite containing the exact language the old,
    unscoped gate used to accept."""

    def test_detect_rejects(self, detector, greenhouse_job_cluster):
        assert detector.detect(greenhouse_job_cluster, domain="business") == []

    def test_diagnose_reason_is_originating_specific(self, detector, greenhouse_job_cluster):
        result = detector.diagnose(greenhouse_job_cluster, domain="business")
        assert result.accepted == []
        assert result.rejected[0].reason == "no_originating_business_signal"


class TestGreenhouseWithNonQualifyingNonGreenhouseEvidence:
    """B: adding a non-Greenhouse signal that itself fails the existing
    business-signal gate must not let the cluster originate."""

    def test_rejected_with_originating_reason(self, detector, greenhouse_job_cluster, make_signal):
        no_evidence_signal = make_signal(
            title="Acme Corp clients integrate commercial product features",
            content=_NO_EVIDENCE_CONTENT,
            source="hn",
        )
        cluster = greenhouse_job_cluster + [no_evidence_signal]
        assert detector._has_business_signal([no_evidence_signal]) is False  # test validity

        result = detector.diagnose(cluster, domain="business")
        assert result.accepted == []
        gated = [r for r in result.rejected if len(r.signals) == len(cluster)]
        assert gated and gated[0].reason == "no_originating_business_signal"
        assert detector.detect(cluster, domain="business") == []


class TestGreenhouseCanCorroborateGenuineEvidence:
    """C: a genuine non-Greenhouse demand signal still originates an
    Opportunity, and Greenhouse signals remain part of it."""

    def test_accepted_with_full_cluster_retained(self, detector, greenhouse_job_cluster, make_signal):
        genuine_demand_signal = make_signal(
            title="Looking for clients integrate commercial product solutions engineer support",
            content=_GENUINE_DEMAND_CONTENT,
            source="hn",
            score=120,
            comments=40,
        )
        cluster = greenhouse_job_cluster + [genuine_demand_signal]
        assert detector._has_business_signal([genuine_demand_signal]) is True  # test validity

        result = detector.diagnose(cluster, domain="business")
        assert len(result.accepted) == 1
        assert len(result.accepted[0].signal_ids) == len(cluster)

        detected = detector.detect(cluster, domain="business")
        assert len(detected) == 1
        assert len(detected[0].signal_ids) == len(cluster)


class TestNonGreenhouseBehaviorUnchanged:
    """D: clusters with no Greenhouse signal behave exactly as before."""

    def test_ordinary_no_business_cluster_unchanged(self, detector, make_signal):
        news_signals = [
            make_signal(title="OpenAI announced a major new feature today", score=500, comments=200)
            for _ in range(3)
        ] + [
            make_signal(title="OpenAI announced a major new feature today", score=400, comments=150, source="reddit")
            for _ in range(3)
        ]
        result = detector.diagnose(news_signals)
        assert result.accepted == []
        assert result.rejected[0].reason == "no_business_signal"

    def test_existing_qualifying_cluster_unchanged(self, detector, demand_signals):
        detected = detector.detect(demand_signals, domain="business")
        diagnosed = detector.diagnose(demand_signals, domain="business").accepted
        assert len(detected) == len(diagnosed)
        assert [o.title for o in detected] == [o.title for o in diagnosed]
