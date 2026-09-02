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
from dataclasses import dataclass, field, InitVar
from datetime import datetime, timezone
from typing import Optional

# SCORE_WEIGHTS/TIER_GOLD/TIER_SILVER are used only as OpportunityScores'
# *default* weights/thresholds (ADR-011) — for objects built without a
# domain context: direct test construction, and from_dict() on any
# persisted row. A domain-aware caller (OpportunityScorer) always supplies
# its own DomainScoring-derived weights/thresholds explicitly at
# construction time and never relies on this default. Values here are
# identical to domains.business.scoring.SCORING's, by design (see that
# module's docstring) — this file does not import domains.* to keep
# models.py free of any dependency beyond config.py, per its own
# docstring ("no dependency on the database, the API framework, or any
# external library").
from config import SCORE_WEIGHTS, TIER_GOLD, TIER_SILVER


# ── Helpers ───────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


# ── Entity ────────────────────────────────────────────────────────────────

# Entity type names are intentionally NOT validated against a fixed set
# here. This dataclass is domain-agnostic core code (see models.py's own
# docstring) — the set of valid types is determined by whichever
# domain's DomainKnowledgeGraph.entity_types produced this Entity (see
# knowledge_graph/extractor.py), and that set genuinely differs by
# domain. A fixed global allowlist here would reject any second
# domain's own entity type names by construction, not by mistake —
# found and fixed alongside the extractor.py/detector.py/canonicalizer.py
# domain-generalization work, since it blocked exactly what that work
# was for. The type is already guaranteed valid for its domain by the
# time an Entity is constructed (extractor.py only ever passes a
# type_name drawn directly from the active domain's own entity_types
# keys), so re-validating against a separate, hardcoded list here was
# both redundant for Business and actively wrong for anything else.


VALID_LIFECYCLE_STATES = frozenset(["active", "dormant", "archived"])


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
    # Knowledge-graph decay (schema v8) — see knowledge_graph/decay.py.
    # `updated_at` above doubles as "last meaningfully referenced" once
    # persisted (extractor.persist_results() bumps it on every
    # re-encounter, not just first insert) — lifecycle_updated_at is
    # deliberately separate: it's the last time lifecycle_state itself
    # changed (by a decay pass or by reactivation), not the last
    # reference. Conflating the two would make "how long has this been
    # dormant" impossible to answer once decay thresholds change.
    lifecycle_state: str = "active"
    lifecycle_updated_at: str = field(default_factory=_now)

    def __post_init__(self):
        if not self.type or not self.type.strip():
            raise ValueError("Entity.type must not be empty")
        if self.lifecycle_state not in VALID_LIFECYCLE_STATES:
            raise ValueError(
                f"Invalid lifecycle_state '{self.lifecycle_state}'. "
                f"Must be one of {VALID_LIFECYCLE_STATES}"
            )

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
            "lifecycle_state": self.lifecycle_state,
            "lifecycle_updated_at": self.lifecycle_updated_at,
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
    # Knowledge-graph decay (schema v8) — see Entity's docstring above for
    # the updated_at vs. lifecycle_updated_at distinction; identical here.
    lifecycle_state: str = "active"
    lifecycle_updated_at: str = field(default_factory=_now)

    def __post_init__(self):
        if self.weight < 0 or self.weight > 10:
            raise ValueError(f"Relationship weight must be 0–10, got {self.weight}")
        if self.lifecycle_state not in VALID_LIFECYCLE_STATES:
            raise ValueError(
                f"Invalid lifecycle_state '{self.lifecycle_state}'. "
                f"Must be one of {VALID_LIFECYCLE_STATES}"
            )

    def to_db_row(self) -> dict:
        import json
        return {
            "id": self.id,
            "from_id": self.from_id,
            "to_id": self.to_id,
            "type": self.type,
            "weight": self.weight,
            "metadata": json.dumps(self.metadata),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "lifecycle_state": self.lifecycle_state,
            "lifecycle_updated_at": self.lifecycle_updated_at,
        }


# ── Signal ────────────────────────────────────────────────────────────────

VALID_SOURCES = frozenset(["hn", "reddit", "rss", "trends", "github", "stackexchange", "greenhouse_jobs"])


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

# Keys in to_dict()'s flat serialization that are not dimension ids.
# from_dict() treats every other key as a dimension. This is what makes
# to_dict()/from_dict() work for any domain's dimension id set, not just
# Business's seven, while staying byte-compatible with every row
# persisted before ADR-011 (see that ADR's "flat JSON compatibility"
# invariant).
_SCORES_META_KEYS = frozenset({"evidence_count", "composite", "tier", "explanations"})


class OpportunityScores:
    """
    Fully transparent scoring breakdown for one opportunity (ADR-011:
    Domain-Generalized Opportunity Scoring).

    Every dimension is 0–10. Higher is always better (difficulty and risk
    are already inverted by the scorer before reaching this model).

    `dimensions` is a dict keyed by dimension id (e.g. "demand" for
    Business; a future domain's ids, e.g. "severity", equally at home
    here) — not a fixed set of named fields. `weights` and `thresholds`
    are supplied by whichever DomainScoring produced this object
    (OpportunityScorer, see opportunity_engine/scorer.py) and default to
    Business's current values if omitted, for any caller with no domain
    context (see the config import note above).

    A plain class with a hand-written __init__, not @dataclass: the
    seven legacy keyword arguments below (demand=, competition=, ...)
    need to be accepted by the constructor without becoming stored
    fields — dataclass's InitVar mechanism can do that, but only if no
    same-named @property also exists on the class, since both share the
    same class-attribute slot at class-definition time and one silently
    clobbers the other. A plain __init__ has no such collision: the
    parameter names are local to the function, unrelated to the
    same-named read-only properties below. No __getattr__ or
    __getattribute__ override is used or needed.

    Backward compatibility, both deliberate and load-bearing:
      - Construction accepts Business's original flat keyword arguments
        (OpportunityScores(demand=10, competition=9, ...)), merged into
        `dimensions`. Existing callers using this form are unaffected
        (see test_scorer.py, test_scoring_explanations.py).
      - Read-only properties (.demand, .competition, etc.) delegate to
        `dimensions.get(id, 0.0)`, so existing read access (including
        opportunity_engine/detector.py's `scores.confidence`, which this
        change does not modify) keeps working unchanged.
      - to_dict()'s shape is unchanged: dimension ids as flat top-level
        keys, alongside evidence_count/composite/tier/explanations —
        every row persisted before this change round-trips through
        from_dict() identically. Tier labels remain the literal strings
        "gold"/"silver"/"bronze" (not domain-neutral "high"/"medium"/
        "low") because opportunity_engine/explainer/{opportunity,
        summary}.py and report/generator.py match on those exact
        strings and are out of scope for this change (ADR-011).
    """

    def __init__(
        self,
        dimensions: Optional[dict[str, float]] = None,
        evidence_count: int = 0,
        explanations: Optional[dict[str, "DimensionExplanation"]] = None,
        weights: Optional[dict[str, float]] = None,
        thresholds: Optional[tuple[float, float]] = None,
        *,
        demand: Optional[float] = None,
        competition: Optional[float] = None,
        revenue_potential: Optional[float] = None,
        execution_difficulty: Optional[float] = None,
        time_to_revenue: Optional[float] = None,
        risk: Optional[float] = None,
        confidence: Optional[float] = None,
    ):
        self.dimensions = dict(dimensions) if dimensions else {}

        # Legacy flat-kwarg construction — merged into `dimensions`.
        legacy = {
            "demand": demand, "competition": competition,
            "revenue_potential": revenue_potential,
            "execution_difficulty": execution_difficulty,
            "time_to_revenue": time_to_revenue, "risk": risk,
            "confidence": confidence,
        }
        for key, value in legacy.items():
            if value is not None:
                self.dimensions[key] = value

        self.evidence_count = evidence_count
        self.explanations = explanations if explanations is not None else {}
        # None -> Business's current values, for any caller with no
        # domain context (direct construction, from_dict() on a
        # persisted row). A domain-aware caller (OpportunityScorer)
        # always supplies its own explicitly.
        self.weights = weights if weights is not None else dict(SCORE_WEIGHTS)
        self.thresholds = thresholds if thresholds is not None else (TIER_GOLD, TIER_SILVER)

    # ── Legacy read-only accessors ──────────────────────────────────────
    # Ordinary properties (get + set), delegating to `dimensions`. Kept
    # specifically because opportunity_engine/detector.py reads
    # `.confidence` directly, and tests/test_explainer.py constructs
    # fixtures by assigning post-construction (e.g. `scores.demand = 9.0`)
    # — both are out of scope for this change (ADR-011) and unmodified.
    # Kept symmetrically for all seven so existing test assertions (e.g.
    # `scorer.score(x).demand`) are unaffected. Not part of the
    # generalized contract — a future domain's own dimension ids are
    # read/written via `.dimensions[id]`, not a matching attribute.

    @property
    def demand(self) -> float:
        return self.dimensions.get("demand", 0.0)

    @demand.setter
    def demand(self, value: float) -> None:
        self.dimensions["demand"] = value

    @property
    def competition(self) -> float:
        return self.dimensions.get("competition", 0.0)

    @competition.setter
    def competition(self, value: float) -> None:
        self.dimensions["competition"] = value

    @property
    def revenue_potential(self) -> float:
        return self.dimensions.get("revenue_potential", 0.0)

    @revenue_potential.setter
    def revenue_potential(self, value: float) -> None:
        self.dimensions["revenue_potential"] = value

    @property
    def execution_difficulty(self) -> float:
        return self.dimensions.get("execution_difficulty", 0.0)

    @execution_difficulty.setter
    def execution_difficulty(self, value: float) -> None:
        self.dimensions["execution_difficulty"] = value

    @property
    def time_to_revenue(self) -> float:
        return self.dimensions.get("time_to_revenue", 0.0)

    @time_to_revenue.setter
    def time_to_revenue(self, value: float) -> None:
        self.dimensions["time_to_revenue"] = value

    @property
    def risk(self) -> float:
        return self.dimensions.get("risk", 0.0)

    @risk.setter
    def risk(self, value: float) -> None:
        self.dimensions["risk"] = value

    @property
    def confidence(self) -> float:
        return self.dimensions.get("confidence", 0.0)

    @confidence.setter
    def confidence(self, value: float) -> None:
        self.dimensions["confidence"] = value

    # ── Computed values ──────────────────────────────────────────────────

    def composite(self) -> float:
        """
        Weighted average of all dimensions, using this object's own
        `weights` (domain-supplied at construction, or Business's
        defaults). No global import: two OpportunityScores from two
        different domains can each carry their own weights simultaneously.
        """
        score = sum(
            self.dimensions.get(dim_id, 0.0) * weight
            for dim_id, weight in self.weights.items()
        )
        return round(min(10.0, max(0.0, score)), 2)

    def tier(self) -> str:
        """
        Classify composite() against this object's own `thresholds`
        (high, medium). Labels stay "gold"/"silver"/"bronze" — see class
        docstring for why these are not generalized in this change.
        """
        s = self.composite()
        high, medium = self.thresholds
        if s >= high:   return "gold"
        if s >= medium: return "silver"
        return "bronze"

    def to_dict(self) -> dict:
        """Serialise to dict for JSON storage and API responses. Flat
        shape preserved exactly (ADR-011): dimension ids as top-level
        keys, unchanged from every row persisted before this change."""
        return {
            **{dim_id: round(value, 2) for dim_id, value in self.dimensions.items()},
            "evidence_count": self.evidence_count,
            "composite":      self.composite(),
            "tier":           self.tier(),
            "explanations": {
                dim: exp.to_dict() for dim, exp in self.explanations.items()
            },
        }

    @classmethod
    def from_dict(cls, d: dict) -> "OpportunityScores":
        """Reconstruct from to_dict()'s flat shape. Any key not in
        _SCORES_META_KEYS is treated as a dimension id — works for
        Business's seven ids on every pre-existing row, and equally for
        any future domain's own ids, with no hardcoded key list."""
        dimensions = {k: v for k, v in d.items() if k not in _SCORES_META_KEYS}
        return cls(
            dimensions=dimensions,
            evidence_count=d.get("evidence_count", 0),
            explanations={
                dim: DimensionExplanation.from_dict(exp)
                for dim, exp in d.get("explanations", {}).items()
            },
        )


# ── Opportunity ───────────────────────────────────────────────────────────

VALID_PROBLEM_LIFECYCLE_STATES = frozenset(["new", "active", "dormant", "archived", "reactivated"])
VALID_PROBLEM_TREND_STATES = frozenset(["unknown", "growing", "stable", "declining"])


@dataclass
class Problem:
    """
    A stable, long-lived pain point — the canonical identity an Opportunity
    observation attaches to.

    Why this exists as a distinct object from Opportunity (see the
    architecture review, §4/§5): the same underlying problem ("solo
    therapists lack purpose-built note tooling") can recur across weeks
    under different wording ("therapist notes", "clinical session
    documentation"), and can have multiple different solution-angle
    Opportunities pointing at it (an AI SaaS, a Notion template pack, a
    consulting service are three different responses to one problem).
    Opportunity used to conflate all of this into one weekly snapshot
    row with no persisted continuity; Problem is the thing that actually
    persists, Opportunity is the dated observation attached to it.

    entity_ids is the accumulated UNION of entity ids seen across every
    Opportunity ever linked to this Problem — it only grows richer over
    time, never shrinks, and is the signature new opportunities are
    matched against (see opportunity_engine/canonicalizer.py).

    lifecycle_state and trend (schema v9, opportunity_engine/lifecycle.py)
    are two DELIBERATELY INDEPENDENT current-state fields, not one
    combined state: lifecycle_state answers "is this operationally
    relevant right now" (new -> active -> dormant -> archived, reversible
    via reactivated), trend answers "how is its evidence cadence
    changing" (unknown -> growing/stable/declining), and confidence lives
    entirely in the existing scorer model, untouched. Keeping these
    separate avoids state-explosion and contradictory combinations (a
    dormant Problem can still carry a last-known "declining" trend; a
    freshly reactivated Problem's trend resets to 'unknown' independently
    of its lifecycle_state also changing) — a single combined enum was
    the first design tried here and was deliberately unwound in favor of
    this before anything shipped, once the state-explosion cost became
    concrete. See opportunity_engine/lifecycle.py's module docstring for
    the full reasoning.

    Every transition on either field is also written to problem_history
    as a "status_changed" event (the event type schema v7 reserved for
    exactly this and left unused until now), tagged with which axis
    changed — so the full trajectory over time remains reconstructable
    even though these columns themselves are overwritten on each
    transition. Deliberately distinct from Opportunity.status
    (new|validated|dismissed|archived — a pre-existing, human-curated
    review field mutated via a separate PATCH endpoint, unrelated):
    lifecycle_state/trend are system-derived from accumulated evidence,
    never human-set. The vocabularies happen to share "archived" and
    "new" — they are not the same concept.
    """
    title: str
    domain: str = "business"
    entity_ids: list[str] = field(default_factory=list)
    first_seen: str = field(default_factory=_now)
    last_seen: str = field(default_factory=_now)
    weeks_seen: int = 1
    id: str = field(default_factory=_uuid)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    lifecycle_state: str = "new"
    lifecycle_updated_at: str = field(default_factory=_now)
    trend: str = "unknown"
    trend_updated_at: str = field(default_factory=_now)

    def __post_init__(self):
        if self.lifecycle_state not in VALID_PROBLEM_LIFECYCLE_STATES:
            raise ValueError(
                f"Invalid lifecycle_state '{self.lifecycle_state}'. "
                f"Must be one of {VALID_PROBLEM_LIFECYCLE_STATES}"
            )
        if self.trend not in VALID_PROBLEM_TREND_STATES:
            raise ValueError(
                f"Invalid trend '{self.trend}'. Must be one of {VALID_PROBLEM_TREND_STATES}"
            )

    def to_db_row(self) -> dict:
        import json
        return {
            "id":         self.id,
            "domain":     self.domain,
            "title":      self.title,
            "entity_ids": json.dumps(self.entity_ids),
            "first_seen": self.first_seen,
            "last_seen":  self.last_seen,
            "weeks_seen": self.weeks_seen,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "lifecycle_state":      self.lifecycle_state,
            "lifecycle_updated_at": self.lifecycle_updated_at,
            "trend":                self.trend,
            "trend_updated_at":     self.trend_updated_at,
        }


# ── ProblemHistoryEvent ───────────────────────────────────────────────────

VALID_HISTORY_EVENT_TYPES = frozenset([
    "created", "evidence_added", "confidence_updated",
    "status_changed", "merged", "split",
])


@dataclass
class ProblemHistoryEvent:
    """
    One append-only event in a Problem's timeline (schema v7).

    Why this exists as a separate table rather than arrays-on-Problem:
    Problem stores only the current canonical state (see its docstring —
    entity_ids is already an accumulated union, not a history). Growing
    JSON arrays on that row would mean rewriting an ever-larger blob on
    every match, no per-event querying, and unbounded row growth over
    years of weekly runs. problem_history is a normal append-only child
    table instead — one row per event, indexed, cheap to query or prune.

    Event types currently written by the pipeline:
      - "created"         — a new Problem was established (no match found).
      - "evidence_added"   — an existing Problem matched a new observation
                              (opportunity_engine/canonicalizer.py).
    Event types defined for future use, not yet written by any code path
    (Problem has no status field and no merge/split logic yet — adding
    those is separate, larger work, not smuggled in here):
      - "confidence_updated", "status_changed", "merged", "split".

    `metadata` is intentionally flexible (JSON) rather than a fixed set of
    columns — different event types carry different facts (a match score,
    a status transition, a merge target), and forcing one rigid schema
    across all of them would mean either NULL-heavy columns or constant
    migrations as new event types are added.
    """
    problem_id: str
    event_type: str
    domain: str = "business"
    week_key: str = ""
    opportunity_id: str = ""
    metadata: dict = field(default_factory=dict)
    occurred_at: str = field(default_factory=_now)
    id: str = field(default_factory=_uuid)
    created_at: str = field(default_factory=_now)

    def __post_init__(self):
        if self.event_type not in VALID_HISTORY_EVENT_TYPES:
            raise ValueError(
                f"Invalid history event_type '{self.event_type}'. "
                f"Must be one of {VALID_HISTORY_EVENT_TYPES}"
            )

    def to_db_row(self) -> dict:
        import json
        return {
            "id":             self.id,
            "problem_id":     self.problem_id,
            "domain":         self.domain,
            "event_type":     self.event_type,
            "occurred_at":    self.occurred_at,
            "week_key":       self.week_key,
            "opportunity_id": self.opportunity_id,
            "metadata":       json.dumps(self.metadata, default=str),
            "created_at":     self.created_at,
        }

    @classmethod
    def from_db_row(cls, row) -> "ProblemHistoryEvent":
        import json
        return cls(
            id=row["id"],
            problem_id=row["problem_id"],
            domain=row["domain"],
            event_type=row["event_type"],
            occurred_at=row["occurred_at"],
            week_key=row["week_key"] or "",
            opportunity_id=row["opportunity_id"] or "",
            metadata=json.loads(row["metadata"] or "{}"),
            created_at=row["created_at"],
        )


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
    problem_id: str = ""        # canonical Problem this observation is linked to (see canonicalizer.py)

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
            "problem_id": self.problem_id,
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
