"""
opportunity_engine/explainer — Intelligence explanation layer

Turns the outputs of PatternDetector and OpportunityScorer into an analyst
briefing: what happened, why it matters, what opportunity exists, how
confident we are, and what to do next. This module never computes new
scores or clusters — it only interprets ones that already exist, either
persisted Opportunity rows (from the database) or RejectedCluster objects
(from PatternDetector.diagnose()).

Editorial stance (deliberately different from a data export):
  - Lead with business meaning, not measurements. "8 signals from 3
    sources" is a fact a machine can compute; "genuine demand with
    relatively low competition" is what a founder needs to know. Numbers
    still exist (see supporting_data on each opportunity) — they support
    the narrative, they don't replace it.
  - No repetition. A title, a piece of evidence, or a score reason is
    stated once, in the section where it's most useful, not restated
    verbatim across the executive summary, the trend section, and the
    opportunity section.
  - Never invent facts. Every sentence must be traceable to a signal,
    a scorer reason/evidence string, or a real historical comparison.
    Where evidence is thin, that's stated as part of the analysis
    ("purchasing intent remains unconfirmed"), not smoothed over.
  - Deterministic and template-based, not AI-generated — consistent with
    detector.py's _synthesise_description() and knowledge_graph/insights.py.

Used by report/generator.py to build the "intelligence brief" content.

---

This was originally a single ~1300-line file with five responsibilities
(flagged as code debt in docs/HANDOFF.md's roadmap: "explainer.py split
(~60KB, five-plus responsibilities)"). Split into this package with no
behavior change: same public functions, same signatures, same return
values, same module-level access pattern (`from opportunity_engine
import explainer; explainer.explain_opportunity(...)` keeps working
exactly as before, since `explainer` is now a package rather than a
single module, and Python treats attribute access on both identically).

Submodules, matching the five responsibilities the original file's own
section comments already named:
  - opportunity.py — per-opportunity narrative explanation (the biggest
    piece: verdict, market size, action plan, founder intelligence).
  - watch_list.py  — promising-but-below-threshold themes, and the
    zero-opportunities explanation.
  - trends.py      — named trends from entity co-occurrence pairs.
  - historical.py  — week-over-week comparison against the previous report.
  - summary.py     — executive summary and closing synthesis; consumes
                      output from the other four, introduces nothing new.

Cross-module dependencies turned out to be minimal once traced by actual
call site rather than by proximity in the original file: watch_list.py
calls historical.py's match_previous_opportunity() (cross-week
recurrence needs the same title-matching logic used for the main
week-over-week comparison); opportunity.py and trends.py both use
_SOURCE_LABELS (see _shared.py). Everything else that looked shared by
its position near the top of the original file — _target_group,
_distinguishing_terms, _why_it_matters — had exactly one real caller and
now lives directly in that caller's module.
"""

from opportunity_engine.explainer.opportunity import explain_opportunity
from opportunity_engine.explainer.watch_list import build_watch_list, explain_zero_opportunities
from opportunity_engine.explainer.trends import build_trend_analysis, pair_recurrence
from opportunity_engine.explainer.historical import match_previous_opportunity, build_historical_comparison
from opportunity_engine.explainer.summary import build_executive_summary, build_closing_synthesis

# Re-exported for backward compatibility: the original single-file
# explainer.py imported explain_pair from knowledge_graph.insights at
# module level, which made it incidentally accessible as
# explainer.explain_pair even though explainer.py never defined it
# itself. At least one real caller (tests/test_report_generator.py)
# depends on that attribute access, so it's preserved here explicitly.
from knowledge_graph.insights import explain_pair

__all__ = [
    "explain_opportunity",
    "build_watch_list",
    "explain_zero_opportunities",
    "build_trend_analysis",
    "pair_recurrence",
    "match_previous_opportunity",
    "build_historical_comparison",
    "build_executive_summary",
    "build_closing_synthesis",
    "explain_pair",
]
