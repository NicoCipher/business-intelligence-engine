#!/usr/bin/env python3
"""Safely install an operator-supplied CI SQLite snapshot into local BIA."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import config
import persistence


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install a downloaded canonical CI SQLite snapshot into local BIA."
    )
    parser.add_argument("--source", required=True, type=Path, help="Downloaded bia-latest.db path")
    parser.add_argument(
        "--destination",
        type=Path,
        default=config.DB_PATH,
        help=f"Local database path (default: {config.DB_PATH})",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Back up an existing local database, then replace it",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(f"Source snapshot: {args.source}")
    print(f"Local destination: {args.destination}")
    try:
        backup = persistence.replace_local_from_snapshot(
            args.source,
            args.destination,
            replace=args.replace,
        )
    except (FileExistsError, FileNotFoundError, OSError, sqlite3.Error) as error:
        print(f"Local sync failed: {error}", file=sys.stderr)
        return 1

    if backup is not None:
        print(f"Existing local database backed up to: {backup}")
    print("Local sync completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
