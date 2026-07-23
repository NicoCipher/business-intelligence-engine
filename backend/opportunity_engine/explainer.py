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

from config import (
    MIN_COMPOSITE_TO_PERSIST, DEMAND_KEYWORDS, COMPLAINT_KEYWORDS,
    WILLINGNESS_TO_PAY, MANUAL_WORKFLOW_KEYWORDS,
)
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
    "too_small": "insufficient mention volume to qualify as a pattern",
    "single_source": "corroboration from only one source, not yet cross-validated",
    "below_threshold": "evidence quality fell short of the investment-grade bar once scored",
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


_WHY_MATTERS_TEMPLATES: dict[tuple[str, str], str] = {
    ("technology", "technology"): (
        "Two tools converging like this often signals an emerging technical stack. "
        "Builders who move early on the combination can establish a positioning "
        "advantage before it becomes conventional wisdom."
    ),
    ("technology", "problem"): (
        "When a technology repeatedly appears next to a named problem, it signals "
        "the market is actively searching for that technology as the solution — "
        "a timing signal for anyone building in the space."
    ),
    ("technology", "market"): (
        "Adoption signals within a specific market segment are an early indicator "
        "of where budget and attention are shifting."
    ),
    ("market", "problem"): (
        "A recurring pain point within a defined market is exactly the kind of "
        "evidence that de-risks a build decision — a named audience with a named problem."
    ),
    ("technology", "skill"): (
        "Rising demand for a skill/technology combination points to a services or "
        "education opportunity, independent of any single product."
    ),
    ("regulation", "market"): (
        "Regulatory pressure on a market segment creates urgency — compliance-driven "
        "purchases tend to move faster than discretionary ones."
    ),
}
_WHY_MATTERS_DEFAULT = (
    "Recurring co-occurrence between two concepts is a leading indicator worth "
    "tracking, even before it's clear which side of the pairing ends up mattering more."
)


def _why_it_matters(a: dict, b: dict) -> str:
    key, rkey = (a["type"], b["type"]), (b["type"], a["type"])
    return _WHY_MATTERS_TEMPLATES.get(key) or _WHY_MATTERS_TEMPLATES.get(rkey) or _WHY_MATTERS_DEFAULT


# ── Founder action recommendations ────────────────────────────────────────
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


_MARKET_TYPE = "market"


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


def _trend_recommendation(confidence_label: str, recurring: bool | None) -> dict:
    if confidence_label == "High" or recurring:
        return {"label": "Research", "justification": (
            "A strongly-weighted, recurring connection is worth deeper research "
            "into how to position around it."
        )}
    if confidence_label == "Medium":
        return {"label": "Monitor", "justification": (
            "A moderate signal — worth watching for recurrence before acting on it."
        )}
    return {"label": "Monitor", "justification": (
        "Early and lightly weighted — track for a few more periods before drawing conclusions."
    )}


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


# ── Founder Intelligence ──────────────────────────────────────────────────
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


# ── Zero / near-miss opportunity explanation ─────────────────────────────

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


def _pair_key(pair: dict) -> frozenset:
    return frozenset({pair["from"]["name"], pair["to"]["name"]})


def pair_recurrence(pair: dict, previous_pairs: list[dict] | None) -> dict:
    """
    Whether this entity pair also showed up in the previous period's
    top pairs — a real week-over-week recurrence signal, distinct from
    relationships.weight (a lifetime cumulative co-occurrence count that
    doesn't know or care about weekly cadence).

    Returns {"recurring": bool | None, "label": str}. `recurring` is None
    when there's no previous period to compare against at all (as opposed
    to False, which means "we checked, and it's new this period").
    """
    if previous_pairs is None:
        return {"recurring": None, "label": "no prior period to compare against"}
    previous_keys = {_pair_key(p) for p in previous_pairs}
    is_recurring = _pair_key(pair) in previous_keys
    return {
        "recurring": is_recurring,
        "label": "recurring from last period" if is_recurring else "new this period",
    }


def build_trend_analysis(
    signals: list[Signal],
    top_pairs: list[dict],
    previous_pairs: list[dict] | None = None,
    limit: int = 5,
) -> list[dict]:
    """
    Build named trends from the strongest entity co-occurrence pairs, each
    with: what co-occurred, why it matters to a founder, who should care,
    the evidence behind it (with engagement and persistence, not just
    titles), how confident we are and why, and a concrete recommended
    action from the report's shared vocabulary.
    """
    trends = []
    for pair in top_pairs[:limit]:
        a, b = pair["from"], pair["to"]
        weight = pair.get("weight", 1.0)

        supporting = _signals_mentioning_both(signals, a["name"], b["name"])
        if not supporting:
            supporting = _signals_mentioning_any(signals, [a["name"], b["name"]])

        evidence = [
            {
                "title": s.title,
                "source": s.source,
                "source_label": _SOURCE_LABELS.get(s.source, s.source),
                "engagement": s.engagement,
            }
            for s in sorted(supporting, key=lambda s: s.engagement, reverse=True)[:3]
        ]

        recurrence = pair_recurrence(pair, previous_pairs)
        if recurrence["recurring"] is None:
            temporal = "There isn't yet enough history to say whether this is a lasting shift — worth tracking over the next few weeks."
        elif recurrence["recurring"]:
            temporal = "This connection also appeared last period, which suggests a developing pattern rather than a one-off discussion."
        else:
            temporal = "This is the first period this connection has appeared — treat it as an early signal until it recurs."

        who = _who_might_care(a, b)
        so_what = f"{explain_pair(pair)} This is particularly relevant to {who}. {temporal}"

        confidence_label = _trend_confidence(weight, len(supporting))
        confidence_reason = _trend_confidence_reason(weight, len(supporting), confidence_label)

        trends.append({
            "name": _trend_name(a, b),
            "so_what": so_what,
            "why_it_matters": _why_it_matters(a, b),
            "who_should_care": who,
            "entities": [a["name"], b["name"]],
            "evidence": evidence,
            "evidence_strength": _evidence_strength_narrative(supporting, recurrence),
            "confidence": confidence_label,
            "confidence_reason": confidence_reason,
            "recommended_action": _trend_recommendation(confidence_label, recurrence.get("recurring")),
        })
    return trends


def _evidence_strength_narrative(supporting: list[Signal], recurrence: dict) -> str:
    """
    Turns raw evidence into a sentence about how strong that evidence
    actually is — source diversity, engagement magnitude, and persistence
    across periods — instead of leaving a reader to infer strength from a
    bare list of titles.
    """
    if not supporting:
        return "No individual signals could be directly matched as supporting evidence for this connection."

    sources = sorted({s.source for s in supporting})
    source_phrase = (
        _SOURCE_LABELS.get(sources[0], sources[0]) if len(sources) == 1
        else f"{len(sources)} independent sources"
    )
    total_engagement = sum(s.engagement for s in supporting)

    persistence = ""
    if recurrence.get("recurring") is True:
        persistence = ", and it persisted from the previous period"
    elif recurrence.get("recurring") is False:
        persistence = ", though this is its first appearance so persistence is unconfirmed"

    return (
        f"Backed by {len(supporting)} signal(s) across {source_phrase}, with "
        f"{total_engagement} combined engagement points{persistence}."
    )


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


def _trend_confidence_reason(weight: float, supporting_count: int, label: str) -> str:
    """
    Explains why the confidence label was assigned, using the exact same
    weight/supporting_count values _trend_confidence used — so the
    explanation can never drift from the label it justifies.

    Deliberately doesn't repeat the label itself (it's already available
    separately via the "confidence" field) — a renderer combining both,
    e.g. "Confidence: {confidence} — {confidence_reason}", would otherwise
    show a redundant "Low — Low — ...".
    """
    if label == "High":
        return (
            f"This connection has been observed repeatedly (co-occurrence "
            f"weight {weight:.1f}) across {supporting_count} matched signal(s)."
        )
    if label == "Medium":
        return (
            f"Some repetition is present (co-occurrence weight {weight:.1f}, "
            f"{supporting_count} matched signal(s)), but it hasn't yet reached a "
            f"strong, repeated pattern."
        )
    return (
        f"Only observed once or twice so far (co-occurrence weight "
        f"{weight:.1f}, {supporting_count} matched signal(s)) — treat as an early "
        f"signal, not a confirmed trend."
    )


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
