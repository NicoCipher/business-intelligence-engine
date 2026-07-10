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

Scoring model — 7 dimensions, all 0–10:

  Demand (D)              Evidence of active unmet need
  Competition (C)         Inverse of market saturation (10 = no good solution exists)
  Revenue Potential (R)   Evidence people will pay for a solution
  Execution Difficulty(E) Inverted: 10 = anyone can do this with free tools today
  Time to Revenue (T)     Inverted: 10 = could earn within one week
  Risk (K)                Inverted: 10 = very low risk (no regulatory/tech/market risk)
  Confidence (CF)         Quality of evidence (source diversity × signal count × engagement)

Composite = weighted average using config.SCORE_WEIGHTS.

The weights encode a priority judgment: demand and revenue potential matter most
because a technically good opportunity with no market is worthless.

Defaults when evidence is insufficient:
  Most dimensions default to 5.0 (neutral) not 0.
  This prevents the system from penalising unknown factors unfairly.
  Confidence starts at 1.0 and can only rise with evidence.
"""

import math
from typing import Sequence

from models import Signal, OpportunityScores
from config import (
    DEMAND_KEYWORDS, COMPLAINT_KEYWORDS, WILLINGNESS_TO_PAY,
    LOW_COMPETITION_SIGNALS, RISK_KEYWORDS,
)


class OpportunityScorer:
    """
    Scores a cluster of signals as a single opportunity.

    A cluster is a group of signals that appear to be about the same
    underlying problem or market gap. The detector (detector.py) creates
    clusters; this class evaluates them.

    Usage:
        scorer = OpportunityScorer()
        scores = scorer.score(signals)
        print(scores.to_dict())
    """

    def score(self, signals: Sequence[Signal]) -> OpportunityScores:
        """
        Score a cluster. Returns a fully populated OpportunityScores object.

        Args:
            signals: All signals in the cluster. Must be non-empty.

        Returns:
            OpportunityScores with every dimension calculated and documented.
        """
        if not signals:
            return OpportunityScores()

        signals = list(signals)
        blob = self._text_blob(signals)

        return OpportunityScores(
            demand=               self._demand(signals, blob),
            competition=          self._competition(blob),
            revenue_potential=    self._revenue_potential(signals, blob),
            execution_difficulty= self._execution_difficulty(blob),
            time_to_revenue=      self._time_to_revenue(blob),
            risk=                 self._risk(blob),
            confidence=           self._confidence(signals),
            evidence_count=       len(signals),
        )

    # ── Dimension calculations ────────────────────────────────────────────

    def _demand(self, signals: list[Signal], blob: str) -> float:
        """
        Demand = evidence that people are actively seeking a solution.

        Three components, each worth up to ~3.3 points:
          1. Frequency: how many independent signals mention this topic?
             Logarithmic because the 5th signal is less surprising than the 2nd.
          2. Keywords: how many demand-intent phrases appear in the text?
          3. Engagement: total upvotes + comments (log-scaled).
             High engagement means real humans cared, not just crawlers.
        """
        n = len(signals)

        # 1. Frequency (0–4 points). log₅ scaling: n=1→0.9, 5→2.0, 25→3.1
        freq = min(4.0, math.log(n + 1, 5) * 2.0)

        # 2. Keyword matches (0–3 points)
        hits = sum(1 for kw in DEMAND_KEYWORDS if kw in blob)
        keywords = min(3.0, hits * 0.4)

        # 3. Engagement (0–3 points). log₁₀: 10 pts→0.8, 100→1.5, 1000→2.3
        total_eng = sum(s.engagement for s in signals)
        engagement = min(3.0, math.log10(total_eng + 1) * 1.0)

        return round(min(10.0, freq + keywords + engagement), 2)

    def _competition(self, blob: str) -> float:
        """
        Competition = inverse of market saturation.
        10 means no quality solution exists. 1 means the market is mature/crowded.

        Base score: 5.5 (moderate competition assumed when unknown — we are
        conservative. We should not claim a market gap without evidence of it.)

        Evidence of low competition pushes this up toward 10.
        Evidence of existing solutions (unnamed) leaves it at base.
        """
        base = 5.5
        hits = sum(1 for kw in LOW_COMPETITION_SIGNALS if kw in blob)
        bonus = min(4.5, hits * 1.5)
        return round(min(10.0, base + bonus), 2)

    def _revenue_potential(self, signals: list[Signal], blob: str) -> float:
        """
        Revenue potential = evidence people will pay money for a solution.

        Direct evidence: mentions of pricing, payment, willingness-to-pay.
        B2B context: business-facing solutions typically command higher prices.
        Indirect: high engagement with explicit demand suggests market size.

        Default floor: 2.0 if there are 3+ demand signals (there must be some
        potential or people wouldn't be asking).
        """
        pay_hits = sum(1 for kw in WILLINGNESS_TO_PAY if kw in blob)
        direct = min(4.0, pay_hits * 0.8)

        b2b_terms = ["business", "enterprise", "b2b", "company", "team",
                     "organization", "startup", "saas", "client"]
        b2b_count = sum(
            1 for s in signals
            if any(t in s.full_text for t in b2b_terms)
        )
        b2b_bonus = min(3.0, b2b_count * 0.6)

        floor = 2.0 if len(signals) >= 3 else 1.0
        return round(min(10.0, floor + direct + b2b_bonus), 2)

    def _execution_difficulty(self, blob: str) -> float:
        """
        Execution difficulty (inverted): 10 = anyone can start today.

        Easy markers: service/information businesses, automation of existing
        tools, SaaS on commodity infra, writing/consulting.

        Hard markers: hardware, biotech, regulatory-gated industries,
        novel research requiring specialised expertise.

        Default: 6.0. We lean optimistic but not absurdly so.
        """
        easy_terms = [
            "template", "newsletter", "content", "writing", "consulting",
            "automation", "integration", "no-code", "api wrapper", "saas",
            "notion", "spreadsheet", "service", "freelance", "tool",
        ]
        hard_terms = [
            "hardware", "chip", "biotech", "clinical trial", "fda",
            "patent", "novel research", "phd", "semiconductor",
        ]

        easy = sum(1 for t in easy_terms if t in blob)
        hard = sum(1 for t in hard_terms if t in blob)

        score = 6.0 + (easy * 0.25) - (hard * 0.8)
        return round(min(10.0, max(1.0, score)), 2)

    def _time_to_revenue(self, blob: str) -> float:
        """
        Time to revenue (inverted): 10 = can earn this week.

        Service businesses pay the fastest (freelance, consulting).
        SaaS products take months. Marketplaces and platforms take longer.

        Default: 5.5 (a few weeks, which is realistic for most opportunities
        that reach the scoring stage).
        """
        if any(t in blob for t in ["freelance", "consulting", "service", "agency", "coaching"]):
            return 8.5
        if any(t in blob for t in ["saas", "app", "product", "software", "tool"]):
            return 6.0
        if any(t in blob for t in ["marketplace", "platform", "community", "network"]):
            return 3.5
        return 5.5

    def _risk(self, blob: str) -> float:
        """
        Risk (inverted): 10 = very low risk.

        Risk factors: regulatory mentions, incumbent threats (big tech
        entering the space), hype indicators (could be a fad).

        Default: 7.0 (moderate-low risk). We don't penalise unknown risk.
        Only detected risk evidence reduces this score.
        """
        hits = sum(1 for kw in RISK_KEYWORDS if kw in blob)
        penalty = min(6.0, hits * 1.2)
        return round(max(1.0, 7.0 - penalty), 2)

    def _confidence(self, signals: list[Signal]) -> float:
        """
        Confidence = how much we should trust the other scores.

        Three components:
          1. Source diversity: signals from multiple independent sources
             provide much stronger evidence than many signals from one source.
             A cross-source signal is 3× harder to fake or be coincidental.
          2. Evidence count: more signals → more confident (log-scaled).
          3. Quality: what fraction of signals have meaningful engagement?
             High engagement = real humans expressed an opinion.

        This score should be read as: "how much to trust the above scores."
        Low confidence with high demand doesn't mean ignore it — it means
        investigate manually before committing time.
        """
        n = len(signals)

        # 1. Source diversity (0–4 points). Max bonus at 3+ distinct sources.
        source_count = len(set(s.source for s in signals))
        diversity = min(4.0, source_count * 1.5)

        # 2. Evidence count (0–3.5 points). log₄: 1→0, 4→1.7, 16→3.5
        count_score = min(3.5, math.log(n, 4) * 1.75) if n > 1 else 0.0

        # 3. Quality (0–2.5 points). What fraction have >10 engagement points?
        high_quality = sum(1 for s in signals if s.engagement > 10)
        quality = min(2.5, (high_quality / n) * 2.5) if n > 0 else 0.0

        return round(min(10.0, diversity + count_score + quality), 2)

    # ── Utilities ─────────────────────────────────────────────────────────

    @staticmethod
    def _text_blob(signals: list[Signal]) -> str:
        """
        Concatenate all signal text for keyword matching.
        Lower-cased once here so individual methods don't need to.
        """
        return " ".join(s.full_text for s in signals)
