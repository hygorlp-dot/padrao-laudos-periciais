from __future__ import annotations

import json
from pathlib import Path
import types

import pytest

from scripts.backend_contract.infrastructure.office_pdf import (
    OwnedProcessIdentity,
    WordRenderDeadlines,
    _WindowsJobWordWorker,
    _same_process_identity,
    _terminate_owned_worker,
    _wait_for_worker,
)


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
        (tmp_path / "status.json").write_text(
            json.dumps({"schemaVersion": "1.0.0", "state": "RUNNING", "phase": phase}),
            encoding="utf-8",
        )
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
