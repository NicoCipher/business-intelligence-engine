"""
knowledge_graph/extractor.py — Rule-based entity extraction

Takes a Signal and returns the entities found in its text, plus the
co-occurrence relationships between those entities.

The extraction pipeline:
  1. Normalise the signal's text (lowercase, collapsed whitespace)
  2. For each entity type, scan its keyword list for matches
     - Short terms (≤4 chars): whole-word match via regex to avoid "AI" matching "MAIL"
     - Longer terms: substring match is sufficient and faster
  3. Deduplicate extracted entities (same type + name → same entity)
  4. Build co-occurrence relationships: any two distinct entities found
     in the same signal are co-occurring (relationship type: "co-occurs")
  5. Attempt semantic relationship inference based on entity type pairs:
     regulation + market → "affects"
     technology + problem → "enables"
     problem + skill → "requires"
     problem/skill/technology + market → "belongs_to"

Persistence:
  Extractor does not write to the database directly.
  It returns (entities, relationships) to the caller, which decides
  whether and when to persist them. This keeps the extractor testable
  and free of I/O side effects.
"""

import re
import logging
from dataclasses import dataclass, field

from models import Entity, Relationship, Signal
from knowledge_graph.schema import ENTITY_TYPES, display_name

logger = logging.getLogger(__name__)

# Pre-compiled regex patterns for short keywords (whole-word matching)
# Built at import time to avoid recompiling on every call.
_SHORT_KEYWORD_THRESHOLD = 4


@dataclass
class ExtractionResult:
    """Result of extracting entities from one signal."""
    entities: list[Entity] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    entity_ids: list[str] = field(default_factory=list)   # IDs of extracted entities


class EntityExtractor:
    """
    Extracts entities and relationships from signal text.

    Thread-safe. Create one instance and call extract() repeatedly.
    """

    def __init__(self):
        # Pre-compile regex patterns for short keywords
        self._short_patterns: dict[str, dict[str, re.Pattern]] = {}
        for type_name, etype in ENTITY_TYPES.items():
            self._short_patterns[type_name] = {}
            for kw in etype.keywords:
                if len(kw) <= _SHORT_KEYWORD_THRESHOLD:
                    self._short_patterns[type_name][kw] = re.compile(
                        r'\b' + re.escape(kw) + r'\b',
                        re.IGNORECASE,
                    )

    def extract(self, signal: Signal) -> ExtractionResult:
        """
        Extract entities and relationships from one signal.

        Returns an ExtractionResult with fresh Entity and Relationship objects.
        These are not persisted — the caller handles persistence.
        """
        text = self._normalise(signal.full_text)
        if not text:
            return ExtractionResult()

        found_entities: list[Entity] = []
        seen_names: set[tuple[str, str]] = set()   # (type, name) deduplication

        for type_name, etype in ENTITY_TYPES.items():
            for kw in etype.keywords:
                if self._matches(kw, text, type_name):
                    name = display_name(kw)
                    key = (type_name, name.lower())
                    if key not in seen_names:
                        seen_names.add(key)
                        found_entities.append(
                            Entity(name=name, type=type_name)
                        )

        if not found_entities:
            return ExtractionResult()

        relationships = self._build_relationships(found_entities, signal.id)

        return ExtractionResult(
            entities=found_entities,
            relationships=relationships,
            entity_ids=[e.id for e in found_entities],
        )

    def extract_batch(self, signals: list[Signal]) -> list[ExtractionResult]:
        """Extract entities from multiple signals. Returns one result per signal."""
        results = []
        for sig in signals:
            try:
                results.append(self.extract(sig))
            except Exception as e:
                logger.warning(f"Extraction failed for signal {sig.id}: {e}")
                results.append(ExtractionResult())
        return results

    # ── Persistence helpers ───────────────────────────────────────────────

    def persist_results(self, results: list[ExtractionResult]) -> dict:
        """
        Write extracted entities and relationships to the database.

        Uses INSERT OR IGNORE for entities (deduplicated by type + name).
        Relationships use INSERT OR IGNORE on (from_id, to_id, type).

        Returns counts of what was inserted.
        """
        import json
        import sqlite3
        import database

        entity_inserts = 0
        rel_inserts = 0

        with database.get_connection() as conn:
            for result in results:
                for entity in result.entities:
                    try:
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO entities
                              (id, type, name, description, metadata, created_at, updated_at)
                            VALUES
                              (:id, :type, :name, :description, :metadata, :created_at, :updated_at)
                            """,
                            {
                                "id":          entity.id,
                                "type":        entity.type,
                                "name":        entity.name,
                                "description": entity.description,
                                "metadata":    json.dumps(entity.metadata),
                                "created_at":  entity.created_at,
                                "updated_at":  entity.updated_at,
                            }
                        )
                        if conn.execute("SELECT changes()").fetchone()[0] > 0:
                            entity_inserts += 1
                    except sqlite3.Error as e:
                        logger.warning(f"Failed to insert entity {entity.name}: {e}")

                for rel in result.relationships:
                    try:
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO relationships
                              (id, from_id, to_id, type, weight, metadata, created_at, updated_at)
                            VALUES
                              (:id, :from_id, :to_id, :type, :weight, :metadata,
                               :created_at, :updated_at)
                            """,
                            {
                                "id":         rel.id,
                                "from_id":    rel.from_id,
                                "to_id":      rel.to_id,
                                "type":       rel.type,
                                "weight":     rel.weight,
                                "metadata":   json.dumps(rel.metadata),
                                "created_at": rel.created_at,
                                "updated_at": rel.updated_at,
                            }
                        )
                        if conn.execute("SELECT changes()").fetchone()[0] > 0:
                            rel_inserts += 1
                    except sqlite3.Error as e:
                        logger.warning(f"Failed to insert relationship: {e}")

            conn.commit()

        return {"entities_inserted": entity_inserts, "relationships_inserted": rel_inserts}

    # ── Private helpers ───────────────────────────────────────────────────

    def _normalise(self, text: str) -> str:
        """Lowercase and collapse whitespace. Preserve apostrophes."""
        return re.sub(r'\s+', ' ', text.lower()).strip()

    def _matches(self, keyword: str, normalised_text: str, type_name: str) -> bool:
        """Check whether a keyword appears in the normalised text."""
        if len(keyword) <= _SHORT_KEYWORD_THRESHOLD:
            pattern = self._short_patterns.get(type_name, {}).get(keyword)
            if pattern:
                return bool(pattern.search(normalised_text))
            return False
        return keyword in normalised_text

    def _build_relationships(
        self,
        entities: list[Entity],
        signal_id: str,
    ) -> list[Relationship]:
        """
        Build relationships between co-occurring entities.

        Rule-based semantic inference:
          regulation + market   → "affects"
          technology + problem  → "enables"
          problem/skill + market → "belongs_to"
          everything else       → "co-occurs"

        We only create relationships for distinct entity pairs (no self-loops).
        """
        relationships: list[Relationship] = []

        for i, a in enumerate(entities):
            for b in entities[i + 1:]:
                rel_type = self._infer_relationship(a, b)
                if rel_type:
                    relationships.append(
                        Relationship(
                            from_id=a.id,
                            to_id=b.id,
                            type=rel_type,
                            weight=1.0,
                            metadata={"signal_id": signal_id},
                        )
                    )

        return relationships

    @staticmethod
    def _infer_relationship(a: Entity, b: Entity) -> str | None:
        """
        Infer the most specific relationship type between two entity types.

        Returns None only if the pair is identical (shouldn't happen after
        deduplication, but guarded anyway).
        """
        if a.id == b.id:
            return None

        pair = frozenset([a.type, b.type])

        if pair == frozenset(["regulation", "market"]):
            return "affects"
        if pair == frozenset(["technology", "problem"]):
            return "enables"
        if "market" in pair and pair != frozenset(["market", "market"]):
            return "belongs_to"
        if pair == frozenset(["problem", "skill"]):
            return "requires"

        return "co-occurs"
