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
_THREAD_LOCKS: dict[str, threading.RLock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class PresenceStore:
    def __init__(self, state_dir: Path, *, stale_after_seconds: float = 300.0):
        self.state_dir = Path(state_dir).resolve()
        self.state_file = self.state_dir / "presence-state.json"
        self.lock_file = self.state_dir / "presence-state.lock"
        self.diagnostic_file = self.state_dir / "diagnostics.log"
        self.stale_after_seconds = float(stale_after_seconds)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_environment(cls, *, workspace: Path | None = None, stale_after_seconds: float | None = None):
        configured = os.getenv("CLAW3D_AGENT_STATE_DIR")
        if configured:
            state_dir = Path(configured)
        else:
            local = os.getenv("LOCALAPPDATA") or tempfile.gettempdir()
            state_dir = Path(local) / "padrao-laudos-periciais" / "claw3d"
        stale = stale_after_seconds if stale_after_seconds is not None else float(os.getenv("CLAW3D_STALE_SECONDS", "300"))
        return cls(state_dir, stale_after_seconds=stale)

    def _empty(self) -> dict:
        now = _utc_now()
        return {"workspaceId": "padrao-laudos-periciais", "timestamp": now,
                "agents": {key: {"name": name, "state": "idle", "lastSeen": None} for key, name in AGENTS.items()}}

    @contextmanager
    def _locked(self):
        key = str(self.lock_file)
        with _THREAD_LOCKS_GUARD:
            thread_lock = _THREAD_LOCKS.setdefault(key, threading.RLock())
        with thread_lock:
            with self.lock_file.open("a+b") as stream:
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
            if set(data.get("agents", {})) != set(AGENTS):
                raise ValueError("invalid agent catalog")
            return data
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            self._diagnose(f"state recovery: {type(exc).__name__}")
            return self._empty()

    def _write_unlocked(self, data: dict) -> None:
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
            with self.diagnostic_file.open("a", encoding="utf-8") as stream:
                stream.write(f"{_utc_now()} {message}\n")
        except OSError:
            pass

    def set_state(self, agent_id: str, state: str) -> None:
        if agent_id not in AGENTS or state not in STATES:
            raise ValueError("unknown agent or operational state")
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

    def recover_stale(self) -> list[str]:
        stale = []
        now = time.time()
        with self._locked():
            data = self._read_unlocked()
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
        return {"workspaceId": data["workspaceId"], "timestamp": data["timestamp"],
                "agents": [{"agentId": key, "name": AGENTS[key], "state": data["agents"][key]["state"]} for key in AGENTS]}
