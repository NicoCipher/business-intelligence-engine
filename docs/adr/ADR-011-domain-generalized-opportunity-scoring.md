# ADR-011 — Domain-Generalized Opportunity Scoring

Version: 1.0

Status: Accepted

Date: 2026-08-10

Supersedes: None

---

# Context

`domains/base.py` (`DomainConfig.scoring: DomainScoring`) has existed since the domain architecture was introduced, specifically to let each domain define its own scoring dimensions, weights, and thresholds. It has never been consumed. An audit of what would be required to add a second domain found that `OpportunityScorer`, `OpportunityScores`, `config.SCORE_WEIGHTS`/`TIER_GOLD`/`TIER_SILVER`, and `api/opportunities.py`'s tier calculation are all hardcoded to Business's specific seven dimensions, in four independent places, none of which read `DomainConfig.scoring`. A second domain could be fully registered and still silently score through Business's vocabulary and thresholds.

This ADR locks the design for closing that gap, following the proposal reviewed and approved in principle. It records the decision; it does not implement it.

---

# Problem

`OpportunityScores` is a dataclass with seven fixed fields (`demand`, `competition`, `revenue_potential`, `execution_difficulty`, `time_to_revenue`, `risk`, `confidence`). `composite()` and `tier()` read `config.SCORE_WEIGHTS`/`TIER_GOLD`/`TIER_SILVER` directly. `api/opportunities.py` independently re-derives tier from hardcoded `8.0`/`6.5` literals rather than calling either of the above. None of these three sites are reachable from a `DomainConfig`.

A second complication, found during design rather than the original audit: not every dimension can be reduced to configuration. `_demand`, `_revenue_potential`, `_risk` are keyword-presence checks and generalize cleanly to data. `_execution_difficulty`, `_time_to_revenue`, `_confidence` encode procedural reasoning over signal structure (engagement, source diversity, signal count) that a keyword list cannot express. Any design that assumes dimensions are uniformly data-driven cannot actually represent Business's own current scoring model.

---

# Decision

**`OpportunityScores` becomes dimension-set-driven, not dimension-count-fixed:**

- `dimensions: dict[str, float]` replaces the seven fixed fields. Dimension ids come from the active domain's `DomainScoring.dimensions`, never hardcoded in `models.py`.
- `explanations: dict[str, DimensionExplanation]` and `evidence_count: int` are unchanged — already domain-neutral.
- `composite()` and `tier()` take the domain's `DomainScoring` (weights + `ScoringThresholds`) as an explicit argument. Nothing in `models.py` imports `config.SCORE_WEIGHTS`/`TIER_GOLD`/`TIER_SILVER` after this change.

**Two-tier dimension computation**, both registered on `DomainScoring`, both feeding the same `dimensions` dict:

- **Tier 1 (data-driven):** a dimension fully defined by `positive_keywords`/`negative_keywords`. Computed by one shared engine method, reusable by any domain with zero new code.
- **Tier 2 (computed):** a dimension requiring signal-structure logic. `DomainScoring`'s per-dimension entry carries an optional registered `compute_fn`. Business's `execution_difficulty`, `time_to_revenue`, `confidence` migrate here as thin wrappers around their existing, unchanged logic — the logic doesn't move, only where it's registered from.

**Serialization shape does not change.** `to_dict()` stays a flat dict — dimension ids as top-level keys, alongside `evidence_count`/`composite`/`tier`/`explanations` — identical to today's shape. This is what makes every existing `opportunities.scores` row readable by `from_dict()` with zero backfill.

**`api/opportunities.py`'s duplicate tier-threshold literals are removed**, replaced with a call through the same domain-supplied `ScoringThresholds` used by `OpportunityScores.tier()`. This is in scope, not a follow-on — an unfixed fourth hardcode site would silently mislabel a second domain's opportunities even after every other site is fixed.

---

# Alternatives Considered

**Alternative 1 — Fully data-driven (config-only, no `compute_fn`).** Rejected. Cannot represent Business's own `execution_difficulty`/`time_to_revenue`/`confidence` logic, which is structural, not keyword-based. Would force those three into either a lossy keyword approximation or leaving Business as a hardcoded exception to the "generalized" model — the second of which is what's being fixed.

**Alternative 2 — Nested serialization (`{"dimensions": {...}, ...}`).** Rejected. Cleaner in isolation, but breaks `from_dict()` compatibility with every existing row and every existing `scores.get(key, ...)` call site in `explainer/opportunity.py` — would require a data migration for no behavioral gain.

**Alternative 3 — Keep the fixed dataclass, add an optional per-domain extra-fields dict alongside it.** Rejected. Reintroduces exactly the hardcoding this decision exists to remove — Business's seven fields would still be structurally privileged over any other domain's dimensions.

**Alternative 4 (accepted) — Two-tier, dict-shaped, domain-owned weights/thresholds, flat serialization preserved.**

---

# Consequences

Positive:

- `DomainConfig.scoring` becomes load-bearing rather than validated-but-unused.
- Zero DB migration — `opportunities.scores` (`TEXT`) and `composite_score` (`REAL`) already support this shape.
- Business's numeric scoring behavior is unchanged; only where dimension ids, weights, and thresholds are sourced from changes.
- Closes all four hardcode sites found in the audit (`scorer.py`, `models.py`/`config.py`, `api/opportunities.py`) in one coordinated change rather than piecemeal.

Trade-offs:

- `test_scorer.py` (33 tests) and `test_scoring_explanations.py` (15 tests) — 48 call sites total — move from `.demand`/`.competition` attribute access to `.dimensions["demand"]` dict access. Mechanical; sampled assertions are relational, not exact-value pegs.
- Tier 2's `compute_fn` is a new extension point with no second real user yet — justified only because Business's own model cannot be expressed without it (see Problem), not spectulative.

---

# Architectural Impact

This decision is scoped to storage, composite/tier calculation, and dimension registration. It explicitly does **not** generalize:

- **Advisory/narrative logic** (`explainer/opportunity.py`, `explainer/watch_list.py`) — `_DIMENSION_LABELS`, `_market_gap`, `_time_to_first_revenue`, and similar helpers stay hardcoded to Business's seven dimensions and their specific meanings. Narrative generation for a second domain is a separate, later design, deferred until a real second domain's narrative needs are known — consistent with this project's standing discipline against speculative architecture (relationship hierarchy, Feedback in RFC-001, entity confidence scoring were all deferred on the same basis).
- **`detector.py`'s cluster-acceptance gate** — whether a signal cluster is even considered a scoring candidate is currently gated on Business-specific demand/complaint/willingness-to-pay keyword presence (Correlation-stage logic, RFC-001 §2.4). Untouched by this decision.

**RFC-001 interaction:** §2.7 (Analysis) currently describes its output as "the seven-dimension composite score." That phrasing is stale once this ADR is implemented and needs an explicit addendum at that section — not a silent gap, and not a reopening of RFC-001's accepted boundaries, since the Investigation/Analysis boundary itself (§3.3) is unaffected. Precedent: ADR-006/007 were corrected via superseding ADRs rather than silent edits; the same discipline applies here as an addendum rather than a RFC-001 rewrite.

**Sequencing:** this decision should be implemented before RFC-001's Investigation stage, if that work begins. Implementing Investigation first would change Analysis's input contract (Findings, not raw signals) and output contract (domain-dynamic dimensions) simultaneously — this ADR removes one of those two moving parts in advance.

---

# Current Implementation

None yet. This ADR locks the design; implementation is future work, tracked separately. No code, schema migration, or test changes are part of this decision.

---

# Future Evolution

A second domain's actual `compute_fn` implementations and dimension vocabulary are explicitly out of scope here — real domain-expertise work belonging to whoever builds that `DomainConfig`, not fabricated in advance. If a future Tier-2 dimension needs data not currently on `Signal`/`Entity`/`Relationship` (e.g., CVSS-adjacent fields for a cybersecurity `severity` dimension), that is its own schema decision, made when a real domain needs it — not pre-built speculatively by this ADR.

---

# Related Decisions

Depends on:

- ADR-003 — Domain-Scoped Knowledge Graph (establishes the domain-isolation precedent this decision extends into scoring)

Interacts with:

- RFC-001 — Constitutional Analyst Pipeline (§2.7 requires an addendum once this ADR is implemented; §3.3's Investigation/Analysis boundary is unaffected)

Distinct from (do not conflate):

- `explainer/*` narrative logic, `detector.py`'s acceptance gate — both explicitly out of scope, see Architectural Impact

---

# References

Architecture Handbook

- `docs/architecture/platform/12_DOMAIN_ARCHITECTURE.md`

Implementation Documentation

- `docs/HANDOFF.md` (Part 4 — Future Roadmap)
- `docs/rfc/RFC-001-constitutional-architecture-transition.md` (§2.7, §3.3)

---

# Status

Accepted.

Design and invariants are locked. Implementation has not started. Any implementation must preserve: dynamic `OpportunityScores.dimensions`, flat JSON serialization compatibility, domain-owned weights/thresholds via `DomainScoring`, the Tier-2 `compute_fn` extension point, and the explicit boundary excluding `explainer/*` and `detector.py` from this decision's scope.
