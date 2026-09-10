"""BIA-57 tests for canonical SQLite Signal persistence resolution."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import database
from collectors.base import (
    BaseCollector,
    SignalDedupeKey,
    SignalPersistenceResolution,
    SignalPersistenceStatus,
    persist_signals,
)
from models import Signal
from pipeline import _retag_for_domain


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "signal-resolution.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    database.initialize()
    return db_path


def _signal(
    source_id: str,
    *,
    signal_id: str,
    title: str = "Stored evidence title",
    content: str = "Stored evidence content",
    domain: str = "business",
) -> Signal:
    return Signal(
        id=signal_id,
        source="hn",
        source_id=source_id,
        title=title,
        content=content,
        url="https://example.test/item",
        platform_score=12,
        comment_count=4,
        entity_ids=["entity-1"],
        tags=["demand"],
        raw_metadata={"origin": "test"},
        collected_at="2026-09-10T00:00:00+00:00",
        domain=domain,
    )


def test_new_signal_returns_hydrated_sqlite_identity(fresh_db):
    incoming = _signal("one", signal_id="collector-temporary-id")

    result = persist_signals([incoming])

    assert result.inserted_count == 1
    assert result.existing_count == 0
    assert result.failed_count == 0
    resolution = result.resolutions[0]
    assert resolution.status is SignalPersistenceStatus.INSERTED
    assert resolution.input_index == 0
    assert resolution.dedupe_key == SignalDedupeKey("hn", "one", "business")
    assert resolution.canonical_signal_id == "collector-temporary-id"
    assert resolution.persisted_signal is not incoming
    assert resolution.persisted_signal == incoming

    with database.get_connection() as conn:
        row = conn.execute(
            "SELECT id, title, content FROM signals WHERE source_id = 'one'"
        ).fetchone()
    assert tuple(row) == (
        resolution.canonical_signal_id,
        resolution.persisted_signal.title,
        resolution.persisted_signal.content,
    )


def test_duplicate_returns_existing_identity_and_stored_evidence(fresh_db):
    original = _signal("duplicate", signal_id="canonical-signal-id")
    assert persist_signals([original]).inserted_count == 1
    recollected = _signal(
        "duplicate",
        signal_id="collector-temporary-id",
        title="Recollected title must not win",
        content="Recollected content must not win",
    )

    result = persist_signals([recollected])

    assert result.inserted_count == 0
    assert result.existing_count == 1
    resolution = result.resolutions[0]
    assert resolution.status is SignalPersistenceStatus.EXISTING
    assert resolution.input_index == 0
    assert resolution.input_signal_id == "collector-temporary-id"
    assert resolution.dedupe_key == SignalDedupeKey("hn", "duplicate", "business")
    assert resolution.canonical_signal_id == "canonical-signal-id"
    assert resolution.canonical_signal_id != recollected.id
    assert resolution.persisted_signal is not recollected
    assert resolution.persisted_signal.title == original.title
    assert resolution.persisted_signal.content == original.content

    with database.get_connection() as conn:
        row = conn.execute(
            "SELECT id, title, content FROM signals WHERE source_id = 'duplicate'"
        ).fetchone()
    assert tuple(row) == ("canonical-signal-id", original.title, original.content)


def test_bulk_resolutions_are_ordered_and_do_not_cross_signal_ids(fresh_db):
    existing = _signal("existing", signal_id="canonical-existing")
    persist_signals([existing])
    inputs = [
        _signal("first", signal_id="first-id"),
        _signal("existing", signal_id="temporary-duplicate-id"),
        _signal("third", signal_id="third-id"),
    ]

    result = persist_signals(inputs)

    assert [r.input_signal_id for r in result.resolutions] == [
        "first-id",
        "temporary-duplicate-id",
        "third-id",
    ]
    assert [r.input_index for r in result.resolutions] == [0, 1, 2]
    assert [r.status for r in result.resolutions] == [
        SignalPersistenceStatus.INSERTED,
        SignalPersistenceStatus.EXISTING,
        SignalPersistenceStatus.INSERTED,
    ]
    assert [r.canonical_signal_id for r in result.resolutions] == [
        "first-id",
        "canonical-existing",
        "third-id",
    ]


def test_domain_fanout_resolves_one_canonical_row_per_domain(fresh_db):
    shared = _signal("shared-item", signal_id="shared-collector-id")
    business, test_intel = _retag_for_domain([shared], "business") + _retag_for_domain(
        [shared], "test_intel"
    )

    result = persist_signals([business, test_intel])

    assert result.inserted_count == 2
    assert [r.persisted_signal.domain for r in result.resolutions] == [
        "business",
        "test_intel",
    ]
    assert [r.canonical_signal_id for r in result.resolutions] == [
        business.id,
        test_intel.id,
    ]


def test_partial_failures_never_receive_a_canonical_mapping(fresh_db):
    valid = _signal("valid", signal_id="valid-id")
    invalid = _signal("invalid", signal_id="failed-temporary-id")
    invalid.source = None  # type: ignore[assignment]  # exercise SQLite NOT NULL rejection

    result = persist_signals([valid, invalid])

    assert result.inserted_count == 1
    assert result.existing_count == 0
    assert result.failed_count == 1
    assert result.persisted_count == 1
    assert result.resolutions[0].canonical_signal_id == "valid-id"
    failed = result.resolutions[1]
    assert failed.input_index == 1
    assert failed.dedupe_key == SignalDedupeKey(None, "invalid", "business")
    assert failed.status is SignalPersistenceStatus.FAILED
    assert failed.canonical_signal_id is None
    assert failed.persisted_signal is None
    assert failed.failure_detail

    with database.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == 1


def test_new_row_is_rolled_back_when_canonical_hydration_fails(fresh_db):
    malformed = _signal("malformed-new", signal_id="malformed-input-id")
    malformed.entity_ids = "not-a-list"  # type: ignore[assignment]

    result = persist_signals([malformed])

    assert result.inserted_count == 0
    assert result.failed_count == 1
    failed = result.resolutions[0]
    assert failed.input_index == 0
    assert failed.dedupe_key == SignalDedupeKey("hn", "malformed-new", "business")
    assert failed.status is SignalPersistenceStatus.FAILED
    assert failed.canonical_signal_id is None
    assert failed.persisted_signal is None

    with database.get_connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM signals WHERE source_id = 'malformed-new'"
        ).fetchone()[0] == 0


def test_hydration_failure_isolates_surrounding_inputs(fresh_db):
    first = _signal("before-malformed", signal_id="first-id")
    malformed = _signal("malformed-middle", signal_id="malformed-id")
    malformed.entity_ids = "not-a-list"  # type: ignore[assignment]
    third = _signal("after-malformed", signal_id="third-id")

    result = persist_signals([first, malformed, third])

    assert len(result.resolutions) == 3
    assert [resolution.input_index for resolution in result.resolutions] == [0, 1, 2]
    assert [resolution.status for resolution in result.resolutions] == [
        SignalPersistenceStatus.INSERTED,
        SignalPersistenceStatus.FAILED,
        SignalPersistenceStatus.INSERTED,
    ]
    assert [resolution.dedupe_key for resolution in result.resolutions] == [
        SignalDedupeKey("hn", "before-malformed", "business"),
        SignalDedupeKey("hn", "malformed-middle", "business"),
        SignalDedupeKey("hn", "after-malformed", "business"),
    ]
    assert result.resolutions[0].persisted_signal is not None
    assert result.resolutions[1].persisted_signal is None
    assert result.resolutions[2].persisted_signal is not None
    assert result.inserted_count == 2

    with database.get_connection() as conn:
        stored_source_ids = {
            row["source_id"]
            for row in conn.execute(
                """SELECT source_id FROM signals
                   WHERE source_id IN ('before-malformed', 'malformed-middle', 'after-malformed')"""
            )
        }
    assert stored_source_ids == {"before-malformed", "after-malformed"}


def test_existing_malformed_row_is_reported_without_mutation(fresh_db):
    original = _signal("malformed-existing", signal_id="stored-malformed-id")
    row = original.to_db_row()
    row["entity_ids"] = '"not-a-list"'
    with database.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO signals
              (id, source, source_id, url, title, content,
               platform_score, comment_count, entity_ids, tags,
               raw_metadata, collected_at, processed, domain)
            VALUES
              (:id, :source, :source_id, :url, :title, :content,
               :platform_score, :comment_count, :entity_ids, :tags,
               :raw_metadata, :collected_at, :processed, :domain)
            """,
            row,
        )
        conn.commit()

    result = persist_signals([_signal("malformed-existing", signal_id="new-temp-id")])

    assert result.inserted_count == 0
    assert result.existing_count == 0
    assert result.failed_count == 1
    failed = result.resolutions[0]
    assert failed.dedupe_key == SignalDedupeKey("hn", "malformed-existing", "business")
    assert failed.status is SignalPersistenceStatus.FAILED
    assert failed.canonical_signal_id is None
    with database.get_connection() as conn:
        row = conn.execute(
            "SELECT id, entity_ids FROM signals WHERE source_id = 'malformed-existing'"
        ).fetchone()
    assert tuple(row) == ("stored-malformed-id", '"not-a-list"')


def test_same_batch_duplicate_uses_one_canonical_stored_signal(fresh_db):
    first = _signal(
        "same-batch",
        signal_id="shared-temporary-id",
        title="First title wins",
        content="First content wins",
    )
    second = _signal(
        "same-batch",
        signal_id="shared-temporary-id",
        title="Second title must not win",
        content="Second content must not win",
    )

    result = persist_signals([first, second])

    assert result.inserted_count == 1
    assert result.existing_count == 1
    assert [resolution.input_index for resolution in result.resolutions] == [0, 1]
    assert [resolution.input_signal_id for resolution in result.resolutions] == [
        "shared-temporary-id",
        "shared-temporary-id",
    ]
    assert [resolution.dedupe_key for resolution in result.resolutions] == [
        SignalDedupeKey("hn", "same-batch", "business"),
        SignalDedupeKey("hn", "same-batch", "business"),
    ]
    assert [resolution.status for resolution in result.resolutions] == [
        SignalPersistenceStatus.INSERTED,
        SignalPersistenceStatus.EXISTING,
    ]
    assert [resolution.canonical_signal_id for resolution in result.resolutions] == [
        "shared-temporary-id",
        "shared-temporary-id",
    ]
    assert result.resolutions[1].persisted_signal.title == "First title wins"
    assert result.resolutions[1].persisted_signal.content == "First content wins"
    with database.get_connection() as conn:
        row = conn.execute(
            "SELECT title, content FROM signals WHERE source_id = 'same-batch'"
        ).fetchone()
    assert tuple(row) == ("First title wins", "First content wins")


def test_resolution_rejects_invalid_status_and_canonical_signal_combinations():
    canonical = _signal("invariant", signal_id="canonical-id")
    dedupe_key = SignalDedupeKey("hn", "invariant", "business")

    with pytest.raises(ValueError, match="failed persistence cannot carry"):
        SignalPersistenceResolution(
            input_index=0,
            input_signal_id="temporary-id",
            dedupe_key=dedupe_key,
            status=SignalPersistenceStatus.FAILED,
            persisted_signal=canonical,
            failure_detail="failed",
        )
    with pytest.raises(ValueError, match="successful persistence requires"):
        SignalPersistenceResolution(
            input_index=0,
            input_signal_id="temporary-id",
            dedupe_key=dedupe_key,
            status=SignalPersistenceStatus.INSERTED,
        )


def test_legacy_collector_count_contract_derives_from_resolution(fresh_db):
    class TestCollector(BaseCollector):
        SOURCE_NAME = "hn"

        def _fetch(self, limit):
            yield from ()

    collector = TestCollector()
    signal = _signal("collector", signal_id="collector-id")

    assert collector.persist([signal]) == 1
    assert collector.persist([signal]) == 0
