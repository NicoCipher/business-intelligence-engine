"""
opportunity_engine/explainer/trends.py — named trends built from the
strongest entity co-occurrence pairs.

See opportunity_engine/explainer/__init__.py for this module's place in
the overall split.

Deliberately not domain-generalized, same principle as
opportunity_engine/explainer/opportunity.py (see that module's
docstring). _TREND_NAME_TEMPLATES and _WHO_CARES hardcode Business's
entity type names into narrative sentence templates ("{a} + {b}
tooling", "developers and technical builders" for a technology-typed
entity, etc.) — a second domain's own entity types (e.g. a security
domain's "threat") have no template here and never will via a generic
substitution; new templates would need to be designed for whatever
narrative a second domain's own entity-pair combinations should read as.

Note: this module's own "confidence" (_trend_confidence and related) is
an unrelated, locally-computed concept — entity co-occurrence strength
(weight, supporting signal count) — not OpportunityScores.dimensions
["confidence"]. It shares an English word with the scoring dimension,
not any code path, so it isn't part of the scoring-generalization
boundary at all.
"""

from knowledge_graph.insights import explain_pair
from models import Signal

from opportunity_engine.explainer._shared import _SOURCE_LABELS

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
