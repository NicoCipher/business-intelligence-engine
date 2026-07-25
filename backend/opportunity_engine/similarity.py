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
