"""
tests/test_similarity.py — Tests for opportunity_engine/similarity.py

These primitives were extracted from explainer.py (where they powered
week-over-week recurrence matching) so canonicalizer.py can reuse them
without duplicating the logic. Existing explainer.py tests already
exercise these indirectly; this file tests the primitives directly.

Run with:
    cd backend && pytest tests/test_similarity.py -v
"""

from opportunity_engine.similarity import title_tokens, jaccard


class TestTitleTokens:
    def test_extracts_significant_words(self):
        tokens = title_tokens("AI meeting notes for therapists")
        assert "meeting" in tokens
        assert "notes" in tokens
        assert "therapists" in tokens

    def test_removes_stopwords(self):
        tokens = title_tokens("A tool for the meeting notes")
        assert "tool" not in tokens
        assert "meeting" in tokens

    def test_removes_short_words(self):
        tokens = title_tokens("An AI tool")
        assert "ai" not in tokens  # 2 chars, filtered

    def test_case_insensitive(self):
        assert title_tokens("Therapist Notes") == title_tokens("therapist notes")

    def test_punctuation_does_not_merge_words(self):
        tokens = title_tokens("compliance-tracking, automated!")
        assert "compliance" in tokens
        assert "tracking" in tokens
        assert "automated" in tokens

    def test_empty_title_returns_empty_set(self):
        assert title_tokens("") == set()


class TestJaccard:
    def test_identical_sets_score_one(self):
        s = {"a", "b", "c"}
        assert jaccard(s, s) == 1.0

    def test_disjoint_sets_score_zero(self):
        assert jaccard({"a"}, {"b"}) == 0.0

    def test_partial_overlap(self):
        assert jaccard({"a", "b"}, {"b", "c"}) == 1 / 3

    def test_empty_set_scores_zero_not_error(self):
        assert jaccard(set(), {"a"}) == 0.0
        assert jaccard({"a"}, set()) == 0.0
        assert jaccard(set(), set()) == 0.0
