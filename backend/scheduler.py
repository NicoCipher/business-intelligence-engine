"""
scheduler.py — persistent, per-domain collector scheduling.

The scheduler decides which collectors are due; it does not collect data or
run the intelligence pipeline. That separation keeps pipeline.py as BIA's one
canonical collector orchestrator while allowing collector_state to survive
ephemeral GitHub Actions runners.

State is isolated by (source, domain). Hacker News is an intentional physical
exception: pipeline.py fetches it once when any due domain needs it, then
records the same attempt outcome independently for each due domain.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Iterable

import database
from collectors.base import CollectorOutcome, CollectorOutcomeKind
from domains.base import DomainConfig


MAX_BACKOFF_MINUTES = 24 * 60

# These are the schema-v10 defaults. They live here as operational defaults
# for newly activated domains; the migration remains responsible for seeding
# an existing Business database exactly once.
COLLECTOR_DEFAULTS: tuple[tuple[str, int, int], ...] = (
    ("hn",             60, 3),
    ("reddit",        120, 4),
    ("rss",           180, 5),
    ("github",        240, 4),
    ("trends",        360, 7),
    ("stackexchange", 240, 4),
)


@dataclass(frozen=True)
class CollectorState:
    source: str
    domain: str
    interval_minutes: int
    priority: int
    quota_per_period: int
    quota_period_minutes: int
    quota_used: int
    quota_reset_at: datetime | None
    last_run_at: datetime | None
    last_success_at: datetime | None
    last_failure_at: datetime | None
    consecutive_failures: int
    backoff_until: datetime | None
    enabled: bool


@dataclass(frozen=True)
class ScheduleDecision:
    state: CollectorState
    due: bool
    reason: str

    @property
    def source(self) -> str:
        return self.state.source

    @property
    def domain(self) -> str:
        return self.state.domain


@dataclass(frozen=True)
class SchedulePlan:
    created_at: datetime
    decisions: tuple[ScheduleDecision, ...]

    @property
    def due(self) -> tuple[ScheduleDecision, ...]:
        return tuple(decision for decision in self.decisions if decision.due)

    @property
    def skipped(self) -> tuple[ScheduleDecision, ...]:
        return tuple(decision for decision in self.decisions if not decision.due)

    def is_due(self, source: str, domain: str) -> bool:
        return any(
            decision.due and decision.source == source and decision.domain == domain
            for decision in self.decisions
        )

    def due_domains(self, source: str) -> tuple[str, ...]:
        return tuple(
            decision.domain for decision in self.due if decision.source == source
        )


def _as_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return _as_utc(parsed)


def _timestamp(value: datetime) -> str:
    return _as_utc(value).isoformat()


def _state_from_row(row) -> CollectorState:
    return CollectorState(
        source=row["source"],
        domain=row["domain"],
        interval_minutes=row["interval_minutes"],
        priority=row["priority"],
        quota_per_period=row["quota_per_period"],
        quota_period_minutes=row["quota_period_minutes"],
        quota_used=row["quota_used"],
        quota_reset_at=_parse_timestamp(row["quota_reset_at"]),
        last_run_at=_parse_timestamp(row["last_run_at"]),
        last_success_at=_parse_timestamp(row["last_success_at"]),
        last_failure_at=_parse_timestamp(row["last_failure_at"]),
        consecutive_failures=row["consecutive_failures"],
        backoff_until=_parse_timestamp(row["backoff_until"]),
        enabled=bool(row["enabled"]),
    )


def _source_is_configured(source: str, domain: DomainConfig) -> bool:
    if source == "hn":
        return True
    if source == "reddit":
        return bool(domain.sources.reddit_sources)
    if source == "rss":
        return bool(domain.sources.rss_feeds)
    if source == "github":
        return bool(domain.sources.github_queries)
    if source == "trends":
        return bool(domain.sources.trends_keywords)
    if source == "stackexchange":
        return bool(domain.sources.stackexchange_queries)
    return False


class AdaptiveScheduler:
    """Read and atomically update persisted collector scheduling state."""

    def __init__(self, now: datetime | None = None):
        self.now = _as_utc(now)

    def plan(self, domains: Iterable[DomainConfig], *, hn_only: bool = False) -> SchedulePlan:
        domains = tuple(domains)
        self._provision_domains(domains)

        decisions: list[ScheduleDecision] = []
        for domain in domains:
            states = self._states_for_domain(domain.id)
            for state in states:
                refreshed = self._reset_quota_if_due(state)
                decisions.append(self._decision_for(refreshed, domain, hn_only=hn_only))

        # Stable source ordering makes a repeated plan reproducible; priority
        # remains a tie-breaker, never a gate that drops a due source.
        decisions.sort(key=lambda item: (item.state.priority, item.source, item.domain))
        return SchedulePlan(created_at=self.now, decisions=tuple(decisions))

    def record_outcome(self, decision: ScheduleDecision, outcome: CollectorOutcome) -> CollectorState:
        """Persist one attempted collector outcome in its own transaction.

        This is intentionally called immediately after each collection attempt.
        A later extraction/detection/report failure therefore cannot discard
        completed scheduler bookkeeping from earlier sources in the invocation.
        """
        if not decision.due:
            raise ValueError("Cannot record an outcome for a skipped collector decision")
        if outcome.source != decision.source:
            raise ValueError("Collector outcome source does not match scheduler decision")
        if outcome.kind is CollectorOutcomeKind.SKIPPED:
            raise ValueError("Skipped outcomes are not collector attempts")

        now = self.now
        with database.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM collector_state WHERE source = ? AND domain = ?",
                (decision.source, decision.domain),
            ).fetchone()
            if row is None:
                raise RuntimeError(f"Missing collector_state for {decision.source}/{decision.domain}")
            state = _state_from_row(row)
            state = self._reset_quota_in_connection(conn, state)

            quota_used = state.quota_used + 1
            last_run_at = _timestamp(now)
            if outcome.kind is CollectorOutcomeKind.SUCCESS:
                updates = {
                    "last_success_at": _timestamp(now),
                    "last_failure_at": row["last_failure_at"],
                    "consecutive_failures": 0,
                    "backoff_until": "",
                }
            else:
                failures = state.consecutive_failures + 1
                delay = min(
                    state.interval_minutes * (2 ** (failures - 1)),
                    MAX_BACKOFF_MINUTES,
                )
                if outcome.kind is CollectorOutcomeKind.RATE_LIMITED:
                    delay = max(delay, 60)
                updates = {
                    "last_success_at": row["last_success_at"],
                    "last_failure_at": _timestamp(now),
                    "consecutive_failures": failures,
                    "backoff_until": _timestamp(now + timedelta(minutes=delay)),
                }

            conn.execute(
                """
                UPDATE collector_state
                   SET quota_used = ?, last_run_at = ?, last_success_at = ?,
                       last_failure_at = ?, consecutive_failures = ?,
                       backoff_until = ?, updated_at = ?
                 WHERE source = ? AND domain = ?
                """,
                (
                    quota_used,
                    last_run_at,
                    updates["last_success_at"],
                    updates["last_failure_at"],
                    updates["consecutive_failures"],
                    updates["backoff_until"],
                    _timestamp(now),
                    decision.source,
                    decision.domain,
                ),
            )
            conn.commit()
            updated = conn.execute(
                "SELECT * FROM collector_state WHERE source = ? AND domain = ?",
                (decision.source, decision.domain),
            ).fetchone()
        return _state_from_row(updated)

    def _provision_domains(self, domains: Iterable[DomainConfig]) -> None:
        now = _timestamp(self.now)
        with database.get_connection() as conn:
            for domain in domains:
                for source, interval, priority in COLLECTOR_DEFAULTS:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO collector_state
                            (source, domain, interval_minutes, priority, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (source, domain.id, interval, priority, now),
                    )
            conn.commit()

    def _states_for_domain(self, domain_id: str) -> tuple[CollectorState, ...]:
        with database.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM collector_state WHERE domain = ?",
                (domain_id,),
            ).fetchall()
        return tuple(_state_from_row(row) for row in rows)

    def _reset_quota_if_due(self, state: CollectorState) -> CollectorState:
        if state.quota_per_period == 0:
            return state
        with database.get_connection() as conn:
            updated = self._reset_quota_in_connection(conn, state)
            conn.commit()
        return updated

    def _reset_quota_in_connection(self, conn, state: CollectorState) -> CollectorState:
        if state.quota_per_period == 0:
            return state
        if state.quota_reset_at is not None and state.quota_reset_at > self.now:
            return state

        reset_at = self.now + timedelta(minutes=state.quota_period_minutes)
        conn.execute(
            """
            UPDATE collector_state
               SET quota_used = 0, quota_reset_at = ?, updated_at = ?
             WHERE source = ? AND domain = ?
            """,
            (_timestamp(reset_at), _timestamp(self.now), state.source, state.domain),
        )
        return replace(state, quota_used=0, quota_reset_at=reset_at)

    def _decision_for(
        self,
        state: CollectorState,
        domain: DomainConfig,
        *,
        hn_only: bool,
    ) -> ScheduleDecision:
        if hn_only and state.source != "hn":
            return ScheduleDecision(state, False, "hn_only")
        if not _source_is_configured(state.source, domain):
            return ScheduleDecision(state, False, "unconfigured")
        if not state.enabled:
            return ScheduleDecision(state, False, "disabled")
        if state.quota_per_period and state.quota_used >= state.quota_per_period:
            return ScheduleDecision(state, False, "quota_exhausted")
        if state.backoff_until is not None and state.backoff_until > self.now:
            return ScheduleDecision(state, False, "backoff")
        if state.last_run_at is None:
            return ScheduleDecision(state, True, "never_run")
        if self.now >= state.last_run_at + timedelta(minutes=state.interval_minutes):
            return ScheduleDecision(state, True, "interval_elapsed")
        return ScheduleDecision(state, False, "interval_not_elapsed")
