from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID

import pytest

from scripts.backend_contract.application.models import (
    ArtifactRevision,
    PericiaWorkspace,
    WorkspaceId,
    thaw_payload,
)
from scripts.backend_contract.application.ports import (
    ArtifactRevisionNotFound,
    RepositoryError,
    WorkspaceNotFound,
)
from scripts.backend_contract.application.services import (
    AppendArtifactRevision,
    CreateWorkspace,
    GetArtifactRevision,
    GetLatestArtifact,
    GetWorkspace,
    ListArtifactRevisions,
    ListWorkspaces,
)
from scripts.backend_contract.infrastructure.sqlite import SQLiteApplicationStore


WORKSPACE_UUID = UUID("11111111-1111-4111-8111-111111111111")
REVISION_UUID = UUID("22222222-2222-4222-8222-222222222222")
NOW = datetime(2026, 8, 21, 12, 30, tzinfo=UTC)


class FixedClock:
    def __init__(self, value=NOW):
        self.value = value
        self.calls = 0

    def now(self):
        self.calls += 1
        return self.value


class FixedIdGenerator:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def new_uuid(self):
        self.calls += 1
        return self.value


class WorkspaceRepositoryFake:
    def __init__(self, records=()):
        self.records = list(records)
        self.created = []

    def create(self, workspace):
        self.created.append(workspace)
        self.records.append(workspace)
        return workspace

    def get(self, workspace_id):
        return next(
            (record for record in self.records if record.workspace_id == workspace_id),
            None,
        )

    def list_all(self):
        return tuple(self.records)


class RevisionRepositoryFake:
    def __init__(self, records=(), *, mutate_received_payload=False):
        self.records = list(records)
        self.appended = []
        self.mutate_received_payload = mutate_received_payload

    def append(self, **values):
        self.appended.append(values)
        payload = values["payload"]
        if self.mutate_received_payload:
            payload["nested"]["items"].append("repository mutation")
        record = ArtifactRevision(
            workspace_id=values["workspace_id"],
            artifact_kind=values["artifact_kind"],
            artifact_id=values["artifact_id"],
            revision_id=values["revision_id"],
            revision=len(self.records) + 1,
            created_at=values["created_at"],
            checksum_sha256="a" * 64,
            payload=payload,
        )
        self.records.append(record)
        return record

    def latest(self, workspace_id, artifact_kind, artifact_id):
        matches = self._matches(workspace_id, artifact_kind, artifact_id)
        return matches[-1] if matches else None

    def get_revision(self, workspace_id, artifact_kind, artifact_id, revision):
        return next(
            (
                record
                for record in self._matches(workspace_id, artifact_kind, artifact_id)
                if record.revision == revision
            ),
            None,
        )

    def list_all(self, workspace_id, artifact_kind, artifact_id):
        return tuple(self._matches(workspace_id, artifact_kind, artifact_id))

    def _matches(self, workspace_id, artifact_kind, artifact_id):
        return [
            record
            for record in self.records
            if record.workspace_id == workspace_id
            and record.artifact_kind == artifact_kind
            and record.artifact_id == artifact_id
        ]


def workspace():
    return PericiaWorkspace(
        WorkspaceId(WORKSPACE_UUID),
        "Perícia sintética",
        NOW.isoformat(),
    )


def revision(number=1):
    return ArtifactRevision(
        workspace_id=WorkspaceId(WORKSPACE_UUID),
        artifact_kind="LAUDO",
        artifact_id="LAU-001",
        revision_id=str(REVISION_UUID),
        revision=number,
        created_at=NOW.isoformat(),
        checksum_sha256="a" * 64,
        payload={"status": "INCONCLUSIVO", "revision": number},
    )


def test_create_workspace_uses_injected_id_and_clock_once():
    repository = WorkspaceRepositoryFake()
    clock = FixedClock()
    ids = FixedIdGenerator(WORKSPACE_UUID)

    result = CreateWorkspace(repository, clock, ids).execute("Perícia sintética")

    assert result == workspace()
    assert repository.created == [result]
    assert clock.calls == 1
    assert ids.calls == 1


@pytest.mark.parametrize(
    ("clock_value", "id_value"),
    (
        ("2026-08-21T12:30:00+00:00", WORKSPACE_UUID),
        (datetime(2026, 8, 21, 12, 30), WORKSPACE_UUID),
        (NOW, str(WORKSPACE_UUID)),
    ),
)
def test_create_workspace_rejects_invalid_generator_contracts_before_write(
    clock_value, id_value
):
    repository = WorkspaceRepositoryFake()
    with pytest.raises((TypeError, ValueError)):
        CreateWorkspace(
            repository,
            FixedClock(clock_value),
            FixedIdGenerator(id_value),
        ).execute("Perícia sintética")
    assert repository.created == []


def test_get_and_list_workspaces_expose_explicit_results():
    record = workspace()
    repository = WorkspaceRepositoryFake([record])

    assert GetWorkspace(repository).execute(record.workspace_id) is record
    assert ListWorkspaces(repository).execute() == (record,)
    assert ListWorkspaces(WorkspaceRepositoryFake()).execute() == ()


def test_get_latest_artifact_raises_explicit_not_found_error():
    missing = WorkspaceId(WORKSPACE_UUID)
    with pytest.raises(ArtifactRevisionNotFound) as raised:
        GetLatestArtifact(RevisionRepositoryFake()).execute(missing, "LAUDO", "LAU-001")
    assert "LAUDO" in str(raised.value)


def test_append_revision_uses_injected_metadata_and_preserves_caller_input():
    payload = {"status": "INCONCLUSIVO", "nested": {"items": [2, 1]}}
    before = deepcopy(payload)
    repository = RevisionRepositoryFake(mutate_received_payload=True)
    clock = FixedClock()
    ids = FixedIdGenerator(REVISION_UUID)

    result = AppendArtifactRevision(repository, clock, ids).execute(
        workspace_id=WorkspaceId(WORKSPACE_UUID),
        artifact_kind="LAUDO",
        artifact_id="LAU-001",
        payload=payload,
    )

    assert payload == before
    assert repository.appended[0]["revision_id"] == str(REVISION_UUID)
    assert repository.appended[0]["created_at"] == NOW.isoformat()
    assert thaw_payload(result.payload)["nested"]["items"] == [2, 1, "repository mutation"]
    assert clock.calls == 1
    assert ids.calls == 1


def test_append_revision_rejects_invalid_generator_contracts_before_write():
    repository = RevisionRepositoryFake()
    with pytest.raises(TypeError):
        AppendArtifactRevision(
            repository,
            FixedClock(NOW),
            FixedIdGenerator(str(REVISION_UUID)),
        ).execute(
            workspace_id=WorkspaceId(WORKSPACE_UUID),
            artifact_kind="LAUDO",
            artifact_id="LAU-001",
            payload={},
        )
    assert repository.appended == []


def test_artifact_read_services_return_latest_exact_and_stable_list():
    first = revision(1)
    second = ArtifactRevision(
        workspace_id=first.workspace_id,
        artifact_kind=first.artifact_kind,
        artifact_id=first.artifact_id,
        revision_id="33333333-3333-4333-8333-333333333333",
        revision=2,
        created_at=NOW.isoformat(),
        checksum_sha256="b" * 64,
        payload={"revision": 2},
    )
    repository = RevisionRepositoryFake([first, second])

    assert GetLatestArtifact(repository).execute(
        first.workspace_id, "LAUDO", "LAU-001"
    ) is second
    assert GetArtifactRevision(repository).execute(
        first.workspace_id, "LAUDO", "LAU-001", 1
    ) is first
    assert ListArtifactRevisions(repository).execute(
        first.workspace_id, "LAUDO", "LAU-001"
    ) == (first, second)


def test_missing_artifact_reads_raise_explicit_not_found_error():
    repository = RevisionRepositoryFake()
    workspace_id = WorkspaceId(WORKSPACE_UUID)

    with pytest.raises(ArtifactRevisionNotFound):
        GetLatestArtifact(repository).execute(workspace_id, "LAUDO", "LAU-001")
    with pytest.raises(ArtifactRevisionNotFound):
        GetArtifactRevision(repository).execute(
            workspace_id, "LAUDO", "LAU-001", 4
        )
    assert ListArtifactRevisions(repository).execute(
        workspace_id, "LAUDO", "LAU-001"
    ) == ()


@pytest.mark.parametrize(
    "service_call",
    (
        lambda repository: CreateWorkspace(
            repository, FixedClock(), FixedIdGenerator(WORKSPACE_UUID)
        ).execute("Perícia sintética"),
        lambda repository: GetWorkspace(repository).execute(
            WorkspaceId(WORKSPACE_UUID)
        ),
        lambda repository: ListWorkspaces(repository).execute(),
    ),
)
def test_workspace_services_preserve_repository_errors(service_call):
    expected = RepositoryError("repository unavailable")

    class FailingRepository:
        def __getattr__(self, _name):
            def fail(*_args, **_kwargs):
                raise expected

            return fail

    with pytest.raises(RepositoryError) as raised:
        service_call(FailingRepository())
    assert raised.value is expected


@pytest.mark.parametrize(
    "service_call",
    (
        lambda repository: AppendArtifactRevision(
            repository, FixedClock(), FixedIdGenerator(REVISION_UUID)
        ).execute(
            workspace_id=WorkspaceId(WORKSPACE_UUID),
            artifact_kind="LAUDO",
            artifact_id="LAU-001",
            payload={},
        ),
        lambda repository: GetLatestArtifact(repository).execute(
            WorkspaceId(WORKSPACE_UUID), "LAUDO", "LAU-001"
        ),
        lambda repository: GetArtifactRevision(repository).execute(
            WorkspaceId(WORKSPACE_UUID), "LAUDO", "LAU-001", 1
        ),
        lambda repository: ListArtifactRevisions(repository).execute(
            WorkspaceId(WORKSPACE_UUID), "LAUDO", "LAU-001"
        ),
    ),
)
def test_artifact_services_preserve_repository_errors(service_call):
    expected = RepositoryError("repository unavailable")

    class FailingRepository:
        def __getattr__(self, _name):
            def fail(*_args, **_kwargs):
                raise expected

            return fail

    with pytest.raises(RepositoryError) as raised:
        service_call(FailingRepository())
    assert raised.value is expected


def test_get_workspace_raises_workspace_not_found_not_artifact_error():
    missing = WorkspaceId(WORKSPACE_UUID)
    with pytest.raises(WorkspaceNotFound) as raised:
        GetWorkspace(WorkspaceRepositoryFake()).execute(missing)
    assert str(missing) in str(raised.value)


def test_services_compose_with_local_store_without_leaking_infrastructure(tmp_path):
    database = tmp_path / "application-services.db"
    with SQLiteApplicationStore(database) as store:
        created = CreateWorkspace(
            store.workspaces,
            FixedClock(),
            FixedIdGenerator(WORKSPACE_UUID),
        ).execute("Perícia sintética")
        appended = AppendArtifactRevision(
            store.revisions,
            FixedClock(),
            FixedIdGenerator(REVISION_UUID),
        ).execute(
            workspace_id=created.workspace_id,
            artifact_kind="LAUDO",
            artifact_id="LAU-001",
            payload={"status": "INCONCLUSIVO"},
        )

        assert GetWorkspace(store.workspaces).execute(created.workspace_id) == created
        assert ListWorkspaces(store.workspaces).execute() == (created,)
        assert GetLatestArtifact(store.revisions).execute(
            created.workspace_id, "LAUDO", "LAU-001"
        ) == appended
        assert GetArtifactRevision(store.revisions).execute(
            created.workspace_id, "LAUDO", "LAU-001", 1
        ) == appended
        assert ListArtifactRevisions(store.revisions).execute(
            created.workspace_id, "LAUDO", "LAU-001"
        ) == (appended,)
