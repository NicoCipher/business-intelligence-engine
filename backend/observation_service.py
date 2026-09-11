"""Producer-neutral validation and persistence for Observation V1."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

import database
from models import (
    CitationSourcePart,
    InterpretedObservation,
    ObservationCitation,
    ObservationConditionState,
    ObservationProducerKind,
    ObservationRun,
    ObservationRunOutcome,
    Signal,
)


class ObservationServiceError(ValueError):
    """An invalid Observation service request; never an operational failure."""


class ObservationLineageConflict(ObservationServiceError):
    """A requested correction cannot be added to immutable lineage."""


@dataclass(frozen=True)
class ObservationResultInput:
    observation_id: str
    canonical_signal_id: str
    condition_citation: ObservationCitation
    condition_state: ObservationConditionState
    semantic_contract_version: str
    recorded_at: str
    state_evidence_citation: ObservationCitation | None = None
    supersedes_observation_id: str | None = None


@dataclass(frozen=True)
class ObservationRunInput:
    run_id: str
    attempted_signal_id: str
    attempted_condition_citation: ObservationCitation
    attempted_semantic_contract_version: str
    producer_kind: ObservationProducerKind
    attempted_at: str
    producer_name: str | None = None
    producer_revision: str | None = None


@dataclass(frozen=True)
class ObservationPersistenceResult:
    observation: InterpretedObservation
    run: ObservationRun
    created: bool


def _source_text(signal: Signal, citation: ObservationCitation) -> str:
    return signal.title if citation.source_part is CitationSourcePart.TITLE else signal.content


def _resolve(signal: Signal, citation: ObservationCitation) -> tuple[int, int]:
    """Return the selected exact range, including overlapping occurrences."""
    text = _source_text(signal, citation)
    starts = [
        position
        for position in range(len(text))
        if text.startswith(citation.literal_text, position)
    ]
    try:
        start = starts[citation.occurrence_ordinal - 1]
    except IndexError as error:
        raise ObservationServiceError("citation literal occurrence does not exist") from error
    return start, start + len(citation.literal_text)


def _hydrate_canonical_signal(conn: sqlite3.Connection, signal_id: str) -> Signal:
    row = conn.execute(
        """
        SELECT id, source, source_id, url, title, content, platform_score,
               comment_count, entity_ids, tags, raw_metadata, collected_at,
               processed, domain
        FROM signals WHERE id = ?
        """,
        (signal_id,),
    ).fetchone()
    if row is None:
        raise ObservationServiceError("canonical persisted Signal does not exist")
    try:
        signal = Signal(
            id=row["id"], source=row["source"], source_id=row["source_id"],
            url=row["url"], title=row["title"], content=row["content"],
            platform_score=row["platform_score"], comment_count=row["comment_count"],
            entity_ids=json.loads(row["entity_ids"]), tags=json.loads(row["tags"]),
            raw_metadata=json.loads(row["raw_metadata"]), collected_at=row["collected_at"],
            processed=row["processed"], domain=row["domain"],
        )
        if not isinstance(signal.id, str) or not signal.id:
            raise ObservationServiceError("canonical persisted Signal has no valid identity")
        return signal
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ObservationServiceError("canonical persisted Signal is not hydratable") from error


def _validate_citations(signal: Signal, condition: ObservationCitation,
                        evidence: ObservationCitation | None,
                        state: ObservationConditionState) -> None:
    condition_range = _resolve(signal, condition)
    if state in (ObservationConditionState.ACTIVE, ObservationConditionState.RESOLVED) and evidence is None:
        raise ObservationServiceError("active and resolved results require state evidence")
    if evidence is not None:
        if evidence.source_part is not condition.source_part:
            raise ObservationServiceError("state evidence must use the condition source part")
        evidence_range = _resolve(signal, evidence)
        if not (condition_range[0] <= evidence_range[0] and evidence_range[1] <= condition_range[1]):
            raise ObservationServiceError("state evidence must be contained in the condition citation")


def _find_exact(conn: sqlite3.Connection, candidate: ObservationResultInput):
    row = candidate.state_evidence_citation
    return conn.execute(
        """
        SELECT * FROM interpreted_observations
        WHERE signal_id = ? AND condition_source_part = ? AND condition_literal_text = ?
          AND condition_occurrence_ordinal = ? AND condition_state = ?
          AND semantic_contract_version = ?
          AND ((state_evidence_source_part IS NULL AND ? IS NULL)
               OR (state_evidence_source_part = ? AND state_evidence_literal_text = ?
                   AND state_evidence_occurrence_ordinal = ?))
          AND ((supersedes_observation_id IS NULL AND ? IS NULL)
               OR supersedes_observation_id = ?)
        """,
        (candidate.canonical_signal_id, candidate.condition_citation.source_part.value,
         candidate.condition_citation.literal_text, candidate.condition_citation.occurrence_ordinal,
         candidate.condition_state.value, candidate.semantic_contract_version,
         row.source_part.value if row else None, row.source_part.value if row else None,
         row.literal_text if row else None, row.occurrence_ordinal if row else None,
         candidate.supersedes_observation_id, candidate.supersedes_observation_id),
    ).fetchone()


def _validate_lineage(conn: sqlite3.Connection, candidate: ObservationResultInput) -> None:
    predecessor = candidate.supersedes_observation_id
    if predecessor is None:
        return
    if predecessor == candidate.observation_id:
        raise ObservationLineageConflict("an observation cannot supersede itself")
    current, visited = predecessor, set()
    while current is not None:
        if current in visited or current == candidate.observation_id:
            raise ObservationLineageConflict("correction lineage contains a cycle")
        visited.add(current)
        row = conn.execute(
            "SELECT supersedes_observation_id FROM interpreted_observations WHERE observation_id = ?",
            (current,),
        ).fetchone()
        if row is None:
            if current == predecessor:
                raise ObservationLineageConflict("superseded observation does not exist")
            raise ObservationLineageConflict("retained correction lineage is malformed")
        current = row["supersedes_observation_id"]
    successor = conn.execute(
        "SELECT observation_id FROM interpreted_observations WHERE supersedes_observation_id = ?",
        (predecessor,),
    ).fetchone()
    if successor is not None:
        raise ObservationLineageConflict("superseded observation already has a direct successor")


def _insert_run(conn: sqlite3.Connection, run: ObservationRun) -> None:
    row = run.to_db_row()
    conn.execute(
        """INSERT INTO observation_runs (
        run_id, attempted_signal_id, attempted_condition_source_part,
        attempted_condition_literal_text, attempted_condition_occurrence_ordinal,
        attempted_semantic_contract_version, producer_kind, producer_name,
        producer_revision, attempted_at, outcome, produced_at, resulting_observation_id
        ) VALUES (:run_id, :attempted_signal_id, :attempted_condition_source_part,
        :attempted_condition_literal_text, :attempted_condition_occurrence_ordinal,
        :attempted_semantic_contract_version, :producer_kind, :producer_name,
        :producer_revision, :attempted_at, :outcome, :produced_at, :resulting_observation_id)""",
        row,
    )


def persist_produced(result: ObservationResultInput, run: ObservationRunInput,
                     *, produced_at: str) -> ObservationPersistenceResult:
    """Persist one explicit semantic result, reusing exact immutable results."""
    if result.canonical_signal_id != run.attempted_signal_id:
        raise ObservationServiceError("produced run must attempt the result's canonical Signal")
    if result.condition_citation != run.attempted_condition_citation:
        raise ObservationServiceError("produced run must attempt the result's condition citation")
    if result.semantic_contract_version != run.attempted_semantic_contract_version:
        raise ObservationServiceError("produced run must use the result's semantic contract")
    with database.get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            signal = _hydrate_canonical_signal(conn, result.canonical_signal_id)
            _validate_citations(signal, result.condition_citation, result.state_evidence_citation, result.condition_state)
            existing = _find_exact(conn, result)
            if existing is None:
                _validate_lineage(conn, result)
                observation = InterpretedObservation(
                    observation_id=result.observation_id, signal_id=signal.id,
                    condition_citation=result.condition_citation, condition_state=result.condition_state,
                    semantic_contract_version=result.semantic_contract_version, recorded_at=result.recorded_at,
                    state_evidence_citation=result.state_evidence_citation,
                    supersedes_observation_id=result.supersedes_observation_id,
                )
                columns = ", ".join(observation.to_db_row())
                conn.execute(f"INSERT INTO interpreted_observations ({columns}) VALUES ({', '.join(':' + key for key in observation.to_db_row())})", observation.to_db_row())
                created = True
            else:
                observation = InterpretedObservation.from_db_row(existing)
                created = False
            retained_run = ObservationRun(
                run_id=run.run_id, attempted_signal_id=run.attempted_signal_id,
                attempted_condition_citation=run.attempted_condition_citation,
                attempted_semantic_contract_version=run.attempted_semantic_contract_version,
                producer_kind=run.producer_kind, producer_name=run.producer_name,
                producer_revision=run.producer_revision, attempted_at=run.attempted_at,
                outcome=ObservationRunOutcome.PRODUCED, produced_at=produced_at,
                resulting_observation_id=observation.observation_id,
            )
            _insert_run(conn, retained_run)
            conn.commit()
            return ObservationPersistenceResult(observation, retained_run, created)
        except Exception:
            conn.rollback()
            raise


def persist_operational_failure(run: ObservationRunInput) -> ObservationRun:
    """Retain a valid attempted target without creating semantic output."""
    with database.get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            signal = _hydrate_canonical_signal(conn, run.attempted_signal_id)
            _resolve(signal, run.attempted_condition_citation)
            retained = ObservationRun(
                run_id=run.run_id, attempted_signal_id=run.attempted_signal_id,
                attempted_condition_citation=run.attempted_condition_citation,
                attempted_semantic_contract_version=run.attempted_semantic_contract_version,
                producer_kind=run.producer_kind, producer_name=run.producer_name,
                producer_revision=run.producer_revision, attempted_at=run.attempted_at,
                outcome=ObservationRunOutcome.OPERATIONAL_FAILURE,
            )
            _insert_run(conn, retained)
            conn.commit()
            return retained
        except Exception:
            conn.rollback()
            raise
