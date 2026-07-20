"""
opportunity_engine/explainer.py — Intelligence explanation layer

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
"""

from collections import defaultdict

from config import MIN_COMPOSITE_TO_PERSIST
from knowledge_graph.insights import explain_pair
from knowledge_graph.schema import ENTITY_TYPES, display_name
from models import Signal

_SOURCE_LABELS = {
    "hn": "Hacker News", "reddit": "Reddit",
    "rss": "RSS feeds", "trends": "Search trends",
}

_DIMENSION_LABELS = [
    ("demand", "Demand"),
    ("competition", "Competition"),
    ("revenue_potential", "Revenue Potential"),
    ("execution_difficulty", "Execution Difficulty"),
    ("time_to_revenue", "Time to Revenue"),
    ("risk", "Risk"),
    ("confidence", "Confidence"),
]

_B2B_TERMS = [
    "business", "enterprise", "b2b", "company", "team",
    "organization", "startup", "saas", "client",
]
_SOLO_TERMS = ["freelance", "freelancer", "solo", "independent", "individual", "consultant"]

_REJECTION_LABELS = {
    "too_small": "the pattern only appeared a handful of times",
    "single_source": "the pattern was confined to a single source",
    "below_threshold": "the evidence, once scored, was too weak overall",
}

_TITLE_STOPWORDS = {
    "the", "a", "an", "for", "and", "or", "of", "to", "in", "on", "with",
    "is", "are", "this", "that", "new", "software", "tool", "app",
}


# ── Small shared helpers ──────────────────────────────────────────────────

def _title_tokens(title: str) -> set[str]:
    words = "".join(c if c.isalnum() else " " for c in title.lower()).split()
    return {w for w in words if len(w) > 3 and w not in _TITLE_STOPWORDS}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _target_group(cluster_signals: list[Signal]) -> str:
    """A short phrase describing who these signals are coming from."""
    blob = " ".join(s.full_text for s in cluster_signals)
    b2b_hits = sum(1 for t in _B2B_TERMS if t in blob)
    solo_hits = sum(1 for t in _SOLO_TERMS if t in blob)
    if b2b_hits >= 2 and b2b_hits >= solo_hits:
        return "business and team users"
    if solo_hits >= 1:
        return "independent professionals and freelancers"
    return "the professionals discussed in these signals"


_GENERIC_TERMS = {"ai", "saas", "api", "apis", "software", "app", "tool", "product", "platform"}


def _distinguishing_terms(cluster_signals: list[Signal], limit: int = 3) -> list[str]:
    """
    Pull a few concrete, real terms out of the cluster's own text — used to
    ground the business-potential narrative in specifics instead of filler.
    Reuses the same entity keyword vocabulary as the extractor, so nothing
    here is invented; every term returned was actually detected in the text.

    Near-universal terms ("AI", "SaaS", "API") are excluded even when
    matched — true almost everywhere in this domain, so they don't actually
    distinguish this opportunity from any other.
    """
    blob = " ".join(s.full_text for s in cluster_signals)
    found: list[str] = []
    seen = set()
    # Prioritise the more distinguishing types first (skip "market", which
    # tends to just restate who the audience is — already covered elsewhere).
    for type_name in ["technology", "problem", "skill", "regulation"]:
        etype = ENTITY_TYPES.get(type_name)
        if not etype:
            continue
        for kw in etype.keywords:
            if kw in _GENERIC_TERMS:
                continue
            if kw in blob:
                name = display_name(kw)
                if name.lower() not in seen:
                    seen.add(name.lower())
                    found.append(name)
            if len(found) >= limit:
                return found
    return found


# ── Opportunity analysis ─────────────────────────────────────────────────

def explain_opportunity(
    opp: dict,
    cluster_signals: list[Signal],
    recurrence: dict | None = None,
) -> dict:
    """
    Build a full analyst-style explanation for one opportunity.

    Args:
        opp: a row dict as returned by ReportGenerator._get_week_opportunities()
             — must include "scores" (the serialised OpportunityScores dict).
        cluster_signals: the actual Signal objects behind this opportunity.
             May be empty if signals fell outside the report's window —
             degrades gracefully rather than failing.
        recurrence: optional {"weeks_seen": int, "direction": "growing"|
             "fading"|"stable"} from matching against previous reports —
             see report/generator.py's use of _match_previous_opportunity().
             None means "no history available" (e.g. first tracked week).

    Returns a dict with the opportunity's identity, a narrative `analysis`,
    concrete `recommended_actions`, and `supporting_data` for anyone who
    wants to drill into the numbers (kept, but deliberately not the focus).
    """
    scores = opp.get("scores", {}) or {}
    explanations = scores.get("explanations", {}) or {}
    tier = opp.get("tier", "bronze")

    if cluster_signals:
        top_signals = sorted(cluster_signals, key=lambda s: s.engagement, reverse=True)[:5]
        evidence = [
            {
                "source": s.source, "source_label": _SOURCE_LABELS.get(s.source, s.source),
                "title": s.title, "engagement": s.engagement, "url": s.url,
            }
            for s in top_signals
        ]
        target_group = _target_group(cluster_signals)
        terms = _distinguishing_terms(cluster_signals)
        sources_involved = sorted({_SOURCE_LABELS.get(s.source, s.source) for s in cluster_signals})
    else:
        evidence, target_group, terms, sources_involved = [], "the professionals discussed in these signals", [], []

    analysis = {
        "market_context": _market_context(target_group, sources_involved, explanations),
        "market_gap": _market_gap(explanations),
        "business_potential": _business_potential(explanations, terms, target_group),
        "risks": _risks_narrative(explanations, scores.get("evidence_count", len(cluster_signals))),
        "confidence": _confidence_narrative(explanations, recurrence),
    }

    score_breakdown = [
        {
            "dimension": label,
            "score": round(scores.get(key, 0.0), 2),
            "reason": explanations.get(key, {}).get("reason", ""),
            "evidence": explanations.get(key, {}).get("evidence", ""),
        }
        for key, label in _DIMENSION_LABELS
    ]

    return {
        "title": opp.get("title", ""),
        "tier": tier,
        "composite_score": opp.get("composite_score", 0.0),
        "analysis": analysis,
        "recommended_actions": _recommended_actions(tier, target_group, explanations),
        "supporting_data": {
            "evidence": evidence,
            "evidence_count": scores.get("evidence_count", len(cluster_signals)),
            "score_breakdown": score_breakdown,
        },
    }


def _market_context(target_group: str, sources_involved: list[str], explanations: dict) -> str:
    demand_reason = explanations.get("demand", {}).get("reason", "")
    if sources_involved:
        source_phrase = (
            sources_involved[0] if len(sources_involved) == 1
            else " and ".join([", ".join(sources_involved[:-1]), sources_involved[-1]])
        )
        lead = f"Current interest comes from {target_group}, visible in independent discussions on {source_phrase}."
    else:
        lead = f"Current interest comes from {target_group}."
    if demand_reason:
        return f"{lead} {demand_reason}"
    return lead


def _market_gap(explanations: dict) -> str:
    exp = explanations.get("competition", {})
    reason = exp.get("reason", "")
    if reason:
        return reason
    return ("No specific competing product was named in the collected discussions; "
            "treat this as an assumed moderate-competition market until validated directly.")


def _business_potential(explanations: dict, terms: list[str], target_group: str) -> str:
    revenue_exp = explanations.get("revenue_potential", {})
    ttr_exp = explanations.get("time_to_revenue", {})

    if terms:
        term_phrase = ", ".join(terms[:-1]) + (" and " + terms[-1] if len(terms) > 1 else terms[0])
        differentiation = f"A focused offering could differentiate around {term_phrase} rather than competing as a generic tool."
    else:
        differentiation = f"A focused offering tailored specifically to {target_group} — rather than a generic tool — is the likeliest differentiation path."

    revenue_reason = revenue_exp.get("reason", "")
    ttr_reason = ttr_exp.get("reason", "")
    parts = [differentiation]
    if revenue_reason:
        parts.append(revenue_reason)
    if ttr_reason:
        parts.append(ttr_reason)
    return " ".join(parts)


def _risks_narrative(explanations: dict, evidence_count: int) -> str:
    risk_exp = explanations.get("risk", {})
    reason = risk_exp.get("reason", "")
    parts = [reason] if reason else []
    if evidence_count and evidence_count < 5:
        parts.append(
            "The market may be too niche to support a standalone product unless "
            "adjacent audiences with the same underlying need are included."
        )
    if not parts:
        parts.append("No specific risk factors were identified in the collected evidence.")
    return " ".join(parts)


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _confidence_narrative(explanations: dict, recurrence: dict | None) -> str:
    exp = explanations.get("confidence", {})
    reason = exp.get("reason", "")
    base = reason or "Confidence could not be assessed from the available evidence."

    if recurrence and recurrence.get("weeks_seen", 1) > 1:
        weeks = recurrence["weeks_seen"]
        direction = recurrence.get("direction", "stable")
        weeks_label = _ordinal(weeks)
        if direction == "growing":
            persistence = (f"This is the {weeks_label} consecutive week this pattern has appeared, "
                            f"and it is strengthening — which raises confidence further.")
        elif direction == "fading":
            persistence = (f"This pattern has now appeared for {weeks} consecutive weeks but is weakening — "
                            f"worth confirming it isn't a fading trend before committing further.")
        else:
            persistence = f"This pattern has now appeared for {weeks} consecutive weeks, which raises confidence further."
        return f"{base} {persistence}"

    return f"{base} This is the first week this pattern has been observed, so persistence across future weeks hasn't been confirmed yet."


def _recommended_actions(tier: str, target_group: str, explanations: dict) -> list[str]:
    actions: list[str] = []
    actions.append(f"Interview 3–5 people from {target_group} to validate this specific pain point before building anything.")

    competition_evidence = explanations.get("competition", {}).get("evidence", "")
    if "0 low-competition" in competition_evidence:
        actions.append("Spend an hour mapping existing alternatives — the assumed market gap hasn't been directly confirmed.")
    else:
        actions.append("Review the named alternatives directly to confirm where the real gap is.")

    revenue_evidence = explanations.get("revenue_potential", {}).get("evidence", "")
    if "0 willingness-to-pay" in revenue_evidence:
        actions.append("Willingness to pay hasn't been directly confirmed — test pricing with a simple landing page before writing code.")
    else:
        actions.append("Estimate pricing and test it with a simple landing page or pre-order page.")

    if tier == "gold":
        actions.append("If validation holds up, build a minimum viable version this week rather than waiting for more signal.")
    elif tier == "silver":
        actions.append("Hold off on building until the competitive picture and pricing are validated.")
    else:
        actions.append("Keep this on a light watch rather than prioritising it yet — evidence is present but not yet strong.")

    actions.append("Monitor next week's signals to see whether this pattern recurs, grows, or fades.")
    return actions


# ── Zero / near-miss opportunity explanation ─────────────────────────────

def explain_zero_opportunities(rejected: list, total_signals: int) -> dict:
    """
    Explain why nothing qualified this period, instead of just reporting a
    count. Args: rejected = list of opportunity_engine.detector.RejectedCluster.
    """
    if total_signals == 0:
        return {
            "reason": ("No signals were collected for this domain in this period, "
                       "so there was nothing to evaluate."),
            "candidates": [],
        }

    if not rejected:
        return {
            "reason": ("No repeated pattern formed at all this period — the collected "
                       "signals were too varied in topic to group into anything worth evaluating."),
            "candidates": [],
        }

    ranked = sorted(
        rejected,
        key=lambda r: (r.scores.composite() if r.scores else -1.0, len(r.signals)),
        reverse=True,
    )[:5]

    candidates = []
    for r in ranked:
        anchor = max(r.signals, key=lambda s: s.engagement)
        candidates.append({
            "title": anchor.title,
            "signal_count": len(r.signals),
            "sources": sorted(set(s.source for s in r.signals)),
            "composite_score": r.scores.composite() if r.scores else None,
            "why_it_failed": r.summary,
            "missing_evidence": _missing_evidence(r),
        })

    reason_counts: dict[str, int] = defaultdict(int)
    for r in rejected:
        reason_counts[r.reason] += 1
    dominant_reason = max(reason_counts, key=reason_counts.get)
    dominant_label = _REJECTION_LABELS.get(dominant_reason, dominant_reason)

    theme = _weak_dimension_theme(rejected)
    reason = (
        f"Nothing reached the confidence bar this period — {dominant_label} across "
        f"{len(rejected)} candidate pattern(s) that were considered.{theme}"
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
    return "Overall evidence was too thin to justify tracking this further."


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


# ── Trend analysis ────────────────────────────────────────────────────────

_TREND_NAME_TEMPLATES: dict[tuple[str, str], str] = {
    ("technology", "technology"): "{a} + {b} tooling",
    ("technology", "problem"):    "{a} for {b}",
    ("technology", "market"):     "{a} adoption among {b}",
    ("market", "problem"):        "{b} in {a}",
    ("technology", "skill"):      "{a}-driven {b}",
    ("regulation", "market"):     "{a} pressure on {b}",
}

_WHO_CARES = {
    "technology": "developers and technical builders",
    "market":     "founders and operators serving that segment",
    "problem":    "product teams looking to solve this pain point",
    "skill":      "freelancers and consultants offering this skill",
    "regulation": "compliance and legal teams",
    "company":    "competitors and partners watching that company",
    "product":    "teams building adjacent products",
}


def build_trend_analysis(
    signals: list[Signal],
    top_pairs: list[dict],
    previous_pairs: list[dict] | None = None,
    limit: int = 5,
) -> list[dict]:
    """
    Build named trends from the strongest entity co-occurrence pairs, each
    with a "so what" narrative: why it's emerging, who benefits, and
    whether it looks like a one-off or an early shift (when history exists).
    """
    previous_names = set()
    if previous_pairs:
        for p in previous_pairs:
            previous_names.add(frozenset({p["from"]["name"], p["to"]["name"]}))

    trends = []
    for pair in top_pairs[:limit]:
        a, b = pair["from"], pair["to"]
        weight = pair.get("weight", 1.0)

        supporting = _signals_mentioning_both(signals, a["name"], b["name"])
        if not supporting:
            supporting = _signals_mentioning_any(signals, [a["name"], b["name"]])
        evidence = [
            f'"{s.title[:100]}" ({_SOURCE_LABELS.get(s.source, s.source)})'
            for s in sorted(supporting, key=lambda s: s.engagement, reverse=True)[:2]
        ]

        is_recurring = frozenset({a["name"], b["name"]}) in previous_names
        if previous_pairs is None:
            temporal = "There isn't yet enough history to say whether this is a lasting shift — worth tracking over the next few weeks."
        elif is_recurring:
            temporal = "This connection also appeared last period, which suggests a developing pattern rather than a one-off discussion."
        else:
            temporal = "This is the first period this connection has appeared — treat it as an early signal until it recurs."

        who = _who_might_care(a, b)
        so_what = f"{explain_pair(pair)} This is particularly relevant to {who}. {temporal}"

        trends.append({
            "name": _trend_name(a, b),
            "so_what": so_what,
            "entities": [a["name"], b["name"]],
            "evidence": evidence,
            "confidence": _trend_confidence(weight, len(supporting)),
        })
    return trends


def _trend_name(a: dict, b: dict) -> str:
    key, rkey = (a["type"], b["type"]), (b["type"], a["type"])
    if key in _TREND_NAME_TEMPLATES:
        return _TREND_NAME_TEMPLATES[key].format(a=a["name"], b=b["name"])
    if rkey in _TREND_NAME_TEMPLATES:
        return _TREND_NAME_TEMPLATES[rkey].format(a=b["name"], b=a["name"])
    return f"{a['name']} & {b['name']}"


def _who_might_care(a: dict, b: dict) -> str:
    labels = sorted({
        _WHO_CARES.get(a["type"], "generalist builders"),
        _WHO_CARES.get(b["type"], "generalist builders"),
    })
    return " and ".join(labels)


def _trend_confidence(weight: float, supporting_count: int) -> str:
    if weight >= 5 or supporting_count >= 5:
        return "High"
    if weight >= 2 or supporting_count >= 2:
        return "Medium"
    return "Low"


def _signals_mentioning_both(signals: list[Signal], name_a: str, name_b: str) -> list[Signal]:
    na, nb = name_a.lower(), name_b.lower()
    return [s for s in signals if na in s.full_text and nb in s.full_text]


def _signals_mentioning_any(signals: list[Signal], names: list[str]) -> list[Signal]:
    lowered = [n.lower() for n in names]
    return [s for s in signals if any(n in s.full_text for n in lowered)]


# ── Historical comparison ───────────────────────────────────────────────

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


# ── Executive summary ──────────────────────────────────────────────────────

def build_executive_summary(
    signal_stats: dict,
    explained_opportunities: list[dict],
    trends: list[dict],
    zero_opps_explanation: dict | None,
    comparison: dict | None,
) -> str:
    """
    A short analyst-briefing paragraph: what happened, why it matters, and
    whether anything is worth attention — leading with business meaning,
    not measurements. Every claim traces back to real computed data.
    """
    n_signals = signal_stats.get("total", 0)
    if n_signals == 0:
        return ("No signals were collected for this domain in this period — "
                "there is nothing to report on yet.")

    gold = [o for o in explained_opportunities if o.get("tier") == "gold"]
    silver = [o for o in explained_opportunities if o.get("tier") == "silver"]
    bronze = [o for o in explained_opportunities if o.get("tier") == "bronze"]

    if gold or silver:
        top = (gold or silver)[0]
        confidence_word = "strong" if gold else "moderate"
        parts = [
            f"This period we identified an emerging opportunity around {top['title'].rstrip('.')}."
        ]
        market_context = top["analysis"]["market_context"]
        parts.append(market_context)
        gap = top["analysis"]["market_gap"]
        parts.append(gap)
        parts.append(
            f"Evidence is {confidence_word} enough to be worth attention, though it should still be validated "
            f"before committing significant time or money."
        )
    elif bronze:
        top = bronze[0]
        parts = [
            f"This period surfaced a possible pattern around {top['title'].rstrip('.')}, "
            f"but evidence is thin enough that it's worth a light watch rather than immediate attention."
        ]
        parts.append(top["analysis"]["market_context"])
    elif zero_opps_explanation:
        parts = [zero_opps_explanation["reason"]]
    else:
        parts = [f"{n_signals} signals were collected this period but no clear pattern emerged worth flagging."]

    if trends:
        names = ", ".join(t["name"] for t in trends[:2])
        parts.append(f"Separately, {names} showed up as a recurring theme worth keeping an eye on.")

    if comparison:
        parts.append(comparison["narrative"])

    return " ".join(parts)
