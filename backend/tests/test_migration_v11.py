"""Fresh, upgrade, and rollback tests for the atomic Observation V1 migration."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import database

_OBSERVATION_OBJECTS = (
    "interpreted_observations",
    "observation_runs",
    "idx_interpreted_observations_signal_id",
    "idx_interpreted_observations_supersedes",
    "idx_interpreted_observations_literal_lookup",
    "idx_observation_runs_attempted_signal_time",
    "idx_observation_runs_producer",
    "idx_observation_runs_result",
    "trg_interpreted_observations_no_duplicate_insert",
    "trg_interpreted_observations_no_update",
    "trg_interpreted_observations_no_delete",
    "trg_observation_runs_no_duplicate_insert",
    "trg_observation_runs_no_update",
    "trg_observation_runs_no_delete",
    "trg_observation_runs_produced_result_matches_attempt",
    "trg_signals_no_citation_bearing_title_update",
    "trg_signals_no_citation_bearing_content_update",
)


def _observation_schema(conn):
    placeholders = ", ".join("?" for _ in _OBSERVATION_OBJECTS)
    rows = conn.execute(
        f"""SELECT type, name, tbl_name, sql FROM sqlite_master
            WHERE name IN ({placeholders}) ORDER BY type, name""",
        _OBSERVATION_OBJECTS,
    ).fetchall()
    return [tuple(row) for row in rows]


def _seed_supported_v10_database(path):
    conn = sqlite3.connect(path)
    conn.executescript(database._SCHEMA_DDL)
    conn.execute(
        "INSERT INTO schema_info (version, applied_at) VALUES (10, '2026-09-10T00:00:00Z')"
    )
    conn.execute(
        """INSERT INTO signals (id, source, source_id, title, collected_at, domain)
           VALUES ('preexisting-signal', 'rss', 'preexisting', 'Existing intelligence',
                   '2026-09-10T00:00:00Z', 'business')"""
    )
    conn.commit()
    conn.close()


def test_fresh_and_supported_upgrade_have_equivalent_observation_schema(monkeypatch, tmp_path):
    fresh_path = tmp_path / "fresh.db"
    monkeypatch.setattr(database, "DB_PATH", fresh_path)
    database.initialize()
    with database.get_connection() as conn:
        fresh_schema = _observation_schema(conn)

    upgrade_path = tmp_path / "upgrade.db"
    _seed_supported_v10_database(upgrade_path)
    monkeypatch.setattr(database, "DB_PATH", upgrade_path)
    database.initialize()
    database.initialize()
    with database.get_connection() as conn:
        assert _observation_schema(conn) == fresh_schema
        assert len(fresh_schema) == len(_OBSERVATION_OBJECTS)
        assert conn.execute("SELECT title FROM signals WHERE id = 'preexisting-signal'").fetchone()[0] == "Existing intelligence"
        assert conn.execute("SELECT MAX(version) FROM schema_info").fetchone()[0] == 11


def test_v11_failure_rolls_back_its_schema_and_leaves_existing_intelligence(monkeypatch, tmp_path):
    db_path = tmp_path / "failure.db"
    _seed_supported_v10_database(db_path)
    monkeypatch.setattr(database, "DB_PATH", db_path)
    monkeypatch.setattr(
        database,
        "_OBSERVATION_V1_DDL_STATEMENTS",
        database._OBSERVATION_V1_DDL_STATEMENTS + ("SELECT no_such_observation_migration_function()",),
    )

    with pytest.raises(sqlite3.OperationalError):
        database.initialize()

    with database.get_connection() as conn:
        names = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master").fetchall()}
        assert "interpreted_observations" not in names
        assert "observation_runs" not in names
        assert conn.execute("SELECT MAX(version) FROM schema_info").fetchone()[0] == 10
        assert conn.execute("SELECT title FROM signals WHERE id = 'preexisting-signal'").fetchone()[0] == "Existing intelligence"
