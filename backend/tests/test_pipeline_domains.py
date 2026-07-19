"""
tests/test_pipeline_domains.py — Integration tests for the domain-aware
pipeline (Milestone 4a).

These tests exercise pipeline.run_full_pipeline() end-to-end against a
real (temporary, file-based) SQLite database, with the three collectors
monkeypatched to return canned Signal objects instead of making network
calls — collectors themselves are unit-tested elsewhere; this file tests
the wiring between DomainRegistry, the pipeline, and the database.

Covered:
  - a single active domain (the real "business" domain) runs correctly
  - two active domains can run in the same pipeline invocation
  - every persisted Signal / Opportunity / WeeklyReport row carries the
    correct domain value, including the shared-collector fan-out case
  - a shared source item (Hacker News) persists one independent row per
    active domain, proving the (source, source_id, domain) dedup index
    is what's actually enforced (not the old (source, source_id) index)
  - the pipeline refuses to run with no active domains, rather than
    silently doing nothing
  - collect.py and main.py both delegate to pipeline.run_full_pipeline
    and do not reimplement collection/detection themselves
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import database
import pipeline
from domains.base import (
    DomainConfig,
    DomainKeywords,
    DomainKnowledgeGraph,
    DomainMetadata,
    DomainReporting,
    DomainScoring,
    DomainSources,
    ScoringDimension,
)
from domains.business import DOMAIN_CONFIG as BUSINESS_DOMAIN_CONFIG
from domains.registry import DomainRegistry
from models import Signal


# ── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Point database.py at a fresh, empty SQLite file for this test."""
    db_path = tmp_path / "test_pipeline.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    database.initialize()
    yield db_path


@pytest.fixture(autouse=True)
def clean_registry():
    """Every test starts and ends with an empty DomainRegistry."""
    DomainRegistry.clear()
    yield
    DomainRegistry.clear()


def _second_domain(domain_id: str = "test_intel") -> DomainConfig:
    """A minimal, valid second domain used only to test multi-domain wiring."""
    return DomainConfig(
        metadata=DomainMetadata(
            id=domain_id, name="Test Intel", description="Fixture domain for tests",
            version="0.0.1", icon="flask", color="#123456", category="test",
        ),
        sources=DomainSources(reddit_sources=["testsubreddit"], rss_feeds=[]),
        keywords=DomainKeywords(),
        graph=DomainKnowledgeGraph(),
        scoring=DomainScoring(dimensions=[
            ScoringDimension(id="signal_strength", label="Signal Strength",
                              description="test dimension", weight=1.0),
        ]),
        reporting=DomainReporting(title="Test Intel Report", description="test"),
    )


def _fake_signals(prefix: str, source: str, n: int, offset: int = 0) -> list[Signal]:
    return [
        Signal(
            source=source,
            source_id=f"{prefix}-{source}-{i + offset}",
            title=f"Ask HN: is there a tool for {prefix} problem {i}?",
            content="",
            platform_score=100 + i,
            comment_count=20 + i,
            tags=["ask", "demand_signal"],
        )
        for i in range(n)
    ]


def _patch_collectors(monkeypatch, hn_signals, reddit_by_domain, rss_by_domain=None):
    """
    Replace HNCollector/RedditCollector/RSSCollector.collect() with canned
    data so pipeline tests never make a real HTTP request. Each fake
    respects `self.domain`, matching how the real collectors are used.
    """
    import collectors.hn_collector as hn_mod
    import collectors.reddit_collector as reddit_mod
    import collectors.rss_collector as rss_mod

    def fake_hn_collect(self, limit=None):
        return list(hn_signals)

    def fake_reddit_collect(self, limit=None):
        return list(reddit_by_domain.get(self.domain, []))

    def fake_rss_collect(self, limit=None):
        return list((rss_by_domain or {}).get(self.domain, []))

    monkeypatch.setattr(hn_mod.HNCollector, "collect", fake_hn_collect)
    monkeypatch.setattr(reddit_mod.RedditCollector, "collect", fake_reddit_collect)
    monkeypatch.setattr(rss_mod.RSSCollector, "collect", fake_rss_collect)


def _rows(query: str) -> list:
    with database.get_connection() as conn:
        return conn.execute(query).fetchall()


# ── Single domain ─────────────────────────────────────────────────────

class TestSingleDomain:
    def test_business_domain_runs_correctly(self, fresh_db, monkeypatch):
        DomainRegistry.register(BUSINESS_DOMAIN_CONFIG)

        hn_signals = _fake_signals("shared", "hn", 3)
        _patch_collectors(
            monkeypatch, hn_signals,
            reddit_by_domain={"business": _fake_signals("business", "reddit", 3)},
        )

        result = pipeline.run_full_pipeline(generate_report=True)

        assert len(result.domains) == 1
        d = result.domains[0]
        assert d.domain_id == "business"
        assert d.signals_collected == 6          # 3 shared HN + 3 reddit
        assert d.signals_persisted == 6
        assert d.report_generated is True

        signal_rows = _rows("SELECT domain FROM signals")
        assert len(signal_rows) == 6
        assert all(r["domain"] == "business" for r in signal_rows)

        report_rows = _rows("SELECT domain FROM reports")
        assert len(report_rows) == 1
        assert report_rows[0]["domain"] == "business"


# ── Multi domain ─────────────────────────────────────────────────────

class TestMultiDomain:
    def test_multiple_active_domains_run(self, fresh_db, monkeypatch):
        DomainRegistry.register(BUSINESS_DOMAIN_CONFIG)
        DomainRegistry.register(_second_domain())

        hn_signals = _fake_signals("shared", "hn", 2)
        _patch_collectors(
            monkeypatch, hn_signals,
            reddit_by_domain={
                "business":   _fake_signals("business", "reddit", 2),
                "test_intel": _fake_signals("test_intel", "reddit", 2, offset=100),
            },
        )

        result = pipeline.run_full_pipeline()

        assert {d.domain_id for d in result.domains} == {"business", "test_intel"}
        for d in result.domains:
            assert d.signals_collected == 4   # 2 shared HN + 2 domain reddit
            assert d.signals_persisted == 4

    def test_domain_values_correctly_stored(self, fresh_db, monkeypatch):
        DomainRegistry.register(BUSINESS_DOMAIN_CONFIG)
        DomainRegistry.register(_second_domain())

        hn_signals = _fake_signals("shared", "hn", 2)
        _patch_collectors(
            monkeypatch, hn_signals,
            reddit_by_domain={
                "business":   _fake_signals("business", "reddit", 2),
                "test_intel": _fake_signals("test_intel", "reddit", 2, offset=100),
            },
        )

        pipeline.run_full_pipeline(generate_report=True)

        signal_domains = {r["domain"] for r in _rows("SELECT domain FROM signals")}
        assert signal_domains == {"business", "test_intel"}

        # The same shared HN source_ids must appear once per domain — this
        # is the concrete proof that the (source, source_id, domain) dedup
        # index (not the old (source, source_id) index) is what's enforced.
        hn_rows = _rows("SELECT source_id, domain FROM signals WHERE source = 'hn'")
        assert len(hn_rows) == 4  # 2 shared HN items x 2 domains
        assert {r["source_id"] for r in hn_rows} == {s.source_id for s in hn_signals}
        assert {r["domain"] for r in hn_rows} == {"business", "test_intel"}

        report_domains = {r["domain"] for r in _rows("SELECT domain FROM reports")}
        assert report_domains == {"business", "test_intel"}

        # Whether a cluster actually forms depends on the detector's
        # scoring thresholds, which is out of scope here — assert only
        # that whatever IS persisted carries a valid domain tag.
        for row in _rows("SELECT domain FROM opportunities"):
            assert row["domain"] in {"business", "test_intel"}

    def test_no_active_domains_raises(self, fresh_db):
        with pytest.raises(RuntimeError):
            pipeline.run_full_pipeline()


# ── Entry-point parity ───────────────────────────────────────────────

class TestEntryPointParity:
    """
    Guards against the duplicate-pipeline regression M4a fixed: collect.py
    and main.py must both delegate to pipeline.run_full_pipeline rather
    than each maintaining their own copy of collection/detection logic.
    """

    def test_collect_py_calls_the_shared_pipeline_function(self):
        import collect
        assert collect.run_full_pipeline is pipeline.run_full_pipeline

    def test_neither_entry_point_reimplements_pipeline_logic(self):
        import collect
        import main

        collect_src = Path(collect.__file__).read_text()
        main_src = Path(main.__file__).read_text()

        assert "run_full_pipeline" in collect_src
        assert "run_full_pipeline" in main_src

        for forbidden in ("PatternDetector(", "HNCollector(", "RedditCollector("):
            assert forbidden not in collect_src, f"collect.py reimplements pipeline logic: {forbidden}"
            assert forbidden not in main_src, f"main.py reimplements pipeline logic: {forbidden}"
