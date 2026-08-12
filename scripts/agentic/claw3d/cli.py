"""Small operator CLI used by first-party PowerShell wrappers."""
from __future__ import annotations

import argparse
import json
from .state import AGENTS, PresenceStore


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    set_parser = sub.add_parser("set")
    set_parser.add_argument("agent_id", choices=AGENTS)
    set_parser.add_argument("state", choices=("idle", "working", "meeting", "error"))
    sub.add_parser("get")
    sub.add_parser("watchdog")
    args = parser.parse_args(argv)
    store = PresenceStore.from_environment()
    if args.command == "set":
        store.set_state(args.agent_id, args.state)
    elif args.command == "watchdog":
        store.recover_stale()
    print(json.dumps(store.snapshot(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
