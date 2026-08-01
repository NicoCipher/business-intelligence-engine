# Schema History

This is the authoritative record of BIA-OS's SQLite schema versions. It
exists because `database.py`'s migration docstrings are the real source
of truth for *why* each change happened, but there was no single place
that summarized the sequence for someone starting a new session. This
file is that summary — for the full reasoning behind any one migration,
read the corresponding `_migrate_vN()` docstring in `backend/database.py`
directly; this file intentionally doesn't duplicate that reasoning in
full, only enough to orient.

Current version: **v8**. Defined by `database.SCHEMA_VERSION`.

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
