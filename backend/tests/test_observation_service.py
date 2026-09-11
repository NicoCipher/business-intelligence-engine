"""Runtime tests for the BIA-58 producer-neutral Observation service."""

import sqlite3
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import database
from models import (
    CitationSourcePart,
    ObservationCitation,
    ObservationConditionState,
    ObservationProducerKind,
)
from observation_service import (
    ObservationLineageConflict,
    ObservationResultInput,
    ObservationRunInput,
    ObservationServiceError,
    persist_operational_failure,
    persist_produced,
)


@pytest.fixture
def db(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "bia.db")
    database.initialize()
    with database.get_connection() as conn:
        conn.execute("""INSERT INTO signals
          (id, source, source_id, title, content, entity_ids, tags, raw_metadata, collected_at, domain)
          VALUES ('canonical-1', 'rss', 'source-1', 'Condition aa aa',
          'The condition remains active today.', '[]', '[]', '{}', 'now', 'business')""")
        conn.execute("""INSERT INTO signals
          (id, source, source_id, title, content, entity_ids, tags, raw_metadata, collected_at, domain)
          VALUES ('canonical-2', 'rss', 'source-2', 'Other condition',
          'The other condition is resolved.', '[]', '[]', '{}', 'now', 'business')""")
        conn.commit()
    return database.DB_PATH


def citation(text, part=CitationSourcePart.CONTENT, occurrence=1):
    return ObservationCitation(part, text, occurrence)


def run(run_id="run-1", signal_id="canonical-1", target=None):
    return ObservationRunInput(
        run_id, signal_id, target or citation("condition remains active"), "condition-state/v1",
        ObservationProducerKind.RULE, "attempted", "reviewed", "r1",
    )


_DEFAULT_EVIDENCE = object()


def result(observation_id="observation-1", signal_id="canonical-1", target=None,
           state=ObservationConditionState.ACTIVE, evidence=_DEFAULT_EVIDENCE,
           semantic_contract_version="condition-state/v1", **kwargs):
    target = target or citation("condition remains active")
    if evidence is _DEFAULT_EVIDENCE and state is not ObservationConditionState.UNKNOWN:
        evidence = citation("active")
    elif evidence is _DEFAULT_EVIDENCE:
        evidence = None
    return ObservationResultInput(
        observation_id, signal_id, target, state, semantic_contract_version, "recorded",
        evidence, **kwargs,
    )


def produced(observation_id="observation-1", run_id="run-1", **kwargs):
    value = result(observation_id, **kwargs)
    return persist_produced(value, run(run_id, value.canonical_signal_id, value.condition_citation), produced_at="produced")


def counts():
    with database.get_connection() as conn:
        return tuple(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                     for table in ("interpreted_observations", "observation_runs"))


def test_produced_result_uses_stored_canonical_text_and_creates_observation_and_run(db):
    persisted = produced()
    assert persisted.created
    assert persisted.observation.signal_id == "canonical-1"
    assert persisted.run.resulting_observation_id == "observation-1"
    assert counts() == (1, 1)


@pytest.mark.parametrize("target", [citation("Condition", CitationSourcePart.TITLE), citation("aa", CitationSourcePart.TITLE, 2)])
def test_title_and_overlapping_citations_resolve(db, target):
    persisted = produced(target=target, evidence=target)
    assert persisted.observation.condition_citation == target


@pytest.mark.parametrize("target", [citation("CONDITION"), citation("missing"), citation("condition", occurrence=2)])
def test_invalid_or_nonexistent_citations_reject_without_writes(db, target):
    with pytest.raises(ObservationServiceError):
        produced(target=target, evidence=target)
    assert counts() == (0, 0)


def test_state_support_rules_and_containment(db):
    with pytest.raises(ObservationServiceError):
        produced(state=ObservationConditionState.ACTIVE, evidence=None)
    unknown = produced(state=ObservationConditionState.UNKNOWN, evidence=None)
    assert unknown.created
    with pytest.raises(ObservationServiceError):
        produced("outside", "outside-run", target=citation("condition"), evidence=citation("active today"))
    with pytest.raises(ObservationServiceError):
        produced("part", "part-run", target=citation("condition"), evidence=citation("Condition", CitationSourcePart.TITLE))


def test_unknown_with_contained_support_and_equal_or_substring_support_are_valid(db):
    assert produced(state=ObservationConditionState.UNKNOWN, evidence=citation("active")).created
    assert produced("whole", "whole-run", target=citation("condition remains active"), evidence=citation("condition remains active")).created
    assert produced("substring", "substring-run", target=citation("condition remains active"), evidence=citation("active")).created


def test_nonexistent_canonical_signal_and_transient_text_cannot_supply_provenance(db):
    with pytest.raises(ObservationServiceError):
        produced(signal_id="missing")
    # The stored text, not a caller recreated Signal/full_text, is the only evidence.
    with pytest.raises(ObservationServiceError):
        produced(target=citation("condition aa"), evidence=citation("condition aa"))
    assert counts() == (0, 0)


def test_exact_reuse_keeps_one_observation_and_inserts_fresh_run(db):
    assert produced().created
    reused = produced("ignored-new-id", "run-2")
    assert not reused.created
    assert reused.observation.observation_id == "observation-1"
    assert counts() == (1, 2)


@pytest.mark.parametrize("change", [
    {"target": citation("remains active"), "evidence": citation("active")},
    {"state": ObservationConditionState.RESOLVED, "target": citation("condition remains active"), "evidence": citation("active")},
    {"state": ObservationConditionState.UNKNOWN, "evidence": None},
    {"semantic_contract_version": "condition-state/v2"},
])
def test_exact_key_boundaries_do_not_reuse(db, change):
    first = result()
    persist_produced(first, run(), produced_at="produced")
    second = result("observation-2", **change)
    second_run = run("run-2", target=second.condition_citation)
    if "semantic_contract_version" in change:
        second_run = ObservationRunInput("run-2", "canonical-1", second.condition_citation, "condition-state/v2", ObservationProducerKind.RULE, "attempted")
    assert persist_produced(second, second_run, produced_at="produced").created


def test_failure_then_retry_preserves_failure_and_creates_only_success_observation(db):
    failed = persist_operational_failure(run())
    assert failed.resulting_observation_id is None and failed.produced_at is None
    assert counts() == (0, 1)
    assert produced("observation-1", "run-2").created
    assert counts() == (1, 2)


def test_initial_run_failure_rolls_back_new_observation_but_not_existing_rows(db):
    persist_operational_failure(run("duplicate"))
    with pytest.raises(sqlite3.IntegrityError):
        produced("candidate", "duplicate")
    assert counts() == (0, 1)


def test_correction_lineage_allows_cross_signal_and_rejects_missing_self_and_second_successor(db):
    produced("root", "root-run")
    successor = result(
        "successor", "canonical-2", citation("other condition is resolved"),
        ObservationConditionState.RESOLVED, citation("resolved"),
        supersedes_observation_id="root",
    )
    persisted = persist_produced(successor, run("successor-run", "canonical-2", successor.condition_citation), produced_at="produced")
    assert persisted.created
    with pytest.raises(ObservationLineageConflict):
        produced("another", "another-run", supersedes_observation_id="root")
    with pytest.raises(ObservationLineageConflict):
        produced("self", "self-run", supersedes_observation_id="self")
    with pytest.raises(ObservationLineageConflict):
        produced("missing", "missing-run", supersedes_observation_id="nope")


def test_operational_failure_never_creates_observation_and_requires_valid_target(db):
    with pytest.raises(ObservationServiceError):
        persist_operational_failure(run(target=citation("absent")))
    assert counts() == (0, 0)


def test_competing_file_backed_attempts_reuse_one_observation(db):
    # Separate service connections start together against the file-backed DB.
    # BEGIN IMMEDIATE serializes lookup+insert, then the loser sees exact reuse.
    barrier = threading.Barrier(3)
    results = []
    def attempt(observation_id, run_id):
        barrier.wait()
        results.append(produced(observation_id, run_id))

    first = threading.Thread(target=attempt, args=("observation-1", "run-1"))
    second = threading.Thread(target=attempt, args=("candidate", "run-2"))
    first.start()
    second.start()
    barrier.wait()
    first.join()
    second.join()
    assert sorted(item.created for item in results) == [False, True]
    assert counts() == (1, 2)
