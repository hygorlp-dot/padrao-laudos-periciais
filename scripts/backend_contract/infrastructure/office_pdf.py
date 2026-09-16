"""Bounded, local Microsoft Word Desktop PDF conversion.

The only process this module can create is the sibling Word render worker,
using the current Python executable and a product-owned Windows Job Object.
No command, executable, argv, shell or COM operation is accepted from callers.
"""

from __future__ import annotations

from contextlib import contextmanager
import ctypes
from dataclasses import dataclass
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
from typing import Callable, Protocol
from uuid import uuid4

from .office_word_worker import RENDER_OPERATION


_SCHEMA_VERSION = "1.0.0"
_PHASES = (
    "WORKER_START",
    "COM_INIT",
    "WORD_PROCESS_START",
    "WORD_COM_BIND",
    "DOCUMENT_OPEN",
    "EXPORT_AS_FIXED_FORMAT",
    "DOCUMENT_CLOSE",
    "WORD_QUIT",
    "WORKER_EXIT",
)
_PHASE_INDEX = {phase: index for index, phase in enumerate(_PHASES)}
# COM_INIT..EXPORT_AS_FIXED_FORMAT are entered in order; DOCUMENT_CLOSE,
# WORD_QUIT and WORKER_EXIT are teardown phases published only when reached.
_LAST_PROGRESS_PHASE = _PHASE_INDEX["EXPORT_AS_FIXED_FORMAT"]
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_DRIVE_FIXED = 3


class RendererUnavailable(ValueError):
    """The local Word renderer is absent, failed, or could not be contained."""


@dataclass(frozen=True, slots=True)
class OwnedProcessIdentity:
    pid: int
    creation_identity: str
    image_path: str


@dataclass(frozen=True, slots=True)
class WordRenderDeadlines:
    worker_start: float = 10.0
    com_init: float = 15.0
    word_process_start: float = 20.0
    word_com_bind: float = 20.0
    document_open: float = 45.0
    export_as_fixed_format: float = 120.0
    document_close: float = 15.0
    word_quit: float = 15.0
    worker_exit: float = 10.0

    def __post_init__(self) -> None:
        if any(
            not math.isfinite(value) or value <= 0 or value > 300
            for value in self.as_mapping().values()
        ):
            raise ValueError("Word render deadlines must be finite and bounded")

    def as_mapping(self) -> dict[str, float]:
        return {
            "WORKER_START": self.worker_start,
            "COM_INIT": self.com_init,
            "WORD_PROCESS_START": self.word_process_start,
            "WORD_COM_BIND": self.word_com_bind,
            "DOCUMENT_OPEN": self.document_open,
            "EXPORT_AS_FIXED_FORMAT": self.export_as_fixed_format,
            "DOCUMENT_CLOSE": self.document_close,
            "WORD_QUIT": self.word_quit,
            "WORKER_EXIT": self.worker_exit,
        }

    @classmethod
    def uniform(cls, seconds: float) -> WordRenderDeadlines:
        return cls(*([seconds] * 9))


class _OwnedWordWorker(Protocol):
    identity: OwnedProcessIdentity

    def wait(self, milliseconds: int) -> bool: ...

    def observed_identity(self) -> OwnedProcessIdentity | None: ...

    def terminate_job(self) -> None: ...

    def wait_contained(self, milliseconds: int) -> bool: ...

    def close(self) -> None: ...


def _normalized_image(path: str) -> str:
    return str(Path(path).resolve()).replace("\\", "/").casefold()


def _same_process_identity(
    expected: OwnedProcessIdentity, observed: OwnedProcessIdentity
) -> bool:
    return (
        expected.pid == observed.pid
        and expected.creation_identity == observed.creation_identity
        and _normalized_image(expected.image_path) == _normalized_image(observed.image_path)
    )


def _terminate_owned_worker(worker: _OwnedWordWorker) -> bool:
    if getattr(worker, "_job_scope_verified", False) is not True:
        observed = worker.observed_identity()
        if observed is None or not _same_process_identity(worker.identity, observed):
            return False
    worker.terminate_job()
    if not worker.wait_contained(5_000):
        raise RendererUnavailable("owned Word worker did not exit after containment")
    return True


def _read_phase(root: Path) -> str | None:
    """Observe closed atomic markers without reopening their Windows-locked payloads."""
    try:
        paths = sorted(root.glob("status*.json"))
    except OSError as exc:
        raise ValueError("invalid Word worker status") from exc
    if not paths:
        return None
    observed: list[tuple[int, str]] = []
    for path in paths:
        match = re.fullmatch(r"status-(\d{2})-([A-Z_]+)\.json", path.name)
        if match is None:
            raise ValueError("invalid Word worker status")
        phase = match.group(2)
        index = int(match.group(1))
        if phase not in _PHASE_INDEX or _PHASE_INDEX[phase] != index:
            raise ValueError("invalid Word worker status")
        observed.append((index, phase))
    if observed[0][0] != 1:
        raise ValueError("invalid Word worker status")
    indices = [index for index, _phase in observed]
    if any(later <= earlier for earlier, later in zip(indices, indices[1:])):
        raise ValueError("invalid Word worker status")
    # The worker advances linearly through COM_INIT..EXPORT_AS_FIXED_FORMAT and
    # then publishes only the teardown phases it actually enters, so a failure
    # before Documents.Open legitimately leaves holes after the progress prefix.
    # Those holes are PHASE_SKIPPED.  A hole *inside* the progress prefix is
    # still PROTOCOL_CORRUPTION, because those phases always precede each other.
    progress = [index for index in indices if index <= _LAST_PROGRESS_PHASE]
    if progress != list(range(1, len(progress) + 1)):
        raise ValueError("invalid Word worker status")
    if not progress and indices:
        raise ValueError("invalid Word worker status")
    return observed[-1][1]


def _wait_for_worker(
    worker: _OwnedWordWorker,
    root: Path,
    deadlines: WordRenderDeadlines,
    *,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    limits = deadlines.as_mapping()
    try:
        phase = _read_phase(root) or "WORKER_START"
        phase_started = clock()
        while True:
            elapsed = clock() - phase_started
            remaining = limits[phase] - elapsed
            if remaining <= 0:
                if not _terminate_owned_worker(worker):
                    raise RendererUnavailable(
                        f"ambiguous Word worker ownership at {phase}; process not terminated"
                    )
                raise TimeoutError(f"Microsoft Word render timed out at {phase}")
            wait_ms = max(1, min(50, int(remaining * 1000)))
            if worker.wait(wait_ms):
                return
            observed_phase = _read_phase(root)
            if observed_phase is None or observed_phase == phase:
                continue
            if _PHASE_INDEX[observed_phase] < _PHASE_INDEX[phase]:
                raise ValueError("invalid Word worker status regression")
            phase = observed_phase
            phase_started = clock()
    except ValueError:
        if worker.wait(0) is False:
            _terminate_owned_worker(worker)
        raise


def _quote_windows_argument(value: str) -> str:
    if not value or any(character in value for character in ("\x00", "\r", "\n")):
        raise RendererUnavailable("invalid local Word worker path")
    escaped: list[str] = ['"']
    backslashes = 0
    for character in value:
        if character == "\\":
            backslashes += 1
        elif character == '"':
            escaped.append("\\" * (backslashes * 2 + 1))
            escaped.append(character)
            backslashes = 0
        else:
            escaped.append("\\" * backslashes)
            escaped.append(character)
            backslashes = 0
    escaped.append("\\" * (backslashes * 2))
    escaped.append('"')
    return "".join(escaped)


class _WindowsJobWordWorker:
    _job_scope_verified = True

    def __init__(self, process, job, identity: OwnedProcessIdentity, modules: tuple) -> None:
        self._process = process
        self._job = job
        self.identity = identity
        self._win32event, self._win32job, self._win32process = modules

    def wait(self, milliseconds: int) -> bool:
        result = self._win32event.WaitForSingleObject(self._process, milliseconds)
        return result == self._win32event.WAIT_OBJECT_0

    def observed_identity(self) -> OwnedProcessIdentity | None:
        try:
            times = self._win32process.GetProcessTimes(self._process)
            image = self._win32process.GetModuleFileNameEx(self._process, 0)
            return OwnedProcessIdentity(
                pid=self.identity.pid,
                creation_identity=str(times["CreationTime"]),
                image_path=image,
            )
        except Exception:
            return None

    def terminate_job(self) -> None:
        self._win32job.TerminateJobObject(self._job, 124)

    def wait_contained(self, milliseconds: int) -> bool:
        return self._wait_contained(self._job, self._process, milliseconds)

    def close(self) -> None:
        if self._process is None or self._job is None:
            return
        process = self._process
        job = self._job
        self._process = None
        self._job = None
        try:
            if not self._wait_contained(job, process, 0):
                self._win32job.TerminateJobObject(job, 124)
            if not self._wait_contained(job, process, 5_000):
                self._win32job.TerminateJobObject(job, 124)
                if not self._wait_contained(job, process, 5_000):
                    raise RendererUnavailable("owned Word job did not close cleanly")
        finally:
            try:
                process.Close()
            finally:
                job.Close()

    def _wait_contained(self, job, process, milliseconds: int) -> bool:
        deadline = time.monotonic() + milliseconds / 1000
        while True:
            information = self._win32job.QueryInformationJobObject(
                job, self._win32job.JobObjectBasicAccountingInformation
            )
            if information["ActiveProcesses"] == 0:
                return True
            remaining_ms = int(max(0, (deadline - time.monotonic()) * 1000))
            if remaining_ms <= 0:
                return False
            self._win32event.WaitForSingleObject(process, min(50, remaining_ms))


def _controlled_worker_environment(
    job_root: Path, *, job_name: str, instance_token: str
) -> dict[str, str]:
    runtime_temp = job_root / "runtime-temp"
    runtime_temp.mkdir()
    environment = {
        "PLP_WORD_INSTANCE_TOKEN": instance_token,
        "PLP_WORD_JOB_NAME": job_name,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONNOUSERSITE": "1",
        "PYTHONUTF8": "1",
        "TEMP": str(runtime_temp),
        "TMP": str(runtime_temp),
    }
    # SystemDrive is required by loaders that resolve system paths relative to it.
    # PATH stays deliberately absent: the worker starts exactly one executable and
    # resolves it by full path, so no search path is needed.
    for key in ("SystemDrive", "SystemRoot", "WINDIR"):
        value = os.environ.get(key)
        if value:
            environment[key] = value
    return environment


def _remove_render_tree(
    root: Path,
    *,
    clock: Callable[[], float] = time.monotonic,
    pause: Callable[[float], object] = time.sleep,
) -> None:
    """Remove one exact render tree within a bounded transient-lock window."""
    sensitive_names = (
        "source.docx",
        "source.docm",
        "output.partial.pdf",
        "request.json",
        "result.json",
        "bootstrap.docx",
    )
    deadline = clock() + 5.0
    while root.exists():
        locked: PermissionError | None = None
        for name in sensitive_names:
            try:
                (root / name).unlink(missing_ok=True)
            except PermissionError as exc:
                locked = exc
        for path in root.glob("status-*.json*"):
            try:
                path.unlink(missing_ok=True)
            except PermissionError as exc:
                locked = exc
        try:
            shutil.rmtree(root)
            return
        except PermissionError as exc:
            locked = locked or exc
            if clock() >= deadline:
                raise locked
            pause(0.05)


@contextmanager
def _render_directory(temp_root: Path | None):
    candidate = Path(temp_root) if temp_root is not None else Path(tempfile.gettempdir())
    raw_candidate = os.fspath(candidate)
    if raw_candidate.startswith(("\\\\", "//")):
        raise RendererUnavailable("local Word render root must be on a local drive")
    try:
        validated_root = candidate.resolve(strict=True)
    except OSError as exc:
        raise RendererUnavailable("local Word render root is unavailable") from exc
    if not validated_root.is_dir():
        raise RendererUnavailable("local Word render root is not a directory")
    if os.name == "nt":
        anchor = validated_root.anchor
        if not anchor or anchor.startswith(("\\\\", "//")):
            raise RendererUnavailable("local Word render root must be on a local drive")
        if ctypes.windll.kernel32.GetDriveTypeW(str(Path(anchor))) != _DRIVE_FIXED:
            raise RendererUnavailable("local Word render root must be on a fixed drive")
        current = validated_root
        while True:
            attributes = getattr(
                os.stat(current, follow_symlinks=False), "st_file_attributes", 0
            )
            if attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
                raise RendererUnavailable("local Word render root cannot use reparse points")
            if current == Path(anchor):
                break
            current = current.parent
    root = Path(
        tempfile.mkdtemp(
            prefix="plp-word-pdf-",
            dir=str(validated_root),
        )
    ).resolve(strict=True)
    try:
        yield root
    finally:
        _remove_render_tree(root)


def _start_owned_word_worker(root: Path) -> _OwnedWordWorker:
    if sys.platform != "win32":
        raise RendererUnavailable("Microsoft Word Desktop COM requires Windows")
    try:
        import win32con
        import win32event
        import win32job
        import win32process
    except ModuleNotFoundError as exc:
        raise RendererUnavailable("Microsoft Word COM automation dependency is unavailable") from exc

    executable = str(Path(sys.executable).resolve(strict=True))
    worker_script = str(Path(__file__).with_name("office_word_worker.py").resolve(strict=True))
    command_line = " ".join(
        _quote_windows_argument(value)
        for value in (executable, "-I", worker_script, str(root.resolve(strict=True)))
    )
    process = thread = job = None
    assigned_to_job = False
    try:
        nonce = uuid4().hex
        job_name = f"Local\\PLP-Word-{nonce}"
        instance_token = f"PLP-Word-{nonce}"
        job = win32job.CreateJobObject(None, job_name)
        information = win32job.QueryInformationJobObject(
            job, win32job.JobObjectExtendedLimitInformation
        )
        information["BasicLimitInformation"]["LimitFlags"] |= (
            win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        win32job.SetInformationJobObject(
            job, win32job.JobObjectExtendedLimitInformation, information
        )
        startup = win32process.STARTUPINFO()
        process, thread, pid, _thread_id = win32process.CreateProcess(
            executable,
            command_line,
            None,
            None,
            False,
            win32con.CREATE_SUSPENDED | win32con.CREATE_NO_WINDOW,
            _controlled_worker_environment(
                root, job_name=job_name, instance_token=instance_token
            ),
            str(Path(__file__).resolve().parents[3]),
            startup,
        )
        win32job.AssignProcessToJobObject(job, process)
        assigned_to_job = True
        times = win32process.GetProcessTimes(process)
        image = win32process.GetModuleFileNameEx(process, 0)
        identity = OwnedProcessIdentity(pid, str(times["CreationTime"]), image)
        expected = OwnedProcessIdentity(pid, identity.creation_identity, executable)
        if not _same_process_identity(expected, identity):
            raise RendererUnavailable("local Word worker identity mismatch")
        win32process.ResumeThread(thread)
        thread.Close()
        thread = None
        owned_worker = _WindowsJobWordWorker(
            process,
            job,
            identity,
            (win32event, win32job, win32process),
        )
        process = None
        job = None
        return owned_worker
    except RendererUnavailable:
        raise
    except Exception as exc:
        raise RendererUnavailable("local Word worker could not start") from exc
    finally:
        if thread is not None:
            thread.Close()
        if process is not None:
            # A process that failed before ownership was returned was created suspended by
            # this exact call; termination is scoped to the returned process/job handles.
            if assigned_to_job:
                win32job.TerminateJobObject(job, 125)
            else:
                win32process.TerminateProcess(process, 125)
            process.Close()
        if job is not None:
            job.Close()


def _load_result(root: Path, word_digest: str) -> tuple[bytes, str]:
    try:
        result = json.loads((root / "result.json").read_text(encoding="utf-8"))
        output = (root / "output.partial.pdf").read_bytes()
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RendererUnavailable("local Word worker returned no valid result") from exc
    if (
        not isinstance(result, dict)
        or set(result)
        != {
            "schemaVersion",
            "status",
            "operation",
            "rendererType",
            "rendererVersion",
            "wordSha256",
            "pdfSha256",
        }
        or result.get("schemaVersion") != _SCHEMA_VERSION
        or result.get("status") != "SUCCESS"
        or result.get("operation") != RENDER_OPERATION
        or result.get("rendererType") != "MICROSOFT_WORD_DESKTOP_COM"
        or result.get("wordSha256") != word_digest
        or result.get("pdfSha256") != sha256(output).hexdigest()
        or not isinstance(result.get("rendererVersion"), str)
        or re.fullmatch(r"16\.\d+(?:\.\d+)*", result["rendererVersion"]) is None
        or not output.startswith(b"%PDF-")
        or not output.rstrip().endswith(b"%%EOF")
    ):
        raise RendererUnavailable("local Word worker result failed integrity verification")
    return output, result["rendererVersion"]


class LocalOfficePdfConverter:
    """Convert an exact Word copy through a bounded product-owned worker."""

    renderer_type = "MICROSOFT_WORD_DESKTOP_COM"
    requires_visual_raster = True

    def __init__(
        self,
        *,
        temp_root: Path | None = None,
        deadlines: WordRenderDeadlines | None = None,
    ) -> None:
        self._temp_root = temp_root
        self._deadlines = deadlines or WordRenderDeadlines()
        self._renderer_version = "UNKNOWN"

    @property
    def renderer_version(self) -> str:
        return self._renderer_version

    @property
    def platform(self) -> str:
        return sys.platform

    def convert(self, word_bytes: bytes, source_format: str) -> bytes:
        if type(word_bytes) is not bytes:
            raise ValueError("Word content must be bytes")
        if source_format not in {"DOCX", "DOCM"}:
            raise ValueError("source format must be DOCX or DOCM")
        word_digest = sha256(word_bytes).hexdigest()
        worker: _OwnedWordWorker | None = None
        try:
            with _render_directory(self._temp_root) as root:
                source = root / ("source.docm" if source_format == "DOCM" else "source.docx")
                source.write_bytes(word_bytes)
                (root / "request.json").write_text(
                    json.dumps(
                        {
                            "schemaVersion": _SCHEMA_VERSION,
                            "operation": RENDER_OPERATION,
                            "sourceFormat": source_format,
                        },
                        ensure_ascii=True,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    encoding="utf-8",
                )
                worker = _start_owned_word_worker(root)
                try:
                    _wait_for_worker(worker, root, self._deadlines)
                    if sha256(source.read_bytes()).hexdigest() != word_digest:
                        raise RendererUnavailable(
                            "authoritative Word copy changed during render"
                        )
                    output, version = _load_result(root, word_digest)
                    self._renderer_version = version
                    return output
                finally:
                    # Close the owned Job before TemporaryDirectory cleanup.  This
                    # also terminates any Word child/helper that outlived the worker.
                    worker.close()
                    worker = None
        except RendererUnavailable:
            raise
        except TimeoutError as exc:
            raise RendererUnavailable("local Microsoft Word PDF conversion timed out") from exc
        except (OSError, RuntimeError, ValueError) as exc:
            raise RendererUnavailable("local Microsoft Word PDF conversion failed") from exc
        finally:
            if worker is not None:
                worker.close()
