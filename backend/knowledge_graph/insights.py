"""
knowledge_graph/insights.py — Narrative explanations for the knowledge graph

graph.py answers "what is connected to what" with structured query results
(entity pairs and a numeric weight). This module turns those structured
results into a plain-language sentence a non-technical reader can act on —
turning "Claude ↔ Rust, weight 3" into an explanation of what the pattern
suggests and why it might matter.

Design principles (same as the rest of the intelligence layer):
  - Every sentence is derived from the pair's actual type/weight/names.
    No invented relationships, no speculation beyond what the co-occurrence
    count supports.
  - Confidence language scales with weight — a weight-1 pair gets a more
    hedged sentence ("appeared together") than a weight-8 pair
    ("frequently appeared together").
  - Phrasing is template-based and deterministic, not AI-generated — the
    same philosophy as detector.py's _synthesise_description() and
    report/generator.py's _generate_insights().
"""

# ── Strength language ────────────────────────────────────────────────────

_STRENGTH_THRESHOLDS: list[tuple[float, str]] = [
    (5.0, "frequently"),
    (2.0, "repeatedly"),
    (0.0, "at least once"),
]


def _strength_label(weight: float) -> str:
    for threshold, label in _STRENGTH_THRESHOLDS:
        if weight >= threshold:
            return label
    return "at least once"


# ── Type-pair phrasing ───────────────────────────────────────────────────
# Keyed by (type_of_a, type_of_b) in the specific order the template reads
# naturally. explain_pair() tries both orders before falling back to a
# generic template.

_PAIR_TEMPLATES: dict[tuple[str, str], str] = {
    ("technology", "technology"): (
        "{a} and {b} {strength} appeared together in collected discussions. "
        "This suggests an emerging relationship between these two tools or "
        "platforms — worth watching if you build in either space."
    ),
    ("technology", "problem"): (
        "{a} {strength} appeared alongside discussions of {b}. This suggests "
        "{a} is being considered as a way to address {b}."
    ),
    ("technology", "market"): (
        "{a} {strength} came up in discussions involving {b}. This points to "
        "{a} adoption within the {b} segment."
    ),
    ("market", "problem"): (
        "{b} {strength} came up specifically in the context of {a}. This is a "
        "candidate pain point for that segment."
    ),
    ("technology", "skill"): (
        "{a} {strength} appeared alongside {b}-related discussion, suggesting "
        "demand for people who can combine the two."
    ),
    ("regulation", "market"): (
        "{a} {strength} came up in discussions involving {b}, suggesting "
        "compliance pressure is shaping activity in that segment."
    ),
    ("regulation", "technology"): (
        "{a} {strength} came up alongside {b}, suggesting {b} is being "
        "evaluated partly through a compliance lens."
    ),
}

_DEFAULT_TEMPLATE = (
    "\"{a}\" and \"{b}\" {strength} appeared together in collected signals "
    "(co-occurrence weight: {weight:.0f}). The connection may be worth "
    "investigating further as more evidence accumulates."
)


def explain_pair(pair: dict) -> str:
    """
    Turn one co-occurrence pair into a plain-language sentence.

    Args:
        pair: shape returned by knowledge_graph.graph.co_occurring_pairs()'s
              elements — {"from": {"id","name","type"},
                          "to":   {"id","name","type"},
                          "weight": float}

    Returns a single sentence. Deterministic — the same pair always
    produces the same sentence.
    """
    a, b = pair["from"], pair["to"]
    weight = pair.get("weight", 1.0)
    strength = _strength_label(weight)

    key = (a["type"], b["type"])
    reverse_key = (b["type"], a["type"])

    if key in _PAIR_TEMPLATES:
        template, (x, y) = _PAIR_TEMPLATES[key], (a, b)
    elif reverse_key in _PAIR_TEMPLATES:
        template, (x, y) = _PAIR_TEMPLATES[reverse_key], (b, a)
    else:
        template, (x, y) = _DEFAULT_TEMPLATE, (a, b)

    return template.format(a=x["name"], b=y["name"], strength=strength, weight=weight)
