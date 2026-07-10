"""
tests/test_extractor.py — Test suite for EntityExtractor

These tests verify that entity extraction is:
  1. Correct      — it finds what's there
  2. Precise      — it doesn't hallucinate what isn't there
  3. Idempotent   — running twice on the same signal gives the same result
  4. Safe         — empty/garbage input doesn't crash

Run with:
    cd backend && pytest tests/test_extractor.py -v
"""

import pytest
from knowledge_graph.extractor import EntityExtractor
from knowledge_graph.schema import ENTITY_TYPES


@pytest.fixture
def extractor():
    return EntityExtractor()


# ── Basic extraction ──────────────────────────────────────────────────────

class TestBasicExtraction:
    def test_extracts_technology_from_title(self, extractor, make_signal):
        sig    = make_signal(title="How to use Python for SaaS automation workflows")
        result = extractor.extract(sig)
        names  = [e.name for e in result.entities]
        assert any("Python" in n for n in names), f"Expected Python in {names}"

    def test_extracts_market_entity(self, extractor, make_signal):
        sig    = make_signal(title="Best compliance tools for B2B enterprise teams")
        result = extractor.extract(sig)
        types  = [e.type for e in result.entities]
        assert "market" in types, f"Expected market entity, got types: {types}"

    def test_extracts_regulation(self, extractor, make_signal):
        sig    = make_signal(title="EU AI Act compliance guide for small businesses")
        result = extractor.extract(sig)
        types  = [e.type for e in result.entities]
        assert "regulation" in types, f"Expected regulation entity, got: {types}"

    def test_extracts_problem_entity(self, extractor, make_signal):
        sig    = make_signal(title="How to fix compliance and documentation problems")
        result = extractor.extract(sig)
        types  = [e.type for e in result.entities]
        assert "problem" in types, f"Expected problem entity, got: {types}"

    def test_content_field_is_also_searched(self, extractor, make_signal):
        # Title has no keywords; content contains AI
        sig    = make_signal(
            title="General question",
            content="We are using an LLM to power our automation pipeline",
        )
        result = extractor.extract(sig)
        names  = [e.name for e in result.entities]
        # LLM should be found in content
        assert any("LLM" in n or "automation" in n.lower() for n in names), \
            f"Expected content keywords in: {names}"


# ── Empty and trivial input ───────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_title_returns_empty_result(self, extractor, make_signal):
        sig    = make_signal(title="", content="")
        result = extractor.extract(sig)
        assert result.entities == []
        assert result.relationships == []

    def test_no_keywords_match_returns_empty(self, extractor, make_signal):
        sig    = make_signal(title="The quick brown fox jumps over the lazy dog")
        result = extractor.extract(sig)
        # None of these words are in our entity keyword lists
        assert result.entities == []

    def test_extract_does_not_crash_on_long_content(self, extractor, make_signal):
        long_content = "Python SaaS automation " * 500
        sig    = make_signal(content=long_content)
        result = extractor.extract(sig)
        # Should not raise; entities may or may not be found
        assert isinstance(result.entities, list)


# ── Deduplication ─────────────────────────────────────────────────────────

class TestDeduplication:
    def test_same_keyword_repeated_produces_one_entity(self, extractor, make_signal):
        sig    = make_signal(title="Python Python Python Python development")
        result = extractor.extract(sig)
        python_entities = [e for e in result.entities if "Python" in e.name]
        assert len(python_entities) <= 1, (
            f"'Python' appeared {len(python_entities)} times — expected at most 1"
        )

    def test_case_insensitive_deduplication(self, extractor, make_signal):
        sig    = make_signal(title="python PYTHON Python development")
        result = extractor.extract(sig)
        python_entities = [e for e in result.entities
                          if e.name.lower() == "python"]
        assert len(python_entities) <= 1


# ── Relationship building ─────────────────────────────────────────────────

class TestRelationshipBuilding:
    def test_two_entities_produce_at_least_one_relationship(
        self, extractor, make_signal
    ):
        sig    = make_signal(title="EU AI Act compliance for small business automation")
        result = extractor.extract(sig)
        if len(result.entities) >= 2:
            assert len(result.relationships) >= 1, (
                "Two entities should produce at least one relationship"
            )

    def test_no_self_relationships(self, extractor, make_signal):
        sig    = make_signal(title="Python SaaS B2B enterprise LLM automation compliance")
        result = extractor.extract(sig)
        for rel in result.relationships:
            assert rel.from_id != rel.to_id, (
                f"Self-relationship detected: {rel.from_id} → {rel.to_id}"
            )

    def test_relationship_types_are_valid(self, extractor, make_signal):
        from knowledge_graph.schema import RELATIONSHIP_TYPES
        sig    = make_signal(title="EU AI Act affects small business SaaS compliance")
        result = extractor.extract(sig)
        valid  = set(RELATIONSHIP_TYPES.keys())
        for rel in result.relationships:
            assert rel.type in valid, (
                f"Relationship type '{rel.type}' is not in RELATIONSHIP_TYPES"
            )

    def test_regulation_market_pair_infers_affects(self, extractor, make_signal):
        sig    = make_signal(title="GDPR compliance requirements for small business")
        result = extractor.extract(sig)
        rel_types = [r.type for r in result.relationships]
        # If we found both a regulation and a market, the relationship should be "affects"
        types_found = {e.type for e in result.entities}
        if "regulation" in types_found and "market" in types_found:
            assert "affects" in rel_types, (
                f"Expected 'affects' between regulation and market, got: {rel_types}"
            )


# ── Idempotency ───────────────────────────────────────────────────────────

class TestIdempotency:
    def test_same_signal_produces_same_entity_count(self, extractor, make_signal):
        sig     = make_signal(title="Python SaaS automation for SMB compliance")
        result1 = extractor.extract(sig)
        result2 = extractor.extract(sig)
        assert len(result1.entities) == len(result2.entities)

    def test_same_signal_produces_same_entity_names(self, extractor, make_signal):
        sig     = make_signal(title="EU AI Act LLM compliance for B2B enterprise")
        result1 = extractor.extract(sig)
        result2 = extractor.extract(sig)
        names1  = sorted(e.name for e in result1.entities)
        names2  = sorted(e.name for e in result2.entities)
        assert names1 == names2


# ── Schema consistency ────────────────────────────────────────────────────

class TestSchemaConsistency:
    def test_all_extracted_entity_types_are_valid(self, extractor, make_signal):
        valid_types = set(ENTITY_TYPES.keys())
        sig         = make_signal(
            title="Python SaaS B2B compliance GDPR automation LLM enterprise"
        )
        result = extractor.extract(sig)
        for entity in result.entities:
            assert entity.type in valid_types, (
                f"Entity type '{entity.type}' is not defined in ENTITY_TYPES"
            )

    def test_batch_extract_length_matches_input(self, extractor, make_signal):
        signals = [make_signal() for _ in range(5)]
        results = extractor.extract_batch(signals)
        assert len(results) == len(signals)
