"""
locking.py — File-based mutual exclusion for pipeline/report generation.

Prevents concurrent pipeline runs or report generations from writing to
SQLite simultaneously -- a previously identified, real failure mode:
concurrent writers raise sqlite3.OperationalError ("database is
locked"), which a narrow `except RuntimeError` elsewhere in this
codebase did not catch, meaning the failure could vanish silently in an
unlogged background task.

Minimal, dependency-free: an atomically-created lock file
(O_CREAT | O_EXCL, which fails immediately if the file already exists --
no check-then-create race window). A stale-lock timeout handles the case
where a prior process crashed without releasing its lock, so one bad run
can't permanently wedge the system.
"""

import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

# Generous on purpose -- a real pipeline run should never take this long;
# this exists only to recover from a crashed process, not to bound
# normal operation.
STALE_LOCK_SECONDS = 3600


class LockBusyError(Exception):
    """Raised when a lock is already held by another (live) process."""


def is_locked(lock_path: Path) -> bool:
    """
    Whether `lock_path` currently represents a live (non-stale) lock.
    Used by API handlers to return 409 Conflict before even attempting
    to queue a background task, rather than letting it fail later.
    """
    if not lock_path.exists():
        return False
    age = time.time() - lock_path.stat().st_mtime
    return age <= STALE_LOCK_SECONDS


@contextmanager
def exclusive_lock(lock_path: Path):
    """
    Acquire an exclusive, atomically-created lock file for the duration
    of the `with` block. Raises LockBusyError immediately if another
    process already holds a live lock -- callers should treat this as
    "already running," not silently retry or queue.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    if lock_path.exists():
        age = time.time() - lock_path.stat().st_mtime
        if age > STALE_LOCK_SECONDS:
            logger.warning(f"Removing stale lock at {lock_path} (age {age:.0f}s)")
            lock_path.unlink(missing_ok=True)
        else:
            raise LockBusyError(f"{lock_path.name} is already running")

    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
    except FileExistsError:
        raise LockBusyError(f"{lock_path.name} is already running")

    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)
