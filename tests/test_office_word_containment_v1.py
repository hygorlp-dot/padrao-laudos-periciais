from __future__ import annotations

from contextlib import ExitStack
import json
from pathlib import Path
import sys
import types

import pytest

from tests.opc_word_fixtures import word_package

from scripts.backend_contract.infrastructure import office_pdf, office_word_worker
from scripts.backend_contract.infrastructure.office_pdf import (
    OwnedProcessIdentity,
    WordRenderDeadlines,
    _WindowsJobWordWorker,
    _same_process_identity,
    _terminate_owned_worker,
    _wait_for_worker,
)


def test_worker_rejects_noncanonical_external_target_mode(tmp_path: Path) -> None:
    """A TargetMode Word still honours, spelled with padding to dodge a compare.

    The fixture is a VALID package in every other respect.  It previously
    declared one Override and stored an undeclared .rels part, so the package was
    malformed on a second count and could be refused without the TargetMode rule
    ever being consulted -- the assertion matched "relationship" loosely enough
    that the test looked green either way.  The refusal is now named exactly, so
    a future reordering cannot quietly answer a different question.
    """
    source = tmp_path / "source.docx"
    source.write_bytes(
        word_package(
            '<w:document xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main"><w:body><w:p><w:r>'
            "<w:t>Synthetic</w:t></w:r></w:p></w:body></w:document>",
            parts={
                "word/_rels/document.xml.rels": (
                    '<Relationships xmlns="http://schemas.openxmlformats.org/'
                    'package/2006/relationships"><Relationship Id="rId1" '
                    'Type="template" Target="synthetic-private.png" '
                    'TargetMode=" External "/></Relationships>'
                )
            },
        )
    )

    with pytest.raises(ValueError, match="external Word relationship"):
        office_word_worker._validate_word_source(source, "DOCX")


class _FakeOwnedWorker:
    def __init__(
        self,
        identity: OwnedProcessIdentity,
        *,
        observed: OwnedProcessIdentity | None = None,
        exits: bool = False,
    ) -> None:
        self.identity = identity
        self._observed = observed if observed is not None else identity
        self._exits = exits
        self.terminated = False
        self.closed = False

    def wait(self, _milliseconds: int) -> bool:
        return self._exits

    def observed_identity(self) -> OwnedProcessIdentity | None:
        return self._observed

    def terminate_job(self) -> None:
        self.terminated = True
        self._exits = True

    def wait_contained(self, _milliseconds: int) -> bool:
        return self._exits

    def close(self) -> None:
        self.closed = True


def _identity(*, pid: int = 101, created: str = "creation-a") -> OwnedProcessIdentity:
    return OwnedProcessIdentity(
        pid=pid,
        creation_identity=created,
        image_path="C:/Python/python.exe",
    )


def _clock(values: list[float]):
    iterator = iter(values)
    return lambda: next(iterator)


@pytest.mark.parametrize(
    "phase",
    [
        "WORKER_START",
        "COM_INIT",
        "WORD_PROCESS_START",
        "WORD_COM_BIND",
        "DOCUMENT_OPEN",
        "EXPORT_AS_FIXED_FORMAT",
        "DOCUMENT_CLOSE",
        "WORD_QUIT",
        "WORKER_EXIT",
    ],
)
def test_each_word_phase_timeout_is_bounded_and_terminates_only_owned_job(
    tmp_path: Path, phase: str
) -> None:
    worker = _FakeOwnedWorker(_identity())
    if phase != "WORKER_START":
        for published_phase in office_word_worker._STATUS_PHASES:
            office_word_worker._status(tmp_path, published_phase)
            if published_phase == phase:
                break
    deadlines = WordRenderDeadlines.uniform(1.0)

    with pytest.raises(TimeoutError, match=phase):
        _wait_for_worker(worker, tmp_path, deadlines, clock=_clock([0.0, 0.0, 2.0]))

    assert worker.terminated is True


def test_pid_reuse_or_creation_identity_mismatch_never_authorizes_kill() -> None:
    expected = _identity()
    reused = _identity(created="creation-b")
    same_pid_wrong_image = OwnedProcessIdentity(
        pid=expected.pid,
        creation_identity=expected.creation_identity,
        image_path="C:/Windows/System32/notepad.exe",
    )

    assert not _same_process_identity(expected, reused)
    assert not _same_process_identity(expected, same_pid_wrong_image)

    worker = _FakeOwnedWorker(expected, observed=reused)
    assert _terminate_owned_worker(worker) is False
    assert worker.terminated is False


def test_verified_job_remains_authoritative_when_process_observation_fails() -> None:
    events: list[str] = []
    active = {"count": 1}

    class _Handle:
        def __init__(self, kind: str) -> None:
            self.kind = kind

        def Close(self) -> None:
            events.append(f"{self.kind}-close")

    process = _Handle("process")
    job = _Handle("job")
    win32event = types.SimpleNamespace(
        WAIT_OBJECT_0=0,
        WaitForSingleObject=lambda _process, _milliseconds: 258,
    )

    def _terminate_job(_job, _code) -> None:
        events.append("job-terminate")
        active["count"] = 0

    win32job = types.SimpleNamespace(
        JobObjectBasicAccountingInformation=1,
        QueryInformationJobObject=lambda _job, _kind: {
            "ActiveProcesses": active["count"]
        },
        TerminateJobObject=_terminate_job,
    )
    win32process = types.SimpleNamespace(
        GetProcessTimes=lambda _process: (_ for _ in ()).throw(
            OSError("synthetic observation failure")
        ),
        GetModuleFileNameEx=lambda _process, _module: "C:/Python/python.exe",
    )
    worker = _WindowsJobWordWorker(
        process,
        job,
        _identity(),
        (win32event, win32job, win32process),
    )

    assert _terminate_owned_worker(worker) is True
    worker.close()

    assert events == ["job-terminate", "process-close", "job-close"]


def test_preexisting_user_word_is_not_a_termination_target() -> None:
    user_word = _FakeOwnedWorker(_identity(pid=55, created="user-word"))
    product_worker = _FakeOwnedWorker(_identity(pid=56, created="product-worker"))

    assert _terminate_owned_worker(product_worker) is True
    assert product_worker.terminated is True
    assert user_word.terminated is False


def test_invalid_or_regressing_worker_status_fails_closed(tmp_path: Path) -> None:
    worker = _FakeOwnedWorker(_identity())
    (tmp_path / "status.json").write_text(
        json.dumps(
            {"schemaVersion": "1.0.0", "state": "RUNNING", "phase": "UNKNOWN"}
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="status"):
        _wait_for_worker(
            worker,
            tmp_path,
            WordRenderDeadlines.uniform(1.0),
            clock=_clock([0.0]),
        )

    assert worker.terminated is True


def test_worker_status_with_missing_predecessor_fails_closed(tmp_path: Path) -> None:
    worker = _FakeOwnedWorker(_identity())
    (tmp_path / "status-01-COM_INIT.json").write_text("published", encoding="utf-8")
    (tmp_path / "status-03-WORD_COM_BIND.json").write_text("published", encoding="utf-8")

    with pytest.raises(ValueError, match="status"):
        _wait_for_worker(
            worker,
            tmp_path,
            WordRenderDeadlines.uniform(1.0),
            clock=_clock([0.0]),
        )

    assert worker.terminated is True


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing semantics")
def test_phase_publication_never_replaces_a_snapshot_held_by_parent(
    tmp_path: Path,
) -> None:
    office_word_worker._status(tmp_path, "COM_INIT")
    published = tuple(tmp_path.glob("status*.json"))
    assert len(published) == 1
    assert published[0].name == "status-01-COM_INIT.json"

    with published[0].open("r", encoding="utf-8") as held_snapshot:
        assert json.load(held_snapshot)["phase"] == "COM_INIT"
        office_word_worker._status(tmp_path, "WORD_PROCESS_START")

    assert office_pdf._read_phase(tmp_path) == "WORD_PROCESS_START"


def test_parent_phase_observation_never_reopens_published_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    office_word_worker._status(tmp_path, "COM_INIT")

    def deny_status_read(path: Path, *args, **kwargs):
        if path.name.startswith("status-"):
            raise PermissionError("synthetic Windows sharing violation")
        return original_read_text(path, *args, **kwargs)

    original_read_text = Path.read_text
    monkeypatch.setattr(Path, "read_text", deny_status_read)

    assert office_pdf._read_phase(tmp_path) == "COM_INIT"


def test_status_snapshots_survive_repeated_parent_reads_with_prior_files_open(
    tmp_path: Path,
) -> None:
    for iteration in range(32):
        root = tmp_path / str(iteration)
        root.mkdir()
        with ExitStack() as open_snapshots:
            for index, phase in enumerate(office_word_worker._STATUS_PHASES, 1):
                office_word_worker._status(root, phase)
                snapshot = root / f"status-{index:02d}-{phase}.json"
                open_snapshots.enter_context(snapshot.open("r", encoding="utf-8"))
                assert office_pdf._read_phase(root) == phase


# --- Phase C F-12: skipped phases are not protocol corruption ---


def _publish(root: Path, phases: tuple[tuple[int, str], ...]) -> None:
    for index, phase in phases:
        (root / f"status-{index:02d}-{phase}.json").write_text(
            '{"schemaVersion":"1.0.0","state":"RUNNING","phase":"' + phase + '"}',
            encoding="utf-8",
        )


def test_phases_skipped_by_an_early_failure_are_readable(tmp_path: Path) -> None:
    """RED F-12: a bind failure publishes 1,2,3,8 and read as corruption."""
    _publish(
        tmp_path,
        ((1, "COM_INIT"), (2, "WORD_PROCESS_START"), (3, "WORD_COM_BIND"), (8, "WORKER_EXIT")),
    )

    assert office_pdf._read_phase(tmp_path) == "WORKER_EXIT"


def test_phases_skipped_by_a_document_open_failure_are_readable(tmp_path: Path) -> None:
    _publish(
        tmp_path,
        (
            (1, "COM_INIT"),
            (2, "WORD_PROCESS_START"),
            (3, "WORD_COM_BIND"),
            (4, "DOCUMENT_OPEN"),
            (7, "WORD_QUIT"),
            (8, "WORKER_EXIT"),
        ),
    )

    assert office_pdf._read_phase(tmp_path) == "WORKER_EXIT"


def test_complete_phase_sequence_is_readable(tmp_path: Path) -> None:
    _publish(
        tmp_path,
        (
            (1, "COM_INIT"),
            (2, "WORD_PROCESS_START"),
            (3, "WORD_COM_BIND"),
            (4, "DOCUMENT_OPEN"),
            (5, "EXPORT_AS_FIXED_FORMAT"),
            (6, "DOCUMENT_CLOSE"),
            (7, "WORD_QUIT"),
            (8, "WORKER_EXIT"),
        ),
    )

    assert office_pdf._read_phase(tmp_path) == "WORKER_EXIT"


@pytest.mark.parametrize(
    "phases",
    (
        ((0, "WORKER_START"),),
        ((1, "COM_INIT"), (3, "DOCUMENT_OPEN")),
        ((2, "COM_INIT"),),
        ((1, "COM_INIT"), (9, "WORKER_EXIT")),
        ((1, "SYNTHETIC_PHASE"),),
    ),
    ids=(
        "phase_zero_is_never_published",
        "index_does_not_match_its_phase",
        "phase_published_under_the_wrong_index",
        "index_outside_the_protocol",
        "unknown_phase_name",
    ),
)
def test_malformed_phase_markers_remain_protocol_corruption(
    tmp_path: Path, phases: tuple[tuple[int, str], ...]
) -> None:
    _publish(tmp_path, phases)

    with pytest.raises(ValueError, match="invalid Word worker status"):
        office_pdf._read_phase(tmp_path)


def test_early_failure_diagnosis_does_not_depend_on_polling(tmp_path: Path) -> None:
    """The same cause must produce the same outcome whenever the poll observes it."""
    _publish(
        tmp_path,
        ((1, "COM_INIT"), (2, "WORD_PROCESS_START"), (3, "WORD_COM_BIND"), (8, "WORKER_EXIT")),
    )

    # Observed before the worker handle signals, and observed after it signals:
    # neither path may report a status-protocol violation for an ordinary
    # early failure, so both fall through to the result-payload gate.
    exited = _FakeOwnedWorker(_identity(), exits=True)
    _wait_for_worker(
        exited, tmp_path, WordRenderDeadlines.uniform(1.0), clock=_clock([0.0, 0.0, 0.0])
    )
    assert exited.terminated is False

    assert office_pdf._read_phase(tmp_path) == "WORKER_EXIT"


# --- Phase C F-11: Word is started without add-ins or global templates ---


def test_owned_word_command_line_disables_add_ins_and_global_templates() -> None:
    executable = "C:/Office16/WINWORD.EXE"
    bootstrap = Path("C:/tmp/plp/bootstrap.docx")

    command = office_word_worker._word_command_line(executable, bootstrap)

    assert command.split(" ")[1:4] == ["/a", "/x", "/q"]
    assert command.startswith(chr(34) + executable + chr(34))
    assert command.endswith(chr(34) + str(bootstrap) + chr(34))
