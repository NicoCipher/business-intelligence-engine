"""
persistence.py — Durable SQLite persistence seam (pull/push).

BIA's database, as of V1, has no durable storage guarantee outside of
whatever the deployment environment provides -- historically, in CI,
only a GitHub Actions cache (explicitly not designed for durability;
subject to eviction with no restore path). This module is the seam
that fixes that without committing to a specific backend: two
functions, pull() and push(), behind which today's minimal
implementation (a configurable snapshot directory, zero new
infrastructure or secrets) can later be swapped for real durable
storage (object storage, a managed database, etc.) without any caller
needing to change.

pull() -- call BEFORE the database is used, to restore the most recent
durable snapshot if the working database doesn't already exist. Never
overwrites a live database -- this is a cold-start recovery path only.

push() -- call after a database-backed pipeline invocation, to snapshot the
current transactionally committed database state to the durable location.

V1 backend: a configurable directory (BIA_DB_BACKUP_DIR, defaults to
backend/data/backups/) containing exactly one canonical ``bia-latest.db``.
collect.yml uploads only that file as a GitHub Actions artifact. The cache
may speed normal runs but is never the durable authority.
"""

import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import config

logger = logging.getLogger(__name__)

BACKUP_DIR = Path(os.getenv("BIA_DB_BACKUP_DIR", str(config.DATA_DIR / "backups")))
CANONICAL_SNAPSHOT_NAME = "bia-latest.db"
LOCAL_SYNC_BACKUP_RETENTION = int(os.getenv("BIA_LOCAL_SYNC_BACKUP_RETENTION", "10"))


def canonical_snapshot_path(backup_dir: Path | None = None) -> Path:
    """Return the sole snapshot included in the CI durability artifact."""
    return (backup_dir or BACKUP_DIR) / CANONICAL_SNAPSHOT_NAME


def _validate_sqlite(path: Path) -> None:
    """Raise if ``path`` is not a complete, readable SQLite database."""
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
        result = conn.execute("PRAGMA quick_check").fetchone()[0]
    if result != "ok":
        raise sqlite3.DatabaseError(f"SQLite integrity check failed for {path}: {result}")


def _snapshot_sqlite(source: Path, destination: Path, *, replace: bool) -> Path:
    """Safely snapshot ``source`` to ``destination`` without partial output."""
    if not source.exists():
        raise FileNotFoundError(f"SQLite source snapshot does not exist: {source}")
    if destination.exists() and not replace:
        raise FileExistsError(f"Refusing to overwrite existing database: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.{uuid4().hex}.tmp"
    try:
        with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as source_conn:
            with sqlite3.connect(temporary) as destination_conn:
                source_conn.backup(destination_conn)
        _validate_sqlite(temporary)
        if destination.exists() and not replace:
            raise FileExistsError(f"Refusing to overwrite existing database: {destination}")
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def _legacy_snapshots() -> list[Path]:
    """Allow one-time recovery from artifacts produced before the canonical V1."""
    return sorted(BACKUP_DIR.glob("bia-*.db"), reverse=True)


def _prune_local_sync_backups(backup_dir: Path) -> None:
    """Retain only known tool-created local-sync backups, newest first."""
    backups = sorted(backup_dir.glob("bia-before-ci-sync-*.db"), reverse=True)
    for stale_backup in backups[max(LOCAL_SYNC_BACKUP_RETENTION, 0):]:
        stale_backup.unlink()


def pull(db_path: Path | None = None) -> bool:
    """Restore a canonical snapshot only when no live database exists."""
    db_path = db_path or config.DB_PATH
    if db_path.exists():
        logger.debug("pull(): %s already exists, skipping restore", db_path)
        return False

    canonical = canonical_snapshot_path()
    if canonical.exists():
        source = canonical
    else:
        legacy = _legacy_snapshots()
        if not legacy:
            logger.info("pull(): no durable snapshot found, starting fresh")
            return False
        source = legacy[0]
        logger.warning("pull(): restoring legacy timestamped snapshot %s", source.name)

    _snapshot_sqlite(source, db_path, replace=False)
    logger.info("pull(): restored %s -> %s", source.name, db_path)
    return True


def restore_canonical_snapshot(db_path: Path | None = None) -> bool:
    """Safely replace a disposable CI cache copy with the canonical artifact."""
    canonical = canonical_snapshot_path()
    if not canonical.exists():
        return False
    destination = db_path or config.DB_PATH
    _snapshot_sqlite(canonical, destination, replace=True)
    logger.info("restore_canonical_snapshot(): restored %s -> %s", canonical, destination)
    return True


def push(db_path: Path | None = None) -> Path | None:
    """Replace the one canonical durable snapshot with a safe SQLite backup."""
    db_path = db_path or config.DB_PATH
    if not db_path.exists():
        logger.warning("push(): %s does not exist, nothing to snapshot", db_path)
        return None

    snapshot = _snapshot_sqlite(db_path, canonical_snapshot_path(), replace=True)
    logger.info("push(): snapshotted %s -> %s", db_path, snapshot)
    return snapshot


def replace_local_from_snapshot(
    source: Path,
    db_path: Path | None = None,
    *,
    replace: bool = False,
) -> Path | None:
    """Explicitly replace a local database, first preserving it as a snapshot.

    Returns the backup path when replacement backed up an existing database,
    or ``None`` when restoring into a missing destination. The caller must
    explicitly opt into replacement; no local database is overwritten by
    default.
    """
    destination = db_path or config.DB_PATH
    if not source.exists():
        raise FileNotFoundError(f"Snapshot to restore does not exist: {source}")
    if not destination.exists():
        _snapshot_sqlite(source, destination, replace=False)
        return None
    if not replace:
        raise FileExistsError(
            f"Refusing to overwrite local database {destination}. Re-run with --replace "
            "to create a backup and replace it."
        )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    local_backup = destination.parent / "backups" / f"bia-before-ci-sync-{timestamp}.db"
    _snapshot_sqlite(destination, local_backup, replace=False)
    _snapshot_sqlite(source, destination, replace=True)
    _prune_local_sync_backups(local_backup.parent)
    return local_backup
