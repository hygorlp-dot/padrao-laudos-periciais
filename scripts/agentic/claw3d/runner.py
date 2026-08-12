"""Managed subprocess lifecycle feeding best-effort presence state."""
from __future__ import annotations
import os, subprocess, threading, uuid
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
        self._done, self._result = threading.Event(), None
        threading.Thread(target=self._observe, name=f"presence-{role}-{execution_id}", daemon=True).start()
    def _observe(self):
        while self.process.poll() is None:
            self.runner._safe("heartbeat_execution", self.execution_id)
            self._done.wait(self.runner.heartbeat_seconds)
        code = int(self.process.returncode)
        self.runner._safe("finish_execution", self.execution_id, exit_code=code)
        self._result = ExecutionResult(self.execution_id, self.role, self.process.pid, code, self.worktree, self.head_sha)
        self._done.set()
    def wait(self, timeout=None):
        self.process.wait(timeout=timeout); self._done.wait(timeout=timeout); return self.process.returncode
    @property
    def result(self):
        self.wait(); return self._result

class ManagedAgentRunner:
    def __init__(self, *, store: PresenceStore | None = None, heartbeat_seconds: float = 1.0):
        self.store, self.heartbeat_seconds = store or PresenceStore.from_environment(), float(heartbeat_seconds)
    def _safe(self, method, *args, **kwargs):
        try: return getattr(self.store, method)(*args, **kwargs)
        except Exception: return None
    def start(self, role: str, command: Sequence[str], *, cwd: str | os.PathLike | None = None,
              environment: Mapping[str, str] | None = None, head_sha: str | None = None) -> ManagedExecution:
        if role not in AGENTS or not command or any(type(part) is not str for part in command):
            raise ValueError("invalid managed role or command")
        worktree, execution_id = str(Path(cwd or os.getcwd()).resolve()), str(uuid.uuid4())
        self._safe("begin_execution", role, execution_id, process_id=None, worktree=worktree, head_sha=head_sha)
        try:
            process = subprocess.Popen(list(command), cwd=worktree, env=dict(environment) if environment else None)
        except BaseException:
            self._safe("finish_execution", execution_id, exit_code=-1)
            raise
        self._safe("attach_process", execution_id, process.pid)
        return ManagedExecution(self, execution_id, role, process, worktree, head_sha)
    def run(self, role: str, command: Sequence[str], **kwargs) -> ExecutionResult:
        execution = self.start(role, command, **kwargs); execution.wait(); return execution.result
    def clear_error(self, role: str) -> None:
        self._safe("set_state", role, "idle")

class ClaudeManagedRunner:
    """Single-attempt Claude adapter. Rate limiting is surfaced; never retried here."""
    def __init__(self, runner: ManagedAgentRunner | None = None):
        self.runner = runner or ManagedAgentRunner()
    def run_once(self, command: Sequence[str], **kwargs) -> ExecutionResult:
        return self.runner.run("claude", command, **kwargs)
