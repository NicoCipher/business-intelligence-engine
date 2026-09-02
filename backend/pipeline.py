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
from collections.abc import Callable
from dataclasses import dataclass, field

from collectors.base import CollectorOutcome, persist_signals
from collectors.hn_collector import HNCollector
from collectors.reddit_collector import RedditCollector
from collectors.rss_collector import RSSCollector
from collectors.github_collector import GitHubCollector
from collectors.trends_collector import TrendsCollector
from collectors.stackexchange_collector import StackExchangeCollector
from collectors.greenhouse_jobs_collector import GreenhouseJobsCollector
from collectors.sec_edgar_collector import SECEdgarCollector
import database
from domains.base import DomainConfig
from domains.registry import DomainRegistry
from knowledge_graph import decay
from knowledge_graph.extractor import EntityExtractor
from models import Signal
from opportunity_engine import change_detection, lifecycle
from opportunity_engine.detector import PatternDetector
from report.generator import ReportGenerator
from scheduler import ScheduleDecision, SchedulePlan

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
    entities_decayed:        int  = 0   # entities newly moved to dormant or archived this run
    relationships_decayed:   int  = 0   # relationships newly moved to dormant or archived this run
    opportunities_detected:  int  = 0
    problems_archived:       int  = 0   # problems newly moved to archived lifecycle_state this run
    change_events_recorded:  int  = 0   # change_events written this run (Stage 3.6) — see opportunity_engine/change_detection.py
    report_generated:        bool = False


@dataclass
class PipelineResult:
    """Summary of a full pipeline run across every active domain."""
    domains: list[DomainRunResult] = field(default_factory=list)
    collector_outcomes: list["ScheduledCollectorOutcome"] = field(default_factory=list)

    @property
    def total_signals(self) -> int:
        return sum(d.signals_collected for d in self.domains)

    @property
    def total_opportunities(self) -> int:
        return sum(d.opportunities_detected for d in self.domains)


@dataclass(frozen=True)
class ScheduledCollectorOutcome:
    """One scheduler-visible collector attempt, including its logical domain."""

    source: str
    domain: str
    outcome: CollectorOutcome


# ── Entry point ──────────────────────────────────────────────────────────

def run_full_pipeline(
    dry_run: bool = False,
    hn_only: bool = False,
    generate_report: bool = False,
    source_plan: SchedulePlan | None = None,
    outcome_recorder: Callable[[ScheduleDecision, CollectorOutcome], object] | None = None,
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

    if source_plan is not None:
        return _run_scheduled_pipeline(
            active_domains,
            source_plan,
            dry_run=dry_run,
            generate_report=generate_report,
            outcome_recorder=outcome_recorder,
        )

    # Manual and API invocations deliberately remain a full-run override:
    # they do not read collector_state or apply due-source gating.
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


def _run_scheduled_pipeline(
    active_domains: list[DomainConfig],
    source_plan: SchedulePlan,
    *,
    dry_run: bool,
    generate_report: bool,
    outcome_recorder: Callable[[ScheduleDecision, CollectorOutcome], object] | None,
) -> PipelineResult:
    """Execute only the due entries in a persisted scheduler plan."""
    result = PipelineResult()
    due = source_plan.due
    if not due:
        logger.info("No collectors are due; skipping pipeline stages and report generation")
        return result

    domain_by_id = {domain.id: domain for domain in active_domains}
    signals_by_domain: dict[str, dict[str, list[Signal]]] = {
        domain.id: {} for domain in active_domains
    }

    def record(decision: ScheduleDecision, outcome: CollectorOutcome) -> None:
        if outcome_recorder is not None:
            outcome_recorder(decision, outcome)
        result.collector_outcomes.append(
            ScheduledCollectorOutcome(
                source=decision.source,
                domain=decision.domain,
                outcome=outcome,
            )
        )

    # HN is physically fetched once. Its one outcome is persisted for every
    # logical domain that was due, and only those domains receive its signals.
    hn_due = tuple(decision for decision in due if decision.source == "hn")
    if hn_due:
        hn_outcome = HNCollector().collect_with_outcome()
        logger.info("[hn] collected %d shared signals this scheduled run", len(hn_outcome.signals))
        for decision in hn_due:
            record(decision, hn_outcome)
            signals_by_domain[decision.domain]["hn"] = hn_outcome.signals

    for decision in due:
        if decision.source == "hn":
            continue
        domain = domain_by_id[decision.domain]
        collector = _collector_for_source(decision.source, domain)
        outcome = collector.collect_with_outcome()
        record(decision, outcome)
        signals_by_domain[decision.domain][decision.source] = outcome.signals

    due_domains = {decision.domain for decision in due}
    for domain in active_domains:
        if domain.id not in due_domains:
            continue
        source_signals = signals_by_domain[domain.id]
        run_result = _run_domain(
            domain,
            source_signals.pop("hn", []),
            dry_run=dry_run,
            hn_only=False,
            generate_report=generate_report,
            collected_source_signals=source_signals,
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
    collected_source_signals: dict[str, list[Signal]] | None = None,
) -> DomainRunResult:
    """Run all pipeline stages for a single domain."""
    run_result = DomainRunResult(domain_id=domain.id)

    # Captured before any stage below writes problem_history/opportunities
    # -- Stage 3.6's query bound, not an idempotency mechanism (see
    # opportunity_engine/change_detection.py's module docstring). Safe to
    # be conservative/early; must not be late enough to miss a real
    # transition written later in this same run.
    run_started_at = database._now()

    # ── Stage 1: Collect ────────────────────────────────────────────────
    domain_signals: list[Signal] = _retag_for_domain(shared_hn_signals, domain.id)

    if collected_source_signals is not None:
        for signals in collected_source_signals.values():
            domain_signals.extend(signals)
    elif not hn_only:
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

        if domain.sources.github_queries:
            github = GitHubCollector(
                queries=domain.sources.github_queries,
                domain=domain.id,
            )
            domain_signals.extend(github.collect())

        if domain.sources.trends_keywords:
            trends = TrendsCollector(
                keywords=domain.sources.trends_keywords,
                domain=domain.id,
            )
            domain_signals.extend(trends.collect())

        if domain.sources.stackexchange_queries:
            se = StackExchangeCollector(
                queries=domain.sources.stackexchange_queries,
                domain=domain.id,
            )
            domain_signals.extend(se.collect())

        if domain.sources.greenhouse_boards:
            gh_jobs = GreenhouseJobsCollector(
                boards=domain.sources.greenhouse_boards,
                domain=domain.id,
            )
            domain_signals.extend(gh_jobs.collect())

        if domain.sources.sec_companies:
            sec = SECEdgarCollector(
                companies=domain.sources.sec_companies,
                domain=domain.id,
            )
            domain_signals.extend(sec.collect())

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
        extractor = EntityExtractor(domain.graph)
        extraction_results = extractor.extract_batch(domain_signals)
        if not dry_run:
            counts = extractor.persist_results(extraction_results, domain=domain.id)
            run_result.entities_inserted = counts["entities_inserted"]
            run_result.relationships_inserted = counts["relationships_inserted"]
            logger.info(
                "[%s] extracted %d new entities, %d new relationships",
                domain.id, counts["entities_inserted"], counts["relationships_inserted"],
            )

    # ── Stage 2.5: Knowledge-graph decay ────────────────────────────────
    # Runs after extraction/persistence (so anything re-encountered this
    # run has already been reactivated to 'active' before decay evaluates
    # it — see extractor.persist_results()) and before detection (so
    # canonical matching sees this run's current lifecycle states, not
    # last run's). Skipped in dry_run, matching every other stage that
    # writes to the database. See knowledge_graph/decay.py.
    if not dry_run:
        with database.get_connection() as conn:
            decay_counts = decay.run_decay_pass(conn, domain=domain.id)
        run_result.entities_decayed = decay_counts["entities_dormant"] + decay_counts["entities_archived"]
        run_result.relationships_decayed = (
            decay_counts["relationships_dormant"] + decay_counts["relationships_archived"]
        )
        if run_result.entities_decayed or run_result.relationships_decayed:
            logger.info(
                "[%s] decay: %d entities, %d relationships transitioned this run",
                domain.id, run_result.entities_decayed, run_result.relationships_decayed,
            )

    # ── Stage 3: Detect opportunities ───────────────────────────────────
    if len(domain_signals) >= 2:
        detector = PatternDetector(domain)
        if dry_run:
            opps = detector.detect(domain_signals, domain=domain.id)
            run_result.opportunities_detected = len(opps)
        else:
            run_result.opportunities_detected = detector.detect_and_persist(
                domain_signals, domain=domain.id,
            )
    else:
        logger.info("[%s] not enough signals for pattern detection", domain.id)

    # ── Stage 3.5: Problem trajectory lifecycle ─────────────────────────
    # Runs after detection (this run's resolve_problem() calls have
    # already written this week's problem_history events, which trend
    # classification reads) and before report generation (so the report
    # reflects this run's current lifecycle_state/trend, not last run's).
    # Reactivation (archived -> reactivated) already happened earlier,
    # inline inside resolve_problem() the moment new evidence matched —
    # this pass only ever moves state forward. Skipped in dry_run,
    # matching every other stage that writes to the database. See
    # opportunity_engine/lifecycle.py.
    if not dry_run:
        with database.get_connection() as conn:
            lifecycle_counts = lifecycle.run_lifecycle_pass(conn, domain=domain.id)
        run_result.problems_archived = lifecycle_counts["archived"]
        if lifecycle_counts["archived"]:
            logger.info(
                "[%s] lifecycle: %d problem(s) archived this run",
                domain.id, lifecycle_counts["archived"],
            )

    # ── Stage 3.6: Change detection ─────────────────────────────────────
    # Projects this run's Problem lifecycle/trend transitions (already
    # written to problem_history by Stage 3/3.5 above) and any Opportunity
    # tier movements into change_events -- a projection layer, not a
    # second intelligence engine; see opportunity_engine/change_detection.py's
    # module docstring for the full reasoning. Skipped in dry_run, matching
    # every other stage that writes to the database.
    #
    # Wrapped in its own try/except, unlike decay/lifecycle above: a
    # change-detection bug must never take down this run's already-
    # committed intelligence (Stage 3/3.5's writes) or block Stage 4's
    # report (Architectural Invariant 16, Failure Isolation). This is a
    # stronger isolation guarantee than decay/lifecycle get, deliberately
    # -- unlike those two, change_events is explicitly reconstructible
    # (see that module's docstring), so swallowing a failure here and
    # logging it costs nothing but this run's convenience, whereas a
    # silent decay/lifecycle failure would mean a real, non-reconstructible
    # state transition went unrecorded.
    if not dry_run:
        try:
            with database.get_connection() as conn:
                cd_counts = change_detection.run_change_detection(
                    conn, domain=domain.id, since=run_started_at,
                )
            run_result.change_events_recorded = cd_counts["written"]
            if cd_counts["written"]:
                logger.info(
                    "[%s] change detection: %d event(s) recorded (%d high-significance)",
                    domain.id, cd_counts["written"], cd_counts["high_significance"],
                )
        except Exception:
            logger.exception(
                "[%s] change detection failed; continuing pipeline", domain.id,
            )

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


def _collector_for_source(source: str, domain: DomainConfig):
    """Instantiate a configured domain-scoped collector for a plan entry."""
    if source == "reddit":
        return RedditCollector(subreddits=domain.sources.reddit_sources, domain=domain.id)
    if source == "rss":
        return RSSCollector(
            feeds=[(feed.url, feed.description) for feed in domain.sources.rss_feeds],
            domain=domain.id,
        )
    if source == "github":
        return GitHubCollector(queries=domain.sources.github_queries, domain=domain.id)
    if source == "trends":
        return TrendsCollector(keywords=domain.sources.trends_keywords, domain=domain.id)
    if source == "stackexchange":
        return StackExchangeCollector(
            queries=domain.sources.stackexchange_queries,
            domain=domain.id,
        )
    if source == "greenhouse_jobs":
        return GreenhouseJobsCollector(
            boards=domain.sources.greenhouse_boards,
            domain=domain.id,
        )
    if source == "sec_edgar":
        return SECEdgarCollector(
            companies=domain.sources.sec_companies,
            domain=domain.id,
        )
    raise ValueError(f"Unsupported scheduled collector source: {source}")


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
