"""
domains/base.py — Platform domain interface

Every intelligence domain is described by a DomainConfig instance composed
from the types defined here. The core platform engine interacts with all
domains exclusively through this interface.

No core file ever imports from a specific domain package (domains.business,
domains.cybersecurity, etc.). All access goes through DomainRegistry.

Adding a new domain requires:
  1. Create domains/<name>/ with the required modules.
  2. Instantiate DomainConfig from those modules.
  3. Call DomainRegistry.register(config) in __init__.py.
  4. No changes to the core engine are required.

Type hierarchy:
  DomainMetadata        identity + UI fields
  DomainSources         data collection configuration
  DomainKeywords        generic keyword signal sets
  EntityType            knowledge graph node type (frozen)
  RelationshipType      knowledge graph edge type (frozen)
  DomainKnowledgeGraph  graph vocabulary for this domain
  ScoringDimension      one scoring axis with weight + keywords
  ScoringThresholds     composite score tier boundaries (frozen)
  DomainScoring         complete scoring profile
  ReportSection         one section in a report template (frozen)
  DomainReporting       report template configuration
  DomainConfig          composed root — the full domain contract
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import NamedTuple


# ── Identity ──────────────────────────────────────────────────────────────

@dataclass
class DomainMetadata:
    """
    Identity and UI metadata for a domain.

    icon     — Tabler Icons name (https://tabler.io/icons), e.g. "briefcase".
               The frontend uses this to render domain icons without hardcoding.

    color    — Primary hex colour for this domain in the UI, e.g. "#534AB7".
               Used for domain badges, navigation indicators, and charts.

    category — Broad grouping for multi-domain views:
               "business" | "security" | "technical" | "financial" | "custom"
    """
    id:           str    # machine-readable slug, e.g. "business"
    name:         str    # human-readable short name, e.g. "Business Intelligence"
    description:  str    # one-sentence description
    version:      str    # semantic version, e.g. "1.0.0"
    icon:         str    # Tabler icon name
    color:        str    # primary hex colour
    category:     str    # broad grouping for UI filtering


# ── Collection ────────────────────────────────────────────────────────────

class RSSFeed(NamedTuple):
    """A configured RSS/Atom source."""
    url:         str
    description: str


@dataclass
class DomainSources:
    """
    Data source configuration for a domain.

    reddit_sources — subreddit names without the r/ prefix.
                     The core Reddit collector reads these at collection time.

    rss_feeds      — RSS/Atom feeds this domain monitors.
                     The core RSS collector fetches these.

    Shared collectors (Hacker News) run at the platform level and produce
    signals that every active domain processes. They are not configured here.
    Domain-specific API collectors (e.g. NVD for cybersecurity) will be
    added to this class in a future milestone.
    """
    reddit_sources: list[str]    = field(default_factory=list)
    rss_feeds:      list[RSSFeed] = field(default_factory=list)


# ── Keywords ──────────────────────────────────────────────────────────────

@dataclass
class DomainKeywords:
    """
    Generic keyword signal sets.

    Categories are intentionally domain-neutral so that every domain
    can assign its own semantic meaning to each group.

    Four named keyword sets. The core engine assigns no meaning to
    these names — each domain decides what belongs in each set and
    how its own processing logic consumes them.

    Common uses within a domain module:
      - collector-level signal tagging
      - entity extraction hints
      - relevance pre-filtering before scoring

    Scoring dimensions carry their own independent positive_keywords
    and negative_keywords and do not source values from here.
    Keeping these concerns separate makes each scoring dimension
    self-contained and easier to reason about in isolation.

    All values are matched case-insensitively against signal text.
    """
    include:  frozenset[str] = field(default_factory=frozenset)
    exclude:  frozenset[str] = field(default_factory=frozenset)
    boost:    frozenset[str] = field(default_factory=frozenset)
    priority: frozenset[str] = field(default_factory=frozenset)


# ── Knowledge graph ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class EntityType:
    """
    A node type in the knowledge graph.

    keywords: lowercase strings the extractor scans for in signal text.
              Terms of 4 characters or fewer use whole-word matching
              (prevents "AI" matching "MAIL", "api" matching "rapid", etc.)
    """
    name:        str
    description: str
    keywords:    tuple[str, ...]


@dataclass(frozen=True)
class RelationshipType:
    """A directed edge type between two entity nodes."""
    name:        str
    description: str
    valid_from:  tuple[str, ...]   # entity type names that may be the source
    valid_to:    tuple[str, ...]   # entity type names that may be the target


@dataclass
class DomainKnowledgeGraph:
    """
    Knowledge graph vocabulary for a domain.

    entity_types       — node types this domain tracks.
    relationship_types — edge types between those nodes.
    display_names      — maps lowercase keyword → canonical display form.
                         e.g. {"llm": "LLM", "saas": "SaaS"}
                         Used for presentation; falls back to title-case.
    """
    entity_types:       dict[str, EntityType]       = field(default_factory=dict)
    relationship_types: dict[str, RelationshipType] = field(default_factory=dict)
    display_names:      dict[str, str]              = field(default_factory=dict)

    def get_display_name(self, keyword: str) -> str:
        """Return the canonical display form for a keyword string."""
        return self.display_names.get(keyword.lower(), keyword.title())


# ── Scoring ───────────────────────────────────────────────────────────────

@dataclass
class ScoringDimension:
    """
    One axis of the scoring model for a domain.

    The scoring engine iterates over the domain's dimensions and computes
    a score for each based on keyword presence and signal properties.
    It does not know whether a dimension represents "demand", "severity",
    "exploitability", or anything else — that is the domain's concern.

    id              — machine-readable identifier, unique within the domain.
                      e.g. "demand", "severity", "exploitability"

    label           — human-readable name for UI display.
                      e.g. "Market Demand", "Severity", "Exploitability"

    description     — one sentence explaining what this dimension measures.

    weight          — this dimension's contribution to the composite score.
                      All dimension weights in a DomainScoring must sum to 1.0.

    positive_keywords — presence boosts this dimension's score.
    negative_keywords — presence reduces this dimension's score.

    Note: For Milestones 1–4, the core scorer still uses config.py values.
    In Milestone 5, it will be updated to consume these keyword sets directly.
    """
    id:                str
    label:             str
    description:       str
    weight:            float
    positive_keywords: frozenset[str] = field(default_factory=frozenset)
    negative_keywords: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class ScoringThresholds:
    """
    Composite score boundaries for tier classification.

    score >= high   → tier "high"   (e.g. Gold, Critical)
    score >= medium → tier "medium" (e.g. Silver, High)
    score < medium  → tier "low"    (e.g. Bronze, Informational)

    Labels are domain-neutral so the same engine serves both
    business ("Gold") and security ("Critical") contexts.
    The frontend maps tier strings to domain-appropriate labels.
    """
    high:   float = 8.0
    medium: float = 6.5


@dataclass
class DomainScoring:
    """
    Complete scoring profile for a domain.

    dimensions — the axes the engine scores each signal cluster on.
                 Order determines display order in reports and UI.

    thresholds — composite score boundaries for tier classification.
    """
    dimensions: list[ScoringDimension]    = field(default_factory=list)
    thresholds: ScoringThresholds         = field(default_factory=ScoringThresholds)

    def validate(self, domain_id: str) -> None:
        """
        Verify dimension weights sum to 1.0.
        Called by DomainRegistry.register() before accepting a domain.
        """
        if not self.dimensions:
            raise ValueError(f"[{domain_id}] DomainScoring must define at least one dimension")

        total = sum(d.weight for d in self.dimensions)
        if abs(total - 1.0) > 1e-9:
            raise ValueError(
                f"[{domain_id}] ScoringDimension weights sum to {total:.8f}; must equal 1.0"
            )

        ids = [d.id for d in self.dimensions]
        if len(ids) != len(set(ids)):
            duplicates = {x for x in ids if ids.count(x) > 1}
            raise ValueError(
                f"[{domain_id}] Duplicate ScoringDimension ids: {sorted(duplicates)}"
            )

    @property
    def weights(self) -> dict[str, float]:
        """Return dimension weights as a dict, keyed by dimension id."""
        return {d.id: d.weight for d in self.dimensions}


# ── Reporting ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ReportSection:
    """
    One section in a report template.

    id    — machine-readable identifier, e.g. "executive_summary".
    title — display title, e.g. "Executive Summary".
    order — ascending sort order for rendering.
    """
    id:    str
    title: str
    order: int


@dataclass
class DomainReporting:
    """
    Report template configuration for a domain.

    title       — heading for generated reports.
    description — one sentence describing what this report covers.
    sections    — ordered list of sections the report template renders.
                  The reporting engine builds each section in order.
                  Unknown section ids are skipped gracefully.
    """
    title:       str
    description: str
    sections:    list[ReportSection] = field(default_factory=list)


# ── Domain configuration contract ─────────────────────────────────────────

@dataclass
class DomainConfig:
    """
    Complete domain contract. One instance per domain, registered at startup.

    The core platform engine interacts with domains exclusively through this
    interface. No core file ever imports from a specific domain package.

    Sub-objects and their responsibilities:
      metadata  — identity + UI fields (icon, color, category)
      sources   — Reddit subreddits + RSS feeds this domain monitors
      keywords  — four generic signal categories (include/exclude/boost/priority)
      graph     — entity types + relationships + display names
      scoring   — dimensions with weights, thresholds
      reporting — report title, description, ordered sections

    Usage (from a domain's __init__.py):
        from domains.registry import DomainRegistry
        config = DomainConfig(metadata=..., sources=..., ...)
        DomainRegistry.register(config)
    """

    metadata:  DomainMetadata
    sources:   DomainSources
    keywords:  DomainKeywords
    graph:     DomainKnowledgeGraph
    scoring:   DomainScoring
    reporting: DomainReporting

    # ── Convenience accessors ─────────────────────────────────────────────

    @property
    def id(self) -> str:
        """The domain's unique identifier. Use this as the DB domain tag."""
        return self.metadata.id

    @property
    def name(self) -> str:
        """Human-readable domain name."""
        return self.metadata.name

    # ── Validation ────────────────────────────────────────────────────────

    def validate(self) -> None:
        """
        Verify internal consistency. Called by DomainRegistry.register().
        Raises ValueError with a descriptive message on any violation.
        """
        _id = self.metadata.id

        if not _id:
            raise ValueError("DomainMetadata.id must not be empty")

        if not _id.replace("_", "").isalnum():
            raise ValueError(
                f"DomainMetadata.id must be alphanumeric (underscores allowed), "
                f"got: {_id!r}"
            )

        if not self.metadata.name:
            raise ValueError(f"[{_id}] DomainMetadata.name must not be empty")

        if not self.metadata.color.startswith("#") or len(self.metadata.color) != 7:
            raise ValueError(
                f"[{_id}] DomainMetadata.color must be a 7-character hex string "
                f"(e.g. '#534AB7'), got: {self.metadata.color!r}"
            )

        self.scoring.validate(_id)
