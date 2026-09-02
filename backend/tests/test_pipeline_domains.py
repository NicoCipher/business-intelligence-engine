"""
tests/test_pipeline_domains.py — Integration tests for the domain-aware
pipeline (Milestone 4a).

These tests exercise pipeline.run_full_pipeline() end-to-end against a
real (temporary, file-based) SQLite database, with all five collectors
(HN, Reddit, RSS, GitHub, Trends) monkeypatched to return canned Signal
objects instead of making network calls — collectors themselves are
unit-tested elsewhere (test_reddit_collector.py [pending],
test_rss_collector.py, test_github_collector.py,
test_trends_collector.py); this file tests the wiring between
DomainRegistry, the pipeline, and the database.

GitHub and Trends are patched to return [] by default even in tests
that don't explicitly care about them (see _patch_collectors below) —
BUSINESS_DOMAIN_CONFIG is the real production domain config and does
carry real github_queries/trends_keywords, so leaving either
unpatched means a live network call, not a test failure with a wrong
count. This was a real regression once (CI hit a live Google Trends
429 mid-test-run) and the fix is structural: _patch_collectors always
patches all five, so no future test using it can reintroduce the leak
by simply forgetting to pass a kwarg.

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


def _patch_collectors(
    monkeypatch, hn_signals, reddit_by_domain,
    rss_by_domain=None, github_by_domain=None, trends_by_domain=None,
    stackexchange_by_domain=None, greenhouse_by_domain=None,
    sec_edgar_by_domain=None,
):
    """
    Replace every collector's .collect() with canned data so pipeline
    tests never make a real HTTP request. Each fake respects
    `self.domain`, matching how the real collectors are used.

    GitHub, Trends, StackExchange, GreenhouseJobs, and SECEdgar default to an empty dict,
    i.e. every domain gets []. This is a deliberate choice, not an oversight:
    BUSINESS_DOMAIN_CONFIG (used directly by several tests below, since it's the real
    production domain config) carries real queries/boards/companies -- pipeline._run_domain()
    calls those collectors unconditionally whenever a domain configures them,
    live network calls and all, if they aren't patched.
    """
    import collectors.hn_collector as hn_mod
    import collectors.reddit_collector as reddit_mod
    import collectors.rss_collector as rss_mod
    import collectors.github_collector as github_mod
    import collectors.trends_collector as trends_mod
    import collectors.stackexchange_collector as se_mod
    import collectors.greenhouse_jobs_collector as gh_mod
    import collectors.sec_edgar_collector as sec_mod

    def fake_hn_collect(self, limit=None):
        return list(hn_signals)

    def fake_reddit_collect(self, limit=None):
        return list(reddit_by_domain.get(self.domain, []))

    def fake_rss_collect(self, limit=None):
        return list((rss_by_domain or {}).get(self.domain, []))

    def fake_github_collect(self, limit=None):
        return list((github_by_domain or {}).get(self.domain, []))

    def fake_trends_collect(self, limit=None):
        return list((trends_by_domain or {}).get(self.domain, []))

    def fake_se_collect(self, limit=None):
        return list((stackexchange_by_domain or {}).get(self.domain, []))

    def fake_gh_collect(self, limit=None):
        return list((greenhouse_by_domain or {}).get(self.domain, []))

    def fake_sec_collect(self, limit=None):
        return list((sec_edgar_by_domain or {}).get(self.domain, []))

    monkeypatch.setattr(hn_mod.HNCollector, "collect", fake_hn_collect)
    monkeypatch.setattr(reddit_mod.RedditCollector, "collect", fake_reddit_collect)
    monkeypatch.setattr(rss_mod.RSSCollector, "collect", fake_rss_collect)
    monkeypatch.setattr(github_mod.GitHubCollector, "collect", fake_github_collect)
    monkeypatch.setattr(trends_mod.TrendsCollector, "collect", fake_trends_collect)
    monkeypatch.setattr(se_mod.StackExchangeCollector, "collect", fake_se_collect)
    monkeypatch.setattr(gh_mod.GreenhouseJobsCollector, "collect", fake_gh_collect)
    monkeypatch.setattr(sec_mod.SECEdgarCollector, "collect", fake_sec_collect)


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

    def test_github_and_trends_signals_get_correct_domain_when_present(self, fresh_db, monkeypatch):
        """
        Coverage gap this fix closes: BUSINESS_DOMAIN_CONFIG has real
        github_queries/trends_keywords, so _run_domain() does call both
        collectors for it — but until now nothing verified their output
        actually gets persisted with the right domain tag in a
        controlled way. Before this fix, either they were unpatched (a
        live network call producing an untested, uncontrolled count) or
        they're patched to []. This proves the wiring itself is correct
        when they DO return signals, without depending on live data.
        """
        DomainRegistry.register(BUSINESS_DOMAIN_CONFIG)
        DomainRegistry.register(_second_domain())

        hn_signals = _fake_signals("shared", "hn", 1)
        _patch_collectors(
            monkeypatch, hn_signals,
            reddit_by_domain={"business": [], "test_intel": []},
            github_by_domain={"business": _fake_signals("business", "github", 2)},
            trends_by_domain={"business": _fake_signals("business", "trends", 3)},
        )

        result = pipeline.run_full_pipeline()

        business = next(d for d in result.domains if d.domain_id == "business")
        test_intel = next(d for d in result.domains if d.domain_id == "test_intel")

        # business: 1 shared HN + 2 github + 3 trends = 6
        assert business.signals_collected == 6
        # test_intel: github_queries/trends_keywords are empty for this
        # fixture domain (see _second_domain()), so only shared HN applies
        assert test_intel.signals_collected == 1

        github_rows = _rows("SELECT domain FROM signals WHERE source = 'github'")
        assert len(github_rows) == 2
        assert all(r["domain"] == "business" for r in github_rows)

        trends_rows = _rows("SELECT domain FROM signals WHERE source = 'trends'")
        assert len(trends_rows) == 3
        assert all(r["domain"] == "business" for r in trends_rows)

    def test_greenhouse_signals_get_correct_domain_when_present(self, fresh_db, monkeypatch):
        DomainRegistry.register(BUSINESS_DOMAIN_CONFIG)
        DomainRegistry.register(_second_domain())

        hn_signals = _fake_signals("shared", "hn", 1)
        _patch_collectors(
            monkeypatch, hn_signals,
            reddit_by_domain={"business": [], "test_intel": []},
            greenhouse_by_domain={"business": _fake_signals("business", "greenhouse_jobs", 3)},
        )

        result = pipeline.run_full_pipeline()

        business = next(d for d in result.domains if d.domain_id == "business")
        assert business.signals_collected == 4  # 1 HN + 3 greenhouse_jobs

        gh_rows = _rows("SELECT domain FROM signals WHERE source = 'greenhouse_jobs'")
        assert len(gh_rows) == 3
        assert all(r["domain"] == "business" for r in gh_rows)

    def test_sec_edgar_signals_get_correct_domain_when_present(self, fresh_db, monkeypatch):
        DomainRegistry.register(BUSINESS_DOMAIN_CONFIG)
        DomainRegistry.register(_second_domain())

        hn_signals = _fake_signals("shared", "hn", 1)
        _patch_collectors(
            monkeypatch, hn_signals,
            reddit_by_domain={"business": [], "test_intel": []},
            sec_edgar_by_domain={"business": _fake_signals("business", "sec_edgar", 3)},
        )

        result = pipeline.run_full_pipeline()

        business = next(d for d in result.domains if d.domain_id == "business")
        assert business.signals_collected == 4  # 1 HN + 3 sec_edgar

        sec_rows = _rows("SELECT domain FROM signals WHERE source = 'sec_edgar'")
        assert len(sec_rows) == 3
        assert all(r["domain"] == "business" for r in sec_rows)


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
