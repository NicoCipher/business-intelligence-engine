"""
opportunity_engine/explainer/historical.py — week-over-week comparison.

Matches this period's opportunities against the previous period's by
title-token overlap, and builds the signal-volume / dimension-average
comparison narrative. See opportunity_engine/explainer/__init__.py for
this module's place in the overall split.
"""

from opportunity_engine.similarity import title_tokens as _title_tokens, jaccard as _jaccard


def match_previous_opportunity(title: str, previous_opportunities: list[dict], threshold: float = 0.35) -> dict | None:
    """
    Find the previous week's opportunity (if any) that this title is
    plausibly a continuation of, using title-keyword overlap — the same
    kind of similarity measure detector.py already uses for clustering,
    just applied across weeks instead of within one.
    """
    current_tokens = _title_tokens(title)
    best, best_score = None, 0.0
    for prev in previous_opportunities:
        score = _jaccard(current_tokens, _title_tokens(prev.get("title", "")))
        if score >= threshold and score > best_score:
            best, best_score = prev, score
    return best


def build_historical_comparison(
    current_stats: dict,
    current_opportunities: list[dict],
    previous_content: dict | None,
) -> dict | None:
    """
    Compare this period against the previous one. Returns None when there
    is nothing to compare against (e.g. the first tracked week for this
    domain) rather than fabricating a comparison.

    Every figure here is a real computed delta from persisted data — no
    estimation or invented trend language.
    """
    if not previous_content:
        return None

    prev_summary = previous_content.get("summary", {}) or {}
    prev_opportunities = previous_content.get("opportunities", []) or []

    curr_total = current_stats.get("total", 0)
    prev_total = prev_summary.get("total_signals", 0)
    volume_change = _pct_change(prev_total, curr_total)

    curr_avg = _avg_dimensions(current_opportunities)
    prev_avg = _avg_dimensions(prev_opportunities)

    growing, fading, new_topics, recurring_count = [], [], [], 0
    for opp in current_opportunities:
        match = match_previous_opportunity(opp.get("title", ""), prev_opportunities)
        if match is None:
            new_topics.append(opp.get("title", ""))
            continue
        recurring_count += 1
        delta = opp.get("composite_score", 0.0) - match.get("composite_score", 0.0)
        if delta > 0.3:
            growing.append(opp.get("title", ""))
        elif delta < -0.3:
            fading.append(opp.get("title", ""))
        # else: recurring but essentially unchanged — not called out either way

    narrative_parts = [
        f"Signal volume is {_trend_phrase(volume_change)} compared with last period"
        + (f" ({volume_change:+.0f}%)." if volume_change is not None else ".")
    ]
    if curr_avg["demand"] is not None and prev_avg["demand"] is not None:
        narrative_parts.append(f"Average demand across this period's opportunities is {_trend_phrase(_pct_change(prev_avg['demand'], curr_avg['demand']))}.")
    if new_topics:
        narrative_parts.append(f"{len(new_topics)} newly emerging pattern(s) weren't present last period.")
    if recurring_count:
        narrative_parts.append(f"{recurring_count} pattern(s) are recurring from last period.")

    return {
        "signal_volume_change_pct": volume_change,
        "signal_volume_trend": _trend_label(volume_change),
        "demand_trend": _trend_label(_pct_change(prev_avg["demand"], curr_avg["demand"])),
        "competition_trend": _trend_label(_pct_change(prev_avg["competition"], curr_avg["competition"])),
        "confidence_trend": _trend_label(_pct_change(prev_avg["confidence"], curr_avg["confidence"])),
        "recurring_topics": {
            "growing": growing,
            "fading": fading,
            "new": new_topics,
        },
        "narrative": " ".join(narrative_parts),
    }


def _avg_dimensions(opportunities: list[dict]) -> dict:
    dims = ["demand", "competition", "confidence"]
    out = {}
    for dim in dims:
        values = [o.get("scores", {}).get(dim) for o in opportunities if o.get("scores", {}).get(dim) is not None]
        out[dim] = (sum(values) / len(values)) if values else None
    return out


def _pct_change(before, after) -> float | None:
    if before in (None, 0) or after is None:
        return None
    return ((after - before) / before) * 100.0


def _trend_label(pct_change: float | None) -> str:
    if pct_change is None:
        return "not enough data to compare"
    if pct_change > 10:
        return "increasing"
    if pct_change < -10:
        return "decreasing"
    return "stable"


def _trend_phrase(pct_change: float | None) -> str:
    label = _trend_label(pct_change)
    return {"increasing": "up", "decreasing": "down", "stable": "roughly stable", "not enough data to compare": "not comparable"}[label]
