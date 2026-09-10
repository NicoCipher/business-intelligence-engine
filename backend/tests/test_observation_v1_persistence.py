"""Direct SQLite enforcement tests for the BIA-56 Observation V1 foundation."""

import sqlite3
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import database
from models import (
    CitationSourcePart,
    InterpretedObservation,
    ObservationCitation,
    ObservationConditionState,
    ObservationProducerKind,
    ObservationRun,
    ObservationRunOutcome,
)


@pytest.fixture
def db(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "bia.db")
    database.initialize()
    with database.get_connection() as conn:
        for signal_id in ("signal-1", "signal-2"):
            conn.execute(
                """
                INSERT INTO signals (id, source, source_id, title, content, collected_at, domain)
                VALUES (?, 'rss', ?, 'A condition is active', 'State evidence is here',
                        '2026-09-10T00:00:00Z', 'business')
                """,
                (signal_id, f"source-{signal_id}"),
            )
        conn.commit()
    return database.DB_PATH


def _insert_observation(conn, observation_id="observation-1", **overrides):
    row = {
        "observation_id": observation_id,
        "signal_id": "signal-1",
        "condition_source_part": "title",
        "condition_literal_text": "A condition is active",
        "condition_occurrence_ordinal": 1,
        "state_evidence_source_part": "title",
        "state_evidence_literal_text": "A condition is active",
        "state_evidence_occurrence_ordinal": 1,
        "condition_state": "active",
        "semantic_contract_version": "condition-state/v1",
        "supersedes_observation_id": None,
        "recorded_at": "2026-09-10T00:00:00Z",
    }
    row.update(overrides)
    conn.execute(
        """
        INSERT INTO interpreted_observations (
            observation_id, signal_id, condition_source_part, condition_literal_text,
            condition_occurrence_ordinal, state_evidence_source_part,
            state_evidence_literal_text, state_evidence_occurrence_ordinal,
            condition_state, semantic_contract_version, supersedes_observation_id, recorded_at
        ) VALUES (
            :observation_id, :signal_id, :condition_source_part, :condition_literal_text,
            :condition_occurrence_ordinal, :state_evidence_source_part,
            :state_evidence_literal_text, :state_evidence_occurrence_ordinal,
            :condition_state, :semantic_contract_version, :supersedes_observation_id, :recorded_at
        )
        """,
        row,
    )


def _insert_run(conn, run_id="run-1", **overrides):
    row = {
        "run_id": run_id,
        "attempted_signal_id": "signal-1",
        "attempted_condition_source_part": "title",
        "attempted_condition_literal_text": "A condition is active",
        "attempted_condition_occurrence_ordinal": 1,
        "attempted_semantic_contract_version": "condition-state/v1",
        "producer_kind": "rule",
        "producer_name": "reviewed-rule",
        "producer_revision": "r1",
        "attempted_at": "2026-09-10T00:00:00Z",
        "outcome": "produced",
        "produced_at": "2026-09-10T00:00:01Z",
        "resulting_observation_id": "observation-1",
    }
    row.update(overrides)
    conn.execute(
        """
        INSERT INTO observation_runs (
            run_id, attempted_signal_id, attempted_condition_source_part,
            attempted_condition_literal_text, attempted_condition_occurrence_ordinal,
            attempted_semantic_contract_version, producer_kind, producer_name,
            producer_revision, attempted_at, outcome, produced_at, resulting_observation_id
        ) VALUES (
            :run_id, :attempted_signal_id, :attempted_condition_source_part,
            :attempted_condition_literal_text, :attempted_condition_occurrence_ordinal,
            :attempted_semantic_contract_version, :producer_kind, :producer_name,
            :producer_revision, :attempted_at, :outcome, :produced_at, :resulting_observation_id
        )
        """,
        row,
    )


def test_observation_append_only_and_lineage_constraints(db):
    with database.get_connection() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            _insert_observation(conn, None)
        _insert_observation(conn)
        original = tuple(conn.execute(
            "SELECT * FROM interpreted_observations WHERE observation_id = 'observation-1'"
        ).fetchone())

        for statement in (
            "INSERT INTO interpreted_observations SELECT * FROM interpreted_observations",
            "INSERT OR REPLACE INTO interpreted_observations SELECT * FROM interpreted_observations",
            "REPLACE INTO interpreted_observations SELECT * FROM interpreted_observations",
            "UPDATE interpreted_observations SET condition_state = 'resolved' WHERE observation_id = 'observation-1'",
            "DELETE FROM interpreted_observations WHERE observation_id = 'observation-1'",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(statement)
        assert tuple(conn.execute(
            "SELECT * FROM interpreted_observations WHERE observation_id = 'observation-1'"
        ).fetchone()) == original

        _insert_observation(conn, "root-2")
        _insert_observation(conn, "successor-1", supersedes_observation_id="observation-1")
        with pytest.raises(sqlite3.IntegrityError):
            _insert_observation(conn, "successor-2", supersedes_observation_id="observation-1")
        with pytest.raises(sqlite3.IntegrityError):
            _insert_observation(conn, "self-link", supersedes_observation_id="self-link")


@pytest.mark.parametrize(
    "overrides",
    (
        {"condition_state": "invalid"},
        {"condition_literal_text": ""},
        {"condition_occurrence_ordinal": 0},
        {"condition_state": "active", "state_evidence_source_part": None,
         "state_evidence_literal_text": None, "state_evidence_occurrence_ordinal": None},
        {"state_evidence_source_part": "content"},
    ),
)
def test_observation_structural_constraints(db, overrides):
    with database.get_connection() as conn, pytest.raises(sqlite3.IntegrityError):
        _insert_observation(conn, **overrides)


def test_runs_are_append_only_and_enforce_outcome_cardinality(db):
    with database.get_connection() as conn:
        _insert_observation(conn)
        with pytest.raises(sqlite3.IntegrityError):
            _insert_run(conn, None)
        _insert_run(conn)
        original = tuple(conn.execute("SELECT * FROM observation_runs WHERE run_id = 'run-1'").fetchone())
        for statement in (
            "INSERT INTO observation_runs SELECT * FROM observation_runs",
            "INSERT OR REPLACE INTO observation_runs SELECT * FROM observation_runs",
            "REPLACE INTO observation_runs SELECT * FROM observation_runs",
            "UPDATE observation_runs SET producer_name = 'other' WHERE run_id = 'run-1'",
            "DELETE FROM observation_runs WHERE run_id = 'run-1'",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(statement)
        assert tuple(conn.execute("SELECT * FROM observation_runs WHERE run_id = 'run-1'").fetchone()) == original

        _insert_run(
            conn,
            "failure-1",
            outcome="operational_failure",
            produced_at=None,
            resulting_observation_id=None,
        )
        with pytest.raises(sqlite3.IntegrityError):
            _insert_run(conn, "failure-with-result", outcome="operational_failure", produced_at=None)
        with pytest.raises(sqlite3.IntegrityError):
            _insert_run(conn, "produced-without-time", produced_at=None)


@pytest.mark.parametrize(
    "overrides",
    (
        {"attempted_signal_id": "signal-2"},
        {"attempted_condition_source_part": "content"},
        {"attempted_condition_literal_text": "different literal"},
        {"attempted_condition_occurrence_ordinal": 2},
        {"attempted_semantic_contract_version": "condition-state/v2"},
    ),
)
def test_produced_run_must_match_its_observation_exactly(db, overrides):
    with database.get_connection() as conn:
        _insert_observation(conn)
        with pytest.raises(sqlite3.IntegrityError):
            _insert_run(conn, **overrides)


def test_citation_bearing_signals_are_protected_without_freezing_unrelated_rows(db):
    with database.get_connection() as conn:
        _insert_observation(conn)
        _insert_run(
            conn,
            "failure-1",
            outcome="operational_failure",
            produced_at=None,
            resulting_observation_id=None,
        )
        for column in ("title", "content"):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(f"UPDATE signals SET {column} = 'changed' WHERE id = 'signal-1'")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM signals WHERE id = 'signal-1'")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT OR REPLACE INTO signals
                   (id, source, source_id, title, content, collected_at, domain)
                   VALUES ('signal-1', 'rss', 'replacement', 'replacement', '',
                           '2026-09-10T00:00:00Z', 'business')"""
            )
        conn.execute("UPDATE signals SET title = 'still mutable' WHERE id = 'signal-2'")


def test_immutable_models_round_trip_through_database_rows(db):
    citation = ObservationCitation(CitationSourcePart.TITLE, "A condition is active")
    observation = InterpretedObservation(
        observation_id="observation-1",
        signal_id="signal-1",
        condition_citation=citation,
        condition_state=ObservationConditionState.UNKNOWN,
        semantic_contract_version="condition-state/v1",
        recorded_at="2026-09-10T00:00:00Z",
    )
    with database.get_connection() as conn:
        _insert_observation(conn, **observation.to_db_row())
        hydrated_observation = InterpretedObservation.from_db_row(conn.execute(
            "SELECT * FROM interpreted_observations WHERE observation_id = 'observation-1'"
        ).fetchone())
        assert hydrated_observation == observation
        assert hydrated_observation.state_evidence_citation is None
    with pytest.raises(FrozenInstanceError):
        hydrated_observation.signal_id = "different"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        citation.literal_text = "different"  # type: ignore[misc]

    run = ObservationRun(
        run_id="run-1",
        attempted_signal_id="signal-1",
        attempted_condition_citation=citation,
        attempted_semantic_contract_version="condition-state/v1",
        producer_kind=ObservationProducerKind.RULE,
        attempted_at="2026-09-10T00:00:00Z",
        outcome=ObservationRunOutcome.OPERATIONAL_FAILURE,
    )
    with database.get_connection() as conn:
        _insert_run(conn, **run.to_db_row())
        assert ObservationRun.from_db_row(conn.execute(
            "SELECT * FROM observation_runs WHERE run_id = 'run-1'"
        ).fetchone()) == run
    with pytest.raises(FrozenInstanceError):
        run.outcome = ObservationRunOutcome.PRODUCED  # type: ignore[misc]
