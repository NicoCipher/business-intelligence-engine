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

push() -- call AFTER a successful pipeline run, to snapshot the current
database to the durable location.

V1 backend: a configurable directory (BIA_DB_BACKUP_DIR, defaults to
backend/data/backups/), timestamped snapshots, most-recent-first
restore. collect.yml uploads this directory as a GitHub Actions
artifact -- artifacts have far longer, more explicit retention than the
cache mechanism previously relied on, and require no new secrets or
dependencies to adopt today.
"""

import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import config

logger = logging.getLogger(__name__)

BACKUP_DIR = Path(os.getenv("BIA_DB_BACKUP_DIR", str(config.DATA_DIR / "backups")))


def pull(db_path: Path | None = None) -> bool:
    """
    Restore the most recent durable snapshot to db_path, if db_path
    doesn't already exist. Returns True if a snapshot was restored,
    False otherwise (including when db_path already exists -- pull()
    never overwrites a live database).
    """
    db_path = db_path or config.DB_PATH
    if db_path.exists():
        logger.debug(f"pull(): {db_path} already exists, skipping restore")
        return False

    if not BACKUP_DIR.exists():
        logger.info("pull(): no backup directory found, starting fresh")
        return False

    snapshots = sorted(BACKUP_DIR.glob("bia-*.db"), reverse=True)
    if not snapshots:
        logger.info("pull(): no snapshots found, starting fresh")
        return False

    latest = snapshots[0]
    db_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(latest, db_path)
    logger.info(f"pull(): restored {latest.name} -> {db_path}")
    return True


def push(db_path: Path | None = None) -> Path | None:
    """
    Snapshot the current database to the durable backup location. Call
    after a successful pipeline run. Returns the snapshot path, or None
    if there was nothing to snapshot.
    """
    db_path = db_path or config.DB_PATH
    if not db_path.exists():
        logger.warning(f"push(): {db_path} does not exist, nothing to snapshot")
        return None

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot_path = BACKUP_DIR / f"bia-{timestamp}.db"
    shutil.copy2(db_path, snapshot_path)
    logger.info(f"push(): snapshotted {db_path} -> {snapshot_path}")
    return snapshot_path
