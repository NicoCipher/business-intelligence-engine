"""
pipeline.py — Canonical intelligence pipeline

This is the single implementation of the collect → extract → detect →
report pipeline. collect.py (CLI / GitHub Actions entry point) and
main.py (the /api/v1/pipeline/run endpoint) both call run_full_pipeline()
here — neither defines its own copy of the pipeline logic. If the
pipeline needs to change, it changes in exactly one place.

DomainRegistry.get_active() is the single source of truth for which
domains run. A domain that is not registered does not run, no matter how
it's referenced elsewhere (env var, CLI flag, etc). Callers must ensure
DomainRegistry.discover_and_register() has already been called — this
module does not call it, so tests can register fixture domains directly.

Shared vs. domain-specific sources
───────────────────────────────────
Hacker News is a platform-level, shared source (see domains/base.py's
DomainSources docstring) — it isn't configured per domain. Reddit and RSS
are domain-specific: each domain's DomainConfig.sources lists its own
subreddits and feeds.

To keep this correct without doubling HTTP traffic per domain, HN is
fetched exactly once per pipeline run, then fanned out — re-tagged with a
fresh id and each active domain's id — so every domain persists its own
independent copy (same source_id, different domain; see the
(source, source_id, domain) dedup index in database.py). Reddit and RSS
collectors are instantiated once per domain, using that domain's own
DomainConfig.sources.

Known trade-off: HNCollector's own duplicate check is domain-agnostic (see
BaseCollector._is_duplicate) — it skips re-fetching an HN item once *any*
domain has seen it, to avoid redundant HTTP calls. This means a newly
activated domain does not retroactively backfill older HN items that an
existing domain already collected; it only picks up new items from the
point it's activated onward. That's an acceptable trade-off for a live
signal-collection system (not a historical backfill system) and is called
out here explicitly rather than left as a silent gap.
"""

from __future__ import annotations

import dataclasses
import logging
import uuid
from dataclasses import dataclass, field

from collectors.base import persist_signals
from collectors.hn_collector import HNCollector
from collectors.reddit_collector import RedditCollector
from collectors.rss_collector import RSSCollector
from domains.base import DomainConfig
from domains.registry import DomainRegistry
from knowledge_graph.extractor import EntityExtractor
from models import Signal
from opportunity_engine.detector import PatternDetector
from report.generator import ReportGenerator

logger = logging.getLogger(__name__)


# ── Results ──────────────────────────────────────────────────────────────

@dataclass
class DomainRunResult:
    """Summary of one domain's pipeline run within a single invocation."""
    domain_id:               str
    signals_collected:       int  = 0
    signals_persisted:       int  = 0
    entities_inserted:       int  = 0
    relationships_inserted:  int  = 0
    opportunities_detected:  int  = 0
    report_generated:        bool = False


@dataclass
class PipelineResult:
    """Summary of a full pipeline run across every active domain."""
    domains: list[DomainRunResult] = field(default_factory=list)

    @property
    def total_signals(self) -> int:
        return sum(d.signals_collected for d in self.domains)

    @property
    def total_opportunities(self) -> int:
        return sum(d.opportunities_detected for d in self.domains)


# ── Entry point ──────────────────────────────────────────────────────────

def run_full_pipeline(
    dry_run: bool = False,
    hn_only: bool = False,
    generate_report: bool = False,
) -> PipelineResult:
    """
    Run collect → extract → detect → (report) for every active domain.

    This is the ONLY pipeline implementation in the codebase. collect.py
    and main.py's pipeline-trigger endpoint both call this function
    directly, so they are guaranteed to behave identically.

    Requires DomainRegistry to already be populated — call
    DomainRegistry.discover_and_register() (or register fixtures directly,
    in tests) before calling this.

    Raises RuntimeError if no domains are active — there is nothing
    meaningful to run, and silently doing nothing would hide a
    misconfiguration (bad ACTIVE_DOMAINS, missing DOMAIN_CONFIG, etc).
    """
    active_domains = DomainRegistry.get_active()
    if not active_domains:
        raise RuntimeError(
            "No active domains registered. Check ACTIVE_DOMAINS and "
            "ensure DomainRegistry.discover_and_register() has been called "
            "before running the pipeline."
        )

    logger.info(
        "Pipeline starting for %d active domain(s): %s",
        len(active_domains), ", ".join(d.id for d in active_domains),
    )

    # Shared collector: fetch HN once for the whole run, then fan the raw
    # signals out per domain below. See module docstring for the rationale.
    shared_hn_signals = HNCollector().collect()
    logger.info("[hn] collected %d shared signals this run", len(shared_hn_signals))

    result = PipelineResult()
    for domain in active_domains:
        run_result = _run_domain(
            domain,
            shared_hn_signals,
            dry_run=dry_run,
            hn_only=hn_only,
            generate_report=generate_report,
        )
        result.domains.append(run_result)

    return result


# ── Per-domain pipeline ──────────────────────────────────────────────────

def _run_domain(
    domain: DomainConfig,
    shared_hn_signals: list[Signal],
    *,
    dry_run: bool,
    hn_only: bool,
    generate_report: bool,
) -> DomainRunResult:
    """Run all pipeline stages for a single domain."""
    run_result = DomainRunResult(domain_id=domain.id)

    # ── Stage 1: Collect ────────────────────────────────────────────────
    domain_signals: list[Signal] = _retag_for_domain(shared_hn_signals, domain.id)

    if not hn_only:
        reddit = RedditCollector(
            subreddits=domain.sources.reddit_sources,
            domain=domain.id,
        )
        domain_signals.extend(reddit.collect())

        if domain.sources.rss_feeds:
            rss = RSSCollector(
                feeds=[(f.url, f.description) for f in domain.sources.rss_feeds],
                domain=domain.id,
            )
            domain_signals.extend(rss.collect())

    run_result.signals_collected = len(domain_signals)
    logger.info("[%s] collected %d signals this run", domain.id, len(domain_signals))

    if not dry_run and domain_signals:
        run_result.signals_persisted = persist_signals(domain_signals)
        logger.info(
            "[%s] persisted %d/%d signals (rest were duplicates)",
            domain.id, run_result.signals_persisted, len(domain_signals),
        )

    # ── Stage 2: Extract entities ───────────────────────────────────────
    if domain_signals:
        extractor = EntityExtractor()
        extraction_results = extractor.extract_batch(domain_signals)
        if not dry_run:
            counts = extractor.persist_results(extraction_results)
            run_result.entities_inserted = counts["entities_inserted"]
            run_result.relationships_inserted = counts["relationships_inserted"]
            logger.info(
                "[%s] extracted %d new entities, %d new relationships",
                domain.id, counts["entities_inserted"], counts["relationships_inserted"],
            )

    # ── Stage 3: Detect opportunities ───────────────────────────────────
    if len(domain_signals) >= 2:
        detector = PatternDetector()
        if dry_run:
            opps = detector.detect(domain_signals, domain=domain.id)
            run_result.opportunities_detected = len(opps)
        else:
            run_result.opportunities_detected = detector.detect_and_persist(
                domain_signals, domain=domain.id,
            )
    else:
        logger.info("[%s] not enough signals for pattern detection", domain.id)

    # ── Stage 4: Report ─────────────────────────────────────────────────
    if generate_report and not dry_run:
        generator = ReportGenerator()
        report = generator.generate(domain=domain.id)
        generator.persist(report)
        run_result.report_generated = True
        logger.info(
            "[%s] report persisted for %s — %d opportunities, %d signals",
            domain.id, report.week_key, report.opp_count, report.signal_count,
        )

    return run_result


# ── Helpers ──────────────────────────────────────────────────────────────

def _retag_for_domain(signals: list[Signal], domain_id: str) -> list[Signal]:
    """
    Produce fresh per-domain copies of a shared signal batch (Hacker News).

    Same source + source_id (so the domain-scoped dedup index still applies
    correctly per domain), new object id, new domain tag — each domain
    scores and stores its own independent row.
    """
    return [
        dataclasses.replace(s, id=str(uuid.uuid4()), domain=domain_id)
        for s in signals
    ]
