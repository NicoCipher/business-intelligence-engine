# Schema History

This is the authoritative record of BIA-OS's SQLite schema versions. It
exists because `database.py`'s migration docstrings are the real source
of truth for *why* each change happened, but there was no single place
that summarized the sequence for someone starting a new session. This
file is that summary — for the full reasoning behind any one migration,
read the corresponding `_migrate_vN()` docstring in `backend/database.py`
directly; this file intentionally doesn't duplicate that reasoning in
full, only enough to orient.

Current version: **v7**. Defined by `database.SCHEMA_VERSION`.

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

---

## Migration discipline (applies to every version above and future ones)

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
