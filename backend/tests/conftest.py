"""
tests/conftest.py — Shared test fixtures for the BIA-OS test suite

Fixtures:
  make_signal    Factory for creating Signal objects with sensible defaults.
                 Call as make_signal() or make_signal(title="...", source="reddit").

  demand_signals Four pre-built demand signals spanning two sources.
                 Sufficient for the detector's cross-source requirement.

  tmp_db         Creates a fresh in-memory SQLite database for tests that
                 need to write. Automatically cleaned up after each test.

Usage:
  def test_something(make_signal, demand_signals):
      sig = make_signal(title="Ask HN: is there a tool for X?")
      ...
"""

import sys
from pathlib import Path

import pytest

# Ensure backend/ is on the path when pytest runs from the repo root.
sys.path.insert(0, str(Path(__file__).parent.parent))

from models import Signal


@pytest.fixture
def make_signal():
    """
    Factory fixture for Signal objects.

    Each call auto-increments the source_id to prevent duplicate-key
    errors if multiple signals are persisted in the same test.

    Examples:
        sig = make_signal()
        sig = make_signal(title="Ask HN: any alternatives to X?", source="hn")
        sig = make_signal(score=500, comments=120, source="reddit")
    """
    counter = [0]

    def _factory(
        title: str = "How do I find a better solution for this problem?",
        content: str = "",
        source: str = "hn",
        score: int = 50,
        comments: int = 15,
        tags: list | None = None,
    ) -> Signal:
        counter[0] += 1
        return Signal(
            source=source,
            source_id=f"test_{counter[0]}",
            title=title,
            content=content,
            platform_score=score,
            comment_count=comments,
            tags=tags or [],
        )

    return _factory


@pytest.fixture
def demand_signals(make_signal):
    """
    A realistic cluster of four demand signals from two sources.
    Covers the cross-source requirement for the detector.
    """
    return [
        make_signal(
            title="Ask HN: any good alternatives to manual compliance tracking?",
            source="hn",
            score=210,
            comments=73,
            tags=["ask", "demand_signal"],
        ),
        make_signal(
            title="Looking for a B2B tool that automates EU AI Act compliance for SMBs",
            source="reddit",
            score=145,
            comments=38,
            tags=["demand_signal", "r/entrepreneur"],
        ),
        make_signal(
            title="How do I set up AI governance documentation for a small business?",
            source="hn",
            score=89,
            comments=24,
            tags=["ask", "demand_signal"],
        ),
        make_signal(
            title="I'd pay good money for a Notion-based compliance tracker with AI Act checklist",
            source="reddit",
            score=201,
            comments=51,
            tags=["demand_signal", "complaint_signal", "r/smallbusiness"],
        ),
    ]


@pytest.fixture
def low_engagement_signals(make_signal):
    """
    Signals with no engagement — tests that the scorer handles zeros gracefully.
    """
    return [
        make_signal(title="Interesting topic", score=0, comments=0)
        for _ in range(3)
    ]


@pytest.fixture
def single_source_signals(make_signal):
    """
    All signals from one source — tests single-source confidence penalty.
    """
    return [
        make_signal(source="hn", score=100, comments=30)
        for _ in range(5)
    ]


@pytest.fixture
def multi_source_signals(make_signal):
    """
    Same number of signals but from three different sources.
    Should score higher confidence than single_source_signals.
    """
    return [
        make_signal(source="hn",     score=100, comments=30),
        make_signal(source="reddit", score=80,  comments=20),
        make_signal(source="rss",    score=40,  comments=5),
        make_signal(source="hn",     score=120, comments=40),
        make_signal(source="reddit", score=95,  comments=25),
    ]
