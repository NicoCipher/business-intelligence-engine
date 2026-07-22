"""
tests/test_explainer.py — Tests for opportunity_engine/explainer.py, the
intelligence explanation layer (analyst-briefing upgrade).

Covers:
  - explain_opportunity(): narrative analysis + actions, numbers demoted
    to supporting_data
  - explain_zero_opportunities(): the "why zero" case
  - build_trend_analysis(): named trends with a "so what" narrative
  - build_executive_summary(): leads with business meaning, not stats
  - match_previous_opportunity() / build_historical_comparison(): the
    week-over-week comparison logic

Run with:
    cd backend && pytest tests/test_explainer.py -v
"""

import pytest

from models import OpportunityScores
from opportunity_engine import explainer
from opportunity_engine.detector import PatternDetector, RejectedCluster
from opportunity_engine.scorer import OpportunityScorer


@pytest.fixture
def scorer():
    return OpportunityScorer()


@pytest.fixture
def detector():
    return PatternDetector()


def _opp_dict(scores: OpportunityScores, title="Test opportunity", signal_ids=None):
    """Build the same shape ReportGenerator._get_week_opportunities() returns."""
    d = scores.to_dict()
    return {
        "id": "opp-1",
        "title": title,
        "description": "Detected across 2 source(s). Cluster size: 4 signals.",
        "composite_score": d["composite"],
        "tier": d["tier"],
        "status": "new",
        "scores": d,
        "week_key": "2026-W29",
        "created_at": "2026-07-19T00:00:00Z",
        "signal_ids": signal_ids or [],
    }


# ── explain_opportunity ────────────────────────────────────────────────

class TestExplainOpportunityShape:
    def test_returns_all_required_keys(self, scorer, demand_signals):
        scores = scorer.score(demand_signals)
        opp = _opp_dict(scores)
        result = explainer.explain_opportunity(opp, demand_signals)
        required = {"title", "tier", "composite_score", "market_size", "build_verdict", "analysis", "action_plan", "supporting_data"}
        assert required.issubset(result.keys())

    def test_analysis_has_five_narrative_sections(self, scorer, demand_signals):
        scores = scorer.score(demand_signals)
        opp = _opp_dict(scores)
        result = explainer.explain_opportunity(opp, demand_signals)
        required_sections = {"market_context", "market_gap", "business_potential", "risks", "confidence"}
        assert required_sections.issubset(result["analysis"].keys())
        for key, text in result["analysis"].items():
            assert isinstance(text, str) and text.strip() != ""

    def test_analysis_text_is_prose_not_a_number_dump(self, scorer, demand_signals):
        """The whole point of this upgrade: analysis text should read as
        sentences, not raw score/label pairs like 'Composite score: 5.78'."""
        scores = scorer.score(demand_signals)
        opp = _opp_dict(scores)
        result = explainer.explain_opportunity(opp, demand_signals)
        for text in result["analysis"].values():
            assert "composite score:" not in text.lower()
            assert len(text.split()) > 5   # a real sentence, not a label

    def test_numbers_live_in_supporting_data_not_analysis(self, scorer, demand_signals):
        scores = scorer.score(demand_signals)
        opp = _opp_dict(scores)
        result = explainer.explain_opportunity(opp, demand_signals)
        assert "evidence" in result["supporting_data"]
        assert "score_breakdown" in result["supporting_data"]
        assert len(result["supporting_data"]["score_breakdown"]) == 7
        for dim in result["supporting_data"]["score_breakdown"]:
            assert set(dim.keys()) == {"dimension", "score", "reason", "evidence"}

    def test_evidence_includes_actual_signal_titles(self, scorer, demand_signals):
        scores = scorer.score(demand_signals)
        opp = _opp_dict(scores)
        result = explainer.explain_opportunity(opp, demand_signals)
        evidence_titles = {e["title"] for e in result["supporting_data"]["evidence"]}
        signal_titles = {s.title for s in demand_signals}
        assert evidence_titles.issubset(signal_titles)
        assert len(result["supporting_data"]["evidence"]) > 0

    def test_action_plan_has_five_concrete_stages(self, scorer, demand_signals):
        scores = scorer.score(demand_signals)
        opp = _opp_dict(scores)
        result = explainer.explain_opportunity(opp, demand_signals)
        plan = result["action_plan"]
        required_stages = {"validate", "build_mvp", "acquire_first_users", "success_criteria", "kill_criteria"}
        assert required_stages.issubset(plan.keys())
        for stage, text in plan.items():
            assert isinstance(text, str) and text.strip() != "", f"{stage} must not be empty"

    def test_action_plan_kill_criteria_present_for_every_verdict(self, scorer, make_signal):
        """Every opportunity — including a weak, likely-Ignore one — must
        still get a kill_criteria, since that's the whole point of a kill
        criterion: knowing when to stop even on marginal candidates."""
        weak_signals = [make_signal(title="A generic product update", score=1, comments=0) for _ in range(3)]
        scores = scorer.score(weak_signals)
        opp = _opp_dict(scores)
        result = explainer.explain_opportunity(opp, weak_signals)
        assert result["action_plan"]["kill_criteria"].strip() != ""

    def test_market_size_shape(self, scorer, demand_signals):
        scores = scorer.score(demand_signals)
        opp = _opp_dict(scores)
        result = explainer.explain_opportunity(opp, demand_signals)
        market_size = result["market_size"]
        assert market_size["size"] in {"Small", "Medium", "Large"}
        assert market_size["explanation"].strip() != ""
        assert isinstance(market_size["adjacent_markets"], list)

    def test_market_size_explanation_never_claims_adjacent_market_when_list_is_empty(self, scorer, make_signal):
        """Regression: 'Medium' used to say 'at least one adjacent segment
        visible' even when adjacent_markets was []. The explanation must
        never claim something the accompanying data contradicts."""
        b2b_signals = [
            make_signal(title="Enterprise B2B SaaS tool for business teams", source="hn")
            for _ in range(3)
        ]
        scores = scorer.score(b2b_signals)
        opp = _opp_dict(scores)
        result = explainer.explain_opportunity(opp, b2b_signals)
        market_size = result["market_size"]
        if not market_size["adjacent_markets"]:
            assert "adjacent segment" not in market_size["explanation"].lower() or "no distinct" in market_size["explanation"].lower()

    def test_market_size_never_invents_dollar_figures(self, scorer, demand_signals):
        """This is explicitly a rough triage signal, not verified market
        research — the explanation text must not claim a specific dollar
        TAM, which would misrepresent what was actually measured."""
        scores = scorer.score(demand_signals)
        opp = _opp_dict(scores)
        result = explainer.explain_opportunity(opp, demand_signals)
        explanation = result["market_size"]["explanation"]
        assert "$" not in explanation

    def test_target_group_language_reflects_b2b_signals(self, scorer, make_signal):
        b2b_signals = [
            make_signal(title="Enterprise B2B SaaS tool for business teams", source="hn")
            for _ in range(3)
        ]
        scores = scorer.score(b2b_signals)
        opp = _opp_dict(scores)
        result = explainer.explain_opportunity(opp, b2b_signals)
        assert "business" in result["analysis"]["market_context"].lower()

    def test_missing_cluster_signals_degrades_gracefully(self, scorer, demand_signals):
        scores = scorer.score(demand_signals)
        opp = _opp_dict(scores)
        result = explainer.explain_opportunity(opp, [])
        assert result["supporting_data"]["evidence"] == []
        # Should still produce a coherent analysis, not crash.
        assert result["analysis"]["market_context"].strip() != ""

    def test_recurrence_context_appears_in_confidence_narrative(self, scorer, demand_signals):
        scores = scorer.score(demand_signals)
        opp = _opp_dict(scores)
        recurrence = {"weeks_seen": 3, "direction": "growing"}
        result = explainer.explain_opportunity(opp, demand_signals, recurrence=recurrence)
        assert "consecutive week" in result["analysis"]["confidence"].lower()

    def test_no_recurrence_states_first_week_observed(self, scorer, demand_signals):
        scores = scorer.score(demand_signals)
        opp = _opp_dict(scores)
        result = explainer.explain_opportunity(opp, demand_signals, recurrence=None)
        assert "first week" in result["analysis"]["confidence"].lower()


# ── explain_zero_opportunities ───────────────────────────────────────────

class TestExplainZeroOpportunities:
    def test_no_signals_at_all(self):
        result = explainer.explain_zero_opportunities([], total_signals=0)
        assert result["candidates"] == []
        assert "no signals" in result["reason"].lower()

    def test_signals_but_no_clusters_at_all(self):
        result = explainer.explain_zero_opportunities([], total_signals=42)
        assert result["candidates"] == []
        assert "no investment-grade opportunities" in result["reason"].lower()

    def test_real_rejected_clusters_from_detector(self, detector, make_signal):
        weak_signals = [
            make_signal(title="Looking for a better way to track compliance", score=5, comments=1)
            for _ in range(3)
        ] + [
            make_signal(title="Looking for a compliance tracking alternative", score=3, comments=0, source="reddit")
            for _ in range(3)
        ]
        diagnostics = detector.diagnose(weak_signals, domain="business")
        assert diagnostics.accepted == [], "fixture should not accidentally qualify as an opportunity"
        assert len(diagnostics.rejected) > 0

        result = explainer.explain_zero_opportunities(diagnostics.rejected, total_signals=len(weak_signals))
        assert result["candidates"]
        for c in result["candidates"]:
            assert set(c.keys()) == {
                "title", "signal_count", "sources", "total_engagement", "composite_score",
                "status", "why_it_failed", "missing_evidence", "recommended_action",
            }
            assert c["why_it_failed"].strip() != ""
            assert c["missing_evidence"].strip() != ""
            assert c["recommended_action"]["label"] in {"Monitor", "Research", "Ignore"}

    def test_candidates_capped_and_ranked_by_score(self, detector, make_signal):
        signals = []
        for i in range(6):
            signals += [
                make_signal(title=f"Unique topic number {i} discussion thread", score=1, comments=0)
                for _ in range(2)
            ]
        diagnostics = detector.diagnose(signals, domain="business")
        result = explainer.explain_zero_opportunities(diagnostics.rejected, total_signals=len(signals))
        assert len(result["candidates"]) <= 5

    def test_below_threshold_missing_evidence_names_weakest_dimension(self, scorer, make_signal):
        # Build a cluster whose weakest dimension is unambiguous: minimal
        # demand language, no pay language, single source -> demand/revenue
        # will be the weakest factors, and the sentence should name one of
        # them. Needs at least some demand language so it passes the
        # is_business_signal filter (pure news gets excluded from the
        # watch list entirely, which would make candidates empty here).
        signals = [
            make_signal(title="Looking for a generic product alternative", score=1, comments=0)
            for _ in range(3)
        ]
        scores = scorer.score(signals)
        rejected = RejectedCluster(
            signals=signals, reason="below_threshold",
            scores=scores, summary="Scored below threshold.",
        )
        result = explainer.explain_zero_opportunities([rejected], total_signals=len(signals))
        candidate = result["candidates"][0]
        assert "weakest factor was" in candidate["missing_evidence"].lower()


# ── build_trend_analysis ─────────────────────────────────────────────────

class TestBuildTrendAnalysis:
    def _pair(self, a_name, a_type, b_name, b_type, weight=3.0):
        return {
            "from": {"id": "e1", "name": a_name, "type": a_type},
            "to":   {"id": "e2", "name": b_name, "type": b_type},
            "weight": weight,
        }

    def test_trend_has_required_fields(self, make_signal):
        signals = [
            make_signal(title="Using Claude with Rust for a fast AI coding agent")
            for _ in range(3)
        ]
        pairs = [self._pair("Claude", "technology", "Rust", "technology", weight=3.0)]
        trends = explainer.build_trend_analysis(signals, pairs)
        assert len(trends) == 1
        trend = trends[0]
        required = {"name", "so_what", "entities", "evidence", "confidence"}
        assert required.issubset(trend.keys())
        assert trend["confidence"] in {"High", "Medium", "Low"}

    def test_so_what_explains_relevance_and_timing(self, make_signal):
        signals = [make_signal(title="Using Claude with Rust for a fast AI coding agent")]
        pairs = [self._pair("Claude", "technology", "Rust", "technology", weight=3.0)]
        trends = explainer.build_trend_analysis(signals, pairs)
        so_what = trends[0]["so_what"]
        assert "Claude" in so_what and "Rust" in so_what
        assert "relevant to" in so_what.lower()

    def test_no_previous_pairs_hedges_temporal_claim(self, make_signal):
        signals = [make_signal(title="Using Claude with Rust for a fast AI coding agent")]
        pairs = [self._pair("Claude", "technology", "Rust", "technology", weight=3.0)]
        trends = explainer.build_trend_analysis(signals, pairs, previous_pairs=None)
        assert "isn't yet enough history" in trends[0]["so_what"].lower()

    def test_recurring_pair_flagged_as_developing_pattern(self, make_signal):
        signals = [make_signal(title="Using Claude with Rust for a fast AI coding agent")]
        pair = self._pair("Claude", "technology", "Rust", "technology", weight=3.0)
        trends = explainer.build_trend_analysis(signals, [pair], previous_pairs=[pair])
        assert "developing pattern" in trends[0]["so_what"].lower()

    def test_new_pair_flagged_as_early_signal(self, make_signal):
        signals = [make_signal(title="Using Claude with Rust for a fast AI coding agent")]
        pair = self._pair("Claude", "technology", "Rust", "technology", weight=3.0)
        other_pair = self._pair("Notion", "technology", "Stripe", "technology", weight=2.0)
        trends = explainer.build_trend_analysis(signals, [pair], previous_pairs=[other_pair])
        assert "early signal" in trends[0]["so_what"].lower()

    def test_respects_limit(self, make_signal):
        signals = [make_signal(title="Claude and Rust together") for _ in range(2)]
        pairs = [
            self._pair(f"Entity{i}A", "technology", f"Entity{i}B", "technology")
            for i in range(10)
        ]
        trends = explainer.build_trend_analysis(signals, pairs, limit=3)
        assert len(trends) == 3

    def test_empty_pairs_produces_no_trends(self, make_signal):
        signals = [make_signal()]
        assert explainer.build_trend_analysis(signals, []) == []


# ── build_executive_summary ──────────────────────────────────────────────

class TestBuildExecutiveSummary:
    def test_no_signals_returns_plain_statement(self):
        stats = {"total": 0, "sources": []}
        summary = explainer.build_executive_summary(stats, [], [], None, None)
        assert "no signals" in summary.lower()

    def test_gold_opportunity_leads_with_business_meaning_not_stats(self, scorer, demand_signals):
        scores = scorer.score(demand_signals)
        # Force gold tier for a deterministic test regardless of fixture scoring.
        scores.demand = scores.competition = scores.revenue_potential = 9.0
        scores.execution_difficulty = scores.time_to_revenue = scores.risk = scores.confidence = 9.0
        opp = _opp_dict(scores, title="AI note-taking software for therapists")
        explained = explainer.explain_opportunity(opp, demand_signals)
        stats = {"total": 8, "sources": ["hn", "reddit"]}
        summary = explainer.build_executive_summary(stats, [explained], [], None, None)
        assert "AI note-taking software for therapists" in summary
        # Should not open with a bare stats sentence like the old version did.
        assert not summary.startswith("8 signal")

    def test_zero_opportunities_reason_surfaced_when_no_tiers(self):
        stats = {"total": 10, "sources": ["hn"]}
        zero = {"reason": "Nothing reached the confidence bar because evidence was thin.", "candidates": []}
        summary = explainer.build_executive_summary(stats, [], [], zero, None)
        assert "evidence was thin" in summary

    def test_comparison_narrative_excluded_from_summary(self):
        """Comparison detail now lives only in comparison_to_last_period —
        repeating it in the executive summary would work against the
        3-4 sentence cap and duplicate content that has its own section."""
        stats = {"total": 10, "sources": ["hn"]}
        zero = {"reason": "Nothing qualified.", "candidates": []}
        comparison = {"narrative": "Signal volume is up compared with last period (+40%)."}
        summary = explainer.build_executive_summary(stats, [], [], zero, comparison)
        assert "Signal volume is up" not in summary

    def test_summary_is_at_most_four_sentences(self, scorer, demand_signals):
        scores = scorer.score(demand_signals)
        scores.demand = scores.competition = scores.revenue_potential = 9.0
        scores.execution_difficulty = scores.time_to_revenue = scores.risk = scores.confidence = 9.0
        opp = _opp_dict(scores, title="AI note-taking software for therapists")
        explained = explainer.explain_opportunity(opp, demand_signals)
        stats = {"total": 8, "sources": ["hn", "reddit"]}
        summary = explainer.build_executive_summary(stats, [explained], [], None, None)
        sentence_count = summary.count(". ") + 1
        assert sentence_count <= 4

    def test_summary_leads_with_strongest_opportunity_immediately(self, scorer, demand_signals):
        scores = scorer.score(demand_signals)
        scores.demand = scores.competition = scores.revenue_potential = 9.0
        scores.execution_difficulty = scores.time_to_revenue = scores.risk = scores.confidence = 9.0
        opp = _opp_dict(scores, title="AI note-taking software for therapists")
        explained = explainer.explain_opportunity(opp, demand_signals)
        stats = {"total": 8, "sources": ["hn", "reddit"]}
        summary = explainer.build_executive_summary(stats, [explained], [], None, None)
        assert summary.startswith("Strongest opportunity:")
        assert "AI note-taking software for therapists" in summary.split(".")[0]

    def test_summary_includes_build_verdict(self, scorer, demand_signals):
        scores = scorer.score(demand_signals)
        scores.demand = scores.competition = scores.revenue_potential = 9.0
        scores.execution_difficulty = scores.time_to_revenue = scores.risk = scores.confidence = 9.0
        opp = _opp_dict(scores, title="AI note-taking software for therapists")
        explained = explainer.explain_opportunity(opp, demand_signals)
        stats = {"total": 8, "sources": ["hn", "reddit"]}
        summary = explainer.build_executive_summary(stats, [explained], [], None, None)
        assert "Verdict:" in summary
        assert explained["build_verdict"]["label"] in summary


# ── match_previous_opportunity / build_historical_comparison ─────────────

class TestPairRecurrence:
    def _pair(self, a_name, a_type, b_name, b_type, weight=3.0):
        return {
            "from": {"id": "e1", "name": a_name, "type": a_type},
            "to":   {"id": "e2", "name": b_name, "type": b_type},
            "weight": weight,
        }

    def test_no_previous_pairs_returns_none_not_false(self):
        pair = self._pair("Claude", "technology", "Rust", "technology")
        result = explainer.pair_recurrence(pair, None)
        assert result["recurring"] is None

    def test_matching_pair_is_recurring(self):
        pair = self._pair("Claude", "technology", "Rust", "technology")
        result = explainer.pair_recurrence(pair, [pair])
        assert result["recurring"] is True

    def test_non_matching_pair_is_not_recurring(self):
        pair = self._pair("Claude", "technology", "Rust", "technology")
        other = self._pair("Notion", "technology", "Stripe", "technology")
        result = explainer.pair_recurrence(pair, [other])
        assert result["recurring"] is False

    def test_reversed_from_to_order_still_matches(self):
        """A <-> B should match B <-> A across weeks — order shouldn't matter."""
        pair = self._pair("Claude", "technology", "Rust", "technology")
        reversed_pair = self._pair("Rust", "technology", "Claude", "technology")
        result = explainer.pair_recurrence(pair, [reversed_pair])
        assert result["recurring"] is True


class TestWatchList:
    def test_empty_rejected_produces_empty_watch_list(self):
        assert explainer.build_watch_list([]) == []

    def test_watch_list_shape(self, make_signal):
        signals = [make_signal(title="Looking for a better product alternative", score=1, comments=0) for _ in range(3)]
        rejected = RejectedCluster(signals=signals, reason="too_small", summary="Too small.")
        watch_list = explainer.build_watch_list([rejected])
        assert len(watch_list) == 1
        item = watch_list[0]
        required = {
            "title", "signal_count", "sources", "total_engagement", "composite_score",
            "status", "why_it_failed", "missing_evidence", "recommended_action",
        }
        assert required.issubset(item.keys())

    def test_pure_news_excluded_from_watch_list(self, make_signal):
        """The core new requirement: pure news/announcements with no
        demand, complaint, or willingness-to-pay language must never
        appear on the Watch List, even if they clustered together."""
        news_signals = [
            make_signal(title="Google announced a new AI feature today", score=50, comments=10)
            for _ in range(3)
        ]
        rejected = RejectedCluster(signals=news_signals, reason="too_small", summary="Too small.")
        assert explainer.build_watch_list([rejected]) == []

    def test_mixed_news_and_business_signals_only_keeps_business_ones(self, make_signal):
        news = RejectedCluster(
            signals=[make_signal(title="Google announced a new AI feature today", score=50, comments=10) for _ in range(2)],
            reason="too_small", summary="x",
        )
        business = RejectedCluster(
            signals=[make_signal(title="Looking for a compliance tracking alternative", score=5, comments=1) for _ in range(2)],
            reason="too_small", summary="x",
        )
        watch_list = explainer.build_watch_list([news, business])
        titles = [w["title"] for w in watch_list]
        assert "Google announced a new AI feature today" not in titles
        assert "Looking for a compliance tracking alternative" in titles

    def test_watch_list_never_recommends_build(self, make_signal):
        """Watch-list items haven't cleared the threshold — Build is never
        an appropriate label for them."""
        signals = [make_signal(title="Looking for a solution to this problem", score=5, comments=1) for _ in range(2)]
        for reason in ("too_small", "single_source", "below_threshold"):
            rejected = RejectedCluster(signals=signals, reason=reason, summary="x")
            watch_list = explainer.build_watch_list([rejected])
            assert watch_list[0]["recommended_action"]["label"] != "Build"

    def test_watch_list_respects_limit(self, make_signal):
        clusters = []
        for i in range(8):
            signals = [make_signal(title=f"Looking for a solution to topic {i}", score=1, comments=0)]
            clusters.append(RejectedCluster(signals=signals, reason="too_small", summary="x"))
        watch_list = explainer.build_watch_list(clusters, limit=3)
        assert len(watch_list) == 3

    def test_watch_list_ranked_by_composite_score(self, scorer, make_signal):
        weak_signals = [make_signal(title="Looking for a weak topic solution", score=1, comments=0) for _ in range(3)]
        strong_signals = [make_signal(title="Looking for a stronger topic solution", score=100, comments=50) for _ in range(3)]
        weak_scores = scorer.score(weak_signals)
        strong_scores = scorer.score(strong_signals)
        weak_rejected = RejectedCluster(signals=weak_signals, reason="below_threshold", scores=weak_scores, summary="x")
        strong_rejected = RejectedCluster(signals=strong_signals, reason="below_threshold", scores=strong_scores, summary="x")
        watch_list = explainer.build_watch_list([weak_rejected, strong_rejected])
        assert watch_list[0]["composite_score"] >= watch_list[1]["composite_score"]


class TestRecommendationVocabulary:
    _OPPORTUNITY_VOCAB = {"Build", "Validate First", "Monitor", "Ignore"}
    _TREND_VOCAB = {"Build", "Validate", "Research", "Monitor", "Ignore"}

    def test_build_verdict_uses_allowed_vocabulary(self, scorer, demand_signals):
        scores = scorer.score(demand_signals)
        opp = _opp_dict(scores)
        result = explainer.explain_opportunity(opp, demand_signals)
        assert result["build_verdict"]["label"] in self._OPPORTUNITY_VOCAB
        assert result["build_verdict"]["justification"].strip() != ""

    def test_weak_bronze_opportunity_can_reach_ignore(self, scorer, make_signal):
        """Unlike the prior design, Build Verdict now allows Ignore for
        opportunities too — a weak bronze-tier cluster with low confidence
        and minimal evidence should be able to reach it."""
        weak_signals = [make_signal(title="Looking for a solution", score=1, comments=0) for _ in range(2)]
        scores = scorer.score(weak_signals)
        scores.demand = scores.confidence = 2.0
        scores.competition = scores.revenue_potential = 3.0
        scores.execution_difficulty = scores.time_to_revenue = scores.risk = 3.0
        opp = _opp_dict(scores)
        result = explainer.explain_opportunity(opp, weak_signals)
        assert result["tier"] == "bronze"
        assert result["build_verdict"]["label"] == "Ignore"

    def test_gold_high_confidence_recommends_build(self, scorer, demand_signals):
        scores = scorer.score(demand_signals)
        scores.demand = scores.competition = scores.revenue_potential = 9.0
        scores.execution_difficulty = scores.time_to_revenue = scores.risk = scores.confidence = 9.0
        opp = _opp_dict(scores)
        result = explainer.explain_opportunity(opp, demand_signals)
        assert result["tier"] == "gold"
        assert result["build_verdict"]["label"] == "Build"

    def test_trend_recommendation_uses_allowed_vocabulary(self, make_signal):
        signals = [make_signal(title="Using Claude with Rust for a fast AI coding agent")]
        pairs = [{
            "from": {"id": "e1", "name": "Claude", "type": "technology"},
            "to":   {"id": "e2", "name": "Rust", "type": "technology"},
            "weight": 3.0,
        }]
        trends = explainer.build_trend_analysis(signals, pairs)
        assert trends[0]["recommended_action"]["label"] in self._TREND_VOCAB


class TestClosingSynthesis:
    def test_all_four_required_sections_present(self, scorer, demand_signals):
        scores = scorer.score(demand_signals)
        scores.demand = scores.competition = scores.revenue_potential = 9.0
        scores.execution_difficulty = scores.time_to_revenue = scores.risk = scores.confidence = 9.0
        opp = _opp_dict(scores)
        explained = explainer.explain_opportunity(opp, demand_signals)
        synthesis = explainer.build_closing_synthesis(
            explained_opportunities=[explained], trends=[], watch_list=[],
            comparison=None, zero_opps_explanation=None,
        )
        required = {"if_i_could_only_pursue_one", "why", "what_id_ignore", "what_id_keep_monitoring"}
        assert required.issubset(synthesis.keys())
        assert synthesis["if_i_could_only_pursue_one"].strip() != ""
        assert synthesis["why"].strip() != ""
        assert isinstance(synthesis["what_id_ignore"], list) and len(synthesis["what_id_ignore"]) > 0
        assert isinstance(synthesis["what_id_keep_monitoring"], list) and len(synthesis["what_id_keep_monitoring"]) > 0

    def test_closing_synthesis_with_nothing_at_all(self):
        """Even an empty report must produce a coherent, non-empty closing —
        never crash, never leave a section blank."""
        synthesis = explainer.build_closing_synthesis(
            explained_opportunities=[], trends=[], watch_list=[],
            comparison=None, zero_opps_explanation=None,
        )
        assert synthesis["if_i_could_only_pursue_one"].strip() != ""
        assert synthesis["why"].strip() != ""
        assert len(synthesis["what_id_ignore"]) > 0
        assert len(synthesis["what_id_keep_monitoring"]) > 0

    def test_strong_opportunity_is_named_as_the_single_best_bet(self, scorer, demand_signals):
        scores = scorer.score(demand_signals)
        scores.demand = scores.competition = scores.revenue_potential = 9.0
        scores.execution_difficulty = scores.time_to_revenue = scores.risk = scores.confidence = 9.0
        opp = _opp_dict(scores, title="AI note-taking software for therapists")
        explained = explainer.explain_opportunity(opp, demand_signals)
        synthesis = explainer.build_closing_synthesis(
            explained_opportunities=[explained], trends=[], watch_list=[],
            comparison=None, zero_opps_explanation=None,
        )
        assert "AI note-taking software for therapists" in synthesis["if_i_could_only_pursue_one"]
        assert explained["build_verdict"]["label"] in ("Build", "Validate First")

    def test_weak_opportunities_produce_honest_none_pick(self, scorer, make_signal):
        """If the only opportunity available is an Ignore-verdict one, the
        report should say so honestly rather than naming it anyway."""
        weak_signals = [make_signal(title="Looking for a solution", score=1, comments=0) for _ in range(2)]
        scores = scorer.score(weak_signals)
        scores.demand = scores.confidence = 2.0
        scores.competition = scores.revenue_potential = 3.0
        scores.execution_difficulty = scores.time_to_revenue = scores.risk = 3.0
        opp = _opp_dict(scores)
        explained = explainer.explain_opportunity(opp, weak_signals)
        assert explained["build_verdict"]["label"] == "Ignore"

        synthesis = explainer.build_closing_synthesis(
            explained_opportunities=[explained], trends=[], watch_list=[],
            comparison=None, zero_opps_explanation=None,
        )
        assert synthesis["if_i_could_only_pursue_one"].startswith("None")

    def test_ignored_items_appear_in_what_id_ignore(self, scorer, make_signal):
        weak_signals = [make_signal(title="Looking for a solution", score=1, comments=0) for _ in range(2)]
        scores = scorer.score(weak_signals)
        scores.demand = scores.confidence = 2.0
        scores.competition = scores.revenue_potential = 3.0
        scores.execution_difficulty = scores.time_to_revenue = scores.risk = 3.0
        opp = _opp_dict(scores, title="Weak niche idea")
        explained = explainer.explain_opportunity(opp, weak_signals)

        synthesis = explainer.build_closing_synthesis(
            explained_opportunities=[explained], trends=[], watch_list=[],
            comparison=None, zero_opps_explanation=None,
        )
        assert "Weak niche idea" in synthesis["what_id_ignore"]

    def test_monitored_items_appear_in_what_id_keep_monitoring(self, scorer, demand_signals):
        scores = scorer.score(demand_signals)
        # Deliberately mid-range so it lands on Monitor, not Build/Ignore.
        scores.demand = scores.confidence = 5.0
        scores.competition = scores.revenue_potential = 5.0
        scores.execution_difficulty = scores.time_to_revenue = scores.risk = 5.0
        opp = _opp_dict(scores, title="Moderate signal idea")
        explained = explainer.explain_opportunity(opp, demand_signals)
        assert explained["build_verdict"]["label"] == "Monitor"

        synthesis = explainer.build_closing_synthesis(
            explained_opportunities=[explained], trends=[], watch_list=[],
            comparison=None, zero_opps_explanation=None,
        )
        assert "Moderate signal idea" in synthesis["what_id_keep_monitoring"]


class TestNegativeWordingRemoved:
    """
    Regression guard for the analyst-language rewrite — these specific
    flat, database-export-style phrases must never appear in generated
    narrative again.
    """
    _FORBIDDEN_PHRASES = [
        "no repeated pattern formed",
        "nothing reached the confidence bar",
        "no clear pattern emerged worth flagging",
    ]

    def test_zero_opportunities_no_signals_case(self):
        result = explainer.explain_zero_opportunities([], total_signals=0)
        for phrase in self._FORBIDDEN_PHRASES:
            assert phrase not in result["reason"].lower()

    def test_zero_opportunities_no_clusters_case(self):
        result = explainer.explain_zero_opportunities([], total_signals=50)
        for phrase in self._FORBIDDEN_PHRASES:
            assert phrase not in result["reason"].lower()
        assert "investment-grade" in result["reason"].lower()

    def test_zero_opportunities_with_rejected_clusters_case(self, detector, make_signal):
        weak_signals = [make_signal(title=f"Announcement {i}", score=1, comments=0) for i in range(3)]
        diagnostics = detector.diagnose(weak_signals)
        result = explainer.explain_zero_opportunities(diagnostics.rejected, total_signals=len(weak_signals))
        for phrase in self._FORBIDDEN_PHRASES:
            assert phrase not in result["reason"].lower()


class TestMatchPreviousOpportunity:
    def test_similar_titles_match(self):
        previous = [{"title": "AI note-taking software for therapists", "composite_score": 7.0}]
        match = explainer.match_previous_opportunity(
            "AI note-taking tool for therapists and coaches", previous
        )
        assert match is not None

    def test_unrelated_titles_do_not_match(self):
        previous = [{"title": "AI note-taking software for therapists", "composite_score": 7.0}]
        match = explainer.match_previous_opportunity(
            "Invoice reconciliation for freelancers", previous
        )
        assert match is None

    def test_empty_previous_list_returns_none(self):
        assert explainer.match_previous_opportunity("Anything", []) is None


class TestBuildHistoricalComparison:
    def test_no_previous_content_returns_none(self):
        assert explainer.build_historical_comparison({"total": 10}, [], None) is None

    def test_signal_volume_change_computed(self):
        previous = {"summary": {"total_signals": 10}, "opportunities": []}
        current_stats = {"total": 15}
        result = explainer.build_historical_comparison(current_stats, [], previous)
        assert result is not None
        assert result["signal_volume_change_pct"] == pytest.approx(50.0)
        assert result["signal_volume_trend"] == "increasing"

    def test_new_topic_detected_when_no_match(self):
        previous = {"summary": {"total_signals": 10}, "opportunities": [
            {"title": "Invoice reconciliation for freelancers", "composite_score": 6.0, "scores": {}}
        ]}
        current = [{"title": "AI note-taking for therapists", "composite_score": 7.0, "scores": {}}]
        result = explainer.build_historical_comparison({"total": 10}, current, previous)
        assert "AI note-taking for therapists" in result["recurring_topics"]["new"]

    def test_growing_topic_detected_on_score_increase(self):
        previous = {"summary": {"total_signals": 10}, "opportunities": [
            {"title": "AI note-taking software for therapists", "composite_score": 6.0, "scores": {}}
        ]}
        current = [{"title": "AI note-taking software for therapists and coaches", "composite_score": 7.0, "scores": {}}]
        result = explainer.build_historical_comparison({"total": 10}, current, previous)
        assert result["recurring_topics"]["growing"]
        assert result["recurring_topics"]["new"] == []
