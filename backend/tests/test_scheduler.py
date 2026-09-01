"""Deterministic coverage for the schema-v10 adaptive scheduler milestone."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import collect
import database
import pipeline
import scheduler
from collectors.base import (
    BaseCollector,
    CollectorError,
    CollectorOutcome,
    CollectorOutcomeKind,
    ConfigurationError,
    RateLimitError,
)
from collectors.hn_collector import HNCollector
from domains.base import (
    DomainConfig,
    DomainKeywords,
    DomainKnowledgeGraph,
    DomainMetadata,
    DomainReporting,
    DomainScoring,
    DomainSources,
    ScoringDimension,
    StackExchangeQuery,
)
from domains.registry import DomainRegistry
from models import Signal


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "scheduler.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    database.initialize()
    yield db_path


@pytest.fixture(autouse=True)
def clean_registry():
    DomainRegistry.clear()
    yield
    DomainRegistry.clear()


def _domain(domain_id: str, *, reddit: bool = False) -> DomainConfig:
    return DomainConfig(
        metadata=DomainMetadata(
            id=domain_id, name=domain_id, description="scheduler fixture",
            version="0.0.1", icon="flask", color="#123456", category="test",
        ),
        sources=DomainSources(reddit_sources=["fixture"] if reddit else []),
        keywords=DomainKeywords(),
        graph=DomainKnowledgeGraph(),
        scoring=DomainScoring(dimensions=[
            ScoringDimension("signal_strength", "Signal Strength", "fixture", 1.0),
        ]),
        reporting=DomainReporting(title="Scheduler fixture", description="fixture"),
    )


def _update_state(source: str, domain: str, **values) -> None:
    assignments = ", ".join(f"{key} = ?" for key in values)
    with database.get_connection() as conn:
        conn.execute(
            f"UPDATE collector_state SET {assignments} WHERE source = ? AND domain = ?",
            (*values.values(), source, domain),
        )
        conn.commit()


def _row(source: str, domain: str):
    with database.get_connection() as conn:
        return conn.execute(
            "SELECT * FROM collector_state WHERE source = ? AND domain = ?",
            (source, domain),
        ).fetchone()


def _decision(plan: scheduler.SchedulePlan, source: str, domain: str):
    return next(item for item in plan.decisions if item.source == source and item.domain == domain)


def _signal() -> Signal:
    return Signal(
        source="hn", source_id="shared-1", title="Ask HN: fixture", content="",
        platform_score=10, comment_count=2, tags=["ask"],
    )


class _OutcomeCollector(BaseCollector):
    SOURCE_NAME = "fixture"

    def __init__(self, error: Exception | None = None):
        super().__init__()
        self.error = error

    def _fetch(self, limit):
        if self.error:
            raise self.error
        if False:
            yield None


class TestCollectorOutcomeBoundary:
    def test_zero_result_is_success_and_legacy_collect_stays_a_list(self):
        collector = _OutcomeCollector()
        outcome = collector.collect_with_outcome()
        assert outcome.kind is CollectorOutcomeKind.SUCCESS
        assert outcome.signals == []
        assert collector.collect() == []

    @pytest.mark.parametrize(
        "error, expected",
        [
            (CollectorError("temporary"), CollectorOutcomeKind.TRANSIENT_FAILURE),
            (RateLimitError("too many"), CollectorOutcomeKind.RATE_LIMITED),
            (ConfigurationError("missing key"), CollectorOutcomeKind.CONFIGURATION_FAILURE),
        ],
    )
    def test_scheduler_outcome_categories(self, error, expected):
        assert _OutcomeCollector(error).collect_with_outcome().kind is expected


class TestDuePlanning:
    def test_first_run_due_and_unconfigured_sources_skipped(self, fresh_db):
        domain = _domain("business", reddit=True)
        plan = scheduler.AdaptiveScheduler(NOW).plan([domain])

        assert {(item.source, item.reason) for item in plan.due} == {
            ("hn", "never_run"), ("reddit", "never_run"),
        }
        assert {
            item.source for item in plan.skipped if item.reason == "unconfigured"
        } == {"rss", "github", "trends", "stackexchange"}

    def test_per_domain_state_is_provisioned_and_isolated(self, fresh_db):
        business = _domain("business")
        other = _domain("other")
        scheduler.AdaptiveScheduler(NOW).plan([business, other])
        _update_state("hn", "business", last_run_at=NOW.isoformat())

        plan = scheduler.AdaptiveScheduler(NOW + timedelta(minutes=30)).plan([business, other])
        assert _decision(plan, "hn", "business").reason == "interval_not_elapsed"
        assert _decision(plan, "hn", "other").due is True
        with database.get_connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM collector_state WHERE domain = 'other'").fetchone()[0] == 6

    def test_disabled_backoff_quota_and_lazy_reset_gate_independently(self, fresh_db):
        domain = _domain("business", reddit=True)
        future = NOW + timedelta(hours=2)
        _update_state(
            "reddit", "business", enabled=0, quota_per_period=1, quota_used=1,
            quota_reset_at=future.isoformat(), backoff_until=future.isoformat(),
        )
        plan = scheduler.AdaptiveScheduler(NOW).plan([domain])
        assert _decision(plan, "reddit", "business").reason == "disabled"

        _update_state("reddit", "business", enabled=1)
        plan = scheduler.AdaptiveScheduler(NOW).plan([domain])
        assert _decision(plan, "reddit", "business").reason == "quota_exhausted"

        _update_state("reddit", "business", quota_reset_at=(NOW - timedelta(minutes=1)).isoformat())
        plan = scheduler.AdaptiveScheduler(NOW).plan([domain])
        assert _decision(plan, "reddit", "business").reason == "backoff"
        assert _row("reddit", "business")["quota_used"] == 0


class TestStateTransitions:
    def test_zero_signal_success_resets_failure_and_counts_one_attempt(self, fresh_db):
        domain = _domain("business", reddit=True)
        _update_state("reddit", "business", consecutive_failures=2, backoff_until="")
        clock = scheduler.AdaptiveScheduler(NOW)
        decision = _decision(clock.plan([domain]), "reddit", "business")
        clock.record_outcome(decision, CollectorOutcome("reddit", CollectorOutcomeKind.SUCCESS, []))

        row = _row("reddit", "business")
        assert row["last_run_at"] == NOW.isoformat()
        assert row["last_success_at"] == NOW.isoformat()
        assert row["consecutive_failures"] == 0
        assert row["backoff_until"] == ""
        assert row["quota_used"] == 1

    def test_failure_backoff_is_exponential_capped_and_rate_limited_minimum_is_one_hour(self, fresh_db):
        domain = _domain("business", reddit=True)
        _update_state("reddit", "business", interval_minutes=30)
        clock = scheduler.AdaptiveScheduler(NOW)
        decision = _decision(clock.plan([domain]), "reddit", "business")
        clock.record_outcome(decision, CollectorOutcome("reddit", CollectorOutcomeKind.TRANSIENT_FAILURE, []))
        assert _row("reddit", "business")["backoff_until"] == (NOW + timedelta(minutes=30)).isoformat()

        later = scheduler.AdaptiveScheduler(NOW + timedelta(minutes=30))
        decision = _decision(later.plan([domain]), "reddit", "business")
        later.record_outcome(decision, CollectorOutcome("reddit", CollectorOutcomeKind.RATE_LIMITED, []))
        assert _row("reddit", "business")["backoff_until"] == (NOW + timedelta(minutes=90)).isoformat()

        _update_state("reddit", "business", consecutive_failures=10, backoff_until="", interval_minutes=240)
        capped = scheduler.AdaptiveScheduler(NOW + timedelta(days=1))
        decision = _decision(capped.plan([domain]), "reddit", "business")
        capped.record_outcome(decision, CollectorOutcome("reddit", CollectorOutcomeKind.CONFIGURATION_FAILURE, []))
        assert _row("reddit", "business")["backoff_until"] == (NOW + timedelta(days=2)).isoformat()

    def test_quota_only_increments_for_attempts_and_resets_after_period(self, fresh_db):
        domain = _domain("business", reddit=True)
        reset = NOW + timedelta(hours=4)
        _update_state(
            "reddit", "business", quota_per_period=1, quota_used=0,
            quota_period_minutes=60, quota_reset_at=reset.isoformat(),
        )
        clock = scheduler.AdaptiveScheduler(NOW)
        decision = _decision(clock.plan([domain]), "reddit", "business")
        clock.record_outcome(decision, CollectorOutcome("reddit", CollectorOutcomeKind.SUCCESS, []))
        assert _row("reddit", "business")["quota_used"] == 1

        exhausted = scheduler.AdaptiveScheduler(NOW + timedelta(hours=2))
        assert _decision(exhausted.plan([domain]), "reddit", "business").reason == "quota_exhausted"
        refreshed = scheduler.AdaptiveScheduler(reset + timedelta(seconds=1))
        assert _decision(refreshed.plan([domain]), "reddit", "business").due is True
        assert _row("reddit", "business")["quota_used"] == 0


class TestPipelineSchedulerIntegration:
    def test_shared_hn_runs_once_fans_out_only_due_domains_and_updates_each_state(self, fresh_db, monkeypatch):
        business = _domain("business")
        other = _domain("other")
        DomainRegistry.register(business)
        DomainRegistry.register(other)
        clock = scheduler.AdaptiveScheduler(NOW)
        plan = clock.plan(DomainRegistry.get_active())
        calls = []

        def fake_hn(self, limit=None):
            calls.append(limit)
            return CollectorOutcome("hn", CollectorOutcomeKind.SUCCESS, [_signal()])

        monkeypatch.setattr(HNCollector, "collect_with_outcome", fake_hn)
        result = pipeline.run_full_pipeline(source_plan=plan, outcome_recorder=clock.record_outcome)

        assert calls == [None]
        assert {(item.source, item.domain) for item in result.collector_outcomes} == {
            ("hn", "business"), ("hn", "other"),
        }
        with database.get_connection() as conn:
            rows = conn.execute("SELECT domain FROM signals WHERE source = 'hn'").fetchall()
        assert {row["domain"] for row in rows} == {"business", "other"}
        assert _row("hn", "business")["last_success_at"] == NOW.isoformat()
        assert _row("hn", "other")["last_success_at"] == NOW.isoformat()

    def test_no_due_sources_does_not_enter_pipeline_stages_or_generate_report(self, fresh_db, monkeypatch):
        business = _domain("business")
        DomainRegistry.register(business)
        _update_state("hn", "business", last_run_at=NOW.isoformat())
        plan = scheduler.AdaptiveScheduler(NOW + timedelta(minutes=1)).plan([business])
        monkeypatch.setattr(HNCollector, "collect_with_outcome", lambda *_: pytest.fail("HN should not run"))

        result = pipeline.run_full_pipeline(source_plan=plan, generate_report=True)
        assert result.domains == []
        assert result.collector_outcomes == []
        with database.get_connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 0

    def test_manual_pipeline_run_is_a_full_override_not_a_due_state_consumer(self, fresh_db, monkeypatch):
        business = _domain("business")
        DomainRegistry.register(business)
        _update_state("hn", "business", last_run_at=(NOW + timedelta(days=1)).isoformat())
        calls = []

        def fake_legacy_hn(self, limit=None):
            calls.append(limit)
            return []

        monkeypatch.setattr(HNCollector, "collect", fake_legacy_hn)
        pipeline.run_full_pipeline()
        assert calls == [None]


class TestPartialRunDurability:
    def test_collect_snapshots_completed_state_after_later_critical_failure(self, fresh_db, tmp_path, monkeypatch):
        business = _domain("business")
        backup_dir = tmp_path / "backups"
        import persistence

        monkeypatch.setattr(persistence, "BACKUP_DIR", backup_dir)
        monkeypatch.setattr(persistence.config, "DB_PATH", fresh_db)
        monkeypatch.setattr(collect, "parse_args", lambda: argparse.Namespace(report=False, hn_only=True, dry_run=False))
        monkeypatch.setattr(DomainRegistry, "discover_and_register", lambda: None)
        monkeypatch.setattr(DomainRegistry, "get_active", lambda: [business])
        monkeypatch.setattr(
            HNCollector,
            "collect_with_outcome",
            lambda *_: CollectorOutcome("hn", CollectorOutcomeKind.SUCCESS, []),
        )
        monkeypatch.setattr(pipeline, "_run_domain", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("later stage failed")))

        assert collect.main() == 1
        assert _row("hn", "business")["last_success_at"]
        assert list(backup_dir.glob("bia-*.db"))


def test_hourly_workflow_uses_scheduler_heartbeat_and_builtin_github_token():
    workflow = (Path(__file__).parents[2] / ".github" / "workflows" / "collect.yml").read_text()
    assert "cron: '0 * * * *'" in workflow
    assert "GITHUB_TOKEN:         ${{ github.token }}" in workflow
    assert 'if [ -z "$REDDIT_CLIENT_ID" ]' not in workflow
    assert "contents: read" in workflow
    assert "actions: read" in workflow
    assert "adaptive" in workflow.lower()


# ── Stack Exchange scheduler integration ─────────────────────────────────

class TestStackExchangeSchedulerIntegration:
    def test_stackexchange_in_collector_defaults(self):
        sources = {name for name, *_ in scheduler.COLLECTOR_DEFAULTS}
        assert "stackexchange" in sources

    def test_source_is_configured_with_no_queries(self):
        domain = _domain("business")
        assert not scheduler._source_is_configured("stackexchange", domain)

    def test_source_is_configured_with_queries(self):
        domain_with_se = DomainConfig(
            metadata=DomainMetadata(
                id="business", name="business", description="SE fixture",
                version="0.0.1", icon="flask", color="#123456", category="test",
            ),
            sources=DomainSources(
                stackexchange_queries=[
                    StackExchangeQuery("stackoverflow", ["saas"]),
                ],
            ),
            keywords=DomainKeywords(),
            graph=DomainKnowledgeGraph(),
            scoring=DomainScoring(dimensions=[
                ScoringDimension("signal_strength", "Signal Strength", "fixture", 1.0),
            ]),
            reporting=DomainReporting(title="SE fixture", description="fixture"),
        )
        assert scheduler._source_is_configured("stackexchange", domain_with_se)

    def test_stackexchange_skipped_when_unconfigured(self, fresh_db):
        domain = _domain("business")
        plan = scheduler.AdaptiveScheduler(NOW).plan([domain])
        skipped_sources = {item.source for item in plan.skipped if item.reason == "unconfigured"}
        assert "stackexchange" in skipped_sources

    def test_stackexchange_due_on_first_run_when_configured(self, fresh_db):
        domain_with_se = DomainConfig(
            metadata=DomainMetadata(
                id="business", name="business", description="SE fixture",
                version="0.0.1", icon="flask", color="#123456", category="test",
            ),
            sources=DomainSources(
                stackexchange_queries=[
                    StackExchangeQuery("stackoverflow", ["saas"]),
                ],
            ),
            keywords=DomainKeywords(),
            graph=DomainKnowledgeGraph(),
            scoring=DomainScoring(dimensions=[
                ScoringDimension("signal_strength", "Signal Strength", "fixture", 1.0),
            ]),
            reporting=DomainReporting(title="SE fixture", description="fixture"),
        )
        plan = scheduler.AdaptiveScheduler(NOW).plan([domain_with_se])
        due_sources = {item.source for item in plan.due}
        assert "stackexchange" in due_sources

    def test_stackexchange_interval_is_240_minutes(self):
        defaults_by_source = {name: interval for name, interval, *_ in scheduler.COLLECTOR_DEFAULTS}
        assert defaults_by_source["stackexchange"] == 240
