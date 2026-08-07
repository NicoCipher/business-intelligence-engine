# RFC-001 — Transition to the Constitutional Analyst Pipeline

Status: Accepted

Date: 2026-08-05

Supersedes: `docs/architecture/00_ARCHITECTURE_SPECIFICATION.md` §5 (the six-layer model)

Depends on / must reconcile with: ADR-001, ADR-002, ADR-005, ADR-010, `09_VALIDATION_INTELLIGENCE.md`, `11_AGENT_ARCHITECTURE.md`

---

# 1. Context

BIA's constitutional architecture (`00_ARCHITECTURE_SPECIFICATION.md` §5) defines six layers: `Signal → Knowledge → Problem → Opportunity → Intelligence → Presentation`. This was written before the platform's own framing of itself — "a digital intelligence analyst" (already present in this project's own tradecraft-oriented architecture review) — was taken to its logical conclusion.

A linear, terminating pipeline is a correct model of *one report cycle*. It is not a correct model of an analyst who never stops investigating, because nothing in it explains why the next cycle should look any different from this one, or where "what should we even be looking at" comes from in the first place.

This RFC proposes a replacement constitutional pipeline, arrived at through several rounds of first-principles review, reconciliation against existing documentation, and resolution of every naming and boundary ambiguity found along the way.

---

# 2. The Proposed Constitutional Pipeline

```
Direction
   ↓
Collection
   ↓
Processing
   ↓
Correlation
   ↓
Problem
   ↓
Investigation
   ↓
Findings
   ↓
Analysis
   ↓
Opportunity
   ↓
Advisory
   ↓
Presentation
   ↺
Feedback  (closes back to Direction)
```

Eleven stages, ten forward transitions, one closing edge. `Findings` is shown as its own line because, unlike every other artifact in this diagram, it doesn't share a name with the stage that produces it (`Investigation` produces `Findings`; `Correlation` produces candidate clusters but isn't itself shown as an artifact node, since — unlike Findings — nothing downstream needs to address it by name independently of the stage that made it). It is an artifact, not a twelfth stage — see §2.6.

**Naming principle governing every stage below:** a stage name is a verb describing a transformation; its output is a noun. This pairing is the actual single-responsibility test used throughout this document — a stage whose name can't cleanly pair with one clear noun-output is either doing more than one job or has the wrong name. (Data-model nouns — Signal, Knowledge, Problem, Findings, Opportunity — are what's persisted or produced; stage names describe the transformation that produces them.) Each stage is defined below by: single responsibility, input, output, and its boundary with its neighbors.

## 2.1 Direction

**Responsibility:** decide what to investigate, and why.

**Input:** accumulated understanding from prior cycles (via Feedback); human-set investigative goals.

**Output:** a `Mandate` — collection scope, keyword vocabulary, source list, monitoring schedule, active domains.

**Reality check:** this is not new territory. `Domain`/`DomainConfig` (schema v5+) already encodes most of this — a distinct investigative purpose, its own keyword vocabulary, its own scoring weights, per domain. What's missing is unifying scattered collection-scope details (currently split across `config.py` constants and hardcoded collector classes) into one explicit, named concept, and — separately, see Feedback below — making that concept responsive to what the system learns rather than static.

**Boundary with Collection:** Direction decides *what and where*; Collection actually does the gathering. Direction produces no signals itself.

## 2.2 Collection

**Responsibility:** gather raw signals per the current Mandate.

**Input:** `Mandate` (from Direction).

**Output:** `Signal` (immutable, append-only — unchanged from the current model, ADR-verified).

**Reality check:** maps directly onto the existing `collectors/` package and `pipeline.py` Stage 1. No conceptual change.

## 2.3 Processing

**Responsibility:** structure raw signal text into usable form.

**Input:** `Signal`.

**Output:** `Knowledge` — Entity and Relationship, domain-scoped, lifecycle-decayed (schema v8).

**Reality check:** maps directly onto `knowledge_graph/extractor.py` and `pipeline.py` Stage 2 (+ Stage 2.5 decay). No conceptual change. `Knowledge` is deliberately *not* a standalone pipeline stage of its own in this model — it's Processing's noun-output, consumed downstream by both Correlation and Investigation rather than flowing through one strict next pipe. That's a more honest representation of the current codebase than the old model's implied strict linearity.

## 2.4 Correlation

**Responsibility:** recognize candidate patterns in current signal/knowledge — ephemeral, not yet committed to anything.

**Input:** `Signal` + `Knowledge` (current batch).

**Output:** candidate clusters (not persisted as such — `RejectedCluster` / accepted-cluster objects, matching `PatternDetector`'s existing behavior).

**Boundary with Collection:** Collection gathers from the *outside world*; Correlation finds patterns *within what's already gathered*. Different direction of information flow entirely — no risk of conflation between the two names, unlike the earlier "Discovery" naming this replaced (see Alternatives Considered).

**Boundary with Problem:** Correlation is ephemeral and per-run; Problem is where a correlated pattern becomes a persistent, canonical, cross-week identity. This is the existing, already-correct split between `PatternDetector`'s clustering and `canonicalizer.resolve_problem()`'s persistence — this RFC just names it as a constitutional boundary rather than leaving it implicit.

## 2.5 Problem

**Responsibility:** maintain the persistent, canonical identity of a recurring pattern.

**Input:** candidate clusters (from Correlation).

**Output:** `Problem` — stable identity, accumulated `entity_ids`, `problem_history` (schema v7), `lifecycle_state`/`trend` (schema v9).

**Reality check:** unchanged from the current model. This is the one stage with the least to reconcile — ADR-001, ADR-005, and ADR-010 already fully specify it.

## 2.6 Investigation

Fully specified above. Restated for completeness:

**Responsibility:** understand the market a Problem exists within, before any judgment is formed.

**Input:** `Problem` + connected `Knowledge`.

**Output:** `Investigation Findings` — a first-class, named artifact organized by facet (Customer, Solution, Competitor, Pricing, Trend, Regulation, Technology). Evidence and structured understanding, not scores. Naming this explicitly (rather than leaving it as an ad hoc "structured findings" description) matters for the same reason every other stage already has a named noun output: it makes the Investigation → Analysis boundary a concrete, citable interface rather than an implicit one, consistent with this platform's explainability standard — every judgment must trace to something inspectable, and an unnamed blob is harder to inspect than a defined artifact.

**Constitutional invariant:** *Investigation never produces scores, rankings, recommendations, or opportunities. It produces only evidence-backed understanding.* This is not a stylistic preference — it closes a specific, already-identified risk. `scorer.py` today already conflates evidence-gathering and scoring in one pass (count keywords, immediately compute a score); without this invariant stated explicitly, a future implementer moving fast could reintroduce exactly that conflation into Investigation "for convenience," silently collapsing the one boundary this RFC's design most depends on. This also mirrors real analytic tradecraft directly: raw collection and processing stay unscored and unbiased; ranking and judgment are analysis's job, kept institutionally separate so that premature conclusions never contaminate the evidence record. That's the same lens this project already chose for itself in framing BIA as an analyst, not an incidental parallel.

**Open question, deliberately not resolved here (architecture-only scope):** should Investigation Findings be an immutable, dated snapshot — one per Problem per cycle, mirroring `Opportunity`'s shape, so that as market conditions genuinely change over time, successive Findings preserve the evidence trail rather than overwriting understanding — or a single mutable object per Problem that accumulates and updates, mirroring `Problem`'s own current-state fields? Both are defensible; this RFC takes no position, since it's a real data-shape decision with implementation consequences, not a naming or boundary question. Whichever is chosen should be argued from the same immutable-observation-vs-mutable-identity distinction already established in `04_DATA_MODEL.md`'s Historical Evolution section, not decided by convenience.

**Boundary with Problem:** Investigation is strictly read-only with respect to Problem. It's triggered *by* a resolved Problem, consumes it as input, and never mutates it. Problem stays the canonical identity; Investigation produces a separate artifact *about* it.

**Boundary with Analysis:** this is the real, load-bearing distinction — **Investigation gathers evidence into Findings; Analysis weighs those Findings into a judgment.** The constitutional invariant above is what keeps this boundary from eroding over time. This is the same collection-vs-analysis distinction real tradecraft already draws (separate INT disciplines feeding all-source analysis), which is exactly the lens this project chose for itself — see §3.3.

## 2.7 Analysis

**Responsibility:** weigh Investigation's evidence into a scored, explainable judgment.

**Input:** `Problem` + the Findings Investigation produces.

**Output:** `OpportunityScores` — the seven-dimension composite score, confidence, verdict inputs. Not yet a persisted, canonical object.

**Boundary with Opportunity:** the real question this RFC has to answer, since the two could plausibly be one stage. Resolved below (§3.4): kept separate, because there's a genuine existing decision boundary between "a judgment was computed" and "that judgment cleared the bar to become a canonical, persisted record" (`MIN_COMPOSITE_TO_PERSIST`).

## 2.8 Opportunity

**Responsibility:** the gated decision to mint a judgment as a canonical, immutable, dated record.

**Input:** `OpportunityScores` (from Analysis) + the `Problem` it's linked to.

**Output:** `Opportunity` — immutable, one row per detection (ADR-002, unchanged).

**Boundary with Problem — explicitly restated, because this is where the earlier reconciliation found real risk:** an Opportunity remains a dated observation *of a Problem*. Investigation's market evidence is additional input consumed upstream by Analysis; it does not redefine what an Opportunity is "of." ADR-002 requires no amendment under this model.

## 2.9 Advisory

**Responsibility:** frame counsel for a human decision-maker.

**Input:** `Opportunity` (+ prior Opportunities on the same Problem, for trend/comparison).

**Output:** verdict (Build/Validate First/Monitor/Ignore), narrative explanation, closing synthesis.

**Reality check:** maps directly onto the now-split `explainer/` package (opportunity.py, watch_list.py, trends.py, historical.py, summary.py). No conceptual change — this RFC just gives that existing separation a constitutional name.

## 2.10 Presentation

**Responsibility:** deliver Advisory's content through some medium.

**Input:** Advisory's content.

**Output:** report, dashboard, API response.

**Boundary with Advisory, kept deliberately distinct rather than merged:** Advisory is *what to say*; Presentation is *how to say it, and through what channel*. A future API consumer might want Advisory's content without BIA's current report format — collapsing the two would foreclose that for no real savings today.

## 2.11 Feedback (closing edge)

**Responsibility:** evaluate what happened, and inform the next Direction.

**Input:** two already-partially-existing sources — human decisions on Opportunities (`Opportunity.status`, real today, human-curated) and later real-world outcome tracking (the existing, retrospective `09_VALIDATION_INTELLIGENCE.md` — its established meaning is fully preserved here, feeding Feedback rather than sitting as a pipeline stage of its own).

**Output:** informs the next cycle's `Mandate`.

**Honesty note, stated plainly rather than smoothed over:** this is the most speculative stage in the whole diagram, and the only one without a real implementation home today. Everything else above is a rename or resequencing of things that substantially exist. This is genuinely new. It belongs in the constitutional diagram regardless, because a diagram that omits it describes a system that runs once and stops — which isn't what's being built — but it should stay explicitly out of implementation scope until there's a concrete design for it, consistent with this project's standing discipline against building ahead of real need (relationship hierarchy, entity confidence scoring were both deferred on exactly this basis).

---

# 3. Conflicts From Prior Review, and Their Resolution

Every naming and boundary conflict identified during reconciliation is addressed here explicitly, not left implicit.

## 3.1 "Validation Intelligence" naming collision — resolved by design, not by renaming

The earlier Market Intelligence proposal risked a name collision (prospective vs. the existing retrospective meaning). This pipeline doesn't reuse the name as a stage at all — retrospective validation now has an explicit, correctly-scoped home: it's one of Feedback's two input sources. `09_VALIDATION_INTELLIGENCE.md` requires no rename and no amendment.

## 3.2 "Execution Intelligence" / "Gap Intelligence" — no longer present

Both names from the earlier proposal have been dropped in this redesign rather than renamed. No further action needed. Worth noting for the record: their disappearance is itself informative — they weren't earning distinct constitutional status once Investigation/Analysis were properly bounded.

## 3.3 Investigation vs. Analysis — the central boundary, restated as the RFC's core design decision

This is the single most important resolution in this document. Investigation and Analysis were at real risk of being either redundant or arbitrarily split. The resolution: **evidence-gathering is architecturally separate from judgment-forming**, mirroring real analytic tradecraft's own collection/analysis distinction, and mirroring a real, already-latent seam in the current codebase (`scorer.py` currently conflates both — count keywords, immediately score — this RFC's Investigation/Analysis split is what that conflation should become).

Two refinements make this boundary concrete rather than aspirational:

1. Investigation's output is a **named, first-class artifact** — `Investigation Findings` — not an ad hoc "findings" description. Analysis has exactly one well-defined thing to consume, not a fuzzy concept.
2. A **constitutional invariant** governs Investigation directly: *Investigation never produces scores, rankings, recommendations, or opportunities. It produces only evidence-backed understanding.* This is what prevents the boundary from eroding back into `scorer.py`'s current conflation the first time an implementer finds it convenient to compute "just one quick score" inside Investigation. Without a stated invariant, that erosion is exactly the kind of drift this project has already had to correct once (see the two ADRs superseded earlier this session for a materially similar failure mode — a boundary that existed in intent but was never stated precisely enough to survive contact with implementation).

## 3.4 Analysis vs. Opportunity — kept separate, on a real existing boundary

Resolved by identifying the actual decision point already in the code: `MIN_COMPOSITE_TO_PERSIST` is a real gate between "a score was computed" and "a canonical record was minted." Two stages, not one, on a boundary that already exists rather than one invented for this RFC.

## 3.5 "Trend" and "Technology" facets vs. existing `Problem.trend` and the `technology` entity type

Lower risk than originally assessed, because these are now sub-capability *facets within* Investigation, not standalone constitutional layers competing for the same name at the same level. Recommendation: keep both names, but document the relationship explicitly wherever Investigation is specified further — `Investigation.Trend` is market-level (is this whole category growing), `Problem.trend` is problem-level (is evidence for this specific pattern accelerating); the two may correlate but are computed independently. `Investigation.Technology` consumes and enriches existing `technology`-typed entities; it does not introduce a competing object.

## 3.6 "Competitor" facet vs. the prior explicit rejection of first-class Company/Competitor objects

**Still live, and this RFC takes a position rather than leaving it open.** The prior rejection ("BIA has never modeled real companies with independent lifecycle... kept as narrative-only callouts") should stand. `Investigation.Competitor`'s evidence should be built on the *existing* Entity/Relationship graph — richer, more rigorously evidence-accumulated treatment of competitor-type entities and their relationships to Problems — not a new first-class `Company` table with independent lifecycle. This satisfies the investigative need without reversing a deliberate prior decision. If real usage later proves this insufficient, that reversal should be its own RFC, argued on its own evidence, not a side effect of adopting this pipeline.

## 3.7 Root spec §5 amendment

This RFC, if accepted, requires amending `00_ARCHITECTURE_SPECIFICATION.md` §5 directly — the six-layer model is replaced by the eleven-stage model above. This is the correct scope for an RFC rather than an ADR: it changes the platform's most authoritative document, not one bounded decision. `03_SYSTEM_ARCHITECTURE.md` §4.3's "Intelligence Layer" (which pre-existing this RFC already disagreed with the root spec about) should be retired in favor of this document's stage definitions.

---

# 4. Alternatives Considered

Terminology is frozen as of this section. Future changes require a new RFC identifying a genuine architectural flaw, not a naming preference.

## 4.1 Investigation — retained, checked against eight alternatives

Evaluated against four criteria: single responsibility, unambiguous, scales to future capabilities, matches how a professional analyst actually works.

| Candidate | Verdict | Why |
|---|---|---|
| Research | Rejected | Too open-ended — connotes broad exploration (literature review), not focused inquiry into one specific Problem |
| Market Research | Rejected | Overloaded with a specific commercial meaning (surveys, primary data collection) BIA doesn't do — it synthesizes already-collected signals, passively. Also too narrow: Regulation and Technology facets aren't strictly market concerns |
| Examination | Rejected | Borrowed medical/legal register, inconsistent with the analyst framing used everywhere else |
| Inquiry | Rejected | Legal/journalistic register; reads passive and procedural rather than active-investigative |
| Assessment | Rejected for this stage | A real term of art, but for the *judgment* phase, not evidence-gathering — using it here would blur the exact boundary this RFC exists to establish |
| Evaluation | Rejected, more strongly | Same issue as Assessment, but self-contradictory: naming the evidence-only stage with a judgment-word directly conflicts with its own constitutional invariant ("no scores, no rankings, no recommendations") |
| Intelligence Gathering | Rejected | Doctrinally accurate in isolation, but reopens the "Intelligence" naming collision this RFC's own §3.1 (reconciliation) worked to retire |
| Diligence / Due Diligence | Rejected, closest contender | Real, established term (VC/PE), arguably domain-fitting — rejected because it imports a compliance/legal register this project hasn't used anywhere else, and sits against BIA's own stated identity as a continuously investigating analyst, not a checklist auditor |

`Investigation` wins on fit against every alternative, and pairs idiomatically with `Findings` in a way none of the others do ("investigation's findings" is an established, natural collocation; "assessment findings," "examination findings" read slightly off).

## 4.2 Findings — replaced "Investigation Profile"

`Investigation Profile` was the artifact's original name. Replaced because:

- **Investigation performs research; Findings are what that research produces.** The original name doubled the word "Investigation" across the stage and its artifact for no reason — `Collection` produces `Signal`, not "Collection Record"; `Processing` produces `Knowledge`, not "Processing Output." No other stage in this pipeline names its artifact after itself.
- **"Findings" directly encodes the constitutional invariant in its own meaning.** A finding is, definitionally, an observed fact — not a score, not a rank, not a recommendation. "Profile" carries no such restriction; a profile could easily contain a score (a "risk profile" commonly does), which is exactly the ambiguity this stage cannot afford given §2.6's invariant.
- **Matches analyst register precisely.** "The investigation's findings" is standard usage; "the investigation's profile" is not idiomatic in the same way.

## 4.3 Correlation — chosen over Discovery

Discovery was the original name for this stage. Rejected in favor of Correlation, for reasons stated most precisely as follows: **the stage isn't discovering anything in the human sense — it's performing a computational operation** (deduplicating, clustering, pattern-recognition, linking signals). A human analyst says *"we correlated multiple reports and identified an emerging problem,"* never *"we discovered multiple reports."* "Discovery" also carries product/sales-register connotations ("service discovery," "a discovery call") inconsistent with the analyst framing used everywhere else in this pipeline.

Correlation also produces a cleaner three-stage responsibility chain than Discovery did: **Processing transforms raw data into knowledge. Correlation transforms knowledge into candidate patterns. Problem persists the validated pattern.** Each of the three now has a unique, precise, non-overlapping responsibility, stated as a transformation rather than a vague activity — directly satisfying this RFC's own naming principle (§2: a stage name is a verb, its output is a noun) rather than just capability names.

---

# 5. Roadmap Impact

Checked against `docs/HANDOFF.md`'s current roadmap:

- **Item 5 (Problem Lifecycle & Trend, schema v9)** — already implemented, fully compatible with this model as-is. No rework required; `Problem.lifecycle_state`/`trend` remain exactly as built, now understood as belonging to the `Problem` constitutional stage.
- **Items 11–12 (Market Intelligence, deferred multiple times)** — this RFC is the formal, deliberate elevation of that deferred item, not a new idea. The prior deferrals were reasoned ("needs genuine trend-over-time analysis across weeks of entity data") — schema v7's `problem_history` and v9's `trend` machinery, both now real, are what makes this the right time; that reasoning should be stated explicitly if this RFC is accepted, not left implicit.
- **Item 6 (Evidence-quality weighting)** — becomes substantially subsumed by Investigation's structured evidence output; likely superseded rather than pursued as a separate item once Investigation exists, since "evidence quality" is precisely what Investigation's facets are meant to make explicit.
- **Item 7 (Relationship hierarchy)** — unaffected, remains independently gated on real multi-hop data.
- **Items 8–9 (`explainer.py` split, keyword consolidation)** — already completed this session; both map cleanly onto Advisory in this model with no rework.

## 5.1 Should "Opportunity Lifecycle" proceed before this exists?

No further work of that kind should proceed before this RFC is decided. There is no live "Opportunity Lifecycle" roadmap item distinct from the already-shipped Problem lifecycle (this was flagged as a terminology question in the earlier reconciliation and remains unresolved — worth confirming what, if anything, is still meant by that phrase before any further scheduling decision). Given Opportunity's boundary with Analysis is one of this RFC's central resolutions (§3.4), any Opportunity-level lifecycle work should wait until Investigation/Analysis are either adopted or explicitly rejected, since it would need to account for the same `MIN_COMPOSITE_TO_PERSIST`-style boundary either way.

---

# 6. What This RFC Does Not Decide

Deliberately left open, consistent with "architecture only, no implementation":

- Whether Investigation runs for every Problem every cycle, or selectively (a real cost question).
- Whether Investigation Findings are an immutable dated snapshot (mirroring `Opportunity`) or a mutable, accumulating object per Problem (mirroring `Problem`'s own current-state fields) — see §2.6.
- The concrete data shape of Investigation's findings (new tables vs. richer use of existing Entity/Relationship).
- Feedback's concrete implementation — this RFC only establishes that it belongs in the constitutional diagram, not how it's built.
- Whether `Investigation.Competitor`'s "richer entity/relationship treatment" is sufficient long-term, or whether a future RFC should reopen the first-class-Company question.

---

# 7. Status

Accepted. `00_ARCHITECTURE_SPECIFICATION.md` §5 is superseded by this document's constitutional pipeline. Implementation of any stage — including Investigation — requires its own architecture (see follow-on RFCs) before code begins.
