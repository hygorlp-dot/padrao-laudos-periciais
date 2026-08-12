import json
import os
import subprocess
import sys
import time

from urllib.request import urlopen

from scripts.agentic.claw3d import AGENTS, ClaudeManagedRunner, PresenceBridge, PresenceStore
from scripts.agentic.claw3d.capabilities import detect_codex_capability
from scripts.agentic.claw3d.runner import ManagedAgentRunner


def state(store, role):
    return next(agent["state"] for agent in store.snapshot()["agents"] if agent["agentId"] == role)


def test_public_snapshot_is_rebuilt_from_first_party_whitelist(tmp_path):
    poisoned = {
        "workspaceId": "CNJ 0000000-00.0000.0.00.0000 Rua Particular, 123",
        "token": "secret",
        "agents": {
            "implementer": {"name": "Pessoa Real", "state": "working", "prompt": "caso privado"},
            "unknown": {"name": "CPF 000.000.000-00", "state": "working"},
        },
        "nested": {"email": "parte@example.test", "path": "referencias/privadas/caso.pdf"},
    }
    (tmp_path / "presence-state.json").write_text(json.dumps(poisoned), encoding="utf-8")
    snapshot = PresenceStore(tmp_path).snapshot()
    assert snapshot["workspaceId"] == "padrao-laudos-periciais"
    assert {agent["agentId"] for agent in snapshot["agents"]} == set(AGENTS)
    assert all(agent["name"] == AGENTS[agent["agentId"]] for agent in snapshot["agents"])
    serialized = json.dumps(snapshot, ensure_ascii=False)
    for forbidden in ("0000000", "Rua Particular", "Pessoa Real", "secret", "caso privado", "unknown", "parte@example", "referencias/privadas"):
        assert forbidden not in serialized


def test_compatibility_presence_endpoint(tmp_path):
    bridge = PresenceBridge(PresenceStore(tmp_path), port=0)
    bridge.start()
    try:
        _, port = bridge.address
        with urlopen(f"http://127.0.0.1:{port}/api/office/presence", timeout=2) as response:
            assert json.load(response)["workspaceId"] == "padrao-laudos-periciais"
    finally:
        bridge.stop()


def test_managed_real_subprocess_lifecycle_and_exit_codes(tmp_path):
    store = PresenceStore(tmp_path)
    runner = ManagedAgentRunner(store=store, heartbeat_seconds=0.01)
    running = runner.start("implementer", [sys.executable, "-c", "import time; time.sleep(.15)"])
    assert state(store, "implementer") == "working"
    assert running.wait() == 0
    assert state(store, "implementer") == "idle"
    failed = runner.run("reviewer", [sys.executable, "-c", "raise SystemExit(7)"])
    assert failed.exit_code == 7
    assert state(store, "reviewer") == "error"
    runner.clear_error("reviewer")
    assert state(store, "reviewer") == "idle"


def test_parallel_managed_processes_have_independent_leases(tmp_path):
    store = PresenceStore(tmp_path)
    runner = ManagedAgentRunner(store=store, heartbeat_seconds=0.01)
    first = runner.start("implementer", [sys.executable, "-c", "import time; time.sleep(.12)"])
    second = runner.start("reviewer", [sys.executable, "-c", "import time; time.sleep(.3)"])
    assert state(store, "implementer") == state(store, "reviewer") == "working"
    assert first.wait() == 0
    assert state(store, "implementer") == "idle"
    assert state(store, "reviewer") == "working"
    assert second.wait() == 0
    assert state(store, "reviewer") == "idle"


def test_live_http_presence_tracks_real_parallel_processes(tmp_path):
    store = PresenceStore(tmp_path)
    bridge = PresenceBridge(store, port=0)
    bridge.start()
    runner = ManagedAgentRunner(store=store, heartbeat_seconds=0.01)
    first = runner.start("implementer", [sys.executable, "-c", "import time; time.sleep(.12)"])
    second = runner.start("reviewer", [sys.executable, "-c", "import time; time.sleep(.3)"])
    try:
        _, port = bridge.address
        def remote_states():
            with urlopen(f"http://127.0.0.1:{port}/presence", timeout=2) as response:
                return {item["agentId"]: item["state"] for item in json.load(response)["agents"]}
        assert remote_states()["implementer"] == remote_states()["reviewer"] == "working"
        first.wait()
        current = remote_states()
        assert current["implementer"] == "idle" and current["reviewer"] == "working"
        second.wait()
        assert remote_states()["implementer"] == remote_states()["reviewer"] == "idle"
    finally:
        bridge.stop()


def test_same_role_remains_working_until_all_real_executions_finish(tmp_path):
    store = PresenceStore(tmp_path)
    runner = ManagedAgentRunner(store=store, heartbeat_seconds=0.01)
    short = runner.start("researcher", [sys.executable, "-c", "import time; time.sleep(.1)"])
    long = runner.start("researcher", [sys.executable, "-c", "import time; time.sleep(.25)"])
    assert short.wait() == 0
    assert state(store, "researcher") == "working"
    assert long.wait() == 0
    assert state(store, "researcher") == "idle"


def test_presence_failure_never_changes_managed_process_exit():
    class BrokenStore:
        def begin_execution(self, *_args, **_kwargs): raise OSError("bridge down")
        def heartbeat_execution(self, *_args, **_kwargs): raise OSError("bridge down")
        def finish_execution(self, *_args, **_kwargs): raise OSError("bridge down")

    result = ManagedAgentRunner(store=BrokenStore(), heartbeat_seconds=0.01).run(
        "auditor", [sys.executable, "-c", "raise SystemExit(3)"]
    )
    assert result.exit_code == 3


def test_stale_real_execution_recovers_without_fabricating_unmanaged_work(tmp_path):
    store = PresenceStore(tmp_path, stale_after_seconds=0.01)
    store.begin_execution("auditor", "run-stale", process_id=999999, worktree=str(tmp_path), head_sha=None)
    time.sleep(0.02)
    assert store.recover_stale() == ["auditor"]
    assert state(store, "auditor") == "error"
    assert state(store, "claude") == "idle"


def test_codex_capability_detection_is_fail_closed():
    absent = detect_codex_capability(executable="definitely-not-a-real-codex-command")
    assert absent.available is False and absent.non_interactive is False and absent.command is None


def test_codex_capability_does_not_accept_exec_as_prose(tmp_path):
    fake = tmp_path / "fake-codex.cmd"
    fake.write_text("@echo off\r\nif \"%1\"==\"--version\" (echo fake 1.0) else (echo cannot execute non-interactively)\r\n", encoding="ascii")
    result = detect_codex_capability(executable=str(fake))
    assert result.available is True
    assert result.non_interactive is False
    assert result.command is None


def test_process_start_failure_sets_error_and_never_leaves_working(tmp_path):
    store = PresenceStore(tmp_path)
    runner = ManagedAgentRunner(store=store)
    try:
        runner.start("implementer", ["definitely-not-a-real-program"])
    except OSError:
        pass
    assert state(store, "implementer") == "error"


def test_claude_adapter_makes_one_attempt_without_retry(tmp_path):
    store = PresenceStore(tmp_path)
    calls_file = tmp_path / "calls.txt"
    command = [sys.executable, "-c", f"from pathlib import Path; p=Path({str(calls_file)!r}); p.write_text('one'); raise SystemExit(29)"]
    result = ClaudeManagedRunner(ManagedAgentRunner(store=store, heartbeat_seconds=0.01)).run_once(command)
    assert result.exit_code == 29
    assert calls_file.read_text() == "one"
    assert state(store, "claude") == "idle"
    assert "RATE_LIMITED" in store.diagnostic_file.read_text(encoding="utf-8")


def test_operator_wrapper_and_safe_stop_identity_are_present():
    root = __import__('pathlib').Path(__file__).resolve().parents[1] / "scripts/agentic/claw3d"
    invoke = (root / "Invoke-AgentRole.ps1").read_text(encoding="utf-8")
    stop = (root / "Stop-Claw3DAgentBridge.ps1").read_text(encoding="utf-8")
    assert "scripts.agentic.claw3d.cli run" in invoke
    assert "Get-CimInstance Win32_Process" in stop
    assert "scripts.agentic.claw3d.bridge" in stop
    assert "instanceToken" in stop and "processId" in stop and "/health" in stop


def test_documented_wrapper_runs_real_child_when_presence_disabled(tmp_path):
    root = __import__('pathlib').Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env.pop("CLAW3D_LIVE_PRESENCE_ENABLED", None)
    script = root / "scripts/agentic/claw3d/Invoke-AgentRole.ps1"
    expression = f"& '{script}' -Role reviewer -Command @('{sys.executable}','--version')"
    result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", expression],
                            cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode == 0
    assert "Python" in result.stdout
