"""Managed subprocess lifecycle feeding best-effort presence state."""
from __future__ import annotations
import os, queue, subprocess, threading, uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence
from .state import AGENTS, PresenceStore

@dataclass(frozen=True)
class ExecutionResult:
    execution_id: str
    role: str
    process_id: int | None
    exit_code: int
    worktree: str
    head_sha: str | None

class ManagedExecution:
    def __init__(self, runner, execution_id, role, process, worktree, head_sha):
        self.runner, self.execution_id, self.role = runner, execution_id, role
        self.process, self.worktree, self.head_sha = process, worktree, head_sha
        self._done, self._published, self._result = threading.Event(), threading.Event(), None
        self.runner._enqueue("begin_execution", self.role, self.execution_id,
                             process_id=self.process.pid, worktree=self.worktree, head_sha=self.head_sha)
        threading.Thread(target=self._observe, name=f"presence-{role}-{execution_id}", daemon=True).start()
    def _observe(self):
        while self.process.poll() is None:
            self._done.wait(self.runner.heartbeat_seconds)
        code = int(self.process.returncode)
        self._result = ExecutionResult(self.execution_id, self.role, self.process.pid, code, self.worktree, self.head_sha)
        self._done.set()
        published = self.runner._enqueue("finish_execution", self.execution_id, exit_code=code)
        if published:
            self._published = published
    def wait(self, timeout=None):
        self.process.wait(timeout=timeout); self._done.wait(timeout=timeout)
        self._published.wait(min(.1, timeout) if timeout is not None else .1)
        return self.process.returncode
    @property
    def result(self):
        self.wait(); return self._result

class ManagedAgentRunner:
    def __init__(self, *, store: PresenceStore | None = None, heartbeat_seconds: float = 1.0):
        self.store, self.heartbeat_seconds = store or PresenceStore.from_environment(), float(heartbeat_seconds)
        self._telemetry = queue.Queue(maxsize=256)
        threading.Thread(target=self._publish, name="presence-publisher-shared", daemon=True).start()
    def _publish(self):
        while True:
            method, args, kwargs, completed = self._telemetry.get()
            try: self._safe(method, *args, **kwargs)
            finally: completed.set()
    def _enqueue(self, method, *args, **kwargs):
        completed = threading.Event()
        try: self._telemetry.put_nowait((method, args, kwargs, completed))
        except queue.Full: return False
        return completed
    def _safe(self, method, *args, **kwargs):
        try: return getattr(self.store, method)(*args, **kwargs)
        except Exception: return None
    def start(self, role: str, command: Sequence[str], *, cwd: str | os.PathLike | None = None,
              environment: Mapping[str, str] | None = None, head_sha: str | None = None) -> ManagedExecution:
        if role not in AGENTS or not command or any(type(part) is not str for part in command):
            raise ValueError("invalid managed role or command")
        worktree, execution_id = str(Path(cwd or os.getcwd()).resolve()), str(uuid.uuid4())
        process = subprocess.Popen(list(command), cwd=worktree, env=dict(environment) if environment else None)
        return ManagedExecution(self, execution_id, role, process, worktree, head_sha)
    def run(self, role: str, command: Sequence[str], **kwargs) -> ExecutionResult:
        execution = self.start(role, command, **kwargs); execution.wait(); return execution.result
    def clear_error(self, role: str) -> None:
        self._safe("set_state", role, "idle")

class ClaudeManagedRunner:
    """Single-attempt Claude adapter. Rate limiting is surfaced; never retried here."""
    def __init__(self, runner: ManagedAgentRunner | None = None):
        self.runner = runner or ManagedAgentRunner()
    def run_once(self, command: Sequence[str], *, rate_limit_exit_codes: tuple[int, ...] = (29,), **kwargs) -> ExecutionResult:
        result = self.runner.run("claude", command, **kwargs)
        if result.exit_code in rate_limit_exit_codes:
            self.runner._safe("record_diagnostic", "RATE_LIMITED")
            self.runner.clear_error("claude")
        return result
