# SQLite Snapshot Continuity (NIC-13 Phase 1)

For the hosted-collector phase, the latest completed collection workflow that
published a valid canonical SQLite snapshot is authoritative for accumulated
production evidence. This includes a run that later failed after committing
collector or scheduler state; a snapshot is database state, not a successful
analytical-pipeline verdict. The local `backend/data/bia.db` is a
development/operator copy. Local changes are not automatically pushed to CI,
and there is no live or bidirectional replication.

## Canonical lifecycle

`persistence.push()` uses SQLite's backup API to create and validate one
`backend/data/backups/bia-latest.db`, then atomically replaces the previous
canonical file. This is safe with BIA's WAL-mode database; raw database-file
copies are not used.

Hourly and manual workflow executions share one queued concurrency group, so
only one run can restore and publish the canonical authority at a time. The
workflow searches all retained completed workflow history, not a fixed recent
run window. A canonical `bia-latest.db` artifact takes precedence wherever it
appears in that history and, once present, ends legacy migration. On the first
canonical rollout only, legacy `bia-*.db` artifacts are staged and the newest
valid SQLite snapshot is migrated through the same SQLite backup and validation
machinery into `bia-latest.db` before replacing the disposable cache copy.
A failure while listing, inspecting, or downloading an existing artifact fails
the run rather than treating the cache as authority. Invalid legacy candidates
are skipped only when an older valid legacy snapshot remains; if none validates,
migration fails before a cache copy can be installed. Only when there is
genuinely no prior database artifact may BIA use a cache copy or initialize
fresh.

`collect.py` snapshots committed state in `finally`, because a collector or
scheduler transition may have committed before a later pipeline stage fails.
After the workflow has safely reached the persistence stage, it uploads only
`bia-latest.db` even when the overall pipeline exits unsuccessfully. That
preserves valid committed state without asserting that the pipeline run itself
succeeded. Failures before the persistence stage never republish a cache copy
as canonical authority. GitHub's per-run artifact retention provides history
without nesting old snapshots inside new artifacts.

Older timestamped snapshots are accepted only as a one-time recovery fallback
by `persistence.pull()`. New pushes do not create timestamped history.

## Explicit local sync

Stop local BIA processes before replacing their database, then run:

```bash
scripts/pull-ci-snapshot.sh
```

The command continues to download the latest successful workflow artifact
using the authenticated `gh` CLI and refuses to overwrite an existing local
`bia.db`. This conservative local operator command is not changed by the CI
failed-run durability policy above.
To replace deliberately:

```bash
scripts/pull-ci-snapshot.sh --replace
```

The replacement path first creates a SQLite-backup-API copy at
`backend/data/backups/bia-before-ci-sync-<timestamp>.db`, then installs the
validated downloaded snapshot. A missing, unreadable, or failed source copy
leaves the existing local database untouched. The command prints its source,
destination, backup path when created, and final outcome.

The ten newest tool-created local-sync backups are retained by default. This
can be adjusted with `BIA_LOCAL_SYNC_BACKUP_RETENTION`; no unrelated database
files are deleted.

Phase 2 remains the decision and migration work for a hosted production
database; this phase intentionally does not add replication, hosted storage,
or multi-user access.
