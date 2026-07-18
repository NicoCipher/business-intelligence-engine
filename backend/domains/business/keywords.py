"""
domains/business/keywords.py

Signal keyword vocabulary for the Business Intelligence domain.

This module organises keywords the business domain uses for
collector-level signal classification and entity extraction hints.
These sets are the business domain's own vocabulary — they are not
a mapping to the core engine's generic groups.

Usage within this domain:
  - HN/Reddit collectors use these to tag signals with domain labels
    (e.g. marking a post as a demand signal or a gap signal)
  - The entity extractor uses graph.py keywords, not these
  - Scoring dimensions define their own keyword sets in scoring.py

The four groups reflect how the business domain thinks about signals:

  include  — signals that indicate business opportunity relevance:
             people actively seeking a solution, or expressing pain.

  exclude  — signals that suggest noise for this domain:
             regulatory risk, big-tech market entry, hype cycles.

  boost    — signals of commercial gravity:
             explicit pricing mention, enterprise context, B2B framing.

  priority — signals of the highest opportunity signal strength:
             no competitor exists, clear market gap identified.
"""

from domains.base import DomainKeywords

KEYWORDS = DomainKeywords(
    include=frozenset([
        # Active demand: people asking for or seeking a solution
        "how to", "looking for", "any tool", "recommend",
        "any alternative", "best way", "how do i", "need help",
        "is there a", "does anyone know", "how can i",
        "what's the best", "i wish there was", "why isn't there",
        "anyone built", "i'd pay", "would pay", "help me find",
        "any library", "any service", "any solution",
        "searching for", "can't find",
        # Pain signals: people frustrated with the status quo
        "frustrated", "annoying", "broken", "terrible", "awful",
        "hate", "worst", "fails", "doesn't work", "problem with",
        "missing feature", "no solution", "impossible to",
        "why doesn't", "nobody does",
    ]),
    exclude=frozenset([
        # Noise: regulatory friction, incumbent threats, hype cycles
        "regulation", "lawsuit", "banned", "illegal",
        "compliance required", "google announced", "apple announced",
        "meta announced", "openai announced", "microsoft announced",
        "overhyped", "bubble",
    ]),
    boost=frozenset([
        # Commercial gravity: evidence of willingness to pay
        "would pay", "i'd pay", "paying for", "subscribed",
        "bought", "purchased", " $", " €", " £", "pricing",
        "charge", "per month", "per year", "enterprise", "b2b",
        "commercial license",
    ]),
    priority=frozenset([
        # Highest signal strength: no competitor, clear market gap
        "no good alternative", "only option", "nothing exists",
        "no solution", "can't find anything", "doesn't exist yet",
        "built this because", "nothing like it", "market gap",
        "underserved", "no competitor",
    ]),
)
