"""
tests/test_report_generator.py — End-to-end tests for ReportGenerator
against a real (temporary) SQLite database, covering the analyst-briefing
content shape: narrative opportunity analysis, historical comparison, and
zero-opportunity explanation.

Run with:
    cd backend && pytest tests/test_report_generator.py -v
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import database
from collectors.base import persist_signals
from opportunity_engine.detector import PatternDetector
from report.generator import ReportGenerator


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_report.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    database.initialize()
    yield db_path


def _current_week_key() -> str:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    return f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"


_QUALIFYING_SIGNAL_SPECS = [
    dict(title="Looking for automated compliance tracking software for business teams",
         source="hn", score=200, comments=80),
    dict(title="I would pay for automated compliance tracking software for business teams",
         source="reddit", score=180, comments=60),
    dict(title="Any automated compliance tracking software for business teams out there?",
         source="hn", score=150, comments=40),
]


def _make_qualifying_signals(make_signal):
    return [make_signal(**spec) for spec in _QUALIFYING_SIGNAL_SPECS]


class TestReportWithOpportunities:
    def test_report_content_has_analyst_briefing_shape(self, fresh_db, make_signal):
        signals = _make_qualifying_signals(make_signal)
        persist_signals(signals)

        inserted = PatternDetector().detect_and_persist(signals, domain="business")
        assert inserted >= 1, "fixture should produce at least one persisted opportunity"

        report = ReportGenerator().generate(week_key=_current_week_key(), domain="business")

        required_top_level = {
            "executive_summary", "trend_analysis", "opportunities",
            "zero_opportunities_explanation", "comparison_to_last_period",
            "summary", "entity_intelligence",
        }
        assert required_top_level.issubset(report.content.keys())

        # Redundant/legacy fields from the pre-analyst-briefing version
        # must be gone — this was an explicit "reduce repetition" ask.
        assert "top_opportunities" not in report.content
        assert "key_insights" not in report.content
        assert "recommended_actions" not in report.content  # now per-opportunity, not global

        assert isinstance(report.content["executive_summary"], str)
        assert report.content["executive_summary"].strip() != ""
        assert report.content["zero_opportunities_explanation"] is None
        # First report for this domain -> nothing to compare against yet.
        assert report.content["comparison_to_last_period"] is None

        assert len(report.content["opportunities"]) >= 1
        for opp in report.content["opportunities"]:
            required_opp_keys = {"title", "tier", "composite_score", "analysis", "recommended_actions", "supporting_data"}
            assert required_opp_keys.issubset(opp.keys())
            assert len(opp["supporting_data"]["score_breakdown"]) == 7
            assert len(opp["recommended_actions"]) >= 4

        assert "narrative_connections" in report.content["entity_intelligence"]

    def test_opportunity_evidence_traces_to_real_signals(self, fresh_db, make_signal):
        signals = _make_qualifying_signals(make_signal)
        persist_signals(signals)
        PatternDetector().detect_and_persist(signals, domain="business")

        report = ReportGenerator().generate(week_key=_current_week_key(), domain="business")
        opp = report.content["opportunities"][0]

        signal_titles = {s.title for s in signals}
        for evidence_item in opp["supporting_data"]["evidence"]:
            assert evidence_item["title"] in signal_titles

    def test_executive_summary_names_the_top_opportunity(self, fresh_db, make_signal):
        signals = _make_qualifying_signals(make_signal)
        persist_signals(signals)
        PatternDetector().detect_and_persist(signals, domain="business")

        report = ReportGenerator().generate(week_key=_current_week_key(), domain="business")
        top_title = report.content["opportunities"][0]["title"]
        assert top_title in report.content["executive_summary"]


class TestReportWithZeroOpportunities:
    def test_zero_opportunities_explanation_present_and_explains_why(self, fresh_db, make_signal):
        weak_signals = [
            make_signal(title="Google announced a minor product update today", score=2, comments=0, source="hn"),
            make_signal(title="Google announced a minor product update today", score=1, comments=0, source="reddit"),
        ]
        persist_signals(weak_signals)

        inserted = PatternDetector().detect_and_persist(weak_signals, domain="business")
        assert inserted == 0, "fixture should not accidentally qualify as an opportunity"

        report = ReportGenerator().generate(week_key=_current_week_key(), domain="business")

        assert report.content["opportunities"] == []
        zero = report.content["zero_opportunities_explanation"]
        assert zero is not None
        assert zero["reason"].strip() != ""
        assert "0 opportunities found" not in zero["reason"]
        assert isinstance(zero["candidates"], list)
        assert report.content["executive_summary"].strip() != ""

    def test_no_signals_at_all_gives_plain_explanation(self, fresh_db):
        report = ReportGenerator().generate(week_key=_current_week_key(), domain="business")
        assert report.content["opportunities"] == []
        zero = report.content["zero_opportunities_explanation"]
        assert zero is not None
        assert "no signals" in zero["reason"].lower()
        assert "no signals" in report.content["executive_summary"].lower()


class TestHistoricalComparison:
    def test_second_week_report_compares_against_first(self, fresh_db, make_signal):
        gen = ReportGenerator()

        # Week 1: persist + generate + persist the report.
        week1_signals = _make_qualifying_signals(make_signal)
        persist_signals(week1_signals)
        PatternDetector().detect_and_persist(week1_signals, domain="business")
        week1_key = "2026-W10"
        report1 = gen.generate(week_key=week1_key, domain="business")
        assert gen.persist(report1) is True

        # Week 2 (the following ISO week): new signals, same underlying
        # topic, slightly more evidence -> should be detected as recurring.
        week2_signals = _make_qualifying_signals(make_signal) + [
            make_signal(title="We would pay for automated compliance tracking for business teams",
                        source="rss", score=20, comments=2),
        ]
        # give week2 signals distinct source_ids so they aren't deduped
        for i, s in enumerate(week2_signals):
            s.source_id = f"w2-{i}"
        persist_signals(week2_signals)
        PatternDetector().detect_and_persist(week2_signals, domain="business")
        week2_key = "2026-W11"
        report2 = gen.generate(week_key=week2_key, domain="business")

        comparison = report2.content["comparison_to_last_period"]
        assert comparison is not None
        assert "signal_volume_change_pct" in comparison
        assert comparison["signal_volume_trend"] in {"increasing", "decreasing", "stable"}
        assert isinstance(comparison["narrative"], str) and comparison["narrative"].strip() != ""

    def test_first_week_has_no_comparison(self, fresh_db, make_signal):
        signals = _make_qualifying_signals(make_signal)
        persist_signals(signals)
        PatternDetector().detect_and_persist(signals, domain="business")
        report = ReportGenerator().generate(week_key="2026-W10", domain="business")
        assert report.content["comparison_to_last_period"] is None


class TestReportPersistence:
    def test_persisted_report_content_survives_round_trip(self, fresh_db, make_signal):
        signals = _make_qualifying_signals(make_signal)
        persist_signals(signals)
        PatternDetector().detect_and_persist(signals, domain="business")

        generator = ReportGenerator()
        report = generator.generate(week_key=_current_week_key(), domain="business")
        assert generator.persist(report) is True

        with database.get_connection() as conn:
            row = conn.execute(
                "SELECT content FROM reports WHERE week_key = ? AND domain = ?",
                (report.week_key, "business"),
            ).fetchone()
        assert row is not None

        import json
        stored_content = json.loads(row["content"])
        assert "executive_summary" in stored_content
        assert "trend_analysis" in stored_content
        assert isinstance(stored_content["summary"]["sources_active"], list)
