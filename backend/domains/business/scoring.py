"""
domains/business/scoring.py

Scoring profile for the Business Intelligence domain.

Each ScoringDimension is self-contained: it carries its own
positive_keywords and negative_keywords directly. Nothing here
references DomainKeywords or keywords.py — the scoring module
owns its vocabulary independently.

Dimension IDs match the current scorer.py method names exactly so that
Milestone 5 (generic scorer) can consume them without a translation layer.

Semantic mapping for this domain:
  demand            → active market need (frequency, explicit ask signals)
  competition       → market gap (inverse saturation; gap/no-solution signals)
  revenue_potential → willingness to pay (pricing, enterprise, B2B signals)
  confidence        → evidence quality  (structure-based; no keyword matching)
  execution_difficulty → execution ease (inverted; template/no-code = easier)
  time_to_revenue   → path to first income (inverted; freelance = faster)
  risk              → external threats   (inverted; big-tech entry = lower score)

Weights are unchanged from config.SCORE_WEIGHTS (sum = 1.0 exactly).
"""

from domains.base import DomainScoring, ScoringDimension, ScoringThresholds

SCORING = DomainScoring(
    dimensions=[
        ScoringDimension(
            id="demand",
            label="Market Demand",
            description=(
                "Evidence of active unmet need: people searching for a "
                "solution, asking whether something exists, or expressing "
                "frustration with the status quo."
            ),
            weight=0.25,
            positive_keywords=frozenset([
                "how to", "looking for", "any tool", "recommend",
                "any alternative", "best way", "how do i", "need help",
                "is there a", "does anyone know", "how can i",
                "what's the best", "i wish there was", "why isn't there",
                "anyone built", "i'd pay", "would pay", "help me find",
                "any library", "any service", "any solution",
                "searching for", "can't find",
                # complaint / frustration signals
                "frustrated", "annoying", "broken", "terrible", "awful",
                "hate", "worst", "fails", "doesn't work", "problem with",
                "missing feature", "no solution", "impossible to",
                "why doesn't", "nobody does",
            ]),
            negative_keywords=frozenset(),
        ),
        ScoringDimension(
            id="competition",
            label="Market Gap",
            description=(
                "Inverse of market saturation. Higher score means fewer "
                "quality alternatives exist for the identified need."
            ),
            weight=0.20,
            positive_keywords=frozenset([
                "no good alternative", "only option", "nothing exists",
                "no solution", "can't find anything", "doesn't exist yet",
                "built this because", "nothing like it", "market gap",
                "underserved", "no competitor",
            ]),
            negative_keywords=frozenset(),
        ),
        ScoringDimension(
            id="revenue_potential",
            label="Revenue Potential",
            description=(
                "Evidence of willingness to pay. B2B context and explicit "
                "pricing signals amplify this dimension."
            ),
            weight=0.20,
            positive_keywords=frozenset([
                "would pay", "i'd pay", "paying for", "subscribed",
                "bought", "purchased", " $", " €", " £", "pricing",
                "charge", "per month", "per year", "enterprise", "b2b",
                "commercial license",
            ]),
            negative_keywords=frozenset(),
        ),
        ScoringDimension(
            id="confidence",
            label="Evidence Confidence",
            description=(
                "Quality and diversity of supporting signals. Computed from "
                "source count, evidence volume, and engagement — not from "
                "keyword matching."
            ),
            weight=0.15,
            positive_keywords=frozenset(),
            negative_keywords=frozenset(),
        ),
        ScoringDimension(
            id="execution_difficulty",
            label="Execution Ease",
            description=(
                "How straightforward this is to act on. Inverted: a higher "
                "score means lower execution difficulty."
            ),
            weight=0.10,
            positive_keywords=frozenset([
                "template", "no-code", "nocode", "automation",
                "consulting", "service", "agency", "notion",
                "spreadsheet", "saas", "api wrapper", "integration",
            ]),
            negative_keywords=frozenset([
                "hardware", "biotech", "clinical trial", "semiconductor",
                "patent", "novel research", "phd", "fda approval",
            ]),
        ),
        ScoringDimension(
            id="time_to_revenue",
            label="Time to Revenue",
            description=(
                "Speed of the path to first income. Inverted: a higher "
                "score means a faster path to payment."
            ),
            weight=0.05,
            positive_keywords=frozenset([
                "freelance", "consulting", "service", "agency", "coaching",
            ]),
            negative_keywords=frozenset([
                "marketplace", "platform", "community", "network effect",
            ]),
        ),
        ScoringDimension(
            id="risk",
            label="External Risk",
            description=(
                "Threats that could undermine the opportunity. Inverted: "
                "a higher score means a lower risk environment."
            ),
            weight=0.05,
            positive_keywords=frozenset(),
            negative_keywords=frozenset([
                "regulation", "lawsuit", "banned", "illegal",
                "compliance required", "google announced",
                "apple announced", "meta announced",
                "openai announced", "microsoft announced",
                "overhyped", "bubble",
            ]),
        ),
    ],
    thresholds=ScoringThresholds(
        high=8.0,    # Gold — act this week
        medium=6.5,  # Silver — validate first
    ),
)
