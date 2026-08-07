# RFC-002 — Investigation Findings: Data Contract and Facet Architecture

Status: Proposed — awaiting decision

Date: 2026-08-05

Depends on: RFC-001 (Accepted) — this document resolves several questions RFC-001 deliberately left open

Scope: architecture only — responsibilities, boundaries, data flow, contracts, integration points. No code, no schema DDL, no implementation sequencing.

---

# 1. Why This Artifact, Why Now

RFC-001 established Investigation as a constitutional stage but deliberately left its output as a description ("a first-class artifact... Investigation Findings") without a contract. Of every stage in the accepted pipeline, Investigation is the only one with no existing implementation home — Collection, Processing, Correlation, Problem, Analysis (today, conflated with evidence-gathering in `scorer.py`), Opportunity, Advisory, and Presentation all map onto real code. Analysis's redefinition under RFC-001 (consuming Findings rather than re-deriving evidence itself) cannot be meaningfully specified until Findings have a contract. This is the critical-path item.

This RFC resolves three questions RFC-001 explicitly deferred:
- The concrete shape of Investigation Findings.
- Whether Findings are an immutable dated snapshot or a mutable accumulating object.
- Where the evidence actually comes from, given "no new tables" hasn't been decided either way.

## 1.1 Stage vs. artifact naming

`Investigation` is the stage (the transformation); `Findings` is what it produces (the noun-output), the same relationship `Collection` has to `Signal` and `Processing` has to `Knowledge`. This is a deliberate departure from how `Problem` and `Opportunity` are named in RFC-001, where the stage and its artifact share one name — Investigation's output needed its own distinct name precisely because "an Investigation" and "a Problem" don't mean the same kind of thing the way "a Problem" and "a Problem" trivially do. The local flow through this segment of the pipeline:

```
Problem
   ↓
Investigation   (the stage — performs research)
   ↓
Findings        (the artifact — evidence-backed understanding, no scores)
   ↓
Analysis        (the stage — forms a judgment from Findings)
   ↓
Opportunity
```

---

# 2. Responsibility, Restated Precisely

Investigation produces exactly one artifact per invocation: Investigation Findings, bound to one `Problem`, containing evidence-backed understanding across seven independent facets. Nothing else. The constitutional invariant from RFC-001 governs this document as strictly as it governs the stage itself: **no scores, no rankings, no recommendations, no opportunities — evidence and characterization only.**

---

# 3. Structural Design Principles

Four principles, established here because they shape every decision below.

## 3.1 The invariant is enforced by shape, not by discipline

A convention that says "don't put a score here" is weaker than a data contract that has no field capable of holding one. Findings' structure should make a numeric score, rank, or verdict *inexpressible*, not merely discouraged. Concretely: no facet has a field named or shaped like `score`, `rank`, `priority`, or `confidence` (confidence belongs to Analysis, which computes it *from* Findings' evidence density — it does not exist yet at Investigation time). This is the same discipline already used elsewhere in this project — `Signal` has no field for a derived judgment either; judgments live downstream of the objects they're computed from.

## 3.2 Facets are independent

No facet reads another facet's output. Each is computed from the same two inputs (`Problem`, connected `Knowledge`) in isolation. This mirrors `scorer.py`'s own seven scoring dimensions, which are already independent functions today — reusing a pattern already proven in this codebase rather than inventing a new one. Independence also means facets can be evaluated selectively or in any order without redesigning the contract later (a real, near-term need — see §6).

## 3.3 An empty facet is a finding, not an absence

If a Problem's connected Knowledge contains no pricing-related entities, the Pricing facet should report that explicitly — "no pricing evidence found" — not be omitted or left null. This is the same principle already applied to zero-opportunity reports this session ("a report should always be generated... with an explanation of the current intelligence state"). An honest, evidence-backed "we don't know" is itself understanding; silently skipping a facet is not.

## 3.4 Investigation does not re-derive evidence Processing already owns

Investigation's inputs are `Problem` and connected `Knowledge` (Entity/Relationship) — never raw `Signal` text directly. If Investigation re-scanned Signal text with its own keyword logic, it would blur into Processing's territory and duplicate extraction work that already has an owner. Every facet is bounded by what the knowledge graph already captures. Where that coverage is currently thin (see §5), that's a stated limitation, not a reason to reach around Processing.

---

# 4. The Shape of Findings

Every facet shares one minimal common structure, so Analysis can consume all seven uniformly rather than handling seven bespoke shapes:

- **Evidence items** — each traceable to a specific `Entity`, `Relationship`, or `problem_history` event. Traceability is not optional: every claim in a facet must resolve back to something inspectable, the same explainability standard already enforced everywhere else in this platform (`DimensionExplanation` in the scorer, match reasons in `find_match()`).
- **Coverage characterization** — a qualitative, evidence-derived statement of how much is known (e.g., "three independent sources, over two weeks" vs. "one mention, no corroboration"), never a numeric score. This is descriptive density, not judgment.
- **Explicit absence marker** — present and populated even when a facet has nothing, per §3.3.

The seven facets (Customer, Solution, Competitor, Pricing, Trend, Regulation, Technology) each add facet-specific evidence fields on top of this shared shape — not specified further here, since the specific evidence vocabulary per facet is closer to implementation detail than architecture, and should be designed against real data once this contract is approved.

---

# 5. Where Evidence Comes From — Mapped Against What Already Exists

Per §3.4, every facet draws from the existing knowledge graph. Checked against `knowledge_graph/schema.py`'s actual `ENTITY_TYPES`, coverage is uneven — stated honestly rather than assumed uniform:

| Facet | Existing coverage | Assessment |
|---|---|---|
| Technology | `technology`-typed entities (direct) | Strong — this facet can be populated immediately |
| Regulation | `regulation`-typed entities (direct) | Strong |
| Customer | `market`-typed entities + demand-related relationships | Partial — usable now, room to deepen |
| Solution | `technology` + `skill`-typed entities | Partial — usable now |
| Trend | Derived from reference-recency patterns (schema v8 decay) + `Problem.trend` as one input signal, not a duplicate of it | Partial, and structurally distinct from `Problem.trend` (RFC-001 §3.5 already resolved this is a market-level signal, computed independently) |
| Competitor | Weak — no first-class competitor concept exists (RFC-001 §3.6 deliberately kept it that way) | Evidence-thin until entity/relationship extraction around competing products improves. Not blocking — an honest thin facet (§3.3) is a valid output, not a defect. |
| Pricing | No dedicated entity type exists today | Weakest facet at present. Options are either a future entity-type addition (out of scope for this RFC) or accepting a narrative-only, low-confidence facet initially. Recommendation: ship with the latter rather than block this RFC on a knowledge-graph extension that deserves its own review. |

This table is itself an architectural output, not a side note: it tells a future implementer exactly where Investigation can start strong and where it will need Processing-layer investment later — the same "explain exactly where information is lost" discipline already applied to this project's own bug investigations.

---

# 6. Lifecycle of the Artifact — Resolving RFC-001's Open Question

RFC-001 explicitly deferred whether Findings are immutable-dated (like `Opportunity`) or mutable-accumulating (like `Problem`). Resolved here:

**Recommendation: immutable and dated — one set of Findings per Problem per Investigation cycle — mirroring `Opportunity`'s shape, not `Problem`'s.**

Reasoning, argued from the same distinction `04_DATA_MODEL.md`'s Historical Evolution section already establishes: Findings represent an *observation* of market conditions at a point in time, not a persistent *identity*. `Problem` legitimately has one current state because it represents one enduring thing; Findings capture what was true about the market *when the Investigation ran*, and market conditions genuinely change. Overwriting prior Findings would discard exactly the kind of evidence trail this platform has consistently chosen to preserve elsewhere (`problem_history`, decay's never-delete principle, `Opportunity` immutability itself). Each Investigation cycle produces its own dated Findings for the same Problem, accumulating the same way successive Opportunities do — none of them rewritten.

This also gives Analysis something Analysis needs but doesn't have today: the ability to compare *this cycle's* market understanding against the *prior* cycle's, the same way `build_historical_comparison()` already compares week-over-week Opportunity scores. That comparison is out of scope for this RFC, but immutability is what makes it possible later without a redesign.

---

# 7. Integration Points

## 7.1 Pipeline position

Investigation sits between Problem resolution and Analysis's scoring pass — conceptually, where `scorer.py`'s keyword-counting currently happens inline. This RFC does not specify how that insertion happens in `pipeline.py`; it specifies that Analysis's new input contract (§7.2) is what changes, and everything upstream of Investigation is unaffected.

## 7.2 Boundary with Analysis

Analysis consumes **only** Investigation Findings (plus `Problem`'s own already-existing scoring-relevant fields, e.g. `weeks_seen`) — never `Knowledge` or `Signal` directly. This is a deliberate layering constraint, not an incidental one: if Analysis could reach around Findings back into the knowledge graph, the Investigation/Analysis boundary RFC-001 identifies as its central contribution would be optional rather than structural. Findings must be complete enough that Analysis never needs to.

## 7.3 Consequence for existing code (stated, not planned)

`scorer.py`'s keyword-counting logic (`DEMAND_KEYWORDS`, `WILLINGNESS_TO_PAY`, `LOW_COMPETITION_SIGNALS`, `RISK_KEYWORDS` — see §5 of RFC-001 and this session's earlier keyword-matching consolidation) is the evidence-gathering half of what Investigation's facets should become; the weighting/scoring half stays in Analysis. This is a consequence worth naming now so a future implementer doesn't have to rediscover it, but the actual migration is explicitly out of scope until this contract is approved.

## 7.4 Boundary with Problem (restated)

Unchanged from RFC-001: read-only. Investigation Findings reference a `Problem` by identity; they never write to it.

---

# 8. What This RFC Does Not Decide

- The exact facet-specific evidence fields beyond the shared minimal shape (§4) — deserves design against real data, not armchair specification.
- Whether Investigation runs for every Problem every cycle or selectively (RFC-001's open question, still open — a cost question, not an architecture question).
- Whether Pricing's evidence gap (§5) is eventually closed by a new entity type — a Processing-layer question for its own future review, not this one.
- Any code, storage mechanism, or migration sequencing.

---

# 9. Status

Proposed. Requires acceptance before Analysis's contract is redefined or any Investigation-adjacent implementation begins.
