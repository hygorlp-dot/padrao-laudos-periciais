import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier, Event, Thread

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
    RepositoryError,
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


def test_non_database_file_fails_with_application_schema_error(tmp_path):
    path = tmp_path / "not-a-database.db"
    path.write_bytes(b"not a SQLite database")
    with pytest.raises(PersistenceSchemaError) as raised:
        SQLiteApplicationStore(path)
    assert not isinstance(raised.value, sqlite3.Error)


@pytest.mark.parametrize(
    "setup_error",
    (PersistenceSchemaError("schema"), sqlite3.OperationalError("setup")),
)
def test_setup_error_remains_application_error_when_cleanup_also_fails(
    monkeypatch, setup_error
):
    class FailingCloseConnection:
        row_factory = None

        def execute(self, _statement):
            return None

        def close(self):
            raise sqlite3.OperationalError("close")

    monkeypatch.setattr(sqlite_store.sqlite3, "connect", lambda *args, **kwargs: FailingCloseConnection())

    def fail_setup(_connection):
        raise setup_error

    monkeypatch.setattr(sqlite_store, "migrate", fail_setup)
    expected = PersistenceSchemaError if isinstance(setup_error, PersistenceSchemaError) else RepositoryError
    with pytest.raises(expected) as raised:
        SQLiteApplicationStore("safe.db")
    assert not isinstance(raised.value, sqlite3.Error)


def test_state_guard_bootstrap_error_closes_and_maps_connection(monkeypatch):
    class FailingGuardConnection:
        row_factory = None
        closed = False

        def execute(self, statement):
            if statement == "PRAGMA foreign_keys = ON":
                return None
            raise sqlite3.OperationalError("guard-bootstrap")

        def close(self):
            self.closed = True

    connection = FailingGuardConnection()
    monkeypatch.setattr(sqlite_store.sqlite3, "connect", lambda *args, **kwargs: connection)
    monkeypatch.setattr(
        sqlite_store,
        "migrate",
        lambda candidate: sqlite_store._database_state_token(candidate),
    )
    with pytest.raises(RepositoryError) as raised:
        SQLiteApplicationStore("safe.db")
    assert not isinstance(raised.value, sqlite3.Error)
    assert connection.closed


def test_post_migration_commit_is_not_absorbed_by_initial_guard(monkeypatch, tmp_path):
    path = tmp_path / "initial-token-race.db"
    with SQLiteApplicationStore(path) as store:
        store.workspaces.create(workspace())
        for revision_id, created_at in (
            (REVISION_1, CREATED_1),
            (REVISION_2, CREATED_2),
        ):
            store.revisions.append(
                workspace_id=WorkspaceId.parse(WORKSPACE_1),
                artifact_kind="LAUDO",
                artifact_id="LAU-001",
                revision_id=revision_id,
                created_at=created_at,
                payload={},
            )
    original_migrate = sqlite_store.migrate

    def migrate_then_corrupt(connection):
        trusted_token = original_migrate(connection)
        with sqlite3.connect(path) as external:
            external.execute(
                "DELETE FROM artifact_revisions WHERE revision_id = ?",
                (REVISION_1,),
            )
        return trusted_token

    monkeypatch.setattr(sqlite_store, "migrate", migrate_then_corrupt)
    with SQLiteApplicationStore(path) as store:
        with pytest.raises(RepositoryIntegrityError, match="sequência|histórico"):
            store.revisions.list_all(
                WorkspaceId.parse(WORKSPACE_1), "LAUDO", "LAU-001"
            )


@pytest.mark.parametrize("target", ("", "   ", ":memory:", "file::memory:"))
def test_durable_store_rejects_ephemeral_or_ambiguous_targets(target):
    with pytest.raises(RepositoryError):
        SQLiteApplicationStore(target)


@pytest.mark.parametrize(
    "target",
    (
        "NUL:",
        "COM1:",
        "CON ",
        "NUL .txt",
        "COM1 .db",
        "CONIN$",
        "CONOUT$",
        "COM¹",
        "LPT¹",
        "AUX .sqlite",
        r"\\.\NUL",
        r"C:\tmp\NUL::$DATA",
        r"\\server\share\application.db",
        "//server/share/application.db",
        r"C:relative.db",
        "application.db ",
        "application.db.",
        r"folder.\application.db",
        "invalid\ud800.db",
    ),
)
def test_unsafe_windows_targets_are_rejected_before_sqlite_open(monkeypatch, target):
    opened = False

    def unexpected_connect(*args, **kwargs):
        nonlocal opened
        opened = True
        raise AssertionError("sqlite3.connect não deve receber device path")

    monkeypatch.setattr(sqlite_store.sqlite3, "connect", unexpected_connect)
    with pytest.raises(RepositoryError):
        SQLiteApplicationStore(target)
    assert not opened


def test_workspace_name_rejects_unpaired_unicode_surrogate():
    with pytest.raises(ValueError, match="Unicode"):
        workspace(name="\ud800")


@pytest.mark.parametrize(
    ("artifact_kind", "artifact_id"),
    (("\ud800", "LAU-001"), ("LAUDO", "\ud800")),
)
def test_artifact_keys_reject_unpaired_unicode_surrogate(
    repository, artifact_kind, artifact_id
):
    repository.workspaces.create(workspace())
    with pytest.raises(ValueError, match="Unicode"):
        repository.revisions.append(
            workspace_id=WorkspaceId.parse(WORKSPACE_1),
            artifact_kind=artifact_kind,
            artifact_id=artifact_id,
            revision_id=REVISION_1,
            created_at=CREATED_1,
            payload={},
        )


def test_context_manager_preserves_body_exception_when_close_also_fails(monkeypatch, tmp_path):
    store = SQLiteApplicationStore(tmp_path / "cleanup.db")

    def fail_close():
        raise RepositoryError("cleanup-failed")

    monkeypatch.setattr(store, "close", fail_close)
    with pytest.raises(ValueError, match="body-failed"):
        with store:
            raise ValueError("body-failed")


@pytest.mark.parametrize(
    "error_code",
    (sqlite3.SQLITE_IOERR, sqlite3.SQLITE_FULL, sqlite3.SQLITE_READONLY),
)
def test_migration_operational_failures_are_not_schema_errors(error_code):
    class ForcedOperationalError(sqlite3.OperationalError):
        sqlite_errorcode = error_code

    class FailingConnection:
        def execute(self, _statement):
            raise ForcedOperationalError("operational")

        def rollback(self):
            return None

    with pytest.raises(RepositoryError) as raised:
        sqlite_store.migrate(FailingConnection())
    assert not isinstance(raised.value, PersistenceSchemaError)
    assert not isinstance(raised.value, sqlite3.Error)


def test_store_open_lock_is_operational_repository_error(tmp_path):
    path = tmp_path / "open-locked.db"
    owner = SQLiteApplicationStore(path)
    owner._connection.execute("BEGIN EXCLUSIVE")
    try:
        with pytest.raises(RepositoryError) as raised:
            SQLiteApplicationStore(path, timeout=0.01)
        assert not isinstance(raised.value, PersistenceSchemaError)
        assert not isinstance(raised.value, sqlite3.Error)
    finally:
        owner._connection.rollback()
        owner.close()


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


def test_schema_mutation_after_open_fails_closed_before_write(tmp_path):
    store = SQLiteApplicationStore(tmp_path / "runtime-schema-tamper.db")
    try:
        store._connection.execute(
            "CREATE TRIGGER tamper AFTER INSERT ON workspaces "
            "BEGIN UPDATE workspaces SET name = 'tampered'; END"
        )
        with pytest.raises(PersistenceSchemaError):
            store.workspaces.create(workspace(name="expected"))
        assert store._connection.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0] == 0
    finally:
        store.close()


def test_external_data_mutation_invalidates_trusted_state_before_read(tmp_path):
    path = tmp_path / "external-corruption.db"
    store = SQLiteApplicationStore(path)
    try:
        store.workspaces.create(workspace())
        with sqlite3.connect(path) as external:
            external.execute("PRAGMA ignore_check_constraints = ON")
            external.execute(
                "UPDATE workspaces SET name = ? WHERE workspace_id = ?",
                (sqlite3.Binary(b"corrupt"), WORKSPACE_1),
            )
        with pytest.raises(RepositoryIntegrityError):
            store.workspaces.list_all()
    finally:
        store.close()


def test_trusted_own_writes_do_not_repeat_full_database_scan(monkeypatch, tmp_path):
    store = SQLiteApplicationStore(tmp_path / "linear-writes.db")
    scans = 0
    original_validate = sqlite_store._validate_database_state

    def count_scan(connection):
        nonlocal scans
        scans += 1
        return original_validate(connection)

    monkeypatch.setattr(sqlite_store, "_validate_database_state", count_scan)
    try:
        store.workspaces.create(workspace())
        for index in range(10):
            store.revisions.append(
                workspace_id=WorkspaceId.parse(WORKSPACE_1),
                artifact_kind="LAUDO",
                artifact_id="LAU-001",
                revision_id=f"{index + 1:08x}-0000-4000-8000-000000000000",
                created_at=CREATED_1,
                payload={"index": index},
            )
        assert len(
            store.revisions.list_all(
                WorkspaceId.parse(WORKSPACE_1), "LAUDO", "LAU-001"
            )
        ) == 10
        assert scans == 0
    finally:
        store.close()


def test_validation_token_cannot_absorb_same_connection_schema_race(
    monkeypatch, tmp_path
):
    path = tmp_path / "validation-token-race.db"
    store = SQLiteApplicationStore(path)
    store.workspaces.create(workspace())
    with sqlite3.connect(path) as external:
        external.execute(
            "UPDATE workspaces SET name = ? WHERE workspace_id = ?",
            ("valid external change", WORKSPACE_1),
        )
    original_validate = sqlite_store._validate_database_state

    def validate_then_mutate_schema(connection):
        original_validate(connection)
        connection.execute(
            "CREATE TRIGGER unvalidated AFTER INSERT ON workspaces BEGIN SELECT 1; END"
        )

    monkeypatch.setattr(sqlite_store, "_validate_database_state", validate_then_mutate_schema)
    try:
        with pytest.raises(RepositoryIntegrityError, match="validação|estado"):
            store.workspaces.list_all()
    finally:
        store.close()


def test_external_commit_between_write_and_token_acceptance_is_not_trusted(
    monkeypatch, tmp_path
):
    path = tmp_path / "write-token-race.db"
    store = SQLiteApplicationStore(path)
    store.workspaces.create(workspace())
    external = sqlite3.connect(path, timeout=2, check_same_thread=False)
    external.execute("PRAGMA ignore_check_constraints = ON")
    ready = Event()
    committed = Event()

    def corrupt_after_write_unlock():
        ready.wait(timeout=2)
        external.execute(
            "UPDATE workspaces SET name = ? WHERE workspace_id = ?",
            (sqlite3.Binary(b"corrupt"), WORKSPACE_1),
        )
        external.commit()
        committed.set()

    thread = Thread(target=corrupt_after_write_unlock)
    thread.start()
    guard = store.workspaces._state_guard
    original_accept = guard.accept_current

    def race_acceptance():
        ready.set()
        committed.wait(timeout=0.2)
        original_accept()

    monkeypatch.setattr(guard, "accept_current", race_acceptance)
    try:
        store.workspaces.create(workspace(WORKSPACE_2, "Second", CREATED_2))
        thread.join(timeout=3)
        assert committed.is_set()
        with pytest.raises(RepositoryIntegrityError):
            store.workspaces.get(
                WorkspaceId.parse("33333333-3333-4333-8333-333333333333")
            )
    finally:
        thread.join(timeout=3)
        external.close()
        store.close()


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


def test_migration_reads_version_only_after_acquiring_write_lock(tmp_path):
    path = tmp_path / "migration-race.db"
    blocker = sqlite3.connect(path, isolation_level=None)
    candidate = sqlite3.connect(
        path, isolation_level=None, check_same_thread=False, timeout=5
    )
    version_read = Event()
    candidate.set_trace_callback(
        lambda statement: version_read.set()
        if statement.strip().upper() == "PRAGMA USER_VERSION"
        else None
    )
    blocker.execute("BEGIN IMMEDIATE")
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            migration = executor.submit(sqlite_store.migrate, candidate)
            assert not version_read.wait(timeout=0.2)
            for statement in sqlite_store.MIGRATIONS[1]:
                blocker.execute(statement)
            blocker.execute("PRAGMA user_version = 1")
            blocker.commit()
            migration.result(timeout=5)
            assert version_read.is_set()
    finally:
        if blocker.in_transaction:
            blocker.rollback()
        blocker.close()
        candidate.close()


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
        for name in dir(SQLiteWorkspaceRepository)
        if not name.startswith("_")
    }
    revision_methods = {
        name
        for name in dir(SQLiteArtifactRevisionRepository)
        if not name.startswith("_")
    }
    assert workspace_methods == {"create", "get", "list_all"}
    assert revision_methods == {
        "append",
        "append_if_latest",
        "latest",
        "get_revision",
        "list_all",
    }
    assert not ({"update", "delete", "replace"} & (workspace_methods | revision_methods))


@pytest.mark.parametrize(
    ("operation", "arguments"),
    (
        ("latest", (WORKSPACE_1, "LAUDO", "LAU-001")),
        ("latest", (WorkspaceId.parse(WORKSPACE_1), "", "LAU-001")),
        ("latest", (WorkspaceId.parse(WORKSPACE_1), "LAUDO", "")),
        ("get_revision", (WorkspaceId.parse(WORKSPACE_1), "LAUDO", "LAU-001", 0)),
        ("get_revision", (WorkspaceId.parse(WORKSPACE_1), "LAUDO", "LAU-001", True)),
    ),
)
def test_revision_reads_reject_invalid_keys(repository, operation, arguments):
    with pytest.raises((TypeError, ValueError)):
        getattr(repository.revisions, operation)(*arguments)


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


def test_detectable_append_only_revision_gap_fails_closed_on_open(tmp_path):
    path = tmp_path / "revision-gap.db"
    with SQLiteApplicationStore(path) as store:
        store.workspaces.create(workspace())
        for revision_id, created_at in (
            (REVISION_1, CREATED_1),
            (REVISION_2, CREATED_2),
        ):
            store.revisions.append(
                workspace_id=WorkspaceId.parse(WORKSPACE_1),
                artifact_kind="LAUDO",
                artifact_id="LAU-001",
                revision_id=revision_id,
                created_at=created_at,
                payload={},
            )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "DELETE FROM artifact_revisions WHERE revision_id = ?", (REVISION_1,)
        )
    with pytest.raises(RepositoryIntegrityError, match="sequência|histórico"):
        SQLiteApplicationStore(path)


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


def test_sqlite_lock_errors_do_not_leak_across_application_ports(tmp_path):
    path = tmp_path / "locked.db"
    owner = SQLiteApplicationStore(path)
    contender = SQLiteApplicationStore(path, timeout=0.01)
    try:
        owner._connection.execute("BEGIN EXCLUSIVE")
        with pytest.raises(RepositoryError) as write_error:
            contender.workspaces.create(workspace())
        assert not isinstance(write_error.value, sqlite3.Error)
        with pytest.raises(RepositoryError) as read_error:
            contender.workspaces.get(WorkspaceId.parse(WORKSPACE_1))
        assert not isinstance(read_error.value, sqlite3.Error)
    finally:
        owner._connection.rollback()
        contender.close()
        owner.close()


def test_append_uses_one_payload_snapshot_for_storage_and_return(monkeypatch, repository):
    repository.workspaces.create(workspace())
    payload = {"items": [1]}
    original_encoder = sqlite_store.canonical_payload_json

    def encode_then_mutate(value):
        encoded = original_encoder(value)
        value["items"].append(2)
        return encoded

    monkeypatch.setattr(sqlite_store, "canonical_payload_json", encode_then_mutate)
    revision = repository.revisions.append(
        workspace_id=WorkspaceId.parse(WORKSPACE_1),
        artifact_kind="LAUDO",
        artifact_id="LAU-001",
        revision_id=REVISION_1,
        created_at=CREATED_1,
        payload=payload,
    )
    assert thaw_payload(revision.payload) == {"items": [1]}


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


def test_database_constraints_reject_noncanonical_uuid_storage(tmp_path):
    path = tmp_path / "canonical-identities.db"
    SQLiteApplicationStore(path).close()
    with sqlite3.connect(path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO workspaces (workspace_id, name, created_at) VALUES (?, ?, ?)",
                ("AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA", "Uppercase", CREATED_1),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO workspaces (workspace_id, name, created_at) VALUES (?, ?, ?)",
                ("11111111-1111-4111-8111-11111111111-", "Malformed", CREATED_1),
            )
        connection.execute(
            "INSERT INTO workspaces (workspace_id, name, created_at) VALUES (?, ?, ?)",
            (WORKSPACE_1, "Canonical", CREATED_1),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO artifact_revisions "
                "(workspace_id, artifact_kind, artifact_id, revision_id, revision, "
                "created_at, checksum_sha256, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    WORKSPACE_1,
                    "LAUDO",
                    "LAU-001",
                    REVISION_1.upper(),
                    1,
                    CREATED_1,
                    hashlib.sha256(b"{}").hexdigest(),
                    "{}",
                ),
            )


def test_noncanonical_uuid_corruption_fails_closed_on_read(tmp_path):
    path = tmp_path / "identity-corruption.db"
    store = SQLiteApplicationStore(path)
    store.workspaces.create(workspace())
    store.revisions.append(
        workspace_id=WorkspaceId.parse(WORKSPACE_1),
        artifact_kind="LAUDO",
        artifact_id="LAU-001",
        revision_id=REVISION_1,
        created_at=CREATED_1,
        payload={},
    )
    store.close()
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute(
            "UPDATE artifact_revisions SET revision_id = upper(revision_id)"
        )
    with pytest.raises(RepositoryIntegrityError, match="identidade|UUID"):
        SQLiteApplicationStore(path)


def test_noncanonical_workspace_uuid_corruption_fails_closed_on_read(tmp_path):
    path = tmp_path / "workspace-identity-corruption.db"
    canonical = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
    store = SQLiteApplicationStore(path)
    store.workspaces.create(workspace(canonical))
    store.close()
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute("UPDATE workspaces SET workspace_id = upper(workspace_id)")
    with pytest.raises(RepositoryIntegrityError, match="identidade|UUID"):
        SQLiteApplicationStore(path)


@pytest.mark.parametrize(
    ("table", "column"),
    (
        ("workspaces", "name"),
        ("workspaces", "created_at"),
        ("artifact_revisions", "artifact_kind"),
        ("artifact_revisions", "artifact_id"),
        ("artifact_revisions", "created_at"),
        ("artifact_revisions", "checksum_sha256"),
        ("artifact_revisions", "payload_json"),
    ),
)
def test_non_text_persisted_fields_fail_closed_on_open(tmp_path, table, column):
    path = tmp_path / f"non-text-{table}-{column}.db"
    with SQLiteApplicationStore(path) as store:
        store.workspaces.create(workspace())
        store.revisions.append(
            workspace_id=WorkspaceId.parse(WORKSPACE_1),
            artifact_kind="LAUDO",
            artifact_id="LAU-001",
            revision_id=REVISION_1,
            created_at=CREATED_1,
            payload={},
        )
    key_column = "workspace_id" if table == "workspaces" else "revision_id"
    key_value = WORKSPACE_1 if table == "workspaces" else REVISION_1
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute(
            f"UPDATE {table} SET {column} = ? WHERE {key_column} = ?",
            (sqlite3.Binary(b"corrupt"), key_value),
        )
    with pytest.raises(RepositoryIntegrityError):
        SQLiteApplicationStore(path)


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
    with pytest.raises(RepositoryIntegrityError, match="checksum"):
        SQLiteApplicationStore(path)


def test_excessively_deep_persisted_json_is_explicit_integrity_error(tmp_path):
    path = tmp_path / "deep-corrupt.db"
    store = SQLiteApplicationStore(path)
    store.workspaces.create(workspace())
    store.close()
    payload_json = "[" * 1500 + "0" + "]" * 1500
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO artifact_revisions "
            "(workspace_id, artifact_kind, artifact_id, revision_id, revision, "
            "created_at, checksum_sha256, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                WORKSPACE_1,
                "LAUDO",
                "LAU-001",
                REVISION_1,
                1,
                CREATED_1,
                hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
                payload_json,
            ),
        )
    with pytest.raises(RepositoryIntegrityError):
        SQLiteApplicationStore(path)


def test_excessively_deep_append_is_explicit_and_rolls_back(repository):
    repository.workspaces.create(workspace())
    payload = 0
    for _ in range(1500):
        payload = [payload]
    with pytest.raises(ValueError, match="profundidade"):
        repository.revisions.append(
            workspace_id=WorkspaceId.parse(WORKSPACE_1),
            artifact_kind="LAUDO",
            artifact_id="LAU-001",
            revision_id=REVISION_1,
            created_at=CREATED_1,
            payload=payload,
        )
    recovered = repository.revisions.append(
        workspace_id=WorkspaceId.parse(WORKSPACE_1),
        artifact_kind="LAUDO",
        artifact_id="LAU-001",
        revision_id=REVISION_2,
        created_at=CREATED_2,
        payload={},
    )
    assert recovered.revision == 1


def test_unpaired_unicode_surrogate_is_rejected_before_append(repository):
    repository.workspaces.create(workspace())
    with pytest.raises(ValueError, match="Unicode"):
        repository.revisions.append(
            workspace_id=WorkspaceId.parse(WORKSPACE_1),
            artifact_kind="LAUDO",
            artifact_id="LAU-001",
            revision_id=REVISION_1,
            created_at=CREATED_1,
            payload={"invalid": "\ud800"},
        )
    assert repository.revisions.list_all(
        WorkspaceId.parse(WORKSPACE_1), "LAUDO", "LAU-001"
    ) == ()


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
