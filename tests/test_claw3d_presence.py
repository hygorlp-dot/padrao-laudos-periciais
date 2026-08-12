import json
import os
import threading
import time
from pathlib import Path
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
    store.set_state("implementer", "working")
    store.set_state("reviewer", "meeting")
    states = {item["agentId"]: item["state"] for item in store.snapshot()["agents"]}
    assert states["implementer"] == "working" and states["reviewer"] == "meeting"
    assert states["researcher"] == "idle"
    with pytest.raises(ValueError):
        store.set_state("implementer", "invented")
    with pytest.raises(ValueError):
        store.set_state("unknown", "working")


def test_concurrent_updates_are_atomic_and_preserve_all_agents(tmp_path):
    store = PresenceStore(tmp_path)
    barrier = threading.Barrier(len(AGENTS))
    errors = []

    def update(agent_id):
        try:
            barrier.wait()
            store.set_state(agent_id, "working")
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
    store.set_state("auditor", "working")
    first = store.internal_state()["agents"]["auditor"]["lastSeen"]
    store.heartbeat("auditor")
    assert store.internal_state()["agents"]["auditor"]["lastSeen"] >= first
    time.sleep(0.03)
    assert store.recover_stale() == ["auditor"]
    assert next(item for item in store.snapshot()["agents"] if item["agentId"] == "auditor")["state"] == "error"


@pytest.mark.parametrize("agent_id", list(AGENTS))
def test_real_lifecycle_sets_working_then_idle_and_failure_sets_error(tmp_path, agent_id):
    sink = Claw3DPresenceSink(PresenceStore(tmp_path))
    with agent_lifecycle(sink, agent_id):
        assert sink.store.internal_state()["agents"][agent_id]["state"] == "working"
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
    first.set_state("researcher", "working")
    assert second.internal_state()["agents"]["researcher"]["state"] == "working"
    assert first.state_dir == second.state_dir == (tmp_path / "shared").resolve()


def test_claude_rate_limit_records_error_without_retry_loop_then_can_idle(tmp_path):
    sink = Claw3DPresenceSink(PresenceStore(tmp_path))
    calls = []
    sink.set_state("claude", "working")
    calls.append("one-real-call")
    sink.set_state("claude", "error")
    sink.set_state("claude", "idle")
    assert calls == ["one-real-call"]
    assert sink.store.internal_state()["agents"]["claude"]["state"] == "idle"


def test_runtime_is_ignored_and_powershell_operator_commands_exist():
    root = Path(__file__).resolve().parents[1]
    ignore = (root / ".gitignore").read_text(encoding="utf-8")
    assert ".runtime/claw3d/" in ignore
    scripts = root / "scripts/agentic/claw3d"
    for name in ("Start-Claw3DAgentBridge.ps1", "Stop-Claw3DAgentBridge.ps1", "Get-Claw3DAgentState.ps1", "Set-Claw3DAgentState.ps1"):
        assert (scripts / name).is_file()
