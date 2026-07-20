"""
tests/test_insights.py — Tests for knowledge_graph/insights.py

Covers explain_pair()'s narrative generation: type-pair phrasing,
strength language scaling with weight, and the generic fallback for
type combinations with no dedicated template.

Run with:
    cd backend && pytest tests/test_insights.py -v
"""

from knowledge_graph.insights import explain_pair


def _pair(a_name, a_type, b_name, b_type, weight=1.0):
    return {
        "from": {"id": "e1", "name": a_name, "type": a_type},
        "to":   {"id": "e2", "name": b_name, "type": b_type},
        "weight": weight,
    }


class TestNoRawWeightDump:
    def test_output_is_a_sentence_not_a_weight_dump(self):
        """The whole point of this module: never emit 'X <-> Y weight N' as the
        primary output — always a narrative sentence built from it."""
        pair = _pair("Claude", "technology", "Rust", "technology", weight=1.0)
        sentence = explain_pair(pair)
        assert "<->" not in sentence
        assert "↔" not in sentence
        assert len(sentence.split()) > 8   # a real sentence, not a label

    def test_entity_names_appear_in_output(self):
        pair = _pair("Claude", "technology", "Rust", "technology", weight=3.0)
        sentence = explain_pair(pair)
        assert "Claude" in sentence
        assert "Rust" in sentence


class TestTypePairTemplates:
    def test_technology_technology_mentions_tooling_relationship(self):
        pair = _pair("Claude", "technology", "Rust", "technology", weight=3.0)
        sentence = explain_pair(pair).lower()
        assert "tool" in sentence or "platform" in sentence

    def test_technology_problem_suggests_solving(self):
        pair = _pair("AI transcription", "technology", "session note-taking", "problem", weight=2.0)
        sentence = explain_pair(pair).lower()
        assert "address" in sentence or "solv" in sentence

    def test_market_problem_suggests_pain_point(self):
        pair = _pair("solo consultants", "market", "compliance overhead", "problem", weight=4.0)
        sentence = explain_pair(pair).lower()
        assert "pain point" in sentence

    def test_reversed_type_order_still_matches_template(self):
        """(problem, market) should read the same as (market, problem) —
        explain_pair must try both orders before falling back to generic."""
        forward = _pair("solo consultants", "market", "compliance overhead", "problem", weight=4.0)
        reversed_pair = _pair("compliance overhead", "problem", "solo consultants", "market", weight=4.0)
        forward_sentence = explain_pair(forward).lower()
        reversed_sentence = explain_pair(reversed_pair).lower()
        assert "pain point" in forward_sentence
        assert "pain point" in reversed_sentence

    def test_unmapped_type_pair_falls_back_to_generic_template(self):
        pair = _pair("Some Company", "company", "Some Product", "product", weight=2.0)
        sentence = explain_pair(pair)
        assert "Some Company" in sentence and "Some Product" in sentence
        assert "co-occurrence weight" in sentence


class TestStrengthLanguageScalesWithWeight:
    def test_high_weight_uses_frequently(self):
        pair = _pair("Claude", "technology", "Rust", "technology", weight=6.0)
        assert "frequently" in explain_pair(pair)

    def test_medium_weight_uses_repeatedly(self):
        pair = _pair("Claude", "technology", "Rust", "technology", weight=3.0)
        assert "repeatedly" in explain_pair(pair)

    def test_low_weight_uses_hedged_language(self):
        pair = _pair("Claude", "technology", "Rust", "technology", weight=1.0)
        assert "at least once" in explain_pair(pair)

    def test_weight_affects_wording_not_just_number(self):
        low = explain_pair(_pair("Claude", "technology", "Rust", "technology", weight=1.0))
        high = explain_pair(_pair("Claude", "technology", "Rust", "technology", weight=8.0))
        assert low != high


class TestDeterminism:
    def test_same_pair_produces_same_sentence(self):
        pair = _pair("Claude", "technology", "Rust", "technology", weight=3.0)
        assert explain_pair(pair) == explain_pair(pair)
