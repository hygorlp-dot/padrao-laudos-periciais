"""Managed subprocess lifecycle projected by one bounded process-wide reconciler."""
from __future__ import annotations

import os
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
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


class _TelemetryCoordinator:
    """Process-lifetime, current-state reconciler; never an event ledger."""

    def __init__(self):
        self._condition = threading.Condition()
        self._owners: dict[str, dict] = {}
        self._inflight: set[int] = set()
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="claw3d-store")
        self._sequence = 0
        self._thread = threading.Thread(target=self._run, name="claw3d-telemetry-reconciler", daemon=True)
        self._thread.start()

    def register(self, owner: str, store, interval: float) -> None:
        with self._condition:
            self._owners.setdefault(owner, {"store": store, "interval": max(.005, interval),
                                             "active": {}, "terminal": {}, "diagnostics": set(), "closed": False})
            self._condition.notify()

    def start(self, owner: str, store, interval: float, execution: dict) -> None:
        with self._condition:
            state = self._owners.setdefault(owner, {"store": store, "interval": max(.005, interval),
                                                     "active": {}, "terminal": {}, "diagnostics": set(), "closed": False})
            if state["closed"]: return
            state["active"][execution["execution_id"]] = execution
            self._condition.notify()

    def diagnostic(self, owner: str, code: str) -> None:
        with self._condition:
            state = self._owners.get(owner)
            if state is not None:
                state["diagnostics"].add(code)
                self._condition.notify()

    def finish(self, owner: str, execution_id: str, role: str, exit_code: int) -> None:
        with self._condition:
            state = self._owners.get(owner)
            if state is None:
                return
            state["active"].pop(execution_id, None)
            self._sequence += 1
            state["terminal"][execution_id] = {"execution_id": execution_id, "role": role,
                                                "state": "idle" if exit_code == 0 else "error",
                                                "exit_code": exit_code, "sequence": self._sequence}
            while len(state["terminal"]) > 256:
                state["terminal"].pop(next(iter(state["terminal"])))
            self._condition.notify()

    def close(self, owner: str) -> None:
        with self._condition:
            state = self._owners.get(owner)
            if state is not None:
                state["closed"] = True
                if not state["active"] and not state["terminal"] and not state["diagnostics"]:
                    self._owners.pop(owner, None)
            self._condition.notify()

    def counts(self) -> dict[str, int]:
        with self._condition:
            return {
                "workers": int(self._thread.is_alive()),
                "store_workers": 4,
                "owners": len(self._owners),
                "active_executions": sum(len(item["active"]) for item in self._owners.values()),
                "pending_states": sum(len(item["terminal"]) + len(item["diagnostics"])
                                      for item in self._owners.values()),
            }

    def _snapshot(self):
        groups: dict[int, dict] = {}
        with self._condition:
            interval = min((item["interval"] for item in self._owners.values()), default=.1)
            self._condition.wait(timeout=interval)
            for owner, item in self._owners.items():
                group = groups.setdefault(id(item["store"]), {"store": item["store"], "owners": [],
                                                               "active": {}, "terminal": {}, "diagnostics": set()})
                group["owners"].append(owner)
                group["active"].update({key: dict(value) for key, value in item["active"].items()})
                for execution_id, terminal in item["terminal"].items():
                    group["terminal"][execution_id] = dict(terminal)
                group["diagnostics"].update(item["diagnostics"])
        return groups

    def _acknowledge(self, group: dict) -> None:
        with self._condition:
            for owner in group["owners"]:
                item = self._owners.get(owner)
                if item is None:
                    continue
                for execution_id, terminal in list(item["terminal"].items()):
                    if terminal["sequence"] <= group["terminal"].get(execution_id, {}).get("sequence", -1):
                        item["terminal"].pop(execution_id, None)
                item["diagnostics"].difference_update(group["diagnostics"])
                if not item["active"] and not item["terminal"] and not item["diagnostics"]:
                    self._owners.pop(owner, None)

    def _run(self):
        while True:
            for group in self._snapshot().values():
                store_id = id(group["store"])
                with self._condition:
                    if store_id in self._inflight:
                        continue
                    self._inflight.add(store_id)
                try:
                    future = self._pool.submit(group["store"].reconcile_presence,
                                               list(group["active"].values()), group["terminal"],
                                               authoritative_owners=group["owners"],
                                               diagnostics=group["diagnostics"])
                    future.add_done_callback(lambda completed, current=group, key=store_id:
                                             self._complete(current, key, completed))
                except RuntimeError:
                    with self._condition: self._inflight.discard(store_id)
                    continue

    def _complete(self, group, store_id, future):
        try:
            if future.exception() is None:
                self._acknowledge(group)
        finally:
            with self._condition:
                self._inflight.discard(store_id)
                self._condition.notify()


_COORDINATOR = _TelemetryCoordinator()


class ManagedExecution:
    def __init__(self, runner, execution_id, role, process, worktree, head_sha):
        self.runner, self.execution_id, self.role = runner, execution_id, role
        self.process, self.worktree, self.head_sha = process, worktree, head_sha
        self._done, self._result = threading.Event(), None
        _COORDINATOR.start(runner._owner, runner.store, runner.heartbeat_seconds,
                           {"execution_id": execution_id, "role": role,
                           "process_id": process.pid, "worktree": worktree, "head_sha": head_sha,
                           "owner_id": runner._owner})
        threading.Thread(target=self._observe, name=f"presence-{role}-{execution_id}", daemon=True).start()

    def _observe(self):
        while self.process.poll() is None:
            self._done.wait(self.runner.heartbeat_seconds)
        code = int(self.process.returncode)
        self._result = ExecutionResult(self.execution_id, self.role, self.process.pid, code,
                                       self.worktree, self.head_sha)
        _COORDINATOR.finish(self.runner._owner, self.execution_id, self.role, code)
        self._done.set()

    def wait(self, timeout=None):
        self.process.wait(timeout=timeout)
        self._done.wait(timeout=timeout)
        return self.process.returncode

    @property
    def result(self):
        self.wait()
        return self._result


class ManagedAgentRunner:
    def __init__(self, *, store: PresenceStore | None = None, heartbeat_seconds: float = 1.0):
        self.store = store or PresenceStore.from_environment()
        self.heartbeat_seconds = float(heartbeat_seconds)
        self._owner, self._closed = str(uuid.uuid4()), False

    @classmethod
    def telemetry_resource_counts(cls):
        return _COORDINATOR.counts()

    def close(self):
        if not self._closed:
            self._closed = True
            _COORDINATOR.close(self._owner)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def _safe(self, method, *args, **kwargs):
        try:
            return getattr(self.store, method)(*args, **kwargs)
        except Exception:
            return None

    def start(self, role: str, command: Sequence[str], *, cwd: str | os.PathLike | None = None,
              environment: Mapping[str, str] | None = None, head_sha: str | None = None) -> ManagedExecution:
        if self._closed or role not in AGENTS or not command or any(type(part) is not str for part in command):
            raise ValueError("invalid or closed managed runner, role, or command")
        worktree, execution_id = str(Path(cwd or os.getcwd()).resolve()), str(uuid.uuid4())
        process = subprocess.Popen(list(command), cwd=worktree, env=dict(environment) if environment else None)
        return ManagedExecution(self, execution_id, role, process, worktree, head_sha)

    def run(self, role: str, command: Sequence[str], **kwargs) -> ExecutionResult:
        execution = self.start(role, command, **kwargs)
        execution.wait()
        return execution.result

    def clear_error(self, role: str) -> None:
        _COORDINATOR.register(self._owner, self.store, self.heartbeat_seconds)
        _COORDINATOR.finish(self._owner, f"diagnostic-{role}", role, 0)

    def record_diagnostic(self, code: str) -> None:
        _COORDINATOR.diagnostic(self._owner, code)


class ClaudeManagedRunner:
    """Single-attempt Claude adapter. Rate limiting is surfaced; never retried here."""
    def __init__(self, runner: ManagedAgentRunner | None = None):
        self.runner = runner or ManagedAgentRunner()

    def run_once(self, command: Sequence[str], *, rate_limit_exit_codes: tuple[int, ...] = (29,), **kwargs) -> ExecutionResult:
        result = self.runner.run("claude", command, **kwargs)
        if result.exit_code in rate_limit_exit_codes:
            # Diagnostics are deliberately best-effort; the real exit must return.
            self.runner.record_diagnostic("RATE_LIMITED")
            self.runner.clear_error("claude")
        return result
