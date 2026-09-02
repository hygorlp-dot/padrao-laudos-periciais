"""Inicialização explícita do runtime local de desenvolvimento do produto."""

from __future__ import annotations

import argparse
from pathlib import Path
from threading import Event

from .composition import build_product_runtime
from .server import ProductBridgeConfig


def main() -> int:
    # Este modulo compoe apenas o backend, sem o intake PJe -- a arquitetura nao
    # permite que BACKEND conheca a ingestao. Iniciar o produto por aqui daria um
    # sistema silenciosamente degradado: os autos entrariam como documento unico
    # e a analise se declararia completa. A composicao completa vive em PLANNING.
    print(
        "Este nao e o ponto de entrada do produto: iniciado por aqui, o sistema\n"
        "nao reconhece autos do PJe e trata o processo como documento unico.\n\n"
        "Use:\n"
        "  python -m scripts.planejamento_pericial.app_composition \\\n"
        "      --database <caminho> --frontend <caminho> --private-root <caminho>\n",
        flush=True,
    )
    return 2


def _compose_backend_only() -> int:
    parser = argparse.ArgumentParser(description="Inicia o Sistema Pericial local")
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--frontend", required=True, type=Path)
    parser.add_argument("--private-root", required=True, type=Path)
    parser.add_argument("--port", type=int, default=0)
    arguments = parser.parse_args()
    runtime = build_product_runtime(
        arguments.database,
        arguments.frontend,
        private_root=arguments.private_root,
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
