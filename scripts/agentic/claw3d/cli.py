"""Small operator CLI used by first-party PowerShell wrappers."""
from __future__ import annotations

import argparse
import json
import os
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
    run_parser.add_argument("process_command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    store = PresenceStore.from_environment()
    if args.command == "codex-capability":
        result = detect_codex_capability(executable=args.executable)
        print(json.dumps({"available": result.available, "version": result.version,
                          "non_interactive": result.non_interactive, "command": result.command}))
        return 0
    if args.command == "run":
        command = args.process_command
        if command[:1] == ["--"]:
            command = command[1:]
        if not command:
            parser.error("managed run requires a command")
        result = ManagedAgentRunner(store=store).run(args.role, command, cwd=args.cwd)
        return result.exit_code
    if args.command == "set":
        store.set_state(args.agent_id, args.state)
    elif args.command == "watchdog":
        store.recover_stale()
    print(json.dumps(store.snapshot(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
