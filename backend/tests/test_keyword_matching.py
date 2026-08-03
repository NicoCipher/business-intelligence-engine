"""
tests/test_keyword_matching.py — Direct unit tests for
opportunity_engine/keyword_matching.py, the shared utility consolidating
the plain-substring keyword-scan pattern previously duplicated across
scorer.py and explainer/watch_list.py.

These are intentionally simple/isolated (no scorer or extractor
involved) — the exhaustive behavioral coverage that these two functions
don't change scorer/watch-list output lives in test_scorer.py and
test_explainer.py, which passed unchanged before and after this
consolidation. This file protects count_keyword_hits()/any_keyword_hit()
themselves, in isolation, against future regression.

Run with:
    cd backend && pytest tests/test_keyword_matching.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from opportunity_engine.keyword_matching import count_keyword_hits, any_keyword_hit


class TestCountKeywordHits:
    def test_counts_every_matching_keyword(self):
        assert count_keyword_hits("i would pay for this and want to buy it", ["pay", "buy"]) == 2

    def test_counts_zero_when_nothing_matches(self):
        assert count_keyword_hits("just a random sentence", ["pay", "buy"]) == 0

    def test_empty_keyword_list_is_zero(self):
        assert count_keyword_hits("anything at all", []) == 0

    def test_empty_blob_is_zero(self):
        assert count_keyword_hits("", ["pay", "buy"]) == 0

    def test_plain_substring_match_no_word_boundary(self):
        """Matches the exact pre-consolidation behavior: plain 'in'
        check, no word-boundary awareness -- "pay" matches inside
        "payroll" too, same as both original call sites did."""
        assert count_keyword_hits("payroll software", ["pay"]) == 1

    def test_each_keyword_counted_once_even_if_it_could_match_multiple_times(self):
        """sum(1 for kw in keywords if kw in blob) counts matching
        KEYWORDS, not occurrences within the blob -- "pay" appearing
        three times in the blob still only contributes 1 to the count."""
        assert count_keyword_hits("pay pay pay", ["pay"]) == 1


class TestAnyKeywordHit:
    def test_true_when_any_keyword_present(self):
        assert any_keyword_hit("i want to buy this", ["pay", "buy"]) is True

    def test_false_when_no_keyword_present(self):
        assert any_keyword_hit("just a random sentence", ["pay", "buy"]) is False

    def test_empty_keyword_list_is_false(self):
        assert any_keyword_hit("anything at all", []) is False

    def test_empty_blob_is_false(self):
        assert any_keyword_hit("", ["pay", "buy"]) is False

    def test_short_circuits_do_not_change_result_correctness(self):
        assert any_keyword_hit("buy this now", ["zzz_no_match", "buy"]) is True
