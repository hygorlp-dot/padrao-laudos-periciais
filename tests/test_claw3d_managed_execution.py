import json
import os
import subprocess
import sys
import time
import socket
import threading
from pathlib import Path

from urllib.request import urlopen

import pytest

from scripts.agentic.claw3d import AGENTS, ClaudeManagedRunner, PresenceBridge, PresenceStore
from scripts.agentic.claw3d.capabilities import detect_codex_capability
from scripts.agentic.claw3d.runner import ManagedAgentRunner
from scripts.agentic.claw3d import cli as claw_cli


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


def test_process_start_failure_never_fabricates_working(tmp_path):
    store = PresenceStore(tmp_path)
    runner = ManagedAgentRunner(store=store)
    try:
        runner.start("implementer", ["definitely-not-a-real-program"])
    except OSError:
        pass
    assert state(store, "implementer") == "idle"


def test_working_is_published_only_after_real_process_exists(tmp_path, monkeypatch):
    store = PresenceStore(tmp_path)
    entered, release = threading.Event(), threading.Event()

    def blocked_popen(*_args, **_kwargs):
        entered.set()
        release.wait(2)
        raise OSError("synthetic spawn failure")

    monkeypatch.setattr(subprocess, "Popen", blocked_popen)
    errors = []
    thread = threading.Thread(target=lambda: _capture_start_error(
        ManagedAgentRunner(store=store), errors, tmp_path
    ))
    thread.start()
    assert entered.wait(1)
    assert state(store, "reviewer") == "idle"
    assert store.internal_state()["executions"] == {}
    release.set(); thread.join(2)
    assert errors and state(store, "reviewer") == "idle"


def _capture_start_error(runner, errors, cwd):
    try:
        runner.start("reviewer", ["synthetic"], cwd=cwd)
    except OSError as exc:
        errors.append(exc)


def test_slow_presence_store_never_delays_real_process_spawn(tmp_path):
    spawned_at = tmp_path / "spawned.txt"

    class SlowStore:
        def begin_execution(self, *_args, **_kwargs): time.sleep(.4)
        def heartbeat_execution(self, *_args, **_kwargs): pass
        def finish_execution(self, *_args, **_kwargs): pass

    started = time.monotonic()
    execution = ManagedAgentRunner(store=SlowStore(), heartbeat_seconds=.01).start(
        "reviewer", [sys.executable, "-c", f"from pathlib import Path; Path({str(spawned_at)!r}).write_text('ok')"]
    )
    deadline = time.monotonic() + .25
    while not spawned_at.exists() and time.monotonic() < deadline:
        time.sleep(.01)
    assert spawned_at.read_text() == "ok"
    assert time.monotonic() - started < .3
    assert execution.wait() == 0


@pytest.mark.parametrize("blocked_method", ["begin_execution", "heartbeat_execution", "finish_execution"])
def test_blocked_presence_store_never_delays_child_completion(tmp_path, blocked_method):
    release = threading.Event()

    class BlockingStore:
        def begin_execution(self, *_args, **_kwargs):
            if blocked_method == "begin_execution": release.wait(5)
        def heartbeat_execution(self, *_args, **_kwargs):
            if blocked_method == "heartbeat_execution": release.wait(5)
        def finish_execution(self, *_args, **_kwargs):
            if blocked_method == "finish_execution": release.wait(5)

    try:
        started = time.monotonic()
        result = ManagedAgentRunner(store=BlockingStore(), heartbeat_seconds=.01).run(
            "reviewer", [sys.executable, "-c", "raise SystemExit(6)"]
        )
        assert result.exit_code == 6
        assert time.monotonic() - started < 1
    finally:
        release.set()


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
    assert "scripts.agentic.claw3d.cli" in invoke and "--command-base64" in invoke
    assert "Get-CimInstance Win32_Process" in stop
    assert "scripts.agentic.claw3d.bridge" in stop
    assert "instanceToken" in stop and "processId" in stop and "/health" in stop
    start = (root / "Start-Claw3DAgentBridge.ps1").read_text(encoding="utf-8")
    assert "identity persistence failed; started process was terminated" in start


@__import__('pytest').mark.parametrize("enabled", [False, True])
def test_documented_wrapper_runs_real_child(tmp_path, enabled):
    root = __import__('pathlib').Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    if enabled:
        env["CLAW3D_LIVE_PRESENCE_ENABLED"] = "1"
        env["CLAW3D_AGENT_STATE_DIR"] = str(tmp_path / "runtime")
    else:
        env.pop("CLAW3D_LIVE_PRESENCE_ENABLED", None)
    script = root / "scripts/agentic/claw3d/Invoke-AgentRole.ps1"
    expression = f"& '{script}' -Role reviewer -Executable '{sys.executable}' -ArgumentList @('--version')"
    result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", expression],
                            cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode == 0
    assert "Python" in result.stdout


def test_enabled_wrapper_store_failure_does_not_block_child(tmp_path):
    root = __import__('pathlib').Path(__file__).resolve().parents[1]
    invalid_state = tmp_path / "not-a-directory"
    invalid_state.write_text("x")
    env = dict(os.environ, CLAW3D_LIVE_PRESENCE_ENABLED="1", CLAW3D_AGENT_STATE_DIR=str(invalid_state))
    script = root / "scripts/agentic/claw3d/Invoke-AgentRole.ps1"
    expression = f"& '{script}' -Role reviewer -Executable '{sys.executable}' -ArgumentList @('--version')"
    result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", expression],
                            cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode == 0
    assert "Python" in result.stdout


def test_observability_failure_never_executes_command_twice(tmp_path, monkeypatch):
    marker = tmp_path / "executions.txt"
    command = [sys.executable, "-c", f"from pathlib import Path; p=Path({str(marker)!r}); p.write_text((p.read_text() if p.exists() else '')+'x')"]

    class PostSpawnFailure:
        def __init__(self, **_kwargs): pass
        def run(self, *_args, **_kwargs):
            subprocess.run(command, check=True)
            raise RuntimeError("observability failed after spawn")

    monkeypatch.setattr(claw_cli, "ManagedAgentRunner", PostSpawnFailure)
    with pytest.raises(RuntimeError):
        claw_cli.main(["run", "reviewer", "--command-json", json.dumps(command)])
    assert marker.read_text() == "x"


def test_store_initialization_failure_executes_child_once(tmp_path, monkeypatch):
    marker = tmp_path / "executions.txt"
    command = [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).write_text('x')"]
    monkeypatch.setattr(claw_cli.PresenceStore, "from_environment", classmethod(lambda cls: (_ for _ in ()).throw(OSError("store"))))
    assert claw_cli.main(["run", "reviewer", "--command-json", json.dumps(command)]) == 0
    assert marker.read_text() == "x"


def test_child_nonzero_exit_is_not_retried(tmp_path):
    marker = tmp_path / "executions.txt"
    command = [sys.executable, "-c", f"from pathlib import Path; p=Path({str(marker)!r}); p.write_text('x'); raise SystemExit(9)"]
    assert claw_cli.main(["run", "reviewer", "--command-json", json.dumps(command)]) == 9
    assert marker.read_text() == "x"


def test_command_argv_is_preserved_without_shell(tmp_path):
    output = tmp_path / "argv.json"
    arguments = ["space value", 'quote"value', "unicode-ç", "&|;$()", "", "x" * 4096]
    command = [sys.executable, "-c", "import json,sys;from pathlib import Path;Path(sys.argv[1]).write_text(json.dumps(sys.argv[2:],ensure_ascii=False),encoding='utf-8')", str(output), *arguments]
    result = ManagedAgentRunner(store=PresenceStore(tmp_path / "state"), heartbeat_seconds=.01).run("implementer", command, cwd=tmp_path)
    assert result.exit_code == 0
    assert json.loads(output.read_text(encoding="utf-8")) == arguments


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _powershell(script, *arguments, env):
    return subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *map(str, arguments)],
                          capture_output=True, text=True, env=env, timeout=20)


def test_start_stop_start_cycle_is_idempotent(tmp_path):
    root = Path(__file__).resolve().parents[1]
    scripts = root / "scripts/agentic/claw3d"
    port = _free_port()
    env = dict(os.environ, CLAW3D_LIVE_PRESENCE_ENABLED="1", CLAW3D_AGENT_STATE_DIR=str(tmp_path))
    start, stop = scripts / "Start-Claw3DAgentBridge.ps1", scripts / "Stop-Claw3DAgentBridge.ps1"
    try:
        first = _powershell(start, "-Port", port, env=env)
        assert first.returncode == 0 and "ready" in first.stdout.casefold()
        identity = json.loads((tmp_path / "bridge.pid").read_text())
        second = _powershell(start, "-Port", port, env=env)
        assert second.returncode == 0
        assert json.loads((tmp_path / "bridge.pid").read_text())["pid"] == identity["pid"]
        assert _powershell(stop, "-Port", port, env=env).returncode == 0
        assert _powershell(start, "-Port", port, env=env).returncode == 0
    finally:
        _powershell(stop, "-Port", port, env=env)


def test_parallel_start_attempts_create_single_bridge(tmp_path):
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts/agentic/claw3d/Start-Claw3DAgentBridge.ps1"
    stop = root / "scripts/agentic/claw3d/Stop-Claw3DAgentBridge.ps1"
    port = _free_port()
    env = dict(os.environ, CLAW3D_LIVE_PRESENCE_ENABLED="1", CLAW3D_AGENT_STATE_DIR=str(tmp_path))
    command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Port", str(port)]
    processes = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env) for _ in range(2)]
    try:
        results = [process.communicate(timeout=20) + (process.returncode,) for process in processes]
        assert [item[2] for item in results] == [0, 0]
        identity = json.loads((tmp_path / "bridge.pid").read_text())
        with urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
            assert json.load(response)["processId"] == identity["pid"]
    finally:
        _powershell(stop, "-Port", port, env=env)


def test_first_party_orphan_bridge_is_detected_and_not_killed(tmp_path):
    root = Path(__file__).resolve().parents[1]
    port = _free_port()
    env = dict(os.environ, CLAW3D_AGENT_STATE_DIR=str(tmp_path))
    process = subprocess.Popen([sys.executable, "-m", "scripts.agentic.claw3d.bridge", "--port", str(port), "--instance-token", "orphan"], cwd=root, env=env)
    stop = root / "scripts/agentic/claw3d/Stop-Claw3DAgentBridge.ps1"
    try:
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                urlopen(f"http://127.0.0.1:{port}/health", timeout=.2).close(); break
            except OSError: time.sleep(.05)
        result = _powershell(stop, "-Port", port, env=env)
        assert result.returncode != 0
        assert process.poll() is None
    finally:
        process.terminate(); process.wait(timeout=5)


def test_stale_pid_file_does_not_kill_reused_pid(tmp_path):
    root = Path(__file__).resolve().parents[1]
    port = _free_port()
    innocent = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(10)"])
    (tmp_path / "bridge.pid").write_text(json.dumps({"pid": innocent.pid, "module":"scripts.agentic.claw3d.bridge", "port":port, "instanceToken":"stale"}))
    env = dict(os.environ, CLAW3D_AGENT_STATE_DIR=str(tmp_path))
    try:
        result = _powershell(root / "scripts/agentic/claw3d/Stop-Claw3DAgentBridge.ps1", "-Port", port, env=env)
        assert result.returncode != 0
        assert innocent.poll() is None
    finally:
        innocent.terminate(); innocent.wait(timeout=5)


def test_stale_missing_pid_does_not_claim_orphan_bridge_stopped(tmp_path):
    root = Path(__file__).resolve().parents[1]
    port = _free_port()
    env = dict(os.environ, CLAW3D_AGENT_STATE_DIR=str(tmp_path))
    bridge = subprocess.Popen([sys.executable, "-m", "scripts.agentic.claw3d.bridge", "--port", str(port), "--instance-token", "live"], cwd=root, env=env)
    (tmp_path / "bridge.pid").write_text(json.dumps({"pid": 999999, "module":"scripts.agentic.claw3d.bridge", "port":port, "instanceToken":"stale"}))
    try:
        deadline = time.time() + 5
        while time.time() < deadline:
            try: urlopen(f"http://127.0.0.1:{port}/health", timeout=.2).close(); break
            except OSError: time.sleep(.05)
        result = _powershell(root / "scripts/agentic/claw3d/Stop-Claw3DAgentBridge.ps1", "-Port", port, env=env)
        assert result.returncode != 0
        assert bridge.poll() is None
        assert (tmp_path / "bridge.pid").exists()
    finally:
        bridge.terminate(); bridge.wait(timeout=5)


def test_foreign_process_on_bridge_port_is_never_killed_and_start_leaves_no_pid(tmp_path):
    root = Path(__file__).resolve().parents[1]
    port = _free_port()
    foreign = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
                               cwd=tmp_path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    env = dict(os.environ, CLAW3D_LIVE_PRESENCE_ENABLED="1", CLAW3D_AGENT_STATE_DIR=str(tmp_path / "state"))
    try:
        time.sleep(.2)
        result = _powershell(root / "scripts/agentic/claw3d/Start-Claw3DAgentBridge.ps1", "-Port", port, env=env)
        assert result.returncode != 0
        assert foreign.poll() is None
        assert not (tmp_path / "state/bridge.pid").exists()
    finally:
        foreign.terminate(); foreign.wait(timeout=5)


def test_parallel_start_stop_collision_is_serialized(tmp_path):
    root = Path(__file__).resolve().parents[1]
    scripts = root / "scripts/agentic/claw3d"
    port = _free_port()
    env = dict(os.environ, CLAW3D_LIVE_PRESENCE_ENABLED="1", CLAW3D_AGENT_STATE_DIR=str(tmp_path))
    start_cmd = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(scripts / "Start-Claw3DAgentBridge.ps1"), "-Port", str(port)]
    stop_cmd = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(scripts / "Stop-Claw3DAgentBridge.ps1"), "-Port", str(port)]
    starter = subprocess.Popen(start_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    time.sleep(.05)
    stopper = subprocess.Popen(stop_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    start_output = starter.communicate(timeout=20)
    stop_output = stopper.communicate(timeout=20)
    try:
        assert starter.returncode == stopper.returncode == 0, (start_output, stop_output)
        assert not (tmp_path / "bridge.pid").exists()
        with pytest.raises(OSError):
            urlopen(f"http://127.0.0.1:{port}/health", timeout=.2)
    finally:
        _powershell(scripts / "Stop-Claw3DAgentBridge.ps1", "-Port", port, env=env)


def test_wrong_port_stop_and_second_port_start_never_orphan_bridge(tmp_path):
    root = Path(__file__).resolve().parents[1]
    scripts = root / "scripts/agentic/claw3d"
    first_port, second_port = _free_port(), _free_port()
    env = dict(os.environ, CLAW3D_LIVE_PRESENCE_ENABLED="1", CLAW3D_AGENT_STATE_DIR=str(tmp_path))
    start, stop = scripts / "Start-Claw3DAgentBridge.ps1", scripts / "Stop-Claw3DAgentBridge.ps1"
    try:
        assert _powershell(start, "-Port", first_port, env=env).returncode == 0
        identity = json.loads((tmp_path / "bridge.pid").read_text())
        wrong_stop = _powershell(stop, "-Port", second_port, env=env)
        assert wrong_stop.returncode != 0
        assert json.loads((tmp_path / "bridge.pid").read_text())["pid"] == identity["pid"]
        assert _powershell(start, "-Port", second_port, env=env).returncode != 0
        with urlopen(f"http://127.0.0.1:{first_port}/health", timeout=2) as response:
            assert json.load(response)["processId"] == identity["pid"]
    finally:
        _powershell(stop, "-Port", first_port, env=env)
