"""Atomic per-agent presence state shared by local worktrees."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:  # pragma: no cover - Windows is the primary platform
    import fcntl

AGENTS = {
    "implementer": "Implementador Codex",
    "researcher": "Pesquisador Codex",
    "reviewer": "Revisor PR Codex",
    "auditor": "Auditor Sistêmico Codex",
    "claude": "Claude Externo",
}
STATES = {"idle", "working", "meeting", "error"}
WORKSPACE_ID = "padrao-laudos-periciais"
MAX_EXECUTION_HISTORY = 256
MAX_DIAGNOSTIC_BYTES = 65536
_THREAD_LOCKS: dict[str, threading.RLock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class PresenceStore:
    def __init__(self, state_dir: Path, *, stale_after_seconds: float = 300.0, max_execution_history: int = MAX_EXECUTION_HISTORY):
        self.state_dir = Path(state_dir).resolve()
        self.state_file = self.state_dir / "presence-state.json"
        self.lock_file = self.state_dir / "presence-state.lock"
        self.diagnostic_file = self.state_dir / "diagnostics.log"
        self.stale_after_seconds = float(stale_after_seconds)
        self.max_execution_history = max(1, int(max_execution_history))
        self.state_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_environment(cls, *, workspace: Path | None = None, stale_after_seconds: float | None = None):
        configured = os.getenv("CLAW3D_AGENT_STATE_DIR")
        if configured:
            state_dir = Path(configured)
            if not state_dir.is_absolute():
                raise ValueError("CLAW3D_AGENT_STATE_DIR must be absolute")
        else:
            local = os.getenv("LOCALAPPDATA") or tempfile.gettempdir()
            state_dir = Path(local) / "padrao-laudos-periciais" / "claw3d"
        stale = stale_after_seconds if stale_after_seconds is not None else float(os.getenv("CLAW3D_STALE_SECONDS", "300"))
        return cls(state_dir, stale_after_seconds=stale)

    def _empty(self) -> dict:
        now = _utc_now()
        return {"timestamp": now, "agents": {key: {"state": "idle", "lastSeen": None} for key in AGENTS},
                "executions": {}}

    @contextmanager
    def _locked(self):
        key = str(self.lock_file)
        with _THREAD_LOCKS_GUARD:
            thread_lock = _THREAD_LOCKS.setdefault(key, threading.RLock())
        with thread_lock:
            mode = "r+b" if self.lock_file.exists() else "w+b"
            with self.lock_file.open(mode) as stream:
                stream.seek(0)
                if stream.tell() == 0:
                    stream.write(b"0")
                    stream.flush()
                stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
                else:  # pragma: no cover
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    stream.seek(0)
                    if os.name == "nt":
                        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                    else:  # pragma: no cover
                        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _read_unlocked(self) -> dict:
        if not self.state_file.is_file():
            return self._empty()
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("presence state root must be an object")
            agents = data.get("agents") if isinstance(data.get("agents"), dict) else {}
            executions = data.get("executions") if isinstance(data.get("executions"), dict) else {}
            clean = self._empty()
            for agent_id in AGENTS:
                raw = agents.get(agent_id, {}) if isinstance(agents.get(agent_id), dict) else {}
                clean["agents"][agent_id] = {"state": raw.get("state") if raw.get("state") in STATES else "idle",
                                                   "lastSeen": raw.get("lastSeen") if type(raw.get("lastSeen")) in (int, float) else None}
            for execution_id, raw in executions.items():
                if type(execution_id) is str and isinstance(raw, dict) and raw.get("role") in AGENTS and raw.get("status") in {"running", "finished", "error", "cancelled"}:
                    clean["executions"][execution_id] = {key: raw.get(key) for key in ("role", "process_id", "started_at", "finished_at", "exit_code", "worktree", "head_sha", "lastSeen", "status")}
            clean["timestamp"] = data.get("timestamp") if type(data.get("timestamp")) is str else _utc_now()
            return clean
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            self._diagnose(f"state recovery: {type(exc).__name__}")
            return self._empty()

    def _write_unlocked(self, data: dict) -> None:
        executions = data.get("executions", {})
        running = {key: value for key, value in executions.items() if value.get("status") == "running"}
        finished = sorted(
            ((key, value) for key, value in executions.items() if value.get("status") != "running"),
            key=lambda item: (item[1].get("finished_at") or item[1].get("started_at") or "", item[0]),
            reverse=True,
        )
        slots = max(0, self.max_execution_history - len(running))
        data["executions"] = {**running, **dict(reversed(finished[:slots]))}
        data["timestamp"] = _utc_now()
        fd, temporary = tempfile.mkstemp(prefix="presence-", suffix=".tmp", dir=self.state_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(data, stream, ensure_ascii=False, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.state_file)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _diagnose(self, message: str) -> None:
        try:
            if self.diagnostic_file.is_file() and self.diagnostic_file.stat().st_size > MAX_DIAGNOSTIC_BYTES:
                tail = self.diagnostic_file.read_bytes()[-(MAX_DIAGNOSTIC_BYTES // 2):]
                self.diagnostic_file.write_bytes(tail)
            with self.diagnostic_file.open("a", encoding="utf-8") as stream:
                stream.write(f"{_utc_now()} {message}\n")
        except OSError:
            pass

    def record_diagnostic(self, code: str) -> None:
        if code not in {"RATE_LIMITED"}:
            raise ValueError("unknown diagnostic code")
        self._diagnose(code)

    def set_state(self, agent_id: str, state: str) -> None:
        if agent_id not in AGENTS or state not in STATES:
            raise ValueError("unknown agent or operational state")
        if state in {"working", "meeting"}:
            raise ValueError("working state requires a managed execution lease")
        with self._locked():
            data = self._read_unlocked()
            data["agents"][agent_id]["state"] = state
            data["agents"][agent_id]["lastSeen"] = time.time() if state in {"working", "meeting"} else None
            self._write_unlocked(data)

    def heartbeat(self, agent_id: str) -> None:
        if agent_id not in AGENTS:
            raise ValueError("unknown agent")
        with self._locked():
            data = self._read_unlocked()
            if data["agents"][agent_id]["state"] in {"working", "meeting"}:
                data["agents"][agent_id]["lastSeen"] = time.time()
                self._write_unlocked(data)

    def begin_execution(self, agent_id: str, execution_id: str, *, process_id: int | None, worktree: str, head_sha: str | None) -> None:
        if agent_id not in AGENTS or not execution_id:
            raise ValueError("unknown agent or execution")
        with self._locked():
            data = self._read_unlocked()
            data["executions"][execution_id] = {"role": agent_id, "process_id": process_id, "started_at": _utc_now(), "finished_at": None,
                                                  "exit_code": None, "worktree": worktree, "head_sha": head_sha,
                                                  "lastSeen": time.time(), "status": "running"}
            self._write_unlocked(data)

    def heartbeat_execution(self, execution_id: str) -> None:
        with self._locked():
            data = self._read_unlocked()
            execution = data["executions"].get(execution_id)
            if execution and execution.get("status") == "running":
                execution["lastSeen"] = time.time()
                self._write_unlocked(data)

    def attach_process(self, execution_id: str, process_id: int) -> None:
        with self._locked():
            data = self._read_unlocked()
            execution = data["executions"].get(execution_id)
            if execution and execution.get("status") == "running":
                execution["process_id"] = int(process_id)
                self._write_unlocked(data)

    def finish_execution(self, execution_id: str, *, exit_code: int | None, cancelled: bool = False) -> None:
        with self._locked():
            data = self._read_unlocked()
            execution = data["executions"].get(execution_id)
            if not execution:
                return
            execution.update(finished_at=_utc_now(), exit_code=exit_code, lastSeen=None,
                             status="cancelled" if cancelled else ("finished" if exit_code == 0 else "error"))
            role = execution["role"]
            if exit_code == 0 or cancelled:
                data["agents"][role].update(state="idle", lastSeen=None)
            elif exit_code is not None:
                data["agents"][role].update(state="error", lastSeen=None)
            self._write_unlocked(data)

    def recover_stale(self) -> list[str]:
        stale = []
        now = time.time()
        with self._locked():
            data = self._read_unlocked()
            for execution in data["executions"].values():
                seen = execution.get("lastSeen")
                if execution.get("status") == "running" and (type(seen) not in (int, float) or now - seen > self.stale_after_seconds):
                    execution.update(status="error", finished_at=_utc_now(), exit_code=None, lastSeen=None)
                    role = execution["role"]
                    data["agents"][role].update(state="error", lastSeen=None)
                    if role not in stale:
                        stale.append(role)
            for agent_id, agent in data["agents"].items():
                seen = agent.get("lastSeen")
                if agent.get("state") in {"working", "meeting"} and (not isinstance(seen, (int, float)) or now - seen > self.stale_after_seconds):
                    agent.update(state="error", lastSeen=None)
                    stale.append(agent_id)
            if stale:
                self._write_unlocked(data)
        return stale

    def internal_state(self) -> dict:
        with self._locked():
            return self._read_unlocked()

    def snapshot(self) -> dict:
        data = self.internal_state()
        active_roles = {item["role"] for item in data["executions"].values() if item.get("status") == "running"}
        return {"workspaceId": WORKSPACE_ID, "timestamp": _utc_now(),
                "agents": [{"agentId": key, "name": AGENTS[key], "state": "working" if key in active_roles else data["agents"][key]["state"]} for key in AGENTS]}
