# SQLite Snapshot Continuity (NIC-13 Phase 1)

For the hosted-collector phase, the latest successful collection workflow's
canonical SQLite snapshot is authoritative for accumulated production evidence.
The local `backend/data/bia.db` is a development/operator copy. Local changes
are not automatically pushed to CI, and there is no live or bidirectional
replication.

## Canonical lifecycle

`persistence.push()` uses SQLite's backup API to create and validate one
`backend/data/backups/bia-latest.db`, then atomically replaces the previous
canonical file. This is safe with BIA's WAL-mode database; raw database-file
copies are not used.

The hourly workflow restores the latest successful artifact first. If it is
available, the validated canonical snapshot replaces the disposable cache copy.
If no artifact exists (the first run) or cannot be downloaded, the cache is a
best-effort optimization and BIA can initialize a new database. Successful
runs upload only `bia-latest.db`; GitHub's per-run artifact retention provides
history without nesting old snapshots inside new artifacts. Failed runs do not
publish a new authoritative artifact.

Older timestamped snapshots are accepted only as a one-time recovery fallback
by `persistence.pull()`. New pushes do not create timestamped history.

## Explicit local sync

Stop local BIA processes before replacing their database, then run:

```bash
scripts/pull-ci-snapshot.sh
```

The command downloads the latest successful workflow artifact using the
authenticated `gh` CLI and refuses to overwrite an existing local `bia.db`.
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
