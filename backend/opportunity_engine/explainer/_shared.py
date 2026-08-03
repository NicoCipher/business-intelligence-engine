"""
opportunity_engine/explainer/_shared.py — genuinely cross-module pieces.

Kept deliberately tiny: the explainer split has almost no real cross-module
dependency (see this package's __init__.py docstring for the map). This
file holds the one piece two modules actually need — everything else that
looked shared at a glance (title casing near the top of the original file)
turned out, on tracing actual call sites, to have exactly one consumer and
now lives directly in that module instead.
"""

_SOURCE_LABELS = {
    "hn": "Hacker News", "reddit": "Reddit",
    "rss": "RSS feeds", "trends": "Search trends",
}
