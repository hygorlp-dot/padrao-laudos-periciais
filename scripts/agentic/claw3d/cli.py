"""Small operator CLI used by first-party PowerShell wrappers."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import base64
from .state import AGENTS, PresenceStore
from .capabilities import detect_codex_capability
from .runner import ManagedAgentRunner


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    set_parser = sub.add_parser("set")
    set_parser.add_argument("agent_id", choices=AGENTS)
    set_parser.add_argument("state", choices=("idle", "working", "meeting", "error"))
    sub.add_parser("get")
    sub.add_parser("watchdog")
    capability_parser = sub.add_parser("codex-capability")
    capability_parser.add_argument("--executable", default="codex")
    run_parser = sub.add_parser("run")
    run_parser.add_argument("role", choices=AGENTS)
    run_parser.add_argument("--cwd", default=os.getcwd())
    run_parser.add_argument("--command-json")
    run_parser.add_argument("--command-base64")
    run_parser.add_argument("process_command", nargs="*")
    args = parser.parse_args(argv)
    if args.command == "codex-capability":
        result = detect_codex_capability(executable=args.executable)
        print(json.dumps({"available": result.available, "version": result.version,
                          "non_interactive": result.non_interactive, "command": result.command}))
        return 0
    if args.command == "run":
        if args.command_base64:
            command = json.loads(base64.b64decode(args.command_base64).decode("utf-8"))
        else:
            command = json.loads(args.command_json) if args.command_json else args.process_command
        if not isinstance(command, list) or any(type(part) is not str for part in command):
            parser.error("managed command must be a JSON string array")
        if command[:1] == ["--"]:
            command = command[1:]
        if not command:
            parser.error("managed run requires a command")
        try:
            store = PresenceStore.from_environment()
            runner = ManagedAgentRunner(store=store)
        except Exception:
            return subprocess.run(command, cwd=args.cwd, check=False).returncode
        # There is exactly one execution boundary. Once delegated to the
        # managed runner, no fallback may execute the child a second time.
        result = runner.run(args.role, command, cwd=args.cwd)
        return result.exit_code
    store = PresenceStore.from_environment()
    if args.command == "set":
        store.set_state(args.agent_id, args.state)
    elif args.command == "watchdog":
        store.recover_stale()
    print(json.dumps(store.snapshot(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
