"""
tests/test_report_generator.py — End-to-end tests for ReportGenerator
against a real (temporary) SQLite database, covering the analyst-briefing
content shape: narrative opportunity analysis, historical comparison, and
zero-opportunity explanation.

Run with:
    cd backend && pytest tests/test_report_generator.py -v
"""

import sys
from datetime import date
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


class TestStrongestPairsRecurrence:
    """
    Regression coverage for issue 5: strongest_pairs used to expose only
    the raw lifetime relationships.weight, which a reader could easily
    (and incorrectly) read as "how many weeks has this recurred". Real
    week-over-week recurrence is now attached explicitly, and weight is
    preserved unchanged for internal compatibility.
    """

    def test_first_report_pairs_have_no_recurrence_info_yet(self, fresh_db, make_signal):
        signals = [
            make_signal(title="Using Claude with Rust for a fast AI coding agent", score=100, comments=20)
            for _ in range(3)
        ]
        persist_signals(signals)
        from knowledge_graph.extractor import EntityExtractor
        EntityExtractor().persist_results(EntityExtractor().extract_batch(signals))
        PatternDetector().detect_and_persist(signals, domain="business")

        report = ReportGenerator().generate(week_key=_current_week_key(), domain="business")
        pairs = report.content["entity_intelligence"]["strongest_pairs"]
        if pairs:  # only meaningful if extraction actually found a co-occurring pair
            for p in pairs:
                assert p["recurring_from_last_period"] is None
                assert "weight" in p  # preserved for compatibility

    def test_weight_field_preserved_for_internal_consumers(self, fresh_db, make_signal):
        """explain_pair() and _trend_confidence() both read pair['weight']
        directly — the enrichment must never remove or rename it."""
        from opportunity_engine import explainer

        signals = [
            make_signal(title="Using Claude with Rust for a fast AI coding agent", score=100, comments=20)
            for _ in range(3)
        ]
        persist_signals(signals)
        from knowledge_graph.extractor import EntityExtractor
        EntityExtractor().persist_results(EntityExtractor().extract_batch(signals))
        PatternDetector().detect_and_persist(signals, domain="business")

        report = ReportGenerator().generate(week_key=_current_week_key(), domain="business")
        pairs = report.content["entity_intelligence"]["strongest_pairs"]
        for p in pairs:
            # Must not raise — proves weight is still a real, readable field.
            explainer.explain_pair(p)


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


class TestSignalCountingIsPeriodScoped:
    """
    Regression coverage for the specific bug reported: weekly reports
    counted ALL historical signals for the domain instead of only signals
    within period_start/period_end.
    """

    def test_signals_outside_the_period_are_excluded_from_the_count(self, fresh_db, make_signal):
        from datetime import datetime, timezone

        old_signals = [make_signal(title=f"Old signal from a past week {i}") for i in range(5)]
        for i, s in enumerate(old_signals):
            s.source_id = f"old-{i}"
            s.collected_at = datetime(2026, 1, 5, tzinfo=timezone.utc).isoformat()  # 2026-W01
        persist_signals(old_signals)

        this_week_signals = _make_qualifying_signals(make_signal)
        persist_signals(this_week_signals)  # default collected_at = now

        report = ReportGenerator().generate(week_key=_current_week_key(), domain="business")

        # Must count only this week's 3 signals, not 5 (old) + 3 (this week) = 8.
        assert report.content["summary"]["total_signals"] == len(this_week_signals)

    def test_opportunities_from_other_weeks_are_excluded(self, fresh_db, make_signal):
        from datetime import datetime, timezone

        # An opportunity manually persisted under a different week_key must
        # not leak into a report generated for the current week.
        old_signals = [make_signal(title=f"Old opportunity signal {i}") for i in range(5)]
        for i, s in enumerate(old_signals):
            s.source_id = f"oldopp-{i}"
            s.collected_at = datetime(2026, 1, 5, tzinfo=timezone.utc).isoformat()
        persist_signals(old_signals)
        detector = PatternDetector()
        # detect_and_persist always stamps the *current* week_key, so
        # simulate a genuinely old opportunity by rewriting its week_key
        # directly in the database after detection.
        detector.detect_and_persist(old_signals, domain="business")
        with database.get_connection() as conn:
            conn.execute("UPDATE opportunities SET week_key = '2026-W01'")
            conn.commit()

        this_week_signals = _make_qualifying_signals(make_signal)
        persist_signals(this_week_signals)
        PatternDetector().detect_and_persist(this_week_signals, domain="business")

        report = ReportGenerator().generate(week_key=_current_week_key(), domain="business")
        titles = {o["title"] for o in report.content["opportunities"]}
        assert not any("Old opportunity signal" in t for t in titles)


class TestHistoricalComparison:
    @staticmethod
    def _mid_week_timestamp(week_key: str) -> str:
        """A timestamp that genuinely falls within the given ISO week —
        needed now that signal stats are correctly period-scoped (see the
        query-scoping fix); tests must date their fixture signals
        realistically instead of relying on the old unscoped queries that
        counted every signal regardless of when it was collected."""
        from datetime import datetime, timezone
        year, week_num = week_key.split("-W")
        wednesday = date.fromisocalendar(int(year), int(week_num), 3)
        return datetime.combine(wednesday, datetime.min.time(), tzinfo=timezone.utc).isoformat()

    def test_second_week_report_compares_against_first(self, fresh_db, make_signal):
        gen = ReportGenerator()

        week1_key = "2026-W10"
        week2_key = "2026-W11"

        # Week 1: persist + generate + persist the report.
        week1_signals = _make_qualifying_signals(make_signal)
        week1_ts = self._mid_week_timestamp(week1_key)
        for s in week1_signals:
            s.collected_at = week1_ts
        persist_signals(week1_signals)
        PatternDetector().detect_and_persist(week1_signals, domain="business")
        report1 = gen.generate(week_key=week1_key, domain="business")
        assert gen.persist(report1) is True
        assert report1.content["summary"]["total_signals"] == len(week1_signals)

        # Week 2 (the following ISO week): new signals, same underlying
        # topic, slightly more evidence -> should be detected as recurring.
        week2_signals = _make_qualifying_signals(make_signal) + [
            make_signal(title="We would pay for automated compliance tracking for business teams",
                        source="rss", score=20, comments=2),
        ]
        week2_ts = self._mid_week_timestamp(week2_key)
        for i, s in enumerate(week2_signals):
            s.source_id = f"w2-{i}"  # distinct ids so they aren't deduped against week 1
            s.collected_at = week2_ts
        persist_signals(week2_signals)
        PatternDetector().detect_and_persist(week2_signals, domain="business")
        report2 = gen.generate(week_key=week2_key, domain="business")

        # Each week's report must only see that week's own signals now.
        assert report2.content["summary"]["total_signals"] == len(week2_signals)

        comparison = report2.content["comparison_to_last_period"]
        assert comparison is not None
        assert "signal_volume_change_pct" in comparison
        # Real signal counts now (4 vs 3) -> a real, computable trend, not
        # "not enough data to compare".
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
