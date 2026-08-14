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
from domains.base import DomainKnowledgeGraph
from domains.business.graph import KNOWLEDGE_GRAPH as _DEFAULT_GRAPH

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

    Entity vocabulary (which keywords map to which entity type, and
    display-name formatting) is domain-supplied via `domain_graph` —
    defaults to Business's when not given, a narrow, documented
    exception to "no core file imports a specific domain package"
    (domains/base.py) made necessary by
    opportunity_engine/canonicalizer.py's resolve_entity_ids() needing
    a safe fallback when its `domain: str` argument doesn't resolve to
    a currently-registered domain (see DomainRegistry.get_or_default()),
    and by existing tests constructing EntityExtractor() directly.

    Relationship *inference* (_infer_relationship below — which pair of
    entity types implies "affects" vs. "enables" vs. "belongs_to", with
    explicit priority ordering) is deliberately NOT generalized here.
    Unlike vocabulary, that's semantic reasoning about what a specific
    entity-type pairing means, not a lookup this domain's config
    happens to hold a substitutable value for — the same kind of
    judgment call ADR-011 drew a boundary around for explainer/*'s
    narrative logic. A future domain would need its own relationship-
    inference design, not a generic substitution of this one's
    priority order.
    """

    def __init__(self, domain_graph: "DomainKnowledgeGraph | None" = None):
        self.domain_graph = domain_graph or _DEFAULT_GRAPH

        # Pre-compile regex patterns for short keywords
        self._short_patterns: dict[str, dict[str, re.Pattern]] = {}
        for type_name, etype in self.domain_graph.entity_types.items():
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

        for type_name, etype in self.domain_graph.entity_types.items():
            for kw in etype.keywords:
                if self._matches(kw, text, type_name):
                    name = self.domain_graph.get_display_name(kw)
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

    def persist_results(self, results: list[ExtractionResult], domain: str = "business") -> dict:
        """
        Write extracted entities and relationships to the database.

        Entities: upserted on the (type, name, domain) unique index (see
        database.py's _migrate_v5) — a true insert and a re-encounter are
        distinguished by comparing the row's created_at after the write,
        since ON CONFLICT DO UPDATE's changes() can't tell them apart the
        way INSERT OR IGNORE's could. Relationships: upserted on
        (from_id, to_id, type, domain) — weight accumulates rather than
        each co-occurrence creating another row.

        Lifecycle (schema v8, knowledge_graph/decay.py): every write here
        — insert or re-encounter — sets lifecycle_state to 'active'. This
        is the system's only reactivation path: new evidence always wins
        over decay. `updated_at` is bumped on every re-encounter too (not
        just first insert) — it doubles as "last meaningfully referenced"
        for decay's own decision logic, so this fixes what used to be a
        gap where a re-encountered entity's updated_at stayed frozen at
        its original creation time forever.

        Domain scoping: entities and relationships are scoped per-domain
        (schema v5) — the same (type, name) can independently exist once
        per domain (e.g. "AI" as a technology entity in both "business"
        and "cybersecurity" are two different rows), so cross-domain
        knowledge doesn't get silently mixed into shared rankings like
        co_occurring_pairs(). All results in one call are assumed to
        belong to the same domain — this matches how pipeline.py actually
        calls this, once per domain per run.

        Entity id resolution: every Entity object built by extract() has
        a fresh random id (models.py), generated before we know whether
        that entity already exists in the database. When it does, the
        INSERT is correctly ignored — but any Relationship referencing
        that fresh, never-persisted id would then violate the foreign
        key. So after each entity insert attempt, we resolve its
        original in-memory id to whatever id is *actually* persisted
        (the fresh one if this was genuinely new, or the pre-existing
        one if it was a duplicate) and remap relationships through that
        before inserting them.

        Returns counts of what was inserted.
        """
        import json
        import sqlite3
        import database

        entity_inserts = 0
        rel_inserts = 0

        with database.get_connection() as conn:
            for result in results:
                # in-memory Entity.id -> actual persisted entities.id
                id_map: dict[str, str] = {}

                for entity in result.entities:
                    try:
                        conn.execute(
                            """
                            INSERT INTO entities
                              (id, type, name, domain, description, metadata, created_at, updated_at,
                               lifecycle_state, lifecycle_updated_at)
                            VALUES
                              (:id, :type, :name, :domain, :description, :metadata, :created_at, :updated_at,
                               'active', :updated_at)
                            ON CONFLICT(type, name, domain) DO UPDATE SET
                              updated_at           = excluded.updated_at,
                              lifecycle_state       = 'active',
                              lifecycle_updated_at  = CASE
                                WHEN lifecycle_state != 'active' THEN excluded.updated_at
                                ELSE lifecycle_updated_at
                              END
                            """,
                            {
                                "id":          entity.id,
                                "type":        entity.type,
                                "name":        entity.name,
                                "domain":      domain,
                                "description": entity.description,
                                "metadata":    json.dumps(entity.metadata),
                                "created_at":  entity.created_at,
                                "updated_at":  entity.updated_at,
                            }
                        )
                        # changes() is 1 for both a true insert and a conflict
                        # update, so it can't distinguish "new" from
                        # "re-encountered" the way INSERT OR IGNORE's 0-vs-1
                        # could. Ask directly instead: a genuinely new row's
                        # created_at will equal what we just supplied.
                        row = conn.execute(
                            "SELECT id, created_at FROM entities WHERE type = ? AND name = ? AND domain = ?",
                            (entity.type, entity.name, domain),
                        ).fetchone()
                        id_map[entity.id] = row["id"]
                        if row["created_at"] == entity.created_at:
                            entity_inserts += 1
                    except sqlite3.Error as e:
                        logger.warning(f"Failed to insert entity {entity.name}: {e}")
                        id_map[entity.id] = entity.id  # best effort — don't silently drop relationships

                for rel in result.relationships:
                    from_id = id_map.get(rel.from_id, rel.from_id)
                    to_id   = id_map.get(rel.to_id, rel.to_id)
                    if from_id == to_id:
                        continue  # would-be self-loop after id resolution — not a real relationship
                    try:
                        conn.execute(
                            """
                            INSERT INTO relationships
                              (id, from_id, to_id, type, weight, domain, metadata, created_at, updated_at,
                               lifecycle_state, lifecycle_updated_at)
                            VALUES
                              (:id, :from_id, :to_id, :type, :weight, :domain, :metadata,
                               :created_at, :updated_at, 'active', :updated_at)
                            ON CONFLICT(from_id, to_id, type, domain) DO UPDATE SET
                              weight     = MIN(10.0, weight + excluded.weight),
                              updated_at = excluded.updated_at,
                              lifecycle_state       = 'active',
                              lifecycle_updated_at  = CASE
                                WHEN lifecycle_state != 'active' THEN excluded.updated_at
                                ELSE lifecycle_updated_at
                              END
                            """,
                            {
                                "id":         rel.id,
                                "from_id":    from_id,
                                "to_id":      to_id,
                                "type":       rel.type,
                                "weight":     rel.weight,
                                "domain":     domain,
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

        Hardcoded to Business's five entity type names, deliberately not
        generalized — see the class docstring's "Relationship inference"
        paragraph for why.
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
