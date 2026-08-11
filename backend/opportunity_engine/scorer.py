"""
opportunity_engine/scorer.py — Transparent opportunity scoring

This is the most important module in Version 1.

Design principles:
  1. Every score is derived from measurable, documented properties of signals.
  2. No black boxes. Someone reading this file should fully understand why
     any given opportunity scored 7.4 vs 6.9.
  3. Scores are deterministic. The same signals produce the same scores every time.
  4. Uncertainty is represented explicitly via the confidence dimension.
     A high-score opportunity with low confidence is clearly different from
     one with high confidence.
  5. We never invent facts. If there's no evidence for a dimension, it scores
     at the documented default (not zero, not ten).

ADR-011 (Domain-Generalized Opportunity Scoring): this class no longer
hardcodes Business's seven dimensions. It iterates whichever dimensions
the active DomainScoring declares (id, weight, compute_fn) and calls
each dimension's compute_fn(signals, blob) -> (score, reason, evidence).
Business's own dimension formulas are unchanged — they moved verbatim to
domains/business/scoring_functions.py and are registered as each
dimension's compute_fn in domains/business/scoring.py. Nothing about
Business's scoring behavior or numeric output changes.

Default domain, and why this file imports domains.business directly:
opportunity_engine/detector.py constructs OpportunityScorer() with zero
arguments and is out of scope for this change (ADR-011). For that call
to keep working, this file's default `domain_scoring` must resolve to a
DomainScoring whose dimensions actually carry compute_fn — i.e. the real
domains.business.scoring.SCORING object, not a value rebuilt from
config.py. This is a deliberate, narrow exception to "no core file
imports a specific domain package" (domains/base.py), scoped to exactly
one default-parameter value, made necessary by detector.py's
unmodifiable zero-arg construction. A future pass that threads domain
context into detector.py's construction could remove this default
entirely.
"""

from typing import Sequence

from models import Signal, OpportunityScores, DimensionExplanation
from domains.base import DomainScoring
from domains.business.scoring import SCORING as _DEFAULT_SCORING


class OpportunityScorer:
    """
    Scores a cluster of signals as a single opportunity.

    A cluster is a group of signals that appear to be about the same
    underlying problem or market gap. The detector (detector.py) creates
    clusters; this class evaluates them.

    Usage:
        scorer = OpportunityScorer()               # Business (default)
        scorer = OpportunityScorer(some_domain.scoring)  # any DomainScoring
        scores = scorer.score(signals)
        print(scores.to_dict())
    """

    def __init__(self, domain_scoring: DomainScoring | None = None):
        self.domain_scoring = domain_scoring or _DEFAULT_SCORING

    def score(self, signals: Sequence[Signal]) -> OpportunityScores:
        """
        Score a cluster. Returns a fully populated OpportunityScores object.

        Args:
            signals: All signals in the cluster. Must be non-empty.

        Returns:
            OpportunityScores with every dimension calculated and documented.
        """
        weights = self.domain_scoring.weights
        thresholds = (self.domain_scoring.thresholds.high, self.domain_scoring.thresholds.medium)

        if not signals:
            return OpportunityScores(weights=weights, thresholds=thresholds)

        signals = list(signals)
        blob = self._text_blob(signals)

        dimensions = {}
        explanations = {}
        for dim in self.domain_scoring.dimensions:
            score, reason, evidence = self._compute_dimension(dim, signals, blob)
            dimensions[dim.id] = score
            explanations[dim.id] = DimensionExplanation(score, reason, evidence)

        return OpportunityScores(
            dimensions=dimensions,
            evidence_count=len(signals),
            explanations=explanations,
            weights=weights,
            thresholds=thresholds,
        )

    def _compute_dimension(self, dim, signals: list[Signal], blob: str) -> tuple[float, str, str]:
        """
        Tier-2 (compute_fn supplied): call it directly — this is the path
        every one of Business's seven dimensions uses today (ADR-011: none
        of them reduce to pure keyword-presence without changing their
        output; see domains/business/scoring_functions.py's docstring).

        Tier-1 (no compute_fn): a generic keyword-presence fallback, for a
        future domain's simple dimensions. Deliberately basic — it is not
        an attempt to replicate any particular domain's tuned formula, and
        no dimension in this codebase currently exercises this path.
        """
        if dim.compute_fn is not None:
            return dim.compute_fn(signals, blob)
        return self._generic_keyword_dimension(dim, blob)

    @staticmethod
    def _generic_keyword_dimension(dim, blob: str) -> tuple[float, str, str]:
        pos_hits = sum(1 for kw in dim.positive_keywords if kw in blob)
        neg_hits = sum(1 for kw in dim.negative_keywords if kw in blob)
        score = round(min(10.0, max(0.0, 5.0 + pos_hits * 0.5 - neg_hits * 0.5)), 2)
        reason = (
            f"Generic Tier-1 scoring: {pos_hits} positive-keyword match(es), "
            f"{neg_hits} negative-keyword match(es), against a neutral "
            f"baseline of 5.0. This dimension has no bespoke compute_fn."
        )
        evidence = f"{pos_hits} positive, {neg_hits} negative keyword match(es)."
        return score, reason, evidence

    # ── Utilities ─────────────────────────────────────────────────────────

    @staticmethod
    def _text_blob(signals: list[Signal]) -> str:
        """
        Concatenate all signal text for keyword matching.
        Lower-cased once here so individual methods don't need to.
        """
        return " ".join(s.full_text for s in signals)
