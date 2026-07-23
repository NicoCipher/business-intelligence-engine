"""
config.py — Centralised configuration for BIA-OS

All tuneable values live here. No magic numbers scattered through the codebase.
Environment variables override defaults so this works locally and in CI without
code changes.

Nothing in this file does I/O. It is imported by everything, so it must have
zero side effects.
"""

import os
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────

ROOT_DIR  = Path(__file__).parent.parent
DATA_DIR  = Path(os.getenv("BIA_DATA_DIR", ROOT_DIR / "backend" / "data"))
DB_PATH   = DATA_DIR / "bia.db"


# ── API server ─────────────────────────────────────────────────────────────

API_HOST  = os.getenv("BIA_HOST", "127.0.0.1")
API_PORT  = int(os.getenv("BIA_PORT", "8000"))


# ── Collector limits ───────────────────────────────────────────────────────
# Keep these conservative. We are guests on public APIs.

HN_STORY_LIMIT       = int(os.getenv("HN_STORY_LIMIT", "80"))
HN_REQUEST_DELAY_S   = float(os.getenv("HN_REQUEST_DELAY", "0.15"))   # seconds between item fetches

REDDIT_POST_LIMIT    = int(os.getenv("REDDIT_POST_LIMIT", "25"))       # per subreddit
REDDIT_REQUEST_DELAY = float(os.getenv("REDDIT_REQUEST_DELAY", "1.0")) # PRAW handles rate limits; this is extra

# Subreddits monitored. Ordered by signal quality for this system's purpose.
REDDIT_SUBREDDITS = [
    "entrepreneur",
    "freelance",
    "sidehustle",
    "smallbusiness",
    "nocode",
    "SaaS",
    "digitalnomad",
    "juststart",
]


# ── Opportunity engine ─────────────────────────────────────────────────────

# Minimum number of signals required to form a cluster worth scoring
MIN_CLUSTER_SIZE = 2

# Minimum composite score to persist an opportunity to the database
MIN_COMPOSITE_TO_PERSIST = 5.0

# Composite score thresholds for tier classification
TIER_GOLD   = 8.0
TIER_SILVER = 6.5

# Dimension weights for composite score calculation.
# Must sum to 1.0. Adjust as the scoring model matures.
SCORE_WEIGHTS: dict[str, float] = {
    "demand":              0.25,
    "competition":         0.20,
    "revenue_potential":   0.20,
    "confidence":          0.15,
    "execution_difficulty": 0.10,
    "time_to_revenue":     0.05,
    "risk":                0.05,
}

assert abs(sum(SCORE_WEIGHTS.values()) - 1.0) < 1e-9, \
    "SCORE_WEIGHTS must sum to exactly 1.0"


# ── Keyword dictionaries ───────────────────────────────────────────────────
# Centralised here so the scorer and detector share the same vocabulary.

DEMAND_KEYWORDS: frozenset[str] = frozenset([
    "how to", "looking for", "recommend", "any tool", "any alternative",
    "best way", "how do i", "need help", "is there a", "does anyone know",
    "how can i", "what's the best", "i wish there was", "why isn't there",
    "anyone built", "i'd pay", "would pay", "help me find", "any library",
    "any service", "any solution", "searching for", "can't find",
])

COMPLAINT_KEYWORDS: frozenset[str] = frozenset([
    "frustrated", "annoying", "broken", "terrible", "awful", "hate",
    "worst", "fails", "doesn't work", "problem with", "missing feature",
    "no solution", "impossible to", "why doesn't", "nobody does",
])

WILLINGNESS_TO_PAY: frozenset[str] = frozenset([
    "would pay", "i'd pay", "paying for", "subscribed", "bought",
    "purchased", " $", " €", " £", "pricing", "charge", "per month",
    "per year", "enterprise", "b2b", "commercial license",
])

LOW_COMPETITION_SIGNALS: frozenset[str] = frozenset([
    "no good alternative", "only option", "nothing exists",
    "no solution", "can't find anything", "doesn't exist yet",
    "built this because", "nothing like it", "market gap",
    "underserved", "no competitor",
])

RISK_KEYWORDS: frozenset[str] = frozenset([
    "regulation", "lawsuit", "banned", "illegal", "compliance required",
    "google announced", "apple announced", "meta announced",
    "openai announced", "microsoft announced",   # big tech entering
    "overhyped", "bubble",
])

# Evidence of a manual, unautomated workflow — a strong signal the person
# is doing something by hand that could be a product. Deliberately NOT
# wired into OpportunityScorer's numeric dimensions (that would change
# every composite score already covered by test_scorer.py's exact-value
# assertions) — this is validation/narrative evidence only, cited directly
# in Build-verdict justifications and founder intelligence, not scored.
MANUAL_WORKFLOW_KEYWORDS: frozenset[str] = frozenset([
    "manually", "by hand", "spreadsheet", "copy and paste", "copy-paste",
    "every week i", "every sunday", "every month i", "spend hours",
    "spending hours", "no automation", "there's no way to automate",
])
