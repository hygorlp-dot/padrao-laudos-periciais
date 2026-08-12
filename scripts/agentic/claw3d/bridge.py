"""Loopback-only HTTP bridge for Claw3D presence."""
from __future__ import annotations

import argparse
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .state import PresenceStore


class PresenceBridge:
    def __init__(self, store: PresenceStore, *, host: str = "127.0.0.1", port: int = 8787, instance_token: str | None = None):
        if host != "127.0.0.1":
            raise ValueError("Claw3D bridge is loopback-only")
        self.store = store
        self.instance_token = instance_token
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path in {"/presence", "/api/office/presence"}:
                    bridge.store.recover_stale()
                    payload, status = bridge.store.snapshot(), 200
                elif self.path == "/health":
                    payload, status = {"status": "ok", "processId": os.getpid()}, 200
                    if bridge.instance_token:
                        payload["instanceToken"] = bridge.instance_token
                else:
                    payload, status = {"error": "not_found"}, 404
                encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, *_args):
                return

        self.server = ThreadingHTTPServer((host, int(port)), Handler)
        self.thread: threading.Thread | None = None

    @property
    def address(self):
        return self.server.server_address

    @property
    def running(self):
        return bool(self.thread and self.thread.is_alive())

    def start(self):
        if not self.running:
            self.thread = threading.Thread(target=self.server.serve_forever, name="claw3d-presence", daemon=True)
            self.thread.start()

    def stop(self):
        if self.running:
            self.server.shutdown()
            self.thread.join(timeout=5)
        self.server.server_close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--instance-token")
    args = parser.parse_args(argv)
    bridge = PresenceBridge(PresenceStore.from_environment(), host=args.host, port=args.port, instance_token=args.instance_token)
    try:
        bridge.server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        bridge.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
