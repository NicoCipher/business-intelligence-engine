"""
models.py — Domain models for BIA-OS

These are plain Python dataclasses. They have no dependency on the database,
the API framework, or any external library. They represent the business domain.

Why dataclasses instead of Pydantic everywhere?
  The domain model should be independent of the API framework. Pydantic models
  exist only at the API boundary (in api/*.py). Here we use dataclasses so
  the core engine can be tested and reasoned about without FastAPI present.

Serialisation:
  Each model provides to_db_row() → dict for persistence
  and a from_db_row() classmethod for reconstruction.
  This is explicit and transparent — no magic mapping.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from config import SCORE_WEIGHTS, TIER_GOLD, TIER_SILVER


# ── Helpers ───────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


# ── Entity ────────────────────────────────────────────────────────────────

VALID_ENTITY_TYPES = frozenset([
    "problem", "market", "technology", "company",
    "skill", "product", "regulation", "person",
])


@dataclass
class Entity:
    """A node in the knowledge graph."""
    name: str
    type: str
    description: str = ""
    metadata: dict = field(default_factory=dict)
    id: str = field(default_factory=_uuid)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def __post_init__(self):
        if self.type not in VALID_ENTITY_TYPES:
            raise ValueError(f"Invalid entity type '{self.type}'. Must be one of {VALID_ENTITY_TYPES}")

    def to_db_row(self) -> dict:
        import json
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "description": self.description,
            "metadata": json.dumps(self.metadata),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# ── Relationship ──────────────────────────────────────────────────────────

VALID_RELATIONSHIP_TYPES = frozenset([
    "solves", "belongs_to", "requires", "competes_with",
    "indicates", "relates_to", "enables",
])


@dataclass
class Relationship:
    """A directed edge in the knowledge graph."""
    from_id: str
    to_id: str
    type: str
    weight: float = 1.0
    metadata: dict = field(default_factory=dict)
    id: str = field(default_factory=_uuid)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def __post_init__(self):
        if self.weight < 0 or self.weight > 10:
            raise ValueError(f"Relationship weight must be 0–10, got {self.weight}")


# ── Signal ────────────────────────────────────────────────────────────────

VALID_SOURCES = frozenset(["hn", "reddit", "rss", "trends"])


@dataclass
class Signal:
    """
    A raw data point collected from one external source.

    Signals are the atomic unit of evidence. The system never modifies
    collected signals — they are append-only facts about what was observed.
    """
    source: str        # hn | reddit | rss | trends
    source_id: str     # original ID in the source system (for deduplication)
    title: str
    content: str = ""
    url: str = ""
    platform_score: int = 0     # upvotes / HN points / post score
    comment_count: int = 0
    entity_ids: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    raw_metadata: dict = field(default_factory=dict)
    collected_at: str = field(default_factory=_now)
    processed: int = 0          # 0=raw, 1=processed, 2=failed
    id: str = field(default_factory=_uuid)
    domain: str = "business"    # originating domain id (see domains/registry.py)

    def __post_init__(self):
        if self.source not in VALID_SOURCES:
            raise ValueError(f"Invalid source '{self.source}'. Must be one of {VALID_SOURCES}")
        if not self.title.strip():
            raise ValueError("Signal title cannot be empty")

    @property
    def full_text(self) -> str:
        """Combined title and content for text analysis."""
        return f"{self.title} {self.content}".lower()

    @property
    def engagement(self) -> int:
        return self.platform_score + self.comment_count

    def to_db_row(self) -> dict:
        import json
        return {
            "id": self.id,
            "source": self.source,
            "source_id": self.source_id,
            "url": self.url,
            "title": self.title,
            "content": self.content,
            "platform_score": self.platform_score,
            "comment_count": self.comment_count,
            "entity_ids": json.dumps(self.entity_ids),
            "tags": json.dumps(self.tags),
            "raw_metadata": json.dumps(self.raw_metadata, default=str),
            "collected_at": self.collected_at,
            "processed": self.processed,
            "domain": self.domain,
        }


# ── DimensionExplanation ─────────────────────────────────────────────────

@dataclass
class DimensionExplanation:
    """
    Why one scoring dimension received the value it did.

    Produced by OpportunityScorer alongside the numeric score itself (see
    scorer.py's "no black boxes" principle). This is the difference between
    a report saying "Demand: 7" and one saying "Demand: 7/10 — multiple
    signals use solution-seeking language, evidenced by 3 keyword matches
    across 5 signals."

    `reason` is one plain-language sentence. `evidence` is the specific
    measurable fact behind it (counts, keyword hits) — kept separate so a
    reader can skim reasons and drill into evidence only when they want to.
    """
    score: float = 0.0
    reason: str = ""
    evidence: str = ""

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 2),
            "reason": self.reason,
            "evidence": self.evidence,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DimensionExplanation":
        return cls(
            score=d.get("score", 0.0),
            reason=d.get("reason", ""),
            evidence=d.get("evidence", ""),
        )


# ── OpportunityScores ─────────────────────────────────────────────────────

@dataclass
class OpportunityScores:
    """
    Fully transparent scoring breakdown for one opportunity.

    Every dimension is 0–10. Higher is always better (difficulty and risk
    are already inverted by the scorer before reaching this model).

    The composite() method applies documented weights from config.py.
    Anyone can inspect, question, or adjust the weights.
    """
    demand: float = 0.0              # evidence of active unmet demand
    competition: float = 0.0        # inverse of market saturation
    revenue_potential: float = 0.0  # signals of willingness to pay
    execution_difficulty: float = 0.0  # inverted: 10 = trivially easy
    time_to_revenue: float = 0.0    # inverted: 10 = can earn this week
    risk: float = 0.0               # inverted: 10 = very low risk
    confidence: float = 0.0         # quality of evidence (count + diversity)
    evidence_count: int = 0         # raw number of signals in the cluster
    # Per-dimension reason + evidence, keyed by dimension name (e.g. "demand").
    # Optional: defaults to {} so every existing caller that builds
    # OpportunityScores with numeric kwargs only (tests, from_dict on old
    # rows) keeps working unchanged. Populated by OpportunityScorer.score().
    explanations: dict[str, "DimensionExplanation"] = field(default_factory=dict)

    def composite(self) -> float:
        """
        Weighted average of all dimensions.
        Weights are defined in config.SCORE_WEIGHTS to keep them adjustable.
        """
        score = sum(
            getattr(self, dim) * weight
            for dim, weight in SCORE_WEIGHTS.items()
        )
        return round(min(10.0, max(0.0, score)), 2)

    def tier(self) -> str:
        s = self.composite()
        if s >= TIER_GOLD:   return "gold"
        if s >= TIER_SILVER: return "silver"
        return "bronze"

    def to_dict(self) -> dict:
        """Serialise to dict for JSON storage and API responses."""
        return {
            "demand":              round(self.demand, 2),
            "competition":         round(self.competition, 2),
            "revenue_potential":   round(self.revenue_potential, 2),
            "execution_difficulty": round(self.execution_difficulty, 2),
            "time_to_revenue":     round(self.time_to_revenue, 2),
            "risk":                round(self.risk, 2),
            "confidence":          round(self.confidence, 2),
            "evidence_count":      self.evidence_count,
            "composite":           self.composite(),
            "tier":                self.tier(),
            "explanations": {
                dim: exp.to_dict() for dim, exp in self.explanations.items()
            },
        }

    @classmethod
    def from_dict(cls, d: dict) -> "OpportunityScores":
        return cls(
            demand=d.get("demand", 0.0),
            competition=d.get("competition", 0.0),
            revenue_potential=d.get("revenue_potential", 0.0),
            execution_difficulty=d.get("execution_difficulty", 0.0),
            time_to_revenue=d.get("time_to_revenue", 0.0),
            risk=d.get("risk", 0.0),
            confidence=d.get("confidence", 0.0),
            evidence_count=d.get("evidence_count", 0),
            explanations={
                dim: DimensionExplanation.from_dict(exp)
                for dim, exp in d.get("explanations", {}).items()
            },
        )


# ── Opportunity ───────────────────────────────────────────────────────────

@dataclass
class Opportunity:
    """
    A scored, evidence-backed opportunity.

    An opportunity is always derived from at least MIN_CLUSTER_SIZE signals.
    It is never invented — every field traces back to observed signals.
    """
    title: str
    description: str
    scores: OpportunityScores
    signal_ids: list[str] = field(default_factory=list)
    entity_ids: list[str] = field(default_factory=list)
    status: str = "new"    # new | validated | dismissed | archived
    week_key: str = ""
    id: str = field(default_factory=_uuid)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    domain: str = "business"    # originating domain id (see domains/registry.py)

    def __post_init__(self):
        if not self.week_key:
            # Default to current ISO week
            now = datetime.now(timezone.utc)
            self.week_key = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"

    @property
    def composite_score(self) -> float:
        return self.scores.composite()

    @property
    def tier(self) -> str:
        return self.scores.tier()

    def to_db_row(self) -> dict:
        import json
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "signal_ids": json.dumps(self.signal_ids),
            "entity_ids": json.dumps(self.entity_ids),
            "scores": json.dumps(self.scores.to_dict()),
            "composite_score": self.composite_score,
            "status": self.status,
            "week_key": self.week_key,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "domain": self.domain,
        }


# ── WeeklyReport ──────────────────────────────────────────────────────────

@dataclass
class WeeklyReport:
    """
    The system's primary output artifact.

    Generated once per week (or on demand) by report.generator.ReportGenerator.
    Stored in the reports table and served via GET /api/v1/reports/latest.

    content is a JSON-serialised dict with the full briefing structure:
      week_key, period_start, period_end, summary, top_opportunities,
      key_insights, recommended_actions, entity_intelligence,
      signal_breakdown, top_tags, generated_at.
    """
    week_key:     str
    period_start: str
    period_end:   str
    content:      dict = field(default_factory=dict)
    opp_count:    int  = 0
    signal_count: int  = 0
    id:           str  = field(default_factory=_uuid)
    created_at:   str  = field(default_factory=_now)
    domain:       str  = "business"    # originating domain id (see domains/registry.py)
