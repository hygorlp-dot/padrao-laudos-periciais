"""Inicialização explícita do runtime local de desenvolvimento do produto."""

from __future__ import annotations

import argparse
from pathlib import Path
from threading import Event

from .composition import build_product_runtime
from .server import ProductBridgeConfig


def main() -> int:
    parser = argparse.ArgumentParser(description="Inicia o Sistema Pericial local")
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--frontend", required=True, type=Path)
    parser.add_argument("--port", type=int, default=0)
    arguments = parser.parse_args()
    runtime = build_product_runtime(
        arguments.database,
        arguments.frontend,
        config=ProductBridgeConfig(port=arguments.port),
    )
    try:
        runtime.start()
        print(f"Sistema Pericial disponível em {runtime.origin}/", flush=True)
        Event().wait()
    except KeyboardInterrupt:
        return 0
    finally:
        runtime.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
