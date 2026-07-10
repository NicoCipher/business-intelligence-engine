"""
opportunity_engine/detector.py — Cross-source pattern detection

The detector answers one question: "Which topics keep appearing across
multiple independent data sources this week?"

A topic appearing once on Reddit is noise. The same topic appearing on
Reddit, Hacker News, and in an RSS feed in the same week is a signal.

Algorithm:

  1. Load recent unprocessed signals from the database.
  2. Extract keyword fingerprints from each signal's title + content.
  3. Group signals by fingerprint similarity (a simple bag-of-words overlap).
  4. Reject clusters with fewer than MIN_CLUSTER_SIZE signals or only one source.
  5. Score each surviving cluster using OpportunityScorer.
  6. Persist opportunities that exceed MIN_COMPOSITE_TO_PERSIST.

Why no NLP or embeddings?
  Embedding models require either a paid API or a locally-run model (slow,
  large, complex to deploy). Keyword fingerprinting is 100× simpler,
  transparent, and sufficient for the volume of signals in Version 1
  (hundreds of posts per week, not millions). When signal volume grows
  or precision needs to improve, this module is the natural place to
  upgrade the clustering algorithm — nothing else needs to change.

Design constraint:
  This module must be replaceable. The contract is:
    detect(signals: list[Signal]) → list[Opportunity]
  Any algorithm that satisfies this signature can replace this one.
"""

import logging
import re
from collections import defaultdict
from datetime import datetime, timezone

import database
from models import Signal, Opportunity, OpportunityScores
from opportunity_engine.scorer import OpportunityScorer
from config import MIN_CLUSTER_SIZE, MIN_COMPOSITE_TO_PERSIST

logger = logging.getLogger(__name__)

# Common English stop words that carry no topical meaning.
# Excluded from keyword fingerprints.
_STOP_WORDS = frozenset([
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "is", "are", "was", "were", "be", "been", "have", "has",
    "had", "do", "does", "did", "will", "would", "could", "should", "may",
    "might", "shall", "can", "i", "you", "we", "they", "it", "this", "that",
    "my", "your", "our", "their", "its", "how", "what", "why", "when",
    "where", "who", "which", "if", "as", "so", "just", "not", "no", "any",
    "some", "also", "about", "from", "there", "here", "than", "then",
    "up", "out", "by", "into", "through", "after", "before", "while",
    "because", "get", "use", "new", "good", "great", "need", "want",
    "know", "make", "go", "come", "see", "think", "look", "like",
    "used", "using", "still", "work", "works", "working",
])

# Minimum token length — short tokens are almost always noise
_MIN_TOKEN_LEN = 4

# Jaccard similarity threshold for two signals to be in the same cluster.
# 0.15 means: if 15% of keywords overlap, they're probably about the same topic.
# This is intentionally loose — better to over-cluster and let the source-
# diversity filter reduce noise than to under-cluster and miss real patterns.
_JACCARD_THRESHOLD = 0.12


class PatternDetector:
    """
    Detects opportunity clusters in a set of signals.

    Usage:
        detector = PatternDetector()
        opportunities = detector.detect(signals)
    """

    def __init__(self):
        self._scorer = OpportunityScorer()

    def detect(self, signals: list[Signal]) -> list[Opportunity]:
        """
        Find and score opportunity clusters in the provided signals.

        Returns a list of Opportunity objects, sorted by composite score
        descending. Only opportunities above MIN_COMPOSITE_TO_PERSIST
        are returned.
        """
        if not signals:
            return []

        logger.info(f"Running pattern detection on {len(signals)} signals")

        fingerprints = {s.id: self._fingerprint(s) for s in signals}
        clusters = self._cluster(signals, fingerprints)

        logger.info(f"Found {len(clusters)} raw clusters before filtering")

        opportunities = []
        for cluster in clusters:
            opp = self._evaluate_cluster(cluster)
            if opp is not None:
                opportunities.append(opp)

        opportunities.sort(key=lambda o: o.composite_score, reverse=True)
        logger.info(
            f"Produced {len(opportunities)} opportunities "
            f"(composite ≥ {MIN_COMPOSITE_TO_PERSIST})"
        )
        return opportunities

    def detect_and_persist(self, signals: list[Signal]) -> int:
        """
        Detect opportunities and write them to the database.
        Returns the number of new opportunities persisted.
        """
        opportunities = self.detect(signals)
        if not opportunities:
            return 0

        inserted = 0
        with database.get_connection() as conn:
            for opp in opportunities:
                row = opp.to_db_row()
                conn.execute(
                    """
                    INSERT OR IGNORE INTO opportunities
                      (id, title, description, signal_ids, entity_ids,
                       scores, composite_score, status, week_key,
                       created_at, updated_at)
                    VALUES
                      (:id, :title, :description, :signal_ids, :entity_ids,
                       :scores, :composite_score, :status, :week_key,
                       :created_at, :updated_at)
                    """,
                    row,
                )
                if conn.execute("SELECT changes()").fetchone()[0] > 0:
                    inserted += 1
            conn.commit()

        logger.info(f"Persisted {inserted} new opportunities to database")
        return inserted

    # ── Fingerprinting ─────────────────────────────────────────────────────

    def _fingerprint(self, signal: Signal) -> frozenset[str]:
        """
        Extract a keyword fingerprint from a signal's title and content.

        A fingerprint is a frozenset of meaningful tokens. Two signals with
        high fingerprint overlap are probably about the same topic.

        Deliberate simplicity: split on non-alphanumeric, filter stop words.
        This handles most cases well for English-language tech content.
        """
        text = signal.full_text  # already lowercased
        tokens = re.split(r"[^a-z0-9]+", text)
        return frozenset(
            t for t in tokens
            if len(t) >= _MIN_TOKEN_LEN and t not in _STOP_WORDS
        )

    # ── Clustering ─────────────────────────────────────────────────────────

    def _cluster(
        self,
        signals: list[Signal],
        fingerprints: dict[str, frozenset],
    ) -> list[list[Signal]]:
        """
        Single-pass greedy clustering by Jaccard similarity.

        For each signal, check whether it belongs to an existing cluster
        (Jaccard similarity against the cluster's merged fingerprint ≥ threshold).
        If yes, merge. If no, start a new cluster.

        Trade-off: greedy clustering is O(n²) in the worst case. For Version 1
        volumes (hundreds of signals per run, not millions) this is acceptable.
        If we need to handle thousands of signals per run, switch to LSH
        (Locality-Sensitive Hashing) — that's an upgrade to this method only.
        """
        by_id = {s.id: s for s in signals}

        # Each cluster is represented by its merged fingerprint
        cluster_fingerprints: list[frozenset] = []
        cluster_members: list[list[str]] = []    # lists of signal IDs

        for sig in signals:
            fp = fingerprints[sig.id]
            if not fp:
                continue   # skip signals with empty fingerprints

            best_cluster = -1
            best_jaccard = 0.0

            for i, cfp in enumerate(cluster_fingerprints):
                j = self._jaccard(fp, cfp)
                if j > best_jaccard:
                    best_jaccard = j
                    best_cluster = i

            if best_jaccard >= _JACCARD_THRESHOLD:
                # Merge into best matching cluster
                cluster_members[best_cluster].append(sig.id)
                cluster_fingerprints[best_cluster] = (
                    cluster_fingerprints[best_cluster] | fp
                )
            else:
                # Start a new cluster
                cluster_members.append([sig.id])
                cluster_fingerprints.append(fp)

        # Reconstruct signal objects from IDs
        return [
            [by_id[sid] for sid in ids if sid in by_id]
            for ids in cluster_members
        ]

    @staticmethod
    def _jaccard(a: frozenset, b: frozenset) -> float:
        """Jaccard similarity: |A ∩ B| / |A ∪ B|. Returns 0 if both empty."""
        if not a and not b:
            return 0.0
        return len(a & b) / len(a | b)

    # ── Cluster evaluation ─────────────────────────────────────────────────

    def _evaluate_cluster(self, cluster: list[Signal]) -> Opportunity | None:
        """
        Evaluate one cluster and produce an Opportunity if it qualifies.

        Filters:
          1. Minimum size (config.MIN_CLUSTER_SIZE)
          2. Minimum source diversity (at least 2 distinct sources preferred;
             single-source clusters allowed if size ≥ 5 — high frequency alone
             is a valid signal)
          3. Minimum composite score (config.MIN_COMPOSITE_TO_PERSIST)

        Returns None if the cluster doesn't qualify.
        """
        if len(cluster) < MIN_CLUSTER_SIZE:
            return None

        sources = set(s.source for s in cluster)
        # Require cross-source for small clusters. Allow single-source
        # only if the cluster is large enough (strong frequency signal).
        if len(sources) == 1 and len(cluster) < 5:
            return None

        scores = self._scorer.score(cluster)
        if scores.composite() < MIN_COMPOSITE_TO_PERSIST:
            return None

        title = self._synthesise_title(cluster)
        description = self._synthesise_description(cluster, scores)

        now = datetime.now(timezone.utc)
        week_key = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"

        return Opportunity(
            title=title,
            description=description,
            scores=scores,
            signal_ids=[s.id for s in cluster],
            week_key=week_key,
        )

    # ── Description synthesis ──────────────────────────────────────────────

    def _synthesise_title(self, cluster: list[Signal]) -> str:
        """
        Produce a concise title for an opportunity cluster.

        Strategy: take the highest-engagement signal's title as the anchor,
        then prefix it with the cluster size and source count for context.

        This is not AI-generated. It is a deterministic summary of evidence.
        When LLM summarisation is added in a future module, it will replace
        this method — not the rest of the system.
        """
        # Sort by engagement to find the most-resonant signal
        anchor = max(cluster, key=lambda s: s.engagement)
        title = anchor.title

        # Truncate if needed
        if len(title) > 120:
            title = title[:117] + "..."

        return title

    def _synthesise_description(
        self,
        cluster: list[Signal],
        scores: OpportunityScores,
    ) -> str:
        """
        Produce a factual, evidence-first description of the opportunity.

        This reads like an intelligence briefing, not a marketing pitch.
        No invented claims. Every sentence is derivable from the signals.
        """
        sources = set(s.source for s in cluster)
        source_labels = {"hn": "Hacker News", "reddit": "Reddit",
                         "rss": "RSS feeds", "trends": "Search trends"}
        source_str = ", ".join(source_labels.get(s, s) for s in sorted(sources))

        top_signals = sorted(cluster, key=lambda s: s.engagement, reverse=True)[:3]
        examples = "; ".join(
            f'"{s.title[:80]}"' for s in top_signals
        )

        demand_tags = [s for s in cluster if "demand_signal" in s.tags]
        complaint_tags = [s for s in cluster if "complaint_signal" in s.tags]

        lines = [
            f"Detected across {len(sources)} source(s): {source_str}.",
            f"Cluster size: {len(cluster)} signals. "
            f"Evidence confidence: {scores.confidence:.1f}/10.",
        ]

        if demand_tags:
            lines.append(
                f"{len(demand_tags)} signals contain explicit demand or "
                f"solution-seeking language."
            )
        if complaint_tags:
            lines.append(
                f"{len(complaint_tags)} signals express frustration with "
                f"existing options."
            )

        lines.append(f"Top signals: {examples}.")

        return " ".join(lines)
