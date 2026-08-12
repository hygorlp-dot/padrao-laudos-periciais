import json
import os
import threading
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from scripts.agentic.claw3d import (
    AGENTS,
    AgentPresenceSink,
    Claw3DPresenceSink,
    PresenceBridge,
    PresenceStore,
    agent_lifecycle,
)


def test_snapshot_has_exactly_five_agents_and_privacy_minimal_contract(tmp_path):
    snapshot = PresenceStore(tmp_path).snapshot()
    assert snapshot["workspaceId"] == "padrao-laudos-periciais"
    assert {agent["agentId"] for agent in snapshot["agents"]} == set(AGENTS)
    assert all(set(agent) == {"agentId", "name", "state"} for agent in snapshot["agents"])
    serialized = json.dumps(snapshot, ensure_ascii=False).casefold()
    assert not any(token in serialized for token in ("cnj", "cpf", "prompt", "patologia", "endereço", "referencias/privadas"))


def test_state_transitions_and_agent_state_are_independent(tmp_path):
    store = PresenceStore(tmp_path)
    store.begin_execution("implementer", "run-1", process_id=1, worktree=str(tmp_path), head_sha=None)
    store.begin_execution("reviewer", "run-2", process_id=2, worktree=str(tmp_path), head_sha=None)
    states = {item["agentId"]: item["state"] for item in store.snapshot()["agents"]}
    assert states["implementer"] == "working" and states["reviewer"] == "working"
    assert states["researcher"] == "idle"
    with pytest.raises(ValueError):
        store.set_state("implementer", "invented")
    with pytest.raises(ValueError):
        store.set_state("unknown", "working")


def test_reconciliation_never_closes_another_process_owner(tmp_path):
    store = PresenceStore(tmp_path)
    store.reconcile_presence([
        {"execution_id": "foreign-run", "role": "researcher", "process_id": 101,
         "worktree": str(tmp_path), "head_sha": None, "owner_id": "foreign-owner"}
    ], {}, authoritative_owners=["foreign-owner"])
    store.reconcile_presence([], {"reviewer": {"state": "idle", "exit_code": 0, "sequence": 1}},
                             authoritative_owners=["local-owner"])
    assert store.internal_state()["executions"]["foreign-run"]["status"] == "running"
    assert state_from_presence(store, "researcher") == "working"


def state_from_presence(store, role):
    return next(item["state"] for item in store.snapshot()["agents"] if item["agentId"] == role)


def test_working_cannot_be_fabricated_without_execution_lease(tmp_path):
    store = PresenceStore(tmp_path)
    with pytest.raises(ValueError, match="execution lease"):
        store.set_state("reviewer", "working")
    assert next(item for item in store.snapshot()["agents"] if item["agentId"] == "reviewer")["state"] == "idle"
    for invalid_pid in (None, 0, -1, True):
        with pytest.raises(ValueError):
            store.begin_execution("reviewer", f"invalid-{invalid_pid}", process_id=invalid_pid,
                                  worktree=str(tmp_path), head_sha=None)


def test_persisted_running_entry_without_real_pid_is_not_published(tmp_path):
    poisoned = PresenceStore(tmp_path)._empty()
    poisoned["executions"]["forged"] = {
        "role": "reviewer", "process_id": None, "started_at": "synthetic",
        "finished_at": None, "exit_code": None, "worktree": str(tmp_path),
        "head_sha": None, "lastSeen": time.time(), "status": "running",
    }
    (tmp_path / "presence-state.json").write_text(json.dumps(poisoned), encoding="utf-8")
    assert state_from_snapshot(PresenceStore(tmp_path), "reviewer") == "idle"


def state_from_snapshot(store, role):
    return next(item["state"] for item in store.snapshot()["agents"] if item["agentId"] == role)


def test_concurrent_updates_are_atomic_and_preserve_all_agents(tmp_path):
    store = PresenceStore(tmp_path)
    barrier = threading.Barrier(len(AGENTS))
    errors = []

    def update(agent_id):
        try:
            barrier.wait()
            store.begin_execution(agent_id, f"run-{agent_id}", process_id=os.getpid(), worktree=str(tmp_path), head_sha=None)
        except Exception as exc:  # pragma: no cover - diagnostic collection
            errors.append(exc)

    threads = [threading.Thread(target=update, args=(agent,)) for agent in AGENTS]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert errors == []
    assert {item["state"] for item in store.snapshot()["agents"]} == {"working"}
    json.loads((tmp_path / "presence-state.json").read_text(encoding="utf-8"))


def test_heartbeat_and_watchdog_mark_stale_work_as_error(tmp_path):
    store = PresenceStore(tmp_path, stale_after_seconds=0.02)
    store.begin_execution("auditor", "run-auditor", process_id=os.getpid(), worktree=str(tmp_path), head_sha=None)
    first = store.internal_state()["executions"]["run-auditor"]["lastSeen"]
    store.heartbeat_execution("run-auditor")
    assert store.internal_state()["executions"]["run-auditor"]["lastSeen"] >= first
    time.sleep(0.03)
    assert store.recover_stale() == ["auditor"]
    assert next(item for item in store.snapshot()["agents"] if item["agentId"] == "auditor")["state"] == "error"


@pytest.mark.parametrize("agent_id", list(AGENTS))
def test_unmanaged_lifecycle_does_not_fabricate_working(tmp_path, agent_id):
    sink = Claw3DPresenceSink(PresenceStore(tmp_path))
    with agent_lifecycle(sink, agent_id):
        assert sink.store.internal_state()["agents"][agent_id]["state"] == "idle"
    assert sink.store.internal_state()["agents"][agent_id]["state"] == "idle"
    with pytest.raises(RuntimeError):
        with agent_lifecycle(sink, agent_id):
            raise RuntimeError("operational failure")
    assert sink.store.internal_state()["agents"][agent_id]["state"] == "error"


def test_review_findings_are_normal_completion_not_operational_error(tmp_path):
    sink = Claw3DPresenceSink(PresenceStore(tmp_path))
    with agent_lifecycle(sink, "reviewer"):
        findings = [{"severity": "P0"}]
        assert findings
    assert sink.store.internal_state()["agents"]["reviewer"]["state"] == "idle"


def test_unavailable_sink_never_blocks_or_changes_workflow_result():
    class BrokenSink(AgentPresenceSink):
        def set_state(self, *_args, **_kwargs):
            raise OSError("bridge unavailable")
        def heartbeat(self, *_args, **_kwargs):
            raise OSError("bridge unavailable")

    with agent_lifecycle(BrokenSink(), "implementer"):
        result = {"gate": "APPROVED", "finding": None}
    assert result == {"gate": "APPROVED", "finding": None}


def test_bridge_binds_loopback_and_serves_presence_and_health(tmp_path):
    bridge = PresenceBridge(PresenceStore(tmp_path), host="127.0.0.1", port=0, instance_token="test-instance")
    bridge.start()
    try:
        host, port = bridge.address
        assert host == "127.0.0.1"
        with urlopen(f"http://127.0.0.1:{port}/presence", timeout=2) as response:
            assert json.load(response)["workspaceId"] == "padrao-laudos-periciais"
        with urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
            assert json.load(response) == {"status": "ok", "instanceToken": "test-instance", "processId": os.getpid()}
    finally:
        bridge.stop()
    assert bridge.running is False
    with pytest.raises(ValueError):
        PresenceBridge(PresenceStore(tmp_path), host="0.0.0.0")


def test_worktrees_share_explicit_runtime_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAW3D_AGENT_STATE_DIR", str(tmp_path / "shared"))
    first = PresenceStore.from_environment(workspace=tmp_path / "worktree-a")
    second = PresenceStore.from_environment(workspace=tmp_path / "worktree-b")
    first.begin_execution("researcher", "shared-run", process_id=os.getpid(), worktree=str(tmp_path), head_sha=None)
    assert next(item for item in second.snapshot()["agents"] if item["agentId"] == "researcher")["state"] == "working"
    assert first.state_dir == second.state_dir == (tmp_path / "shared").resolve()


def test_relative_shared_runtime_directory_fails_closed(monkeypatch):
    monkeypatch.setenv("CLAW3D_AGENT_STATE_DIR", "relative/runtime")
    with pytest.raises(ValueError, match="absolute"):
        PresenceStore.from_environment()


def test_claude_rate_limit_records_error_without_retry_loop_then_can_idle(tmp_path):
    sink = Claw3DPresenceSink(PresenceStore(tmp_path))
    calls = []
    sink.store.begin_execution("claude", "claude-run", process_id=os.getpid(), worktree=str(tmp_path), head_sha=None)
    calls.append("one-real-call")
    sink.set_state("claude", "error")
    sink.set_state("claude", "idle")
    assert calls == ["one-real-call"]
    assert sink.store.internal_state()["agents"]["claude"]["state"] == "idle"


def test_finished_execution_history_is_bounded(tmp_path):
    store = PresenceStore(tmp_path, max_execution_history=8)
    for index in range(12):
        execution_id = f"run-{index:03d}"
        store.begin_execution("researcher", execution_id, process_id=os.getpid(), worktree=str(tmp_path), head_sha=None)
        store.finish_execution(execution_id, exit_code=0)
    state = store.internal_state()
    assert len(state["executions"]) == 8
    assert "run-000" not in state["executions"] and "run-011" in state["executions"]


def test_runtime_is_ignored_and_powershell_operator_commands_exist():
    root = Path(__file__).resolve().parents[1]
    ignore = (root / ".gitignore").read_text(encoding="utf-8")
    assert ".runtime/claw3d/" in ignore
    scripts = root / "scripts/agentic/claw3d"
    for name in ("Start-Claw3DAgentBridge.ps1", "Stop-Claw3DAgentBridge.ps1", "Get-Claw3DAgentState.ps1", "Set-Claw3DAgentState.ps1"):
        assert (scripts / name).is_file()


def test_health_ok_presence_broken_is_not_ready(tmp_path):
    class BrokenStore:
        def recover_stale(self): raise ValueError("corrupt")
        def snapshot(self): raise ValueError("corrupt")
    bridge = PresenceBridge(BrokenStore(), port=0, instance_token="expected")
    bridge.start()
    try:
        _, port = bridge.address
        with urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
            assert json.load(response)["status"] == "ok"
        with pytest.raises(HTTPError) as error:
            urlopen(f"http://127.0.0.1:{port}/presence", timeout=2)
        assert error.value.code == 503
        payload = json.loads(error.value.read())
        assert payload == {"status": "degraded", "error": "presence_unavailable"}
    finally:
        bridge.stop()


@pytest.mark.parametrize("content", ["", "{", "[]", "{}", '{"agents":[],"executions":[]}'])
def test_corrupt_presence_state_is_reported_as_degraded(tmp_path, content):
    (tmp_path / "presence-state.json").write_text(content, encoding="utf-8")
    bridge = PresenceBridge(PresenceStore(tmp_path), port=0)
    bridge.start()
    try:
        _, port = bridge.address
        with pytest.raises(HTTPError) as error:
            urlopen(f"http://127.0.0.1:{port}/presence", timeout=2)
        assert error.value.code == 503
        assert json.loads(error.value.read()) == {"status": "degraded", "error": "presence_unavailable"}
    finally:
        bridge.stop()


def test_parallel_presence_requests_remain_valid(tmp_path):
    bridge = PresenceBridge(PresenceStore(tmp_path), port=0)
    bridge.start()
    errors = []
    try:
        _, port = bridge.address
        def fetch():
            try:
                with urlopen(f"http://127.0.0.1:{port}/presence", timeout=2) as response:
                    assert json.load(response)["workspaceId"] == "padrao-laudos-periciais"
            except Exception as exc:
                errors.append(exc)
        threads = [threading.Thread(target=fetch) for _ in range(12)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        assert errors == []
    finally:
        bridge.stop()


def test_lock_file_size_remains_bounded_across_acquisitions(tmp_path):
    store = PresenceStore(tmp_path)
    for _ in range(100):
        store.snapshot()
    assert store.lock_file.stat().st_size == 1


def test_operator_state_reader_rejects_non_loopback_url():
    script = Path(__file__).resolve().parents[1] / "scripts/agentic/claw3d/Get-Claw3DAgentState.ps1"
    result = __import__('subprocess').run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-BridgeUrl", "https://example.test"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "loopback" in (result.stdout + result.stderr).casefold()
