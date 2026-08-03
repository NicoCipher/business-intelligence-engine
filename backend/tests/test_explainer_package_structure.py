"""
tests/test_explainer_package_structure.py — Protects the explainer.py ->
explainer/ package split from silent regression.

The functional tests in test_explainer.py already exercise every public
function's behavior thoroughly, but they wouldn't necessarily catch a
future edit to __init__.py accidentally dropping a re-export (a test
calling explainer.build_watch_list(...) fails loudly if the function's
BEHAVIOR breaks, but a typo removing it from __init__.py while the
underlying implementation in watch_list.py stays fine would only surface
as an AttributeError at whatever call site happens to exercise it --
this file makes that failure immediate and explicit instead).

Also guards the one incidental-but-real dependency this split had to
account for: explain_pair being accessible as explainer.explain_pair,
which was never defined in the original single-file explainer.py, only
imported into it from knowledge_graph.insights -- easy to lose when
splitting into a package unless it's deliberately re-exported.

Run with:
    cd backend && pytest tests/test_explainer_package_structure.py -v
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from opportunity_engine import explainer


class TestPublicAPISurfaceIntact:
    """Every function callable as explainer.X(...) before the split into
    a package must remain callable exactly the same way after it."""

    @pytest.mark.parametrize("name", [
        "explain_opportunity",
        "build_watch_list",
        "explain_zero_opportunities",
        "build_trend_analysis",
        "pair_recurrence",
        "match_previous_opportunity",
        "build_historical_comparison",
        "build_executive_summary",
        "build_closing_synthesis",
    ])
    def test_public_function_is_accessible_and_callable(self, name):
        assert hasattr(explainer, name), f"explainer.{name} is missing"
        assert callable(getattr(explainer, name))

    def test_explain_pair_still_accessible_incidental_reexport(self):
        """explain_pair was never defined in the original explainer.py --
        it was imported from knowledge_graph.insights at module level,
        which made it incidentally available as explainer.explain_pair.
        At least one real caller (test_report_generator.py) depends on
        this exact attribute access continuing to work."""
        assert hasattr(explainer, "explain_pair")
        assert callable(explainer.explain_pair)

    def test_all_declares_the_complete_public_surface(self):
        expected = {
            "explain_opportunity", "build_watch_list", "explain_zero_opportunities",
            "build_trend_analysis", "pair_recurrence", "match_previous_opportunity",
            "build_historical_comparison", "build_executive_summary",
            "build_closing_synthesis", "explain_pair",
        }
        assert set(explainer.__all__) == expected


class TestPackageIsActuallySplit:
    """Confirms this is genuinely a package with separate submodules now,
    not just a renamed single file -- the actual point of the refactor."""

    def test_explainer_is_a_package_not_a_single_module(self):
        assert hasattr(explainer, "__path__"), (
            "explainer should be a package (have __path__), not a plain module"
        )

    @pytest.mark.parametrize("submodule", [
        "opportunity", "watch_list", "trends", "historical", "summary", "_shared",
    ])
    def test_submodule_is_importable(self, submodule):
        import importlib
        mod = importlib.import_module(f"opportunity_engine.explainer.{submodule}")
        assert mod is not None

    def test_opportunity_module_owns_explain_opportunity(self):
        from opportunity_engine.explainer import opportunity
        assert opportunity.explain_opportunity is explainer.explain_opportunity

    def test_watch_list_module_owns_build_watch_list(self):
        from opportunity_engine.explainer import watch_list
        assert watch_list.build_watch_list is explainer.build_watch_list

    def test_trends_module_owns_build_trend_analysis(self):
        from opportunity_engine.explainer import trends
        assert trends.build_trend_analysis is explainer.build_trend_analysis

    def test_historical_module_owns_match_previous_opportunity(self):
        from opportunity_engine.explainer import historical
        assert historical.match_previous_opportunity is explainer.match_previous_opportunity

    def test_summary_module_owns_build_executive_summary(self):
        from opportunity_engine.explainer import summary
        assert summary.build_executive_summary is explainer.build_executive_summary

    def test_watch_list_correctly_depends_on_historical_for_recurrence(self):
        """The one genuine cross-module dependency this split has:
        watch_list.build_watch_list() calls historical's
        match_previous_opportunity() for cross-week recurrence."""
        from opportunity_engine.explainer import watch_list
        assert watch_list.match_previous_opportunity is explainer.match_previous_opportunity
