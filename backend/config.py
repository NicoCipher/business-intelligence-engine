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


# ── Slack ↔ Linear ticket sync ───────────────────────────────────────────
# Disabled by default so the existing Zap can remain the sole ticket creator
# until the BIA webhook cutover is deliberately enabled.

TICKET_SYNC_ENABLED = os.getenv("BIA_TICKET_SYNC_ENABLED", "false").lower() in {
    "1", "true", "yes", "on",
}
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_OPS_CHANNEL_ID = os.getenv("SLACK_OPS_CHANNEL_ID", "")
SLACK_TICKET_REACTION = os.getenv("SLACK_TICKET_REACTION", "ticket")
LINEAR_API_KEY = os.getenv("LINEAR_API_KEY", "")
LINEAR_WEBHOOK_SECRET = os.getenv("LINEAR_WEBHOOK_SECRET", "")
LINEAR_TEAM_ID = os.getenv("LINEAR_TEAM_ID", "")
LINEAR_BACKLOG_STATE_ID = os.getenv("LINEAR_BACKLOG_STATE_ID", "")
LINEAR_DONE_STATE_ID = os.getenv("LINEAR_DONE_STATE_ID", "")


# ── Collector limits ───────────────────────────────────────────────────────
# Keep these conservative. We are guests on public APIs.

HN_STORY_LIMIT       = int(os.getenv("HN_STORY_LIMIT", "80"))
HN_REQUEST_DELAY_S   = float(os.getenv("HN_REQUEST_DELAY", "0.15"))   # seconds between item fetches

REDDIT_POST_LIMIT    = int(os.getenv("REDDIT_POST_LIMIT", "25"))       # per subreddit
REDDIT_REQUEST_DELAY = float(os.getenv("REDDIT_REQUEST_DELAY", "1.0")) # PRAW handles rate limits; this is extra

GITHUB_SEARCH_LIMIT   = int(os.getenv("GITHUB_SEARCH_LIMIT", "20"))        # per query, per endpoint (issues/repos)
GITHUB_REQUEST_DELAY  = float(os.getenv("GITHUB_REQUEST_DELAY", "2.5"))    # seconds between search calls --
                                                                             # the Search API's 30 req/min limit is
                                                                             # far stricter than GitHub's general
                                                                             # 5000 req/hr authenticated limit

GOOGLE_TRENDS_KEYWORD_LIMIT  = int(os.getenv("GOOGLE_TRENDS_KEYWORD_LIMIT", "20"))     # rising-query signals, total across all keywords
GOOGLE_TRENDS_REQUEST_DELAY  = float(os.getenv("GOOGLE_TRENDS_REQUEST_DELAY", "30.0")) # seconds between keywords --
                                                                             # pytrends is unofficial/reverse-
                                                                             # engineered with no documented rate
                                                                             # limit; deliberately conservative

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


# ── Knowledge-graph decay (schema v8) ──────────────────────────────────────
# Lifecycle: ACTIVE -> DORMANT -> SOFT_ARCHIVED. Never deleted. See
# knowledge_graph/decay.py for the full decision logic. Scoped separately
# to entities vs. relationships since they decay for different reasons
# (an entity is a concept that can matter for years; a relationship is
# one specific co-occurrence pattern that goes stale faster).

ENTITY_DORMANT_DAYS       = int(os.getenv("BIA_ENTITY_DORMANT_DAYS", "365"))
ENTITY_ARCHIVE_DAYS       = int(os.getenv("BIA_ENTITY_ARCHIVE_DAYS", "730"))
RELATIONSHIP_DORMANT_DAYS = int(os.getenv("BIA_RELATIONSHIP_DORMANT_DAYS", "180"))
RELATIONSHIP_ARCHIVE_DAYS = int(os.getenv("BIA_RELATIONSHIP_ARCHIVE_DAYS", "365"))

# Connection-strength protection: entities linked by many relationships, or
# relationships with high accumulated co-occurrence weight, are more
# likely to reflect a real, recurring pattern than a one-off mention —
# give them more time before decaying. Multiplier, not immunity: strongly
# connected items still eventually decay if genuinely unreferenced.
ENTITY_STRONG_CONNECTION_COUNT   = int(os.getenv("BIA_ENTITY_STRONG_CONNECTION_COUNT", "5"))
RELATIONSHIP_STRONG_WEIGHT       = float(os.getenv("BIA_RELATIONSHIP_STRONG_WEIGHT", "5.0"))
DECAY_PROTECTION_MULTIPLIER      = float(os.getenv("BIA_DECAY_PROTECTION_MULTIPLIER", "1.5"))

# Two-layer matching eligibility (opportunity_engine/canonicalizer.py):
# dormant entities still count toward canonical Problem matching, just at
# reduced weight; archived entities are excluded entirely from new
# matching (weight 0) but the rows themselves are never deleted, so they
# remain queryable as historical context.
DORMANT_MATCH_WEIGHT = float(os.getenv("BIA_DORMANT_MATCH_WEIGHT", "0.5"))


# ── Problem lifecycle & trend (schema v9) ──────────────────────────────────
# Two INDEPENDENT axes, not one combined state — see
# opportunity_engine/lifecycle.py's module docstring for the full
# reasoning (one field, one concept; avoids state-explosion and
# contradictory combinations like "declining but freshly reactivated").
#
#   lifecycle_state: new -> active -> dormant -> archived
#                                        ^-- reactivated <--'
#     "Is this Problem operationally relevant right now?"
#
#   trend: unknown -> {growing | stable | declining}
#     "How is its evidence cadence changing?" Independent of lifecycle —
#     a dormant Problem can still carry a last-known trend value.
#
# Distinct from the knowledge-graph decay thresholds above (different
# model) and from Opportunity.status (human-curated review field,
# unrelated, never enforced).

# weeks_seen at or above this exits 'new' into 'active'.
PROBLEM_RECURRENCE_WEEKS = int(os.getenv("BIA_PROBLEM_RECURRENCE_WEEKS", "2"))

# Lifecycle: no new evidence for this long -> dormant; this much longer
# again -> archived. Same active->dormant->archived shape as the
# knowledge-graph decay thresholds above, mirrored here for consistency,
# with its own thresholds since a Problem going quiet is a different,
# higher-level signal than a single entity mention going stale.
PROBLEM_DORMANT_DAYS = int(os.getenv("BIA_PROBLEM_DORMANT_DAYS", "90"))
PROBLEM_ARCHIVE_DAYS = int(os.getenv("BIA_PROBLEM_ARCHIVE_DAYS", "180"))

# Trend classification compares problem_history evidence cadence in the
# most recent window against the window before it. Needs 2x this many
# days of elapsed history (since the relevant anchor — first_seen, or
# the most recent reactivation if later) before a trend can be
# classified at all; before that, trend stays 'unknown' rather than
# being forced into a guess.
PROBLEM_TREND_WINDOW_DAYS = int(os.getenv("BIA_PROBLEM_TREND_WINDOW_DAYS", "28"))  # 4 weeks

# recent_count / prior_count >= this -> growing; <= this -> declining;
# between the two (inclusive of neither) -> stable.
PROBLEM_GROWTH_RATIO  = float(os.getenv("BIA_PROBLEM_GROWTH_RATIO", "1.5"))
PROBLEM_DECLINE_RATIO = float(os.getenv("BIA_PROBLEM_DECLINE_RATIO", "0.5"))


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
