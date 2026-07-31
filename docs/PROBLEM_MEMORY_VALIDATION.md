# Schema v7 Validation Report — Persistent Problem Memory

Closes out the v7 milestone. Everything below was actually executed and
its output captured, not asserted from reading the code.

## 1. End-to-end pipeline check

**First attempt failed instructively.** Running `detect_and_persist()`
directly against hand-built signals (skipping `extractor.persist_results()`)
produced opportunities with `entity_ids: []` and `problem_history`
events with `metadata.entity_count: 0`, even for titles containing
"compliance" — a real, registered `problem`-type keyword in
`knowledge_graph/schema.py`. Root cause: `canonicalizer.resolve_entity_ids()`
only *looks up* entities already persisted to the `entities` table; it
doesn't extract or persist them. The real pipeline
(`pipeline.py::run_full_pipeline()`) runs `extractor.persist_results()`
before `detector.detect_and_persist()` — my first script skipped that
stage. Documented as a real footgun in `docs/ARCHITECTURE.md`; not a v7
regression (this dependency existed before v7 too), but v7 makes a
silent failure here easier to overlook since the history event still
gets written, just with `entity_count: 0` and no match.

**Corrected run**, in the right order (`extractor.persist_results()` →
`detector.detect_and_persist()`), two rounds:

Round 1 (new Problem):
```
entities_inserted: 1
opportunity.entity_ids: ['38eb38f8-...']
problem_history event: event_type=created, problem_id == the real Problem row,
  opportunity_id == the real Opportunity row, occurred_at/created_at both
  well-formed ISO 8601, metadata={"title": "...", "entity_count": 1}
```

Round 2 (second, differently-worded cluster sharing the same extracted
entity — "compliance"):
```
detect_and_persist() → 1 new opportunity, 0 new problems (correctly matched)
problem_history now has 2 events: [created, evidence_added]
evidence_added.problem_id    == same Problem as round 1
evidence_added.opportunity_id == the NEW opportunity (not round 1's)
metadata.match_score = 0.887
```

All assertions (`problem_id`, `opportunity_id`, `event_type`, timestamp
format, event ordering) passed.

*Note on the `demand_signals` conftest fixture*, which the validation
request specifically named: run through `PatternDetector.diagnose()`, it
produced **0 accepted clusters / 3 rejected** (`below_threshold`,
`too_small` × 2). This isn't a v7 issue — it's already documented in
`test_detector_diagnose.py`'s own comments as a fixture that "doesn't
always cluster into one group" by design (it's meant for gating/scoring
tests, not guaranteed-clustering tests). The check above used the
fixture from `test_qualifying_cluster_appears_in_accepted` instead, which
is the one the test suite itself uses when a real accepted cluster is
required.

## 2. Migration verified against a real v6 database

Not a hand-simulated v6 shape — an *authentic* one:

1. Checked out commit `ad95a3b` (the actual pre-v7 commit) into a
   separate clone.
2. Ran its real `database.initialize()`, then its real
   `EntityExtractor` + `PatternDetector` pipeline against two distinct
   signal clusters, producing 2 genuine Problems with no
   `problem_history` table (didn't exist yet at that commit).
3. Confirmed via query: `schema version: 6`, `problem_history table
   exists: False`, 2 real Problems present.
4. Copied that `.db` file, pointed the **current** (v7) `database.py` at
   it, and called `initialize()` — the real upgrade path a production
   deployment would take.

Result:
```
version before: 6 → version after: 7
Both pre-existing Problem rows unchanged (id, title, first_seen, weeks_seen)
2 backfilled problem_history events, one per Problem:
  event_type = created
  occurred_at == that Problem's own first_seen (not "now")
  metadata.backfilled = true
  metadata.title == that Problem's real title
Re-running initialize() a second time: still exactly 2 events (idempotent)
```

## 3. Transaction boundaries and failure modes

Two things checked empirically, not just read from the code:

**a. Does an uncommitted write survive a non-`sqlite3.Error` exception?**
`database.get_connection()`'s explicit rollback only catches
`sqlite3.Error` — a `ValueError` (e.g. from `ProblemHistoryEvent`'s
`event_type` validation) would skip that branch. Tested directly: an
INSERT followed by a raised `ValueError`, connection closed via the
context manager's `finally`. Reopening the database afterward: **the
write did not persist.** SQLite's semantics discard an uncommitted
transaction on connection close regardless of exception type, so the
narrow `except sqlite3.Error` clause doesn't actually create a gap in
practice — worth knowing, not worth "fixing" defensively, since the
outcome is already correct.

**b. Can a Problem row ever exist without its corresponding history
event, or vice versa?** Monkeypatched `problem_history.record_event()`
to raise immediately after `resolve_problem()`'s `INSERT INTO problems`
had already executed (uncommitted). Result: **zero rows in either
table** after the exception — the Problem insert never survives without
its paired history event. Confirms the two writes are genuinely coupled
within one transaction, not just "usually fine."

**c. Batch-level note (pre-existing behavior, not introduced by v7):**
`detect_and_persist()` commits once, after its whole `for opp in
opportunities` loop — not per-opportunity. This means Problem creation,
history writes, and Opportunity inserts are atomic *across the entire
batch* for one call, which is stronger than per-opportunity atomicity in
one sense (a batch either fully lands or fully rolls back) but also
means one bad opportunity in a batch of ten currently blocks the other
nine from persisting too. This boundary already existed before v7 (the
Opportunity insert worked this way in v6); v7 just added more work
inside the same boundary. Flagging it here because the validation
request specifically asked about transaction boundaries — not proposing
a change, since per-opportunity commits would be a separate, larger
design decision (partial-batch persistence changes what "a detection
run" means) outside this milestone's scope.

## Test suite

341/341 passing (313 baseline + 28 new: `test_migration_v7.py`,
`test_problem_history.py`, `TestResolveProblemHistory` in
`test_canonicalizer.py`). Two pre-existing tests that hardcoded
`SCHEMA_VERSION == 6` were updated to track the current version instead
of pinning it — same treatment applied when v5 → v6 landed previously.

## Regressions, edge cases, and debt identified during this milestone

**No regressions found.** Everything above either passed on first
principles or (in the `entity_count: 0` case) turned out to be a gap in
my own ad-hoc validation script, not the production code path.

**New debt/edge cases surfaced, none blocking:**
1. Silent zero-entity degradation (§1 above) — worth a defensive check
   or at least a log warning if `detect_and_persist()` is ever called
   with an empty `entities` table for the domain, since it currently
   fails silently into "everything is a new Problem."
2. Deterministic matching's real limitation is vocabulary coverage, not
   an algorithm weakness (§ "Matching" in `docs/ARCHITECTURE.md`) — generic
   titles with zero recognized entity keywords never merge across weeks,
   regardless of how similar they read. Already an accepted, documented
   trade-off from the RFC review; restating it here because this
   validation session is the first time it was empirically demonstrated
   rather than theorized.
3. Batch-level commit granularity in `detect_and_persist()` (§3c) — not
   a bug, but worth remembering before building anything that assumes
   partial-batch persistence.

None of the above block moving to the next roadmap item.
