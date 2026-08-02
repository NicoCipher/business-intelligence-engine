# Schema History

This is the authoritative record of BIA-OS's SQLite schema versions. It
exists because `database.py`'s migration docstrings are the real source
of truth for *why* each change happened, but there was no single place
that summarized the sequence for someone starting a new session. This
file is that summary — for the full reasoning behind any one migration,
read the corresponding `_migrate_vN()` docstring in `backend/database.py`
directly; this file intentionally doesn't duplicate that reasoning in
full, only enough to orient.

Current version: **v9**. Defined by `database.SCHEMA_VERSION`.

---

## v1 — Initial schema

Signals, opportunities, reports. No domain concept, no knowledge graph,
no Problem identity. One global dataset.

## v2 — Domain column

Added a `domain` column (default `'business'`) to signals, opportunities,
and reports, ahead of the pipeline actually iterating multiple domains.

## v3 — Domain-aware uniqueness

`signals` dedup key changed from `(source, source_id)` to
`(source, source_id, domain)` — a shared collector (e.g. Hacker News)
needs to persist one independent copy per active domain, not one
globally. `reports` similarly moved from a `week_key`-only uniqueness to
`(week_key, domain)`, since the old constraint let a second domain's
report silently overwrite the first domain's report for the same week.

## v4 — Entity/relationship deduplication

Root cause fixed: `Entity.id`/`Relationship.id` are random UUIDs with no
other uniqueness constraint, so "dedup by type + name" in
`persist_results()` could never actually catch a true duplicate — every
extraction run added another row for the same conceptual entity. This
migration is a one-time cleanup (merge duplicate entities by
case-insensitive `(type, name)`, repoint relationships to the survivor,
merge colliding relationships summing `weight`) plus new unique indexes
that prevent recurrence going forward.

## v5 — Domain-scoped knowledge graph

Root cause fixed: `entities`/`relationships` had **no domain column at
all** — a single global graph shared across every domain. Invisible
while only `business` had real data; would have silently mixed domains'
entities together the moment a second domain got real signals. Added
`domain` (default `'business'`, so existing rows are correctly
classified without ambiguous backfill logic), replaced the old
non-domain-aware unique indexes with domain-aware ones.

## v6 — Canonical Problem identity

This is the architecturally significant one: introduced the `problems`
table and `opportunities.problem_id`. Before this, `Opportunity`
conflated four things — problem identity, customer segment, solution
angle, and dated observation. `Problem` is now the long-lived identity a
weekly `Opportunity` observation attaches to (see
`opportunity_engine/canonicalizer.py` for the matching logic:
entity-Jaccard primary, title-Jaccard secondary support, deliberately
conservative thresholds — see that module's docstring for the full
reasoning on why false-merge risk is weighted higher than false-split).

Backfill: each pre-v6 opportunity became its own initial Problem root
(`entity_ids=[]`) — an honest, explicitly-limited backfill, since pre-v6
opportunities never had `entity_ids` populated either, so there was no
real signature to retroactively match against.

## v7 — Persistent Problem memory (`problem_history`)

Added `problem_history`: a normalized, **append-only** event log for a
Problem's timeline. `Problem` itself continues to store only current
canonical state (title, entity_ids, first_seen, last_seen, weeks_seen) —
this table stores the complete evidence and change timeline as one row
per event, appended by `opportunity_engine/canonicalizer.py`'s
`resolve_problem()` in the same transaction as the Problem write.

**Why a normalized table, not JSON arrays on `problems`:** arrays-on-row
would mean rewriting an ever-larger blob on every match, no per-event
querying, and unbounded row growth over years of weekly runs. An
append-only child table is a normal, indexable, prunable pattern instead.

**Event types** (`models.VALID_HISTORY_EVENT_TYPES`):
| Event | Written by | Status |
|---|---|---|
| `created` | `resolve_problem()` — no match found, new Problem established | Active |
| `evidence_added` | `resolve_problem()` — existing Problem matched a new observation | Active |
| `confidence_updated` | — | Reserved, not yet written by any code path |
| `status_changed` | — | Reserved — `Problem` has no status field yet |
| `merged` | — | Reserved — no merge logic exists yet |
| `split` | — | Reserved — no split logic exists yet |

The four reserved types are defined now so the column's valid values
don't need another migration when lifecycle work (roadmap item after
this one) lands — but nothing writes them yet. Don't treat their
presence in the enum as evidence the corresponding features exist.

**Backfill:** each pre-v7 Problem gets exactly one synthetic `created`
event, `occurred_at` = the Problem's own `first_seen`, with
`metadata.backfilled = true`. No fabricated per-week events — `weeks_seen`
survived as a count, not as a record of *which* weeks, so synthesizing
one `evidence_added` per counted week would misrepresent data that was
never actually captured. Verified against both a hand-constructed pre-v7
shape and an authentic database created by the real pre-v7 (v6) code
running its real pipeline (see `PROBLEM_MEMORY_VALIDATION.md`).

**Table shape:**
```sql
CREATE TABLE problem_history (
    id             TEXT PRIMARY KEY,
    problem_id     TEXT NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
    domain         TEXT NOT NULL DEFAULT 'business',
    event_type     TEXT NOT NULL,
    occurred_at    TEXT NOT NULL,
    week_key       TEXT DEFAULT '',
    opportunity_id TEXT DEFAULT '',  -- plain reference, not FK — consistent
                                     -- with opportunities.problem_id
    metadata       TEXT DEFAULT '{}', -- JSON, event-type-specific
    created_at     TEXT NOT NULL
);
```

Read/write API: `opportunity_engine/problem_history.py`
(`record_event()`, `list_for_problem()`, `count_for_problem()`) — kept
separate from `canonicalizer.py` since matching and recording are
different responsibilities.

## v8 — Knowledge-graph decay (lifecycle states)

Added `lifecycle_state` (`active`|`dormant`|`archived`) and
`lifecycle_updated_at` to `entities` and `relationships`. Never deletes
anything — decay is purely a reversible state transition. Deliberately
scoped to the knowledge graph only: `Signal` stays append-only/immutable
and `Opportunity` stays immutable, one row per detection — neither gets
a lifecycle here. Problem/Opportunity lifecycle (Discovery → Validation →
Growing → Mature → Declining → Archived, per the RFC review's roadmap
item 5) is a separate, future, explicitly-gated decision — bundling it
into this migration would have blurred the Problem/Opportunity split
schema v6/v7 exist to establish.

**Lifecycle:** `ACTIVE → DORMANT → SOFT_ARCHIVED`. A decay pass
(`knowledge_graph/decay.py::run_decay_pass()`) runs once per domain per
pipeline execution — after entity extraction/persistence, before
detection (see `pipeline.py` Stage 2.5) — and only ever moves state
*forward* or leaves it alone. Reactivation (state moving back to
`active`) happens exclusively in `knowledge_graph/extractor.py`'s
`persist_results()`, on new evidence — new evidence is the only thing
that undoes decay.

**Decision factors** (all inspectable per-row, no black-box score):
- last meaningful reference time — `updated_at`, which `persist_results()`
  now bumps on *every* re-encounter, not just first insert. This closed
  a real pre-existing gap: entities previously used `INSERT OR IGNORE`,
  which touched nothing at all on a re-encounter, so a re-referenced
  entity's `updated_at` stayed frozen at its original creation time
  forever. Relationships already bumped `updated_at` correctly; only
  entities had the gap.
- connection strength — entity: count of non-archived relationships
  referencing it; relationship: its own accumulated `weight`. Extends
  (not immunizes) the dormant/archive thresholds by
  `config.DECAY_PROTECTION_MULTIPLIER` when above a configurable
  threshold.
- referenced by any current Problem's `entity_ids` in the domain — the
  best available concrete proxy for "importance" today. This *protects*
  (freezes current state, skips further decay) rather than reactivates.

**Extension points, explicitly not implemented:** confidence score,
evidence quality, user-interaction signals. None of these exist
anywhere in this codebase yet (no per-entity confidence field, no
evidence-quality scoring distinct from the opportunity scorer's
composite formula, no auth/user model at all). `run_decay_pass()` and
`decide_lifecycle_state()` accept keyword-only parameters for all three,
currently always `None`/no-op, so real signals can be wired in later
without changing every call site again.

**Two-layer matching eligibility** (`opportunity_engine/canonicalizer.py`):
entity-Jaccard in `find_match()` is now weighted by lifecycle state via
`opportunity_engine/similarity.py`'s new `weighted_jaccard()` (a strict
generalization of the existing `jaccard()`, which is untouched and still
used for title comparison). Active entities count fully; dormant
entities count at a reduced, configurable weight
(`config.DORMANT_MATCH_WEIGHT`); archived entities are excluded
entirely (weight 0) from new matching — the rows themselves are never
deleted, so they remain queryable as historical context. Entity ids with
no corresponding `entities` row (including every pre-v8 test's bare
synthetic ids) default to full weight, preserving exact backward
compatibility.

**Index-creation lesson applied directly:** both `idx_entities_lifecycle`
and `idx_rel_lifecycle` are created unconditionally in `_migrate_v8()`,
outside any column-existence guard — this is the exact fix already
applied to `idx_opp_problem` in `_migrate_v6()` after it was found that
nesting index creation inside a "column doesn't exist yet" guard means a
*fresh* database (where the column already exists via the DDL's own
`CREATE TABLE`) never gets the index at all.

**Backfill:** every pre-v8 row gets `lifecycle_state = 'active'` and
`lifecycle_updated_at` set to its own existing `updated_at` — the most
honest available proxy for "when did this become active," since there's
no earlier truthful timestamp, and defaulting to the migration's own
run-time would make every pre-existing row falsely look like it just
became active.

---

## v9 — Problem lifecycle & trend (two independent axes)

Added two INDEPENDENT current-state fields to `problems`, not one
combined state:

- `lifecycle_state` (`new → active → dormant → archived`, reversible via
  `reactivated`) — "is this Problem operationally relevant right now?"
- `trend` (`unknown → growing/stable/declining`) — "how is its evidence
  cadence changing?"

**This is a corrected design, not the first one built.** The initial
implementation used a single combined `trajectory_state` field
(`discovery → validation → growing/mature/declining → archived`,
plus `reactivated`) spanning both concepts. Before anything was pushed,
a design review argued for splitting it: one field should represent one
concept, and a combined enum either explodes combinatorially or
produces contradictory-reading states — a Problem that just came back
from archival but also happens to be declining; a Problem that's
growing but whose single most recent data point looks quiet. The split
was adopted, and the single-field version was fully replaced (not
patched around) before merging. See `opportunity_engine/lifecycle.py`'s
module docstring for the complete reasoning, and `models.py`'s `Problem`
docstring for the same point stated from the data-model side.

**Mechanics**, mirroring schema v8's decay/reactivation split exactly:

- **Forward progression** (both axes) happens in
  `opportunity_engine/lifecycle.py::run_lifecycle_pass()`, run once per
  domain per pipeline execution (`pipeline.py` Stage 3.5, after
  detection so this run's `problem_history` events already exist, before
  report generation so the report reflects this run's current state).
- **Reactivation** (`archived → reactivated`, with `trend` reset to
  `unknown` in the same moment — the old trend predates the dormancy and
  is no longer meaningful) is immediate and event-driven:
  `opportunity_engine/canonicalizer.py`'s `resolve_problem()` checks the
  matched Problem's current `lifecycle_state` the instant new evidence
  arrives. `reactivated` is a one-pass marker — the very next
  `run_lifecycle_pass()` promotes it straight to `active` (the archive
  check still takes precedence if it immediately goes quiet again).

**Lifecycle transition rules** (evaluated fresh every pass, time-based
check takes precedence over everything):
1. No new evidence for `PROBLEM_ARCHIVE_DAYS` (default 180) → `archived`.
2. No new evidence for `PROBLEM_DORMANT_DAYS` (default 90) → `dormant`.
   Same `active → dormant → archived` shape as knowledge-graph decay,
   mirrored here with its own thresholds — a Problem going quiet is a
   different, higher-level signal than a single entity mention going
   stale.
3. Currently `reactivated` → `active` (one-pass promotion).
4. `weeks_seen < PROBLEM_RECURRENCE_WEEKS` (default 2) → `new`.
5. Otherwise → `active`.

**Trend transition rules**, independent of lifecycle (skipped entirely
if `lifecycle_state` is `archived` this pass — no point classifying a
trend for something that just went fully quiet):
- Anchor = the most recent reactivation timestamp if later than
  `first_seen`, else `first_seen`.
- Elapsed time since anchor `< 2 × PROBLEM_TREND_WINDOW_DAYS` (default
  28, so 56 days) → `unknown` — not enough data to say anything.
- Otherwise, compare `problem_history` evidence-event counts in the most
  recent window against the window before it:
  `recent/prior ≥ PROBLEM_GROWTH_RATIO` (default 1.5) → `growing`;
  `recent/prior ≤ PROBLEM_DECLINE_RATIO` (default 0.5) → `declining`;
  otherwise → `stable`. `prior_count == 0` is handled explicitly
  (any evidence where there was none before is unambiguous growth; none
  in either window stays `stable` rather than guessed at).

**Every transition on either axis** writes a `status_changed`
`problem_history` event — the event type schema v7 reserved for exactly
this and left unused until now — tagged `metadata["axis"]` (`"lifecycle"`
or `"trend"`) so the two never get conflated in the history log, even
though both underlying columns are current-state fields, overwritten on
each transition.

**Deliberately distinct from `Opportunity.status`** (`new|validated|
dismissed|archived` — a pre-existing, human-curated review field set via
`PATCH /opportunities/{id}/status`, explicitly unenforced, discovered
during this migration's design and unrelated to it entirely).
`lifecycle_state`/`trend` are system-derived from accumulated evidence,
never human-set. The vocabularies happen to share "new" and "archived";
they are not the same concept.

**Backfill:** every pre-v9 Problem gets `lifecycle_state='new'` and
`trend='unknown'` (the DDL's own `NOT NULL DEFAULT`s handle this
automatically), with both `*_updated_at` columns backfilled from the
row's own `updated_at` — the same honest-backfill reasoning used in
every prior migration in this file. The real lifecycle pass, run once
after migration, promptly reclassifies anything with enough real history
to be `active`/`dormant` or a real trend.

**Index-creation lesson applied directly, a third time:** both
`idx_problems_lifecycle` and `idx_problems_trend` are created
unconditionally in `_migrate_v9()`, outside any column-existence guard —
the same fix already applied to `idx_opp_problem` (`_migrate_v6`) and
`idx_entities_lifecycle`/`idx_rel_lifecycle` (`_migrate_v8`).

---



- **Migrations are immutable once shipped.** `_migrate_v4` was left
  untouched when v5/v6 needed related index changes — new migrations do
  proper forward corrections, never rewrite history in place.
- **Every migration must be idempotent** — safe to run against a
  database that's already at the target version, or a fresh database
  where the DDL block already matches the end state.
- **Backfills are honest, not best-effort.** If pre-migration data can't
  support a real reconstruction (e.g. v6/v7's lack of real per-item
  history), the backfill says so explicitly in its metadata rather than
  fabricating a plausible-looking value.
- **Commit messages in this repo must never use backticks in an inline
  `git commit -m "..."`** — shell command substitution will silently
  eat the quoted text. Write the message to a file and use
  `git commit -F file` instead. (This bit a real commit message once —
  see the schema v6 session handoff.)
