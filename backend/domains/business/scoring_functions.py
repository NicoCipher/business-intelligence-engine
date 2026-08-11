"""
domains/business/scoring_functions.py

Tier-2 compute_fn implementations (ADR-011) for the Business Intelligence
domain's 7 scoring dimensions.

These are the exact formulas that previously lived as private methods on
opportunity_engine.scorer.OpportunityScorer (`_demand`, `_competition`,
`_revenue_potential`, `_execution_difficulty`, `_time_to_revenue`,
`_risk`, `_confidence`) — moved here verbatim, with `self` dropped, since
none of them referenced instance state. No formula, constant, threshold,
or keyword list has changed; this is a relocation, not a rewrite.

Why these are Tier-2, not Tier-1 (ADR-011 §"What replaces..."): every
one of these combines its keyword-hit count with its own base value,
multiplier, and cap — or, for demand/confidence, with non-keyword
signal-structure math (frequency, engagement, source diversity) — not a
uniform "count hits, scale linearly" shape a generic engine could
reproduce without per-dimension parameters. None qualifies for the
generic Tier-1 fallback (see opportunity_engine/scorer.py) without
changing its output.

Known documentation/implementation discrepancy, left uncorrected here
deliberately (see ADR-011, "preserve all existing Business scoring
behavior"): this domain's ScoringDimension for "demand" documents
positive_keywords as DEMAND_KEYWORDS ∪ COMPLAINT_KEYWORDS, but
compute_demand() below only ever checked DEMAND_KEYWORDS —
COMPLAINT_KEYWORDS has been imported and unused in the scorer since
before this change. Reconciling the two would change every existing
demand score for signals containing complaint language but no
demand-intent language, which is exactly the behavior change this
migration must not introduce. Flagged for a future, separate decision.
"""

from __future__ import annotations

import math

from config import (
    DEMAND_KEYWORDS, WILLINGNESS_TO_PAY,
    LOW_COMPETITION_SIGNALS, RISK_KEYWORDS,
)
from opportunity_engine.keyword_matching import count_keyword_hits


def compute_demand(signals: list, blob: str) -> tuple[float, str, str]:
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
    hits = count_keyword_hits(blob, DEMAND_KEYWORDS)
    keywords = min(3.0, hits * 0.4)

    # 3. Engagement (0–3 points). log₁₀: 10 pts→0.8, 100→1.5, 1000→2.3
    total_eng = sum(s.engagement for s in signals)
    engagement = min(3.0, math.log10(total_eng + 1) * 1.0)

    score = round(min(10.0, freq + keywords + engagement), 2)

    if hits >= 3:
        reason = ("Multiple signals use explicit demand or solution-seeking "
                   "language, and engagement suggests real reader interest.")
    elif hits >= 1:
        reason = ("Some signals use demand-seeking language, but explicit "
                   "requests for a solution are limited.")
    else:
        reason = ("No explicit demand-seeking language was detected; this "
                   "score rests mainly on how often the topic recurred and "
                   "how much engagement it drew, not on stated intent.")
    evidence = (f"{n} signal(s) in cluster, {hits} demand-keyword match(es), "
                f"{total_eng} combined upvotes/comments.")
    return score, reason, evidence


def compute_competition(signals: list, blob: str) -> tuple[float, str, str]:
    """
    Competition = inverse of market saturation.
    10 means no quality solution exists. 1 means the market is mature/crowded.

    Base score: 5.5 (moderate competition assumed when unknown — we are
    conservative. We should not claim a market gap without evidence of it.)

    Evidence of low competition pushes this up toward 10.
    Evidence of existing solutions (unnamed) leaves it at base.
    """
    base = 5.5
    hits = count_keyword_hits(blob, LOW_COMPETITION_SIGNALS)
    bonus = min(4.5, hits * 1.5)
    score = round(min(10.0, base + bonus), 2)

    if hits >= 2:
        reason = ("Multiple signals explicitly describe a market gap or the "
                   "absence of a good existing solution.")
    elif hits == 1:
        reason = ("One signal suggests an underserved market, but this is "
                   "not yet corroborated by other signals.")
    else:
        reason = ("No explicit evidence of a market gap was found; this score "
                   "reflects the conservative default assumption of moderate "
                   "competition, not a confirmed crowded market.")
    evidence = (f"{hits} low-competition phrase match(es) "
                f"(e.g. \"no good alternative\", \"nothing exists\").")
    return score, reason, evidence


def compute_revenue_potential(signals: list, blob: str) -> tuple[float, str, str]:
    """
    Revenue potential = evidence people will pay money for a solution.

    Direct evidence: mentions of pricing, payment, willingness-to-pay.
    B2B context: business-facing solutions typically command higher prices.
    Indirect: high engagement with explicit demand suggests market size.

    Default floor: 2.0 if there are 3+ demand signals (there must be some
    potential or people wouldn't be asking).
    """
    pay_hits = count_keyword_hits(blob, WILLINGNESS_TO_PAY)
    direct = min(4.0, pay_hits * 0.8)

    b2b_terms = ["business", "enterprise", "b2b", "company", "team",
                 "organization", "startup", "saas", "client"]
    b2b_count = sum(
        1 for s in signals
        if any(t in s.full_text for t in b2b_terms)
    )
    b2b_bonus = min(3.0, b2b_count * 0.6)

    floor = 2.0 if len(signals) >= 3 else 1.0
    score = round(min(10.0, floor + direct + b2b_bonus), 2)

    if pay_hits >= 1 and b2b_count >= 1:
        reason = ("Direct willingness-to-pay language is present, and the "
                   "context is business/B2B-facing — typically the strongest "
                   "combination for revenue potential.")
    elif pay_hits >= 1:
        reason = "Direct willingness-to-pay language is present in the signals."
    elif b2b_count >= 1:
        reason = ("No explicit pricing language, but the context is "
                   "business/B2B-facing, which usually supports higher "
                   "willingness to pay than consumer contexts.")
    else:
        reason = ("No pricing or B2B language was found; this score rests on "
                   "the floor granted for a repeated demand pattern, not on "
                   "direct evidence people will pay.")
    evidence = (f"{pay_hits} willingness-to-pay phrase match(es), "
                f"{b2b_count}/{len(signals)} signal(s) with business/B2B context.")
    return score, reason, evidence


def compute_execution_difficulty(signals: list, blob: str) -> tuple[float, str, str]:
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

    raw = 6.0 + (easy * 0.25) - (hard * 0.8)
    score = round(min(10.0, max(1.0, raw)), 2)

    if hard > 0:
        reason = ("Signals reference hardware, biotech, or regulatory-gated "
                   "work — these categories take materially longer to execute.")
    elif easy >= 3:
        reason = ("Signals reference service, content, or no-code/automation "
                   "work — categories that can typically be started with free "
                   "or low-cost tools.")
    else:
        reason = ("No strong easy or hard markers were found; this score "
                   "reflects the default assumption for an unspecified "
                   "software/service opportunity.")
    evidence = f"{easy} easy-execution term match(es), {hard} hard-execution term match(es)."
    return score, reason, evidence


def compute_time_to_revenue(signals: list, blob: str) -> tuple[float, str, str]:
    """
    Time to revenue (inverted): 10 = can earn this week.

    Service businesses pay the fastest (freelance, consulting).
    SaaS products take months. Marketplaces and platforms take longer.

    Default: 5.5 (a few weeks, which is realistic for most opportunities
    that reach the scoring stage).
    """
    service_terms = ["freelance", "consulting", "service", "agency", "coaching"]
    product_terms = ["saas", "app", "product", "software", "tool"]
    platform_terms = ["marketplace", "platform", "community", "network"]

    if any(t in blob for t in service_terms):
        hit = next(t for t in service_terms if t in blob)
        return (8.5,
                "Signals describe a service-style offering (e.g. freelance, "
                "consulting) — these can typically generate revenue almost "
                "immediately, without a build phase.",
                f"Matched service-category term: \"{hit}\".")
    if any(t in blob for t in product_terms):
        hit = next(t for t in product_terms if t in blob)
        return (6.0,
                "Signals describe a software product (e.g. SaaS, app) — these "
                "usually need a build phase before the first sale.",
                f"Matched product-category term: \"{hit}\".")
    if any(t in blob for t in platform_terms):
        hit = next(t for t in platform_terms if t in blob)
        return (3.5,
                "Signals describe a marketplace or platform model — these "
                "typically need to reach critical mass on both sides before "
                "generating revenue, which takes longer.",
                f"Matched platform-category term: \"{hit}\".")
    return (5.5,
            "No service, product, or platform category language was "
            "detected; this score reflects the default assumption of a "
            "few weeks to first revenue.",
            "0 category-term matches.")


def compute_risk(signals: list, blob: str) -> tuple[float, str, str]:
    """
    Risk (inverted): 10 = very low risk.

    Risk factors: regulatory mentions, incumbent threats (big tech
    entering the space), hype indicators (could be a fad).

    Default: 7.0 (moderate-low risk). We don't penalise unknown risk.
    Only detected risk evidence reduces this score.
    """
    hits = count_keyword_hits(blob, RISK_KEYWORDS)
    penalty = min(6.0, hits * 1.2)
    score = round(max(1.0, 7.0 - penalty), 2)

    if hits >= 2:
        reason = ("Multiple risk indicators were found — regulatory exposure, "
                   "incumbent big-tech entrants, or hype/fad language.")
    elif hits == 1:
        reason = "One risk indicator was found; treat this as a moderate flag, not a dealbreaker."
    else:
        reason = ("No risk indicators were detected; this score reflects the "
                   "moderate-low default, not a confirmed absence of risk.")
    evidence = f"{hits} risk-keyword match(es) (regulation, incumbent entry, or hype language)."
    return score, reason, evidence


def compute_confidence(signals: list, blob: str) -> tuple[float, str, str]:
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

    `blob` is unused — confidence is computed purely from signal
    structure, not text content — but kept in the signature for a
    uniform (signals, blob) -> (score, reason, evidence) compute_fn
    contract across all dimensions.
    """
    n = len(signals)

    # 1. Source diversity (0–4 points). Max bonus at 3+ distinct sources.
    sources = set(s.source for s in signals)
    source_count = len(sources)
    diversity = min(4.0, source_count * 1.5)

    # 2. Evidence count (0–3.5 points). log₄: 1→0, 4→1.7, 16→3.5
    count_score = min(3.5, math.log(n, 4) * 1.75) if n > 1 else 0.0

    # 3. Quality (0–2.5 points). What fraction have >10 engagement points?
    high_quality = sum(1 for s in signals if s.engagement > 10)
    quality = min(2.5, (high_quality / n) * 2.5) if n > 0 else 0.0

    score = round(min(10.0, diversity + count_score + quality), 2)

    if source_count >= 3:
        reason = ("This pattern was corroborated by 3 or more independent "
                   "sources — the strongest form of evidence this system "
                   "recognises.")
    elif source_count == 2:
        reason = "This pattern was corroborated by 2 independent sources."
    else:
        reason = (f"This pattern was only observed on a single source "
                   f"({next(iter(sources)) if sources else 'unknown'}); "
                   f"treat the other scores with more caution until a second "
                   f"source confirms it.")
    evidence = (f"{source_count} distinct source(s), {n} signal(s), "
                f"{high_quality}/{n} with engagement above 10.")
    return score, reason, evidence
