import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier

import pytest

from scripts.backend_contract.application.models import (
    PericiaWorkspace,
    WorkspaceId,
    canonical_payload_json,
    thaw_payload,
)
from scripts.backend_contract.application.ports import (
    PersistenceSchemaError,
    RepositoryConflict,
    RepositoryIntegrityError,
    WorkspaceNotFound,
)
from scripts.backend_contract.infrastructure import sqlite as sqlite_store
from scripts.backend_contract.infrastructure.sqlite import (
    SQLiteApplicationStore,
    SQLiteArtifactRevisionRepository,
    SQLiteWorkspaceRepository,
)


WORKSPACE_1 = "11111111-1111-4111-8111-111111111111"
WORKSPACE_2 = "22222222-2222-4222-8222-222222222222"
REVISION_1 = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
REVISION_2 = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
CREATED_1 = "2026-08-21T12:00:00+00:00"
CREATED_2 = "2026-08-21T12:01:00+00:00"


def workspace(identity=WORKSPACE_1, name="Perícia local", created_at=CREATED_1):
    return PericiaWorkspace(WorkspaceId.parse(identity), name, created_at)


@pytest.fixture
def repository(tmp_path):
    repo = SQLiteApplicationStore(tmp_path / "application.db")
    try:
        yield repo
    finally:
        repo.close()


def test_canonical_payload_json_preserves_meaning_and_does_not_mutate_input():
    payload = {
        "z": "não conclusivo",
        "itens": [3, 1, {"warning": "INCONCLUSIVO", "authority": False}],
        "unknown": {"nested": [True, None]},
    }
    before = deepcopy(payload)
    encoded = canonical_payload_json(payload)
    assert encoded == (
        '{"itens":[3,1,{"authority":false,"warning":"INCONCLUSIVO"}],'
        '"unknown":{"nested":[true,null]},"z":"não conclusivo"}'
    )
    assert json.loads(encoded) == payload
    assert payload == before


@pytest.mark.parametrize("payload", ({"bad": float("nan")}, {1: "bad"}, {"bad": object()}))
def test_canonical_payload_json_rejects_non_json_values(payload):
    with pytest.raises((TypeError, ValueError)):
        canonical_payload_json(payload)


def test_empty_database_migrates_once_and_reopen_is_idempotent(tmp_path):
    path = tmp_path / "application.db"
    SQLiteApplicationStore(path).close()
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        assert tables == {"workspaces", "artifact_revisions"}
    SQLiteApplicationStore(path).close()


def test_future_schema_version_fails_closed(tmp_path):
    path = tmp_path / "future.db"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 2")
    with pytest.raises(PersistenceSchemaError, match="future|futura"):
        SQLiteApplicationStore(path)


def test_malformed_or_extra_current_schema_fails_closed(tmp_path):
    malformed = tmp_path / "malformed.db"
    with sqlite3.connect(malformed) as connection:
        connection.execute("CREATE TABLE workspaces (wrong TEXT)")
        connection.execute("PRAGMA user_version = 1")
    with pytest.raises(PersistenceSchemaError):
        SQLiteApplicationStore(malformed)

    for object_sql in (
        "CREATE TABLE unexpected (value TEXT)",
        "CREATE INDEX unexpected_index ON workspaces(name)",
        "CREATE VIEW unexpected_view AS SELECT * FROM workspaces",
        "CREATE TRIGGER unexpected_trigger AFTER INSERT ON workspaces BEGIN SELECT 1; END",
    ):
        extra = tmp_path / f"extra-{object_sql.split()[1].lower()}.db"
        SQLiteApplicationStore(extra).close()
        with sqlite3.connect(extra) as connection:
            connection.execute(object_sql)
        with pytest.raises(PersistenceSchemaError):
            SQLiteApplicationStore(extra)


def test_failed_migration_rolls_back_schema_and_version(monkeypatch):
    connection = sqlite3.connect(":memory:", isolation_level=None)
    monkeypatch.setattr(
        sqlite_store,
        "MIGRATIONS",
        {1: ("CREATE TABLE partial (value TEXT)", "THIS IS NOT SQL")},
    )
    with pytest.raises(PersistenceSchemaError):
        sqlite_store.migrate(connection)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
    assert connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='partial'"
    ).fetchone() is None
    connection.close()


def test_workspace_create_get_list_and_conflict_are_explicit(repository):
    second = workspace(WORKSPACE_2, "Segunda", CREATED_2)
    first = workspace()
    assert repository.workspaces.create(second) == second
    assert repository.workspaces.create(first) == first
    assert repository.workspaces.get(first.workspace_id) == first
    assert repository.workspaces.get(
        WorkspaceId.parse("33333333-3333-4333-8333-333333333333")
    ) is None
    assert repository.workspaces.list_all() == (first, second)
    with pytest.raises(RepositoryConflict):
        repository.workspaces.create(first)


def test_public_adapters_implement_only_append_only_port_operations():
    workspace_methods = {
        name
        for name in SQLiteWorkspaceRepository.__dict__
        if not name.startswith("_")
    }
    revision_methods = {
        name
        for name in SQLiteArtifactRevisionRepository.__dict__
        if not name.startswith("_")
    }
    assert workspace_methods == {"create", "get", "list_all"}
    assert revision_methods == {"append", "latest", "get_revision", "list_all"}
    assert not ({"update", "delete", "replace"} & (workspace_methods | revision_methods))


def test_revision_round_trip_is_append_only_monotonic_and_exact(repository):
    repository.workspaces.create(workspace())
    payload = {
        "texto": "Ação sem conclusão",
        "ordem": [2, 1],
        "warning": {"code": "INCONCLUSIVO"},
        "authority": {"source": "HUMAN", "granted": False},
        "unknown_future_field": [{"x": 1}],
    }
    before = deepcopy(payload)
    first = repository.revisions.append(
        workspace_id=WorkspaceId.parse(WORKSPACE_1),
        artifact_kind="LAUDO",
        artifact_id="LAU-001",
        revision_id="{aaaaaaaaaaaa4aaa8aaaaaaaaaaaaaaa}",
        created_at=CREATED_1,
        payload=payload,
    )
    payload["ordem"].reverse()
    payload["unknown_future_field"].append("mutated")
    assert first.revision == 1
    assert first.revision_id == REVISION_1
    assert thaw_payload(first.payload) == before
    assert first.checksum_sha256 == hashlib.sha256(
        canonical_payload_json(before).encode("utf-8")
    ).hexdigest()

    second = repository.revisions.append(
        workspace_id=first.workspace_id,
        artifact_kind="LAUDO",
        artifact_id="LAU-001",
        revision_id=REVISION_2,
        created_at=CREATED_2,
        payload={"status": "REVISAO", "ordem": [1, 2]},
    )
    assert second.revision == 2
    assert repository.revisions.latest(first.workspace_id, "LAUDO", "LAU-001") == second
    assert repository.revisions.get_revision(
        first.workspace_id, "LAUDO", "LAU-001", 1
    ) == first
    assert repository.revisions.get_revision(
        first.workspace_id, "LAUDO", "LAU-001", 99
    ) is None
    assert repository.revisions.list_all(
        first.workspace_id, "LAUDO", "LAU-001"
    ) == (first, second)


def test_revision_workspace_isolation_and_missing_workspace(repository):
    repository.workspaces.create(workspace())
    repository.workspaces.create(workspace(WORKSPACE_2, "Segunda", CREATED_2))
    first = repository.revisions.append(
        workspace_id=WorkspaceId.parse(WORKSPACE_1),
        artifact_kind="VISTORIA",
        artifact_id="VIS-001",
        revision_id=REVISION_1,
        created_at=CREATED_1,
        payload={"workspace": 1},
    )
    second = repository.revisions.append(
        workspace_id=WorkspaceId.parse(WORKSPACE_2),
        artifact_kind="VISTORIA",
        artifact_id="VIS-001",
        revision_id=REVISION_2,
        created_at=CREATED_2,
        payload={"workspace": 2},
    )
    assert first.revision == second.revision == 1
    assert repository.revisions.latest(first.workspace_id, "VISTORIA", "VIS-001") == first
    assert repository.revisions.latest(second.workspace_id, "VISTORIA", "VIS-001") == second
    with pytest.raises(WorkspaceNotFound):
        repository.revisions.append(
            workspace_id=WorkspaceId.parse("33333333-3333-4333-8333-333333333333"),
            artifact_kind="VISTORIA",
            artifact_id="VIS-001",
            revision_id="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            created_at=CREATED_1,
            payload={},
        )


def test_failed_append_rolls_back_without_revision_gap(repository):
    repository.workspaces.create(workspace())
    repository.revisions.append(
        workspace_id=WorkspaceId.parse(WORKSPACE_1),
        artifact_kind="A",
        artifact_id="ONE",
        revision_id=REVISION_1,
        created_at=CREATED_1,
        payload={},
    )
    with pytest.raises(RepositoryConflict):
        repository.revisions.append(
            workspace_id=WorkspaceId.parse(WORKSPACE_1),
            artifact_kind="B",
            artifact_id="TWO",
            revision_id=REVISION_1,
            created_at=CREATED_1,
            payload={},
        )
    recovered = repository.revisions.append(
        workspace_id=WorkspaceId.parse(WORKSPACE_1),
        artifact_kind="B",
        artifact_id="TWO",
        revision_id=REVISION_2,
        created_at=CREATED_2,
        payload={},
    )
    assert recovered.revision == 1


def test_canonical_revision_identity_conflicts_across_uuid_spellings(repository):
    repository.workspaces.create(workspace())
    repository.revisions.append(
        workspace_id=WorkspaceId.parse(WORKSPACE_1),
        artifact_kind="A",
        artifact_id="ONE",
        revision_id=REVISION_1,
        created_at=CREATED_1,
        payload={},
    )
    with pytest.raises(RepositoryConflict):
        repository.revisions.append(
            workspace_id=WorkspaceId.parse(WORKSPACE_1),
            artifact_kind="B",
            artifact_id="TWO",
            revision_id="{aaaaaaaaaaaa4aaa8aaaaaaaaaaaaaaa}",
            created_at=CREATED_2,
            payload={},
        )


def test_workspace_and_revision_round_trip_survive_reopen(tmp_path):
    path = tmp_path / "round-trip.db"
    with SQLiteApplicationStore(path) as store:
        expected_workspace = store.workspaces.create(workspace())
        expected_revision = store.revisions.append(
            workspace_id=expected_workspace.workspace_id,
            artifact_kind="LAUDO",
            artifact_id="LAU-001",
            revision_id=REVISION_1,
            created_at=CREATED_1,
            payload={"unicode": "perícia", "ordem": [3, 1, 2]},
        )
    with SQLiteApplicationStore(path) as reopened:
        assert reopened.workspaces.get(expected_workspace.workspace_id) == expected_workspace
        assert reopened.revisions.latest(
            expected_workspace.workspace_id, "LAUDO", "LAU-001"
        ) == expected_revision


def test_payload_corruption_is_detected_on_read(tmp_path):
    path = tmp_path / "corrupt.db"
    repo = SQLiteApplicationStore(path)
    repo.workspaces.create(workspace())
    repo.revisions.append(
        workspace_id=WorkspaceId.parse(WORKSPACE_1),
        artifact_kind="LAUDO",
        artifact_id="LAU-001",
        revision_id=REVISION_1,
        created_at=CREATED_1,
        payload={"intacto": True},
    )
    repo.close()
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE artifact_revisions SET payload_json = ? WHERE revision_id = ?",
            ('{"corrompido":true}', REVISION_1),
        )
    repo = SQLiteApplicationStore(path)
    try:
        with pytest.raises(RepositoryIntegrityError, match="checksum"):
            repo.revisions.latest(
                WorkspaceId.parse(WORKSPACE_1), "LAUDO", "LAU-001"
            )
    finally:
        repo.close()


def test_concurrent_append_allocates_unique_monotonic_revisions(tmp_path):
    path = tmp_path / "concurrent.db"
    setup = SQLiteApplicationStore(path)
    setup.workspaces.create(workspace())
    setup.close()
    repositories = [SQLiteApplicationStore(path), SQLiteApplicationStore(path)]
    barrier = Barrier(2)

    def append(index):
        barrier.wait(timeout=5)
        return repositories[index].revisions.append(
            workspace_id=WorkspaceId.parse(WORKSPACE_1),
            artifact_kind="LAUDO",
            artifact_id="LAU-001",
            revision_id=(REVISION_1, REVISION_2)[index],
            created_at=(CREATED_1, CREATED_2)[index],
            payload={"worker": index},
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            revisions = tuple(executor.map(append, range(2)))
        assert {item.revision for item in revisions} == {1, 2}
        assert repositories[0].revisions.list_all(
            WorkspaceId.parse(WORKSPACE_1), "LAUDO", "LAU-001"
        ) == tuple(sorted(revisions, key=lambda item: item.revision))
    finally:
        for repo in repositories:
            repo.close()
