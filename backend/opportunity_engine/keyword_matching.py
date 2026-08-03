"""
opportunity_engine/keyword_matching.py — shared plain-substring keyword
scanning, used by scorer.py and explainer/watch_list.py.

Consolidates a pattern that was independently duplicated in both files:
counting or checking how many terms from a keyword list appear in a blob
of lowercased signal text (`sum(1 for kw in KEYWORDS if kw in blob)` /
`any(kw in blob for kw in KEYWORDS)`). Both files used exactly this
plain "substring in string" check, on different keyword lists
(DEMAND_KEYWORDS, WILLINGNESS_TO_PAY, LOW_COMPETITION_SIGNALS,
RISK_KEYWORDS, COMPLAINT_KEYWORDS), for different purposes (scoring
dimensions vs. watch-list filtering) — genuinely the same algorithm,
just applied to different vocabularies.

Deliberately NOT consolidated with knowledge_graph/extractor.py's
keyword matching (`EntityExtractor._matches()`): that method is a
different, more sophisticated algorithm — word-boundary-aware regex for
short keywords (to avoid "ai" matching inside "said" or "maintain"),
falling back to plain substring matching only for longer keywords — and
it's coupled to per-instance compiled regex patterns cached at
EntityExtractor construction time, not a stateless text-in-blob check.
Forcing scorer.py/explainer.py onto that algorithm would change their
scoring/filtering behavior (some keyword lists here may contain short
terms that currently match via plain substring and would stop matching
under word-boundary rules, or vice versa) — a real behavior change,
which this refactor is explicitly not allowed to introduce. Forcing
extractor.py onto the cruder plain-substring algorithm would risk
introducing new false-positive entity extraction. Keeping them separate
is the correct, honest scope: consolidate what's actually identical,
leave what's actually different alone.
"""


def count_keyword_hits(blob: str, keywords) -> int:
    """How many terms from `keywords` appear anywhere in `blob` (plain
    substring match, no word-boundary handling — matches the exact
    behavior both call sites already had before this consolidation)."""
    return sum(1 for kw in keywords if kw in blob)


def any_keyword_hit(blob: str, keywords) -> bool:
    """Whether any term from `keywords` appears anywhere in `blob`."""
    return any(kw in blob for kw in keywords)
