"""
opportunity_engine/similarity.py — Shared similarity primitives.

Small, deterministic, dependency-free comparison functions used anywhere
in the intelligence layer that needs to answer "are these two things the
same thing, roughly." Extracted from explainer.py (which used
title-token Jaccard for week-over-week opportunity/pair recurrence
matching) so canonicalizer.py doesn't duplicate the same primitives a
third time — "avoid duplicated logic" per the engineering principles.

Deliberately NOT semantic/embedding-based. This is real, honest
tokenized-set overlap — good enough to catch near-identical wording,
not good enough to know "therapist notes" and "clinical documentation"
mean the same thing unless the shared vocabulary (entity keywords, or
literal words) actually overlaps. See canonicalizer.py's docstring for
where this limitation matters and what upgrading it would take.
"""

_STOPWORDS = {
    "the", "a", "an", "for", "and", "or", "of", "to", "in", "on", "with",
    "is", "are", "this", "that", "new", "software", "tool", "app",
}


def title_tokens(title: str) -> set[str]:
    """Significant words (>3 chars, stopwords removed) from a title string."""
    words = "".join(c if c.isalnum() else " " for c in title.lower()).split()
    return {w for w in words if len(w) > 3 and w not in _STOPWORDS}


def jaccard(a: set, b: set) -> float:
    """Jaccard similarity between two sets. 0.0 if either is empty."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def weighted_jaccard(a: set, b: set, weight_fn) -> float:
    """
    Jaccard similarity where each member's contribution to both the
    intersection and union is scaled by `weight_fn(member)` instead of
    counting as a flat 1. Reduces to plain jaccard() exactly when
    weight_fn returns 1.0 for everything — this is a generalization, not
    a replacement, and every existing caller of jaccard() is untouched.

    Built for knowledge-graph lifecycle weighting (schema v8,
    knowledge_graph/decay.py): archived entities get weight 0 (excluded
    from both sides, as if absent), dormant entities get a configurable
    reduced weight, active entities (or anything with no lifecycle
    information at all — see decay.match_weight()'s default) get full
    weight. A member with weight 0 in `a`/`b` is dropped from
    consideration entirely rather than distorting the denominator.
    """
    weighted_a = {x for x in a if weight_fn(x) > 0}
    weighted_b = {x for x in b if weight_fn(x) > 0}
    if not weighted_a or not weighted_b:
        return 0.0
    intersection = sum(weight_fn(x) for x in weighted_a & weighted_b)
    union = sum(weight_fn(x) for x in weighted_a | weighted_b)
    return intersection / union if union > 0 else 0.0
