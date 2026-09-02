"""Focused coverage for canonical SQLite snapshot continuity."""

import sqlite3
from pathlib import Path

import pytest

import persistence


def _write_value(path: Path, value: str, *, wal: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        if wal:
            conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("CREATE TABLE IF NOT EXISTS values_table (value TEXT NOT NULL)")
        conn.execute("DELETE FROM values_table")
        conn.execute("INSERT INTO values_table (value) VALUES (?)", (value,))


def _read_value(path: Path) -> str:
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
        return conn.execute("SELECT value FROM values_table").fetchone()[0]


@pytest.fixture
def snapshot_paths(tmp_path, monkeypatch):
    backup_dir = tmp_path / "backups"
    monkeypatch.setattr(persistence, "BACKUP_DIR", backup_dir)
    return tmp_path / "bia.db", backup_dir


def test_pull_restores_canonical_snapshot_on_cold_start(snapshot_paths):
    source, _ = snapshot_paths
    _write_value(source, "remote evidence")
    persistence.push(source)
    destination = source.parent / "cold" / "bia.db"

    assert persistence.pull(destination) is True
    assert _read_value(destination) == "remote evidence"


def test_pull_never_overwrites_existing_live_database(snapshot_paths):
    source, _ = snapshot_paths
    _write_value(source, "canonical")
    persistence.push(source)
    destination = source.parent / "local" / "bia.db"
    _write_value(destination, "local work")

    assert persistence.pull(destination) is False
    assert _read_value(destination) == "local work"


def test_push_creates_one_valid_canonical_snapshot_without_history_growth(snapshot_paths):
    source, backup_dir = snapshot_paths
    _write_value(source, "first")
    first = persistence.push(source)
    _write_value(source, "second")
    second = persistence.push(source)

    assert first == second == backup_dir / persistence.CANONICAL_SNAPSHOT_NAME
    assert [path.name for path in backup_dir.iterdir()] == [persistence.CANONICAL_SNAPSHOT_NAME]
    assert _read_value(second) == "second"


def test_push_uses_sqlite_backup_api_for_wal_database(snapshot_paths):
    source, _ = snapshot_paths
    with sqlite3.connect(source) as source_conn:
        source_conn.execute("PRAGMA journal_mode = WAL")
        source_conn.execute("CREATE TABLE values_table (value TEXT NOT NULL)")
        source_conn.execute("INSERT INTO values_table (value) VALUES ('committed wal evidence')")
        source_conn.commit()
        assert source.with_name(f"{source.name}-wal").exists()

        snapshot = persistence.push(source)

    assert snapshot is not None
    assert _read_value(snapshot) == "committed wal evidence"
    with sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True) as conn:
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"


def test_local_sync_refuses_to_overwrite_by_default(snapshot_paths):
    destination, _ = snapshot_paths
    _write_value(destination, "local work")
    source = destination.parent / "downloaded" / "bia-latest.db"
    _write_value(source, "remote evidence")

    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        persistence.replace_local_from_snapshot(source, destination)

    assert _read_value(destination) == "local work"


def test_explicit_local_replacement_backs_up_existing_database(snapshot_paths):
    destination, _ = snapshot_paths
    _write_value(destination, "local work")
    source = destination.parent / "downloaded" / "bia-latest.db"
    _write_value(source, "remote evidence")

    backup = persistence.replace_local_from_snapshot(source, destination, replace=True)

    assert backup is not None and backup.exists()
    assert _read_value(backup) == "local work"
    assert _read_value(destination) == "remote evidence"


def test_local_sync_retention_prunes_only_tool_created_backups(snapshot_paths, monkeypatch):
    destination, _ = snapshot_paths
    source = destination.parent / "downloaded" / "bia-latest.db"
    _write_value(destination, "local work")
    _write_value(source, "remote one")
    monkeypatch.setattr(persistence, "LOCAL_SYNC_BACKUP_RETENTION", 1)

    persistence.replace_local_from_snapshot(source, destination, replace=True)
    _write_value(source, "remote two")
    persistence.replace_local_from_snapshot(source, destination, replace=True)

    backup_dir = destination.parent / "backups"
    assert len(list(backup_dir.glob("bia-before-ci-sync-*.db"))) == 1
    sentinel = backup_dir / "operator-created.db"
    sentinel.write_text("do not remove")
    persistence._prune_local_sync_backups(backup_dir)
    assert sentinel.exists()


def test_missing_or_invalid_remote_snapshot_preserves_existing_database(snapshot_paths):
    destination, backup_dir = snapshot_paths
    _write_value(destination, "local work")

    with pytest.raises(FileNotFoundError):
        persistence.replace_local_from_snapshot(backup_dir / "missing.db", destination, replace=True)

    canonical = persistence.canonical_snapshot_path()
    canonical.parent.mkdir(parents=True)
    canonical.write_text("not sqlite")
    with pytest.raises(sqlite3.DatabaseError):
        persistence.restore_canonical_snapshot(destination)

    assert _read_value(destination) == "local work"


def test_absent_canonical_snapshot_allows_first_run_without_overwriting_cache(snapshot_paths):
    destination, _ = snapshot_paths
    _write_value(destination, "cache copy")

    assert persistence.restore_canonical_snapshot(destination) is False
    assert _read_value(destination) == "cache copy"


def test_legacy_snapshot_migration_restores_first_post_migration_run(snapshot_paths):
    destination, backup_dir = snapshot_paths
    legacy = backup_dir / "staged" / "bia-20260101T000000Z.db"
    _write_value(legacy, "legacy evidence")

    canonical = persistence.migrate_legacy_snapshot(backup_dir / "staged")

    assert canonical == persistence.canonical_snapshot_path()
    assert persistence.restore_canonical_snapshot(destination) is True
    assert _read_value(destination) == "legacy evidence"


def test_legacy_migration_replaces_stale_cache_with_legacy_authority(snapshot_paths):
    destination, backup_dir = snapshot_paths
    _write_value(destination, "stale cache")
    legacy = backup_dir / "staged" / "bia-20260101T000000Z.db"
    _write_value(legacy, "legacy authority")

    persistence.migrate_legacy_snapshot(backup_dir / "staged")
    persistence.restore_canonical_snapshot(destination)

    assert _read_value(destination) == "legacy authority"


def test_legacy_migration_selects_newest_valid_snapshot(snapshot_paths):
    _, backup_dir = snapshot_paths
    staged = backup_dir / "staged"
    _write_value(staged / "bia-20260101T000000Z.db", "older valid evidence")
    invalid_newer = staged / "bia-20260201T000000Z.db"
    invalid_newer.write_text("not sqlite")

    canonical = persistence.migrate_legacy_snapshot(staged)

    assert _read_value(canonical) == "older valid evidence"


def test_invalid_legacy_migration_preserves_cache_and_does_not_create_canonical(snapshot_paths):
    destination, backup_dir = snapshot_paths
    _write_value(destination, "cache copy")
    legacy = backup_dir / "staged" / "bia-20260101T000000Z.db"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("not sqlite")

    with pytest.raises(sqlite3.DatabaseError, match="No valid legacy SQLite snapshots"):
        persistence.migrate_legacy_snapshot(backup_dir / "staged")

    assert _read_value(destination) == "cache copy"
    assert not persistence.canonical_snapshot_path().exists()


def test_existing_canonical_snapshot_takes_precedence_over_legacy(snapshot_paths):
    destination, backup_dir = snapshot_paths
    _write_value(backup_dir / "staged" / "bia-20260101T000000Z.db", "legacy evidence")
    _write_value(persistence.canonical_snapshot_path(), "canonical evidence")
    _write_value(destination, "stale cache")

    persistence.restore_canonical_snapshot(destination)

    assert _read_value(destination) == "canonical evidence"


def test_workflow_serializes_canonical_authority_and_rejects_retrieval_fallback():
    workflow = (Path(__file__).parents[2] / ".github" / "workflows" / "collect.yml").read_text()
    local_sync = (Path(__file__).parents[2] / "scripts" / "pull-ci-snapshot.sh").read_text()

    assert "concurrency:" in workflow
    assert "group: bia-collection-canonical-snapshot" in workflow
    assert "cancel-in-progress: false" in workflow
    assert 'CANONICAL_ARTIFACT_NAME="bia-database-canonical"' in workflow
    assert 'LEGACY_ARTIFACT_NAME="bia-database-backup"' in workflow
    assert "path: backend/data/backups/bia-latest.db" in workflow
    assert "name: bia-database-canonical" in workflow
    assert "name: bia-database-backup" not in workflow
    assert "Install validated canonical database snapshot" in workflow
    assert "Migrate selected legacy database snapshot" in workflow
    assert "persistence.migrate_legacy_snapshot" in workflow
    assert "persistence.restore_canonical_snapshot()" in workflow
    assert "Mark persistence authority ready" in workflow
    assert "if: ${{ always() && steps.persistence_authority.outputs.ready == 'true' }}" in workflow
    assert "Unable to list canonical artifacts; refusing cache fallback." in workflow
    assert "Unable to list legacy artifacts; refusing cache fallback." in workflow
    assert "Canonical artifact retrieval failed; refusing cache fallback." in workflow
    assert "Legacy artifact retrieval failed; refusing cache fallback." in workflow
    assert "No prior database artifact found -- first run; cache/fresh start is allowed" in workflow
    assert "BIA_SNAPSHOT_FORMAT=legacy" in workflow
    assert "BIA_SNAPSHOT_FORMAT=canonical" in workflow
    assert workflow.count("gh run download") == 2
    assert 'gh run download "$CANONICAL_RUN_ID" -n "$CANONICAL_ARTIFACT_NAME"' in workflow
    assert 'gh run download "$LEGACY_RUN_ID" -n "$LEGACY_ARTIFACT_NAME"' in workflow
    assert workflow.index('if [ -n "$CANONICAL_ARTIFACT_RECORD" ]; then') < workflow.index("LEGACY_ARTIFACT_RECORD")
    assert "while IFS= read -r RUN_ID" not in workflow
    assert "--paginate" in workflow
    assert "--slurp" in workflow
    assert "sort_by(.created_at) | reverse" in workflow
    assert "actions/artifacts?per_page=100" in workflow
    assert "actions/workflows/collect.yml/runs?status=completed&per_page=100" not in workflow
    assert "--limit=20" not in workflow
    assert "continue-on-error" not in workflow
    assert "path: backend/data/backups/\n" not in workflow
    assert "bia-database-canonical" in local_sync
    assert "bia-database-backup" not in local_sync
    assert "legacy artifacts are not used for local sync" in local_sync
