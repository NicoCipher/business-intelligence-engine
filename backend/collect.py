#!/usr/bin/env python3
"""
collect.py — Standalone intelligence pipeline runner

This script runs the full pipeline without requiring the FastAPI server.
It is the entry point for:
  - Local cron jobs:   */60 * * * * cd /path/to/bia-os && python backend/collect.py
  - GitHub Actions:    see .github/workflows/collect.yml
  - Manual runs:       python backend/collect.py [--report]

Pipeline stages:
  1. Collect  — fetch signals from HN, Reddit, RSS
  2. Extract  — pull entities from signal text → knowledge graph
  3. Detect   — find opportunity clusters across sources
  4. Report   — generate weekly intelligence briefing (Sundays or --report flag)

Exit codes:
  0  success (even if nothing new was found)
  1  critical failure (database unreachable, etc.)
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
from collectors.hn_collector import HNCollector
from collectors.reddit_collector import RedditCollector
from collectors.rss_collector import RSSCollector
from knowledge_graph.extractor import EntityExtractor
from opportunity_engine.detector import PatternDetector
from report.generator import ReportGenerator
from domains.registry import DomainRegistry

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


def run_collection(dry_run: bool = False, hn_only: bool = False) -> list:
    """
    Stage 1: Collect signals from all configured sources.
    Returns the list of new Signal objects collected.
    """
    collector_classes = [HNCollector, RSSCollector]
    if not hn_only:
        collector_classes.append(RedditCollector)

    all_signals = []

    for CollectorClass in collector_classes:
        name = CollectorClass.SOURCE_NAME
        try:
            collector = CollectorClass()
            signals   = collector.collect()
            logger.info(f"[{name}] collected {len(signals)} signals")

            if not dry_run and signals:
                inserted = collector.persist(signals)
                logger.info(f"[{name}] persisted {inserted} new signals")

            all_signals.extend(signals)
        except Exception:
            logger.exception(f"[{name}] collector failed — skipping")

    return all_signals


def run_extraction(signals: list, dry_run: bool = False) -> dict:
    """
    Stage 2: Extract entities from collected signals, build knowledge graph.
    """
    if not signals:
        logger.info("[extract] No signals to process")
        return {"entities": 0, "relationships": 0}

    extractor = EntityExtractor()
    results   = extractor.extract_batch(signals)

    if dry_run:
        entity_count = sum(len(r.entities) for r in results)
        rel_count    = sum(len(r.relationships) for r in results)
        logger.info(f"[extract] DRY RUN — would insert {entity_count} entities, {rel_count} relationships")
        return {"entities": entity_count, "relationships": rel_count}

    counts = extractor.persist_results(results)
    logger.info(
        f"[extract] {counts['entities_inserted']} new entities, "
        f"{counts['relationships_inserted']} new relationships"
    )
    return counts


def run_detection(signals: list, dry_run: bool = False) -> int:
    """
    Stage 3: Detect opportunity clusters, score and persist.
    Returns number of new opportunities detected.
    """
    if len(signals) < 2:
        logger.info("[detect] Not enough signals for pattern detection")
        return 0

    detector = PatternDetector()

    if dry_run:
        opps = detector.detect(signals)
        logger.info(f"[detect] DRY RUN — would persist {len(opps)} opportunities")
        for o in opps[:3]:
            logger.info(f"  {o.tier.upper():6s} {o.composite_score:.1f}  {o.title}")
        return len(opps)

    new_opps = detector.detect_and_persist(signals)
    logger.info(f"[detect] {new_opps} new opportunities persisted")
    return new_opps


def run_report(dry_run: bool = False) -> None:
    """Stage 4: Generate and persist the weekly intelligence report."""
    generator = ReportGenerator()
    report    = generator.generate()

    logger.info(
        f"[report] Generated {report.week_key} — "
        f"{report.opp_count} opportunities, {report.signal_count} signals, "
        f"{len(report.content.get('key_insights', []))} insights"
    )

    if dry_run:
        logger.info("[report] DRY RUN — not persisting")
        return

    generator.persist(report)
    logger.info(f"[report] Persisted report for {report.week_key}")


def main() -> int:
    args    = parse_args()
    start   = time.monotonic()
    today   = datetime.now(timezone.utc)
    is_sunday = today.weekday() == 6

    logger.info(f"BIA-OS pipeline starting ({today.strftime('%Y-%m-%d %H:%M UTC')})")
    if args.dry_run:
        logger.info("DRY RUN mode — nothing will be written to the database")

    try:
        # Stage 0: Ensure database schema exists
        database.initialize()
        DomainRegistry.discover_and_register()
        stats = database.get_stats()
        logger.info(
            f"Database: {stats['signals']} signals, "
            f"{stats['opportunities']} opportunities, "
            f"{stats['entities']} entities"
        )

        # Stage 1: Collect
        signals = run_collection(dry_run=args.dry_run, hn_only=args.hn_only)
        logger.info(f"Total signals this run: {len(signals)}")

        # Stage 2: Extract entities
        run_extraction(signals, dry_run=args.dry_run)

        # Stage 3: Detect opportunities
        run_detection(signals, dry_run=args.dry_run)

        # Stage 4: Generate report (Sundays automatically, or when --report flag is set)
        if args.report or is_sunday:
            run_report(dry_run=args.dry_run)

        elapsed = time.monotonic() - start
        logger.info(f"Pipeline complete in {elapsed:.1f}s")
        return 0

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 0
    except Exception:
        logger.exception("Pipeline failed with unhandled exception")
        return 1


if __name__ == "__main__":
    sys.exit(main())
