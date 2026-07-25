"""
knowledge_graph/graph.py — Graph query operations

The knowledge graph is stored in SQLite (entities + relationships tables).
This module provides business-meaningful queries on top of that storage.

Why not NetworkX?
  For the query patterns Version 1 needs, SQL joins are faster and more
  transparent than loading the entire graph into memory. When we need
  actual graph algorithms (shortest path, PageRank, community detection),
  we will add NetworkX here — it's a one-file change.

Available queries:
  - entity_context(entity_id)          full neighbourhood of one entity
  - opportunity_context(opportunity_id) entities + relationships for one opportunity
  - top_entities(type, limit)          most-connected entities by type
  - co_occurring_pairs(min_weight)     entity pairs with strongest co-occurrence
  - weekly_entity_summary(week_key)    what the graph learned this week
  - find_or_create_entity(type, name)  upsert an entity, return its id

These are the queries the report generator and API need. Add new queries here
as the system grows; never scatter graph logic into other modules.
"""

import logging
from datetime import datetime, timezone

import database
from database import decode_json, encode_json

logger = logging.getLogger(__name__)


# ── Public query interface ─────────────────────────────────────────────────

def entity_context(entity_id: str) -> dict:
    """
    Return an entity and everything directly connected to it.

    Response shape:
      {
        "entity": {...},
        "connected": [{"entity": {...}, "relationship": {...}}, ...]
      }
    """
    with database.get_connection() as conn:
        entity_row = conn.execute(
            "SELECT * FROM entities WHERE id = ?", (entity_id,)
        ).fetchone()

        if not entity_row:
            return {}

        # All relationships where this entity is either source or target
        rel_rows = conn.execute(
            """
            SELECT r.*, e.id as peer_id, e.type as peer_type,
                   e.name as peer_name
            FROM   relationships r
            JOIN   entities e ON (
                     CASE WHEN r.from_id = ? THEN r.to_id ELSE r.from_id END = e.id
                   )
            WHERE  r.from_id = ? OR r.to_id = ?
            ORDER  BY r.weight DESC
            LIMIT  50
            """,
            (entity_id, entity_id, entity_id),
        ).fetchall()

    connected = [
        {
            "entity": {
                "id":   r["peer_id"],
                "type": r["peer_type"],
                "name": r["peer_name"],
            },
            "relationship": {
                "type":   r["type"],
                "weight": r["weight"],
            },
        }
        for r in rel_rows
    ]

    return {
        "entity":    dict(entity_row),
        "connected": connected,
    }


def opportunity_context(opportunity_id: str) -> dict:
    """
    Return the entity neighbourhood for a specific opportunity.
    Uses the opportunity's entity_ids array to find all connected entities
    and then expands one hop outward.
    """
    with database.get_connection() as conn:
        opp_row = conn.execute(
            "SELECT entity_ids FROM opportunities WHERE id = ?",
            (opportunity_id,)
        ).fetchone()

        if not opp_row:
            return {}

        entity_ids = decode_json(opp_row["entity_ids"], [])
        if not entity_ids:
            return {"entities": [], "relationships": []}

        placeholders = ",".join("?" * len(entity_ids))

        entities = conn.execute(
            f"SELECT id, type, name FROM entities WHERE id IN ({placeholders})",
            entity_ids,
        ).fetchall()

        relationships = conn.execute(
            f"""
            SELECT from_id, to_id, type, weight
            FROM   relationships
            WHERE  from_id IN ({placeholders}) OR to_id IN ({placeholders})
            """,
            entity_ids + entity_ids,
        ).fetchall()

    return {
        "entities":     [dict(e) for e in entities],
        "relationships": [dict(r) for r in relationships],
    }


def top_entities(entity_type: str | None = None, limit: int = 20, domain: str | None = None) -> list[dict]:
    """
    Return entities ranked by the number of relationships they participate in.
    Higher relationship count = this concept is more central to the intelligence.

    domain=None returns across all domains (backward-compatible default);
    real callers pass it explicitly, same as co_occurring_pairs().
    """
    filters = []
    params: dict = {"limit": limit}
    if entity_type:
        filters.append("e.type = :type")
        params["type"] = entity_type
    if domain:
        filters.append("e.domain = :domain")
        params["domain"] = domain
    where_clause = ("WHERE " + " AND ".join(filters)) if filters else ""

    with database.get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT   e.id, e.type, e.name,
                     COUNT(r.id) as relationship_count
            FROM     entities e
            LEFT JOIN relationships r
                   ON (r.from_id = e.id OR r.to_id = e.id)
            {where_clause}
            GROUP BY e.id
            ORDER BY relationship_count DESC, e.name ASC
            LIMIT    :limit
            """,
            params,
        ).fetchall()

    return [dict(r) for r in rows]


def co_occurring_pairs(min_weight: float = 2.0, limit: int = 15, domain: str | None = None) -> list[dict]:
    """
    Return entity pairs with the strongest co-occurrence relationships.
    Weight accumulates each time the pair appears together in a new signal.

    domain=None returns pairs across all domains (the old, pre-v5
    behavior) — kept as the default for backward compatibility with
    direct/debugging callers, but every real production call site
    (report/generator.py) always passes the actual domain explicitly.
    Without it, two domains' entities could appear paired together in
    the same ranking, which schema v5's domain-scoping exists to prevent.
    """
    domain_filter = "AND r.domain = :domain" if domain else ""
    params: dict = {"min_weight": min_weight, "limit": limit}
    if domain:
        params["domain"] = domain

    with database.get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT   r.from_id, r.to_id, r.type, r.weight,
                     a.name as from_name, a.type as from_type,
                     b.name as to_name,   b.type as to_type
            FROM     relationships r
            JOIN     entities a ON a.id = r.from_id
            JOIN     entities b ON b.id = r.to_id
            WHERE    r.type = 'co-occurs' AND r.weight >= :min_weight
            {domain_filter}
            ORDER BY r.weight DESC
            LIMIT    :limit
            """,
            params,
        ).fetchall()

    return [
        {
            "from": {"id": r["from_id"], "name": r["from_name"], "type": r["from_type"]},
            "to":   {"id": r["to_id"],   "name": r["to_name"],   "type": r["to_type"]},
            "weight": r["weight"],
        }
        for r in rows
    ]


def weekly_entity_summary(week_key: str | None = None, domain: str | None = None) -> dict:
    """
    Summarise graph activity for a given ISO week.
    Defaults to the current week.

    domain=None summarises across all domains (old behavior, kept for
    backward compatibility) — real production callers always pass domain
    explicitly, same reasoning as co_occurring_pairs().
    """
    if not week_key:
        now = datetime.now(timezone.utc)
        week_key = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"

    domain_filter = "WHERE domain = :domain" if domain else ""
    params = {"domain": domain} if domain else {}

    with database.get_connection() as conn:
        total_entities = conn.execute(
            f"SELECT COUNT(*) FROM entities {domain_filter}", params
        ).fetchone()[0]

        by_type = conn.execute(
            f"SELECT type, COUNT(*) as count FROM entities {domain_filter} "
            f"GROUP BY type ORDER BY count DESC",
            params,
        ).fetchall()

        total_rels = conn.execute(
            f"SELECT COUNT(*) FROM relationships {domain_filter}", params
        ).fetchone()[0]

        by_rel_type = conn.execute(
            f"SELECT type, COUNT(*) as count FROM relationships {domain_filter} "
            f"GROUP BY type ORDER BY count DESC",
            params,
        ).fetchall()

    return {
        "week_key":      week_key,
        "total_entities": total_entities,
        "entities_by_type": {r["type"]: r["count"] for r in by_type},
        "total_relationships": total_rels,
        "relationships_by_type": {r["type"]: r["count"] for r in by_rel_type},
        "top_entities": top_entities(limit=10, domain=domain),
        "top_co_occurrences": co_occurring_pairs(min_weight=1.0, limit=8, domain=domain),
    }


def find_or_create_entity(entity_type: str, name: str, domain: str = "business") -> str:
    """
    Return the ID of an existing entity (matched by type + name + domain,
    case-insensitive on name) or create it if it doesn't exist.

    This is the safe way to reference entities during opportunity linking —
    it ensures the entity exists and returns its stable ID.

    Note: not currently called anywhere in the pipeline — persist_results()
    in extractor.py does its own equivalent insert+resolve inline. Kept
    correct and domain-scoped rather than left as a stale, pre-v5 trap for
    whoever picks it up next; consolidating the two implementations is
    flagged as code debt, not fixed here.
    """
    from models import Entity

    with database.get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM entities WHERE type = ? AND name = ? COLLATE NOCASE AND domain = ?",
            (entity_type, name, domain),
        ).fetchone()

        if existing:
            return existing["id"]

        new_entity = Entity(name=name, type=entity_type)
        row = {
            "id":          new_entity.id,
            "type":        new_entity.type,
            "name":        new_entity.name,
            "domain":      domain,
            "description": new_entity.description,
            "metadata":    encode_json(new_entity.metadata),
            "created_at":  new_entity.created_at,
            "updated_at":  new_entity.updated_at,
        }
        conn.execute(
            """
            INSERT OR IGNORE INTO entities
              (id, type, name, domain, description, metadata, created_at, updated_at)
            VALUES
              (:id, :type, :name, :domain, :description, :metadata, :created_at, :updated_at)
            """,
            row,
        )
        conn.commit()
        return new_entity.id


def increment_relationship_weight(from_id: str, to_id: str, rel_type: str, domain: str = "business") -> None:
    """
    Increment the weight of an existing relationship, or set it to 1 if new.

    Used when the same entity pair co-occurs across multiple signals —
    each new co-occurrence strengthens the relationship.

    Note: not currently called anywhere in the pipeline — same status as
    find_or_create_entity() above.
    """
    from models import Relationship
    import json

    with database.get_connection() as conn:
        existing = conn.execute(
            "SELECT id, weight FROM relationships WHERE from_id=? AND to_id=? AND type=? AND domain=?",
            (from_id, to_id, rel_type, domain),
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE relationships SET weight = weight + 1, updated_at = datetime('now','utc') WHERE id = ?",
                (existing["id"],)
            )
        else:
            rel = Relationship(from_id=from_id, to_id=to_id, type=rel_type, weight=1.0)
            conn.execute(
                """
                INSERT OR IGNORE INTO relationships
                  (id, from_id, to_id, type, weight, domain, metadata, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (rel.id, rel.from_id, rel.to_id, rel.type, rel.weight, domain,
                 json.dumps(rel.metadata), rel.created_at, rel.updated_at)
            )
        conn.commit()
