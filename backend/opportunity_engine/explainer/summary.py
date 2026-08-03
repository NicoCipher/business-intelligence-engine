"""
opportunity_engine/explainer/summary.py — executive summary and closing
synthesis.

Both functions here only consume already-built content from the other
explainer submodules (explained opportunities, trends, watch list,
comparison) — neither reaches into another module's private helpers, so
this file has zero cross-module dependencies of its own.
"""


# ── Executive summary ──────────────────────────────────────────────────────

def build_executive_summary(
    signal_stats: dict,
    explained_opportunities: list[dict],
    trends: list[dict],
    zero_opps_explanation: dict | None,
    comparison: dict | None,
) -> str:
    """
    3-4 sentences, maximum. Leads immediately with the strongest
    opportunity (or the honest absence of one) — an executive should get
    the headline in the first sentence, not after context-setting.
    Trend and week-over-week detail deliberately live in their own
    sections (trend_analysis, comparison_to_last_period) rather than
    being repeated here.
    """
    n_signals = signal_stats.get("total", 0)
    if n_signals == 0:
        return ("No signals were collected for this domain in this period — "
                "there is nothing to report on yet.")

    gold = [o for o in explained_opportunities if o.get("tier") == "gold"]
    silver = [o for o in explained_opportunities if o.get("tier") == "silver"]
    bronze = [o for o in explained_opportunities if o.get("tier") == "bronze"]

    if gold or silver or bronze:
        top = (gold or silver or bronze)[0]
        headline = (
            f"Strongest opportunity: {top['title'].rstrip('.')} "
            f"({top['tier']}-tier, {top['composite_score']:.1f}/10)."
        )
        why = top["analysis"]["market_context"].split(". ")[0].rstrip(".") + "."
        verdict = top["build_verdict"]
        verdict_line = f"Verdict: {verdict['label']} — {verdict['justification']}"
        return " ".join([headline, why, verdict_line])

    if zero_opps_explanation:
        return zero_opps_explanation["reason"]

    return f"{n_signals} signals were collected this period, none forming a pattern strong enough to underwrite yet."


# ── Closing synthesis ─────────────────────────────────────────────────────

_VERDICT_PRIORITY = {"Build": 0, "Validate First": 1, "Monitor": 2, "Ignore": 3}


def build_closing_synthesis(
    explained_opportunities: list[dict],
    trends: list[dict],
    watch_list: list[dict],
    comparison: dict | None,
    zero_opps_explanation: dict | None,
) -> dict:
    """
    The mandatory closing of every report, framed as a direct analyst
    recommendation rather than a repeated summary: if you could only
    pursue one opportunity this week, which one and why — plus what to
    explicitly deprioritise and what's still worth watching. Every field
    is deterministically derived from content already built elsewhere in
    this module (build_verdict, analysis, watch list) — nothing new is
    introduced here, only prioritised and summarised.
    """
    ranked = sorted(
        explained_opportunities,
        key=lambda o: (_VERDICT_PRIORITY.get(o["build_verdict"]["label"], 9), -o["composite_score"]),
    )
    best = ranked[0] if ranked else None
    best_is_actionable = bool(best) and best["build_verdict"]["label"] != "Ignore"

    return {
        "if_i_could_only_pursue_one": _closing_single_best_bet(best, best_is_actionable),
        "why": _closing_why(best, best_is_actionable),
        "what_id_ignore": _closing_what_to_ignore(explained_opportunities, watch_list),
        "what_id_keep_monitoring": _closing_what_to_monitor(explained_opportunities, watch_list, trends),
    }


def _closing_single_best_bet(best: dict | None, actionable: bool) -> str:
    if not best or not actionable:
        return (
            "None — nothing this period clears the bar for a confident pick. "
            "Best use of the coming week is broadening signal collection rather "
            "than committing to a specific opportunity."
        )
    return f"{best['title'].rstrip('.')} ({best['tier']}-tier, {best['composite_score']:.1f}/10)."


def _closing_why(best: dict | None, actionable: bool) -> str:
    if not best or not actionable:
        return "No opportunity this period has strong enough evidence to justify committing a week of founder time."
    return f"{best['build_verdict']['justification']} {best['analysis']['business_potential']}"


def _closing_what_to_ignore(explained_opportunities: list[dict], watch_list: list[dict]) -> list[str]:
    ignored = [o["title"] for o in explained_opportunities if o["build_verdict"]["label"] == "Ignore"]
    ignored += [w["title"] for w in watch_list if w["recommended_action"]["label"] == "Ignore"]
    if not ignored:
        return ["Nothing this period — everything evaluated is either worth pursuing or worth continued monitoring."]
    return ignored[:5]


def _closing_what_to_monitor(
    explained_opportunities: list[dict],
    watch_list: list[dict],
    trends: list[dict],
) -> list[str]:
    items = [o["title"] for o in explained_opportunities if o["build_verdict"]["label"] == "Monitor"]
    items += [w["title"] for w in watch_list if w["recommended_action"]["label"] in ("Monitor", "Research")]
    if trends:
        items.append(f"{trends[0]['name']} (emerging trend)")
    if not items:
        return ["Nothing specific — revisit with fresh signal collection next period."]
    return items[:5]
