"""
opportunity_engine/explainer/opportunity.py — single-opportunity narrative
explanation (explain_opportunity and everything it alone depends on).

See opportunity_engine/explainer/__init__.py for this module's place in
the overall split.
"""

from collections import defaultdict

from config import MANUAL_WORKFLOW_KEYWORDS
from knowledge_graph.schema import ENTITY_TYPES, display_name
from models import Signal

from opportunity_engine.explainer._shared import _SOURCE_LABELS

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

_GENERIC_TERMS = {"ai", "saas", "api", "apis", "software", "app", "tool", "product", "platform"}

_MARKET_TYPE = "market"

# Actual named SaaS/tool products from the technology entity keyword list —
# deliberately excludes programming languages/frameworks (react, python),
# infrastructure (aws, postgresql), and generic AI model names (gpt,
# claude, gemini) from the "existing competitors" callout, since none of
# those are competing products for a typical business-opportunity idea.
_KNOWN_PRODUCT_KEYWORDS = {"notion", "airtable", "slack", "github", "figma", "zapier", "ifttt", "make", "n8n"}

_DISTRIBUTION_CHANNEL_BY_SOURCE = {
    "hn": ("Direct engagement in Hacker News threads (a Show HN post, replies in the "
           "relevant Ask HN thread) — the same audience already discussing this."),
    "reddit": ("Organic participation in the same subreddit(s) where this was "
               "discussed — direct replies to the people who posted, plus a "
               "relevant post of your own once you have something to show."),
    "rss": "Content/SEO targeting the same publications and search terms surfaced in the evidence.",
    "trends": "SEO and content targeting the search terms that surfaced this signal.",
}


# ── Small helpers ────────────────────────────────────────────────────────

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


def _distinguishing_terms(cluster_signals: list[Signal], limit: int = 3) -> list[str]:
    """
    Pull a few concrete, real terms out of the cluster's own text — used to
    ground the business-potential narrative in specifics instead of filler.
    Reuses the same entity keyword vocabulary as the extractor, so nothing
    here is invented; every term returned was actually detected in the text.

    Near-universal terms ("AI", "SaaS", "API") are excluded even when
    matched — true almost everywhere in this domain, so they don't actually
    distinguish this opportunity from any other. Known competitor/product
    names (see _KNOWN_PRODUCT_KEYWORDS, used by _named_competitors) are
    also excluded — a term that's already named as competition should
    never be framed as the direction to differentiate "around" or build
    an MVP "focused on"; that's self-contradictory.
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
            if kw in _GENERIC_TERMS or kw in _KNOWN_PRODUCT_KEYWORDS:
                continue
            if kw in blob:
                name = display_name(kw)
                if name.lower() not in seen:
                    seen.add(name.lower())
                    found.append(name)
            if len(found) >= limit:
                return found
    return found


# ── Founder action recommendation ───────────────────────────────────────
# A fixed, shared vocabulary used everywhere the report tells a reader what
# to actually do: Build, Validate, Research, Monitor, Ignore. Kept as a
# small closed set deliberately — a founder scanning many reports over time
# should be able to pattern-match the label without reading the justification
# every time, the same way "Buy/Hold/Sell" works in an analyst note.

def _build_verdict(
    tier: str,
    recurrence: dict | None,
    confidence_score: float,
    evidence_count: int,
    source_count: int,
    pay_confirmed: bool,
    manual_workflow_confirmed: bool,
    underserved_niche_confirmed: bool,
) -> dict:
    """
    The single most decision-relevant field on an opportunity: what would
    a founder actually do with this? Fixed vocabulary: Build, Validate
    First, Monitor, Ignore — deliberately small so it reads at a glance
    across many reports over time, the same way "Buy/Hold/Sell" works in
    an analyst note.

    "Build" requires more than a high blended score: it requires named,
    checkable evidence — cross-source confirmation (≥2 independent
    sources) AND confirmed willingness-to-pay language, not just a
    composite number that could be high for other reasons. A cluster can
    reach gold-tier and high confidence through execution/competition/risk
    dimensions alone; those don't tell you anyone will pay for anything.
    """
    growing_recurring = bool(
        recurrence and recurrence.get("direction") == "growing"
        and recurrence.get("weeks_seen", 1) >= 2
    )
    cross_source_confirmed = source_count >= 2

    evidence_cited = []
    if pay_confirmed:
        evidence_cited.append("confirmed willingness-to-pay language")
    if manual_workflow_confirmed:
        evidence_cited.append("evidence of a manual, unautomated workflow")
    if underserved_niche_confirmed:
        evidence_cited.append("evidence of an underserved niche")
    if growing_recurring:
        evidence_cited.append(f"recurring for {recurrence['weeks_seen']} consecutive weeks and growing")
    if cross_source_confirmed:
        evidence_cited.append(f"confirmed across {source_count} independent sources")

    if len(evidence_cited) == 0:
        cited_text = "no strong corroborating evidence beyond the raw score"
    elif len(evidence_cited) == 1:
        cited_text = evidence_cited[0]
    else:
        cited_text = ", ".join(evidence_cited[:-1]) + ", and " + evidence_cited[-1]

    if tier == "gold" and confidence_score >= 7.0 and cross_source_confirmed and pay_confirmed:
        return {"label": "Build", "justification": (
            f"Clears the full evidence bar: {cited_text}. Strong enough to "
            f"justify a minimum build this period."
        )}

    if (tier == "gold" or growing_recurring or (tier == "silver" and confidence_score >= 6.0)) and cross_source_confirmed:
        missing = "confirmed willingness-to-pay language" if not pay_confirmed else "a longer track record of recurrence"
        return {"label": "Validate First", "justification": (
            f"Promising on {cited_text}, but {missing} hasn't been directly "
            f"confirmed yet — validate with user interviews and a pricing test "
            f"before committing build time."
        )}

    if tier == "silver" or confidence_score >= 4.0 or evidence_count >= 3:
        return {"label": "Monitor", "justification": (
            f"Some evidence present ({cited_text}), but not yet strong enough "
            f"to act on — worth tracking to see whether it strengthens."
        )}

    return {"label": "Ignore", "justification": (
        f"Evidence is too thin relative to the likely payoff ({cited_text}) — "
        f"not worth spending founder time on unless the pattern strengthens materially."
    )}


def _market_size(cluster_signals: list[Signal], target_group: str) -> dict:
    """
    A deliberately rough Small/Medium/Large read on addressable market
    breadth, derived only from what's actually detectable in the evidence
    — the number of distinct market-type terms mentioned and how broad
    vs. niche the primary target group reads. This is NOT a substitute
    for real market sizing research (TAM/SAM/SOM with actual data) — it's
    a fast, evidence-grounded triage signal, and is explicitly labelled
    as such in the explanation text so it's never mistaken for verified
    market data.
    """
    blob = " ".join(s.full_text for s in cluster_signals) if cluster_signals else ""
    market_type = ENTITY_TYPES.get(_MARKET_TYPE)
    matched_markets: list[str] = []
    if market_type:
        for kw in market_type.keywords:
            if kw in blob:
                name = display_name(kw)
                if name not in matched_markets:
                    matched_markets.append(name)

    is_broad_group = target_group in (
        "business and team users",
        "the professionals discussed in these signals",
    )
    adjacent = [m for m in matched_markets if m.lower() not in target_group.lower()][:3]
    n_adjacent = len(adjacent)

    # Branches are ordered so the explanation text can never claim an
    # adjacent segment exists unless `adjacent` is actually non-empty —
    # that mismatch was a real bug caught in review (Medium used to say
    # "at least one adjacent segment visible" while adjacent_markets was []).
    if is_broad_group and n_adjacent >= 2:
        size = "Large"
        explanation = (
            f"The audience reads broadly (business/team users) and multiple distinct "
            f"market segments appear in the evidence ({', '.join(adjacent)}) — this "
            f"could extend well beyond the initial niche if the core problem generalises."
        )
    elif n_adjacent >= 1:
        size = "Medium"
        explanation = (
            f"At least one adjacent market segment is visible in the evidence "
            f"({', '.join(adjacent)}) — a real market, but likely requiring expansion "
            f"beyond the initial niche to reach significant scale."
        )
    elif is_broad_group:
        size = "Medium"
        explanation = (
            "The audience reads broadly (business/team users), though no distinct "
            "adjacent market segments were detected in the evidence yet — likely a "
            "real market, but breadth beyond the initial niche isn't yet confirmed."
        )
    else:
        size = "Small"
        explanation = (
            "The evidence points to a narrow, specific niche with no adjacent "
            "segments detected yet — a real but likely small addressable market "
            "unless it can be shown to generalise."
        )

    return {
        "size": size,
        "explanation": explanation,
        "adjacent_markets": adjacent,
    }


def _action_plan(tier: str, target_group: str, explanations: dict, verdict_label: str) -> dict:
    """
    A concrete five-stage execution plan, in place of a generic action
    list — every founder-facing report should answer "what do I actually
    do, and when do I stop."
    """
    competition_evidence = explanations.get("competition", {}).get("evidence", "")
    pay_confirmed = "0 willingness-to-pay" not in explanations.get("revenue_potential", {}).get("evidence", "")

    if verdict_label == "Ignore":
        return {
            "validate": "Not recommended — evidence is too thin to justify the time cost of formal validation right now.",
            "build_mvp": "Do not build. Revisit only if this pattern resurfaces with materially stronger evidence.",
            "acquire_first_users": "N/A at this stage.",
            "success_criteria": f"Would need 3+ independent, corroborated signals from {target_group} before reconsidering.",
            "kill_criteria": "Already below the bar — no further action needed unless new evidence appears.",
        }

    validate_step = f"Interview 3–5 people from {target_group} to confirm the pain point is real and prioritised."
    if "0 low-competition" in competition_evidence:
        validate_step += " Also map existing alternatives directly — the assumed gap hasn't been confirmed."

    if verdict_label == "Build":
        build_step = "Ship a minimum version this period — evidence is strong enough to skip further validation delay."
    else:
        build_step = "Hold off on building until validation (above) confirms demand and pricing."

    if pay_confirmed:
        acquire_step = "Reach out directly to the people already expressing this need in the collected signals — they're the fastest first users."
    else:
        acquire_step = "Test willingness to pay first (landing page or pre-order) before investing in user acquisition."

    success_criteria = (
        f"3+ people from {target_group} confirm they'd pay for this, and at least "
        f"one commits to a paid pilot within the next 2–3 weeks."
    )
    kill_criteria = (
        f"Fewer than 2 of 5 interviewed {target_group} confirm the pain point, or "
        f"no one commits to a paid pilot within 3 weeks of asking — deprioritise "
        f"and return this to the watch list."
    )

    return {
        "validate": validate_step,
        "build_mvp": build_step,
        "acquire_first_users": acquire_step,
        "success_criteria": success_criteria,
        "kill_criteria": kill_criteria,
    }


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
    `market_size` (Small/Medium/Large with adjacent markets), a
    `build_verdict` (Build/Validate First/Monitor/Ignore), a concrete
    `action_plan`, and `supporting_data` for anyone who wants to drill
    into the numbers (kept, but deliberately not the focus).
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

    market_gap_text = _market_gap(explanations)
    analysis = {
        "market_context": _market_context(target_group, sources_involved, explanations),
        "market_gap": market_gap_text,
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

    pay_confirmed = "0 willingness-to-pay" not in explanations.get("revenue_potential", {}).get("evidence", "")
    underserved_niche_confirmed = "0 low-competition" not in explanations.get("competition", {}).get("evidence", "")
    cluster_blob = " ".join(s.full_text for s in cluster_signals) if cluster_signals else ""
    manual_workflow_confirmed = any(kw in cluster_blob for kw in MANUAL_WORKFLOW_KEYWORDS)

    verdict = _build_verdict(
        tier, recurrence, scores.get("confidence", 0.0),
        scores.get("evidence_count", len(cluster_signals)),
        source_count=len(sources_involved),
        pay_confirmed=pay_confirmed,
        manual_workflow_confirmed=manual_workflow_confirmed,
        underserved_niche_confirmed=underserved_niche_confirmed,
    )

    return {
        "title": opp.get("title", ""),
        "tier": tier,
        "composite_score": opp.get("composite_score", 0.0),
        "market_size": _market_size(cluster_signals, target_group),
        "build_verdict": verdict,
        "analysis": analysis,
        "founder_intelligence": _founder_intelligence(
            target_group, cluster_signals, explanations, terms, market_gap_text,
        ),
        "action_plan": _action_plan(tier, target_group, explanations, verdict["label"]),
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


def _named_competitors(cluster_signals: list[Signal]) -> str:
    blob = " ".join(s.full_text for s in cluster_signals) if cluster_signals else ""
    found = sorted({display_name(kw) for kw in _KNOWN_PRODUCT_KEYWORDS if kw in blob})
    if found:
        return f"Named directly in the evidence: {', '.join(found)}."
    return ("No specific competing product was named in the collected evidence — "
            "competition assessment relies on the general market-gap signal only, "
            "not a confirmed absence of competitors.")


def _fastest_mvp(terms: list[str], target_group: str) -> str:
    if terms:
        return (
            f"A narrow, single-purpose tool focused on {terms[0]} for {target_group} — "
            f"skip general-purpose features and ship the one workflow the evidence "
            f"actually describes."
        )
    return (
        f"A narrow, single-purpose tool solving the specific pain point described by "
        f"{target_group} — avoid building a general-purpose platform on the first pass."
    )


def _first_distribution_channel(cluster_signals: list[Signal]) -> str:
    if not cluster_signals:
        return "Not enough evidence to identify a likely first channel."
    source_counts: dict[str, int] = defaultdict(int)
    for s in cluster_signals:
        source_counts[s.source] += 1
    dominant_source = max(source_counts, key=source_counts.get)
    return _DISTRIBUTION_CHANNEL_BY_SOURCE.get(
        dominant_source,
        f"The {dominant_source} community where this was discussed.",
    )


def _time_to_first_revenue(explanations: dict) -> str:
    exp = explanations.get("time_to_revenue", {})
    score = exp.get("score", 5.5)
    reason = exp.get("reason", "")
    if score >= 8.0:
        bucket = "Days to a couple of weeks"
    elif score >= 6.0:
        bucket = "A few weeks to a couple of months"
    elif score >= 4.0:
        bucket = "A few months"
    else:
        bucket = "Likely 6+ months"
    return f"{bucket} — {reason}" if reason else bucket


def _founder_intelligence(
    target_group: str,
    cluster_signals: list[Signal],
    explanations: dict,
    terms: list[str],
    market_gap_text: str,
) -> dict:
    """
    Answers the seven questions a founder actually asks before committing
    time to an idea. market_gap reuses the exact same text already computed
    for analysis.market_gap (not recomputed) — this is the one deliberate
    exception to the no-repetition principle, since the founder-intelligence
    block is meant to be scanned top-to-bottom as a checklist, a different
    reading mode from the flowing analysis narrative above it.
    """
    why_pay = explanations.get("revenue_potential", {}).get("reason") or (
        "Not directly confirmed in the evidence — willingness to pay should "
        "be validated before building."
    )
    return {
        "who_is_the_customer": target_group[:1].upper() + target_group[1:] + ".",
        "why_do_they_pay": why_pay,
        "existing_competitors": _named_competitors(cluster_signals),
        "market_gap": market_gap_text,
        "fastest_mvp": _fastest_mvp(terms, target_group),
        "first_distribution_channel": _first_distribution_channel(cluster_signals),
        "time_to_first_revenue": _time_to_first_revenue(explanations),
    }


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
