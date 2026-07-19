#!/usr/bin/env python3
"""
collect.py — CLI entry point for the intelligence pipeline

This script is a thin wrapper around pipeline.run_full_pipeline(). It owns
CLI concerns only (argument parsing, logging setup, exit codes) — it does
NOT implement pipeline logic itself. That logic lives in pipeline.py and
is shared with main.py's /api/v1/pipeline/run endpoint, so the CLI and the
API are guaranteed to behave identically.

Entry point for:
  - Local cron jobs:   */60 * * * * cd /path/to/bia-os && python backend/collect.py
  - GitHub Actions:    see .github/workflows/collect.yml
  - Manual runs:       python backend/collect.py [--report]

Exit codes:
  0  success (even if nothing new was found)
  1  critical failure (database unreachable, no active domains, etc.)
"""

import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Ensure backend/ is on the path when run from repo root
sys.path.insert(0, str(Path(__file__).parent))

import database
from domains.registry import DomainRegistry
from pipeline import run_full_pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("collect")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="BIA-OS intelligence pipeline runner"
    )
    parser.add_argument(
        "--report", action="store_true",
        help="Generate weekly report after collection (always runs on Sundays)"
    )
    parser.add_argument(
        "--hn-only", action="store_true",
        help="Run only the HN collector (useful for testing without Reddit credentials)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Collect but do not persist anything — useful for debugging"
    )
    return parser.parse_args()


def main() -> int:
    args      = parse_args()
    start     = time.monotonic()
    today     = datetime.now(timezone.utc)
    is_sunday = today.weekday() == 6

    logger.info(f"BIA-OS pipeline starting ({today.strftime('%Y-%m-%d %H:%M UTC')})")
    if args.dry_run:
        logger.info("DRY RUN mode — nothing will be written to the database")

    try:
        # Stage 0: Ensure database schema exists and domains are registered.
        # DomainRegistry is the single source of truth for which domains run
        # — pipeline.py reads it directly, so registration must happen here,
        # before run_full_pipeline() is called.
        database.initialize()
        DomainRegistry.discover_and_register()
        stats = database.get_stats()
        logger.info(
            f"Database: {stats['signals']} signals, "
            f"{stats['opportunities']} opportunities, "
            f"{stats['entities']} entities"
        )

        result = run_full_pipeline(
            dry_run=args.dry_run,
            hn_only=args.hn_only,
            generate_report=(args.report or is_sunday),
        )

        for d in result.domains:
            logger.info(
                f"[{d.domain_id}] {d.signals_collected} signals collected, "
                f"{d.signals_persisted} persisted, "
                f"{d.entities_inserted} entities, {d.relationships_inserted} relationships, "
                f"{d.opportunities_detected} opportunities"
                + (", report generated" if d.report_generated else "")
            )

        elapsed = time.monotonic() - start
        logger.info(
            f"Pipeline complete in {elapsed:.1f}s — "
            f"{result.total_signals} total signals, "
            f"{result.total_opportunities} total opportunities across "
            f"{len(result.domains)} domain(s)"
        )
        return 0

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 0
    except Exception:
        logger.exception("Pipeline failed with unhandled exception")
        return 1


if __name__ == "__main__":
    sys.exit(main())
