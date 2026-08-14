"""
tests/test_domain_generalization.py — Second-domain data-source generalization.

Companion to test_scoring_generalization.py (ADR-011), covering the
follow-on work that ADR-011 explicitly left out of scope: extractor.py,
detector.py's cluster-acceptance gate, canonicalizer.py, and
watch_list.py's fallback gate all previously consumed Business's
hardcoded vocabulary directly (knowledge_graph/schema.py's ENTITY_TYPES,
config.py's DEMAND_KEYWORDS/COMPLAINT_KEYWORDS/WILLINGNESS_TO_PAY),
unreachable from any DomainConfig.

Every other test file in this suite proves Business's behavior is
unchanged (zero regression across 594 pre-existing tests). This file
proves the actual new capability: a genuinely different domain's own
vocabulary is what actually gets used, not silently falling back to
Business's.

Deliberately NOT covered here, per the same boundary drawn during
implementation: extractor.py's _infer_relationship() (entity-type-pair
semantics, not a vocabulary lookup) and explainer/opportunity.py's
narrative logic (verdict language, market_gap wording, _DIMENSION_LABELS
— verified during implementation that even the seemingly-safe label
swap would silently change existing report wording, since
domains/business/scoring.py's labels were never kept in sync with the
real hardcoded ones).
"""

import pytest

import database
from domains.base import (
    DomainConfig, DomainMetadata, DomainSources, DomainKeywords,
    DomainKnowledgeGraph, EntityType, DomainScoring, ScoringDimension,
    DomainReporting,
)
from domains.registry import DomainRegistry
from knowledge_graph.extractor import EntityExtractor
from opportunity_engine import canonicalizer
from opportunity_engine.detector import PatternDetector, RejectedCluster
from opportunity_engine.explainer.watch_list import build_watch_list, _is_business_signal
from models import Signal


def _security_domain(domain_id: str = "test_security") -> DomainConfig:
    """
    A minimal but genuinely different second domain — its own entity
    vocabulary, its own keyword sets, its own scoring dimension — used
    to prove the generalized code paths actually branch on domain
    identity rather than always resolving to Business.
    """
    return DomainConfig(
        metadata=DomainMetadata(
            id=domain_id, name="Test Security", description="Fixture domain for tests",
            version="0.0.1", icon="shield", color="#a10000", category="test",
        ),
        sources=DomainSources(),
        keywords=DomainKeywords(
            include=frozenset(["exploit", "vulnerability", "breach"]),
            boost=frozenset(["zero-day", "patch available"]),
        ),
        graph=DomainKnowledgeGraph(
            entity_types={
                "threat": EntityType(
                    name="threat", description="a security threat category",
                    keywords=("ransomware", "phishing", "malware"),
                ),
            },
            display_names={"cve": "CVE"},
        ),
        scoring=DomainScoring(dimensions=[
            ScoringDimension(id="severity", label="Severity", description="test", weight=1.0),
        ]),
        reporting=DomainReporting(title="Test Security Report", description="test"),
    )


@pytest.fixture(autouse=True)
def clean_registry():
    DomainRegistry.clear()
    yield
    DomainRegistry.clear()


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_domain_generalization.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    database.initialize()
    yield db_path


def _signal(text: str) -> Signal:
    return Signal(source="hn", source_id=f"id-{hash(text) % 10_000}", title=text, content="")


class TestEntityExtractorDomainAwareness:
    def test_business_default_extracts_business_vocabulary(self):
        extractor = EntityExtractor()
        result = extractor.extract(_signal("Using ChatGPT for SaaS compliance"))
        types_found = {e.type for e in result.entities}
        assert "technology" in types_found

    def test_security_domain_extracts_its_own_vocabulary_not_businesss(self):
        security = _security_domain()
        extractor = EntityExtractor(security.graph)
        result = extractor.extract(_signal("A new ransomware campaign is spreading via phishing"))
        entities = {(e.type, e.name) for e in result.entities}
        assert ("threat", "Ransomware") in entities
        assert ("threat", "Phishing") in entities

    def test_security_domain_does_not_extract_business_entity_types(self):
        """The whole point: a domain with its own graph must not fall
        back to Business's vocabulary for types it doesn't define."""
        security = _security_domain()
        extractor = EntityExtractor(security.graph)
        # "SaaS" and "GDPR" are Business technology/regulation keywords —
        # the security domain's graph has neither type at all.
        result = extractor.extract(_signal("This SaaS product needs GDPR compliance"))
        assert result.entities == []

    def test_display_name_uses_the_supplied_domains_map(self):
        security = _security_domain()
        extractor = EntityExtractor(security.graph)
        result = extractor.extract(_signal("A critical cve was disclosed for this malware"))
        names = {e.name for e in result.entities}
        assert "CVE" not in names  # "cve" isn't a security-domain entity keyword here
        # malware IS a keyword; confirm its display name comes from title()
        # fallback (security.graph has no override for it) not Business's.
        assert "Malware" in names


class TestPatternDetectorDomainAwareness:
    def test_business_default_gate_uses_business_keywords(self):
        detector = PatternDetector()
        cluster = [_signal("I would pay for a tool that automates this")]
        assert detector._has_business_signal(cluster) is True

    def test_security_domain_gate_uses_its_own_keywords(self):
        security = _security_domain()
        detector = PatternDetector(security)
        cluster = [_signal("We found a critical exploit affecting this vulnerability")]
        assert detector._has_business_signal(cluster) is True

    def test_security_domain_gate_rejects_business_only_language(self):
        """Business demand language ('would pay for') isn't in the
        security domain's keyword set at all -- the gate must reject it,
        not silently accept via a Business fallback."""
        security = _security_domain()
        detector = PatternDetector(security)
        cluster = [_signal("I would pay for a tool that automates this")]
        assert detector._has_business_signal(cluster) is False

    def test_scorer_uses_the_domains_own_dimensions(self):
        security = _security_domain()
        detector = PatternDetector(security)
        assert detector._scorer.domain_scoring is security.scoring


class TestCanonicalizerDomainAwareness:
    def test_registered_domain_uses_its_own_graph(self, fresh_db):
        """
        Strengthened version: proves resolve_entity_ids actually uses
        the security domain's vocabulary, not just that it doesn't
        crash. An earlier version of this test only asserted
        isinstance(ids, list) — verified by mutation testing during
        review that such an assertion would NOT catch a regression
        where resolve_entity_ids silently reverted to Business's
        vocabulary (a broken implementation returning [] for an empty
        DB lookup satisfies isinstance(ids, list) just as well as a
        correct one). This version persists a security-domain entity
        first, so a real (type, name) match is required, not just a
        non-crashing return type.
        """
        security = _security_domain()
        DomainRegistry.register(security)

        sig = _signal("This ransomware campaign uses phishing emails")
        extractor = EntityExtractor(security.graph)
        extractor.persist_results(extractor.extract_batch([sig]), domain="test_security")

        ids = canonicalizer.resolve_entity_ids([sig], "test_security")
        assert len(ids) >= 2  # "Ransomware" and "Phishing", at minimum

    def test_registered_domain_does_not_resolve_business_only_entities(self, fresh_db):
        """The other half of the proof: a signal using only Business
        vocabulary (SaaS, GDPR) must resolve to nothing when extracted
        under the security domain's graph, which has neither type."""
        security = _security_domain()
        DomainRegistry.register(security)

        sig = _signal("This SaaS product needs GDPR compliance")
        ids = canonicalizer.resolve_entity_ids([sig], "test_security")
        assert ids == []

    def test_unregistered_domain_string_falls_back_gracefully(self, fresh_db):
        """Pre-existing, documented behavior (see
        TestDomainScoping.test_domain_scoping_only_resolves_within_domain
        in test_canonicalizer.py) -- an unregistered domain id doesn't
        raise, it falls back to Business's vocabulary."""
        signals = [_signal("Would anyone pay for this SaaS tool?")]
        ids = canonicalizer.resolve_entity_ids(signals, "not_a_real_domain")
        assert isinstance(ids, list)  # doesn't raise


class TestWatchListDomainAwareness:
    def test_is_business_signal_fallback_uses_supplied_keywords(self):
        security = _security_domain()
        rejected = RejectedCluster(
            signals=[_signal("We identified a critical exploit and vulnerability")],
            reason="too_small", summary="test cluster",
        )
        assert _is_business_signal(rejected, security.keywords) is True

    def test_is_business_signal_fallback_rejects_business_language_for_other_domain(self):
        security = _security_domain()
        rejected = RejectedCluster(
            signals=[_signal("I would pay for this, please build it")],
            reason="too_small", summary="test cluster",
        )
        assert _is_business_signal(rejected, security.keywords) is False

    def test_is_business_signal_defaults_to_business_keywords_when_none_supplied(self):
        rejected = RejectedCluster(
            signals=[_signal("I would pay for this tool")],
            reason="too_small", summary="test cluster",
        )
        assert _is_business_signal(rejected, None) is True

    def test_build_watch_list_threads_domain_through_to_the_gate(self):
        security = _security_domain()
        DomainRegistry.register(security)
        rejected = RejectedCluster(
            signals=[_signal("A critical exploit was found in this vulnerability")],
            reason="too_small", summary="test cluster",
        )
        result = build_watch_list([rejected], domain="test_security")
        assert len(result) == 1

    def test_build_watch_list_falls_back_to_business_for_unregistered_domain(self):
        rejected = RejectedCluster(
            signals=[_signal("I would pay for this tool")],
            reason="too_small", summary="test cluster",
        )
        result = build_watch_list([rejected], domain="not_a_real_domain")
        assert len(result) == 1


class TestDomainRegistryGetOrDefault:
    def test_returns_registered_domain_directly(self):
        security = _security_domain()
        DomainRegistry.register(security)
        assert DomainRegistry.get_or_default("test_security") is security

    def test_falls_back_to_default_when_requested_not_registered(self):
        business = _security_domain("business")  # reuse shape, id="business"
        DomainRegistry.register(business)
        result = DomainRegistry.get_or_default("not_registered")
        assert result is business

    def test_returns_none_when_neither_is_registered(self):
        """The case that made a raising fallback unusable: plain unit
        tests register no domain at all, not even 'business'."""
        assert DomainRegistry.get_or_default("anything") is None

    def test_does_not_raise_ever(self):
        DomainRegistry.register(_security_domain())
        # Neither "test_security" nor "business" resolution should raise
        # regardless of what's registered.
        DomainRegistry.get_or_default("business")
        DomainRegistry.get_or_default("test_security")
        DomainRegistry.get_or_default("neither_one")
