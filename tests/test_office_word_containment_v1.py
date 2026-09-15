from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.backend_contract.infrastructure.office_pdf import (
    OwnedProcessIdentity,
    WordRenderDeadlines,
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
