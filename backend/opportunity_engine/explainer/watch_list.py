"""
opportunity_engine/explainer/watch_list.py — promising-but-below-threshold
themes, and the "why did nothing qualify this period" narrative.

See opportunity_engine/explainer/__init__.py for this module's place in
the overall split.
"""

from collections import defaultdict

from config import DEMAND_KEYWORDS, COMPLAINT_KEYWORDS, WILLINGNESS_TO_PAY

from opportunity_engine.explainer.historical import match_previous_opportunity

_REJECTION_LABELS = {
    "too_small": "insufficient mention volume to qualify as a pattern",
    "single_source": "corroboration from only one source, not yet cross-validated",
    "below_threshold": "evidence quality fell short of the investment-grade bar once scored",
}


def _is_business_signal(rejected) -> bool:
    """
    Filters out clusters that read as pure news/announcements rather than
    a potential business opportunity — e.g. a product-launch announcement
    with no demand or willingness-to-pay language anywhere in it. The
    Watch List should only ever surface things a founder might plausibly
    act on, not general industry news that happened to cluster together.

    Below-threshold clusters were actually scored, so this uses the
    scorer's own demand/revenue-potential evidence directly — the same
    real signal the scoring engine already computed, not a new check.
    too_small/single_source clusters were never scored (too small to
    evaluate), so this falls back to the same keyword vocabulary the
    scorer itself uses, applied directly to the cluster's text.
    """
    if rejected.scores and rejected.scores.explanations:
        demand_exp = rejected.scores.explanations.get("demand")
        revenue_exp = rejected.scores.explanations.get("revenue_potential")
        no_demand = demand_exp is None or "0 demand-keyword" in demand_exp.evidence
        no_pay = revenue_exp is None or "0 willingness-to-pay" in revenue_exp.evidence
        return not (no_demand and no_pay)

    blob = " ".join(s.full_text for s in rejected.signals)
    return (
        any(kw in blob for kw in DEMAND_KEYWORDS)
        or any(kw in blob for kw in WILLINGNESS_TO_PAY)
        or any(kw in blob for kw in COMPLAINT_KEYWORDS)
    )


def _watch_list_recommendation(rejection_reason: str, composite_score, weeks_seen: int = 1) -> dict:
    """
    Watch-list items have NOT cleared the threshold, so "Build" is never
    appropriate here — the question is whether it's worth continuing to
    track at all.

    A theme recurring 3+ weeks running escalates to "Research" regardless
    of the underlying rejection reason — a pain point nobody's numbers
    ever individually cleared the bar for is still, cumulatively, real
    evidence once it's shown up repeatedly.
    """
    if weeks_seen >= 3:
        return {"label": "Research", "justification": (
            f"This has now recurred for {weeks_seen} consecutive weeks without any "
            f"single week's evidence clearing the bar alone — the cumulative pattern "
            f"is itself worth a closer look, even though no individual week was strong."
        )}
    if rejection_reason == "below_threshold" and composite_score is not None and composite_score >= 4.0:
        return {"label": "Research", "justification": (
            "Close to the threshold — worth a closer look at what's missing "
            "before dismissing it."
        )}
    if rejection_reason == "single_source":
        return {"label": "Monitor", "justification": (
            "A second independent source would meaningfully change the picture — "
            "worth watching for corroboration."
        )}
    if rejection_reason == "too_small":
        return {"label": "Monitor", "justification": (
            "Too early to act on — revisit if mention volume increases."
        )}
    return {"label": "Ignore", "justification": (
        "Evidence is too thin relative to the likely payoff to justify continued "
        "tracking at this time."
    )}


def build_watch_list(rejected: list, limit: int = 5, previous_watch_list: list[dict] | None = None) -> list[dict]:
    """
    Promising-but-below-threshold themes — always available regardless of
    whether real opportunities exist this period. This is what lets a
    reader see what's "on deck": patterns worth watching even though
    nothing here has cleared the investment bar yet.

    Pure news/announcement clusters (no demand or complaint language
    detected — see _is_business_signal) are excluded entirely: this list
    is for potential business opportunities, not general industry news.

    Cross-week recurrence: a pain point that never individually clusters
    strongly enough within a single week can still be real, recurring
    demand — it's just fragmented across weeks (different wording, small
    volume each time). Matching this week's items against last week's
    watch list (same title-token approach used for opportunity
    recurrence) surfaces that cumulative signal, which a single week's
    view would miss entirely.

    Args: rejected = list of opportunity_engine.detector.RejectedCluster
    (from PatternDetector.diagnose()). previous_watch_list = last period's
    watch_list content, or None/empty if there's nothing to compare against.
    """
    business_candidates = [r for r in rejected if _is_business_signal(r)]
    if not business_candidates:
        return []

    ranked = sorted(
        business_candidates,
        key=lambda r: (r.scores.composite() if r.scores else -1.0, len(r.signals)),
        reverse=True,
    )[:limit]

    previous_watch_list = previous_watch_list or []

    watch_list = []
    for r in ranked:
        anchor = max(r.signals, key=lambda s: s.engagement)
        composite = r.scores.composite() if r.scores else None

        match = match_previous_opportunity(anchor.title, previous_watch_list)
        if match is not None:
            weeks_seen = (match.get("recurrence") or {}).get("weeks_seen", 1) + 1
        else:
            weeks_seen = 1

        watch_list.append({
            "title": anchor.title,
            "signal_count": len(r.signals),
            "sources": sorted(set(s.source for s in r.signals)),
            "total_engagement": sum(s.engagement for s in r.signals),
            "composite_score": composite,
            "status": r.summary,
            "why_it_failed": r.summary,
            "missing_evidence": _missing_evidence(r),
            "recurrence": {"weeks_seen": weeks_seen, "recurring": match is not None},
            "recommended_action": _watch_list_recommendation(r.reason, composite, weeks_seen),
        })
    return watch_list


def explain_zero_opportunities(rejected: list, total_signals: int, previous_watch_list: list[dict] | None = None) -> dict:
    """
    Explain why nothing qualified this period, instead of just reporting a
    count. Args: rejected = list of opportunity_engine.detector.RejectedCluster.
    """
    if total_signals == 0:
        return {
            "reason": ("No signals were collected for this domain in this period, "
                       "so there is nothing yet to evaluate against the investment bar."),
            "candidates": [],
        }

    if not rejected:
        return {
            "reason": ("No investment-grade opportunities met the threshold this period — "
                       "collected signals were too dispersed across topics to form a "
                       "coherent pattern worth underwriting."),
            "candidates": [],
        }

    candidates = build_watch_list(rejected, previous_watch_list=previous_watch_list)

    reason_counts: dict[str, int] = defaultdict(int)
    for r in rejected:
        reason_counts[r.reason] += 1
    dominant_reason = max(reason_counts, key=reason_counts.get)
    dominant_label = _REJECTION_LABELS.get(dominant_reason, dominant_reason)

    theme = _weak_dimension_theme(rejected)
    reason = (
        f"No investment-grade opportunities met the threshold this period — the "
        f"limiting factor was {dominant_label}, across {len(rejected)} candidate "
        f"pattern(s) evaluated.{theme}"
    )
    return {"reason": reason, "candidates": candidates}


def _missing_evidence(rejected) -> str:
    if rejected.reason == "too_small":
        return "More independent mentions of the same topic would be needed before it's worth a closer look."
    if rejected.reason == "single_source":
        return "Corroboration from a second, independent source would meaningfully strengthen this."
    if rejected.reason == "below_threshold" and rejected.scores and rejected.scores.explanations:
        dim, exp = min(rejected.scores.explanations.items(), key=lambda kv: kv[1].score)
        return f"The weakest factor was {dim.replace('_', ' ')} — {exp.reason.lower() if exp.reason else 'insufficient evidence.'}"
    return "Insufficient corroborating evidence at this stage to justify continued tracking."


def _weak_dimension_theme(rejected: list) -> str:
    below_threshold = [r for r in rejected if r.reason == "below_threshold" and r.scores]
    if not below_threshold:
        return ""

    weak_counts: dict[str, int] = defaultdict(int)
    for r in below_threshold:
        for dim, exp in r.scores.explanations.items():
            if exp.score < 5.0:
                weak_counts[dim] += 1
    if not weak_counts:
        return ""

    top_weak = max(weak_counts, key=weak_counts.get)
    if top_weak in ("demand", "revenue_potential"):
        return (" Most candidates read as technology or product announcements rather "
                "than expressions of genuine user demand — that's the main gap.")
    if top_weak == "competition":
        return " Most candidates describe spaces with existing, named alternatives."
    if top_weak == "confidence":
        return " Most candidates lacked corroboration across independent sources."
    if top_weak == "risk":
        return " Most candidates carried regulatory, incumbent, or hype-related risk flags."
    return ""
