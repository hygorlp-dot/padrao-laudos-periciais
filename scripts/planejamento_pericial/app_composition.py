"""Composition root da aplicacao pericial local.

`config/architecture-policy-v1.json` autoriza PLANNING a depender de BACKEND,
TRIAGE e PJE; BACKEND nao pode depender de nenhum deles. Este e, portanto, o
unico lugar que pode conhecer os dois lados: aqui o adaptador de triagem e
instanciado e injetado na porta que o backend declara, sem que o backend importe
nada de ingestao e sem alargar a politica.

A inversao e real: nao ha import dinamico, service locator, monkey patch nem
consulta a variavel de ambiente para escolher classe. O backend recebe um objeto
e o usa pelo comportamento.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from threading import Event

from scripts.backend_contract.local_api.composition import build_local_api
from scripts.backend_contract.product_bridge.composition import build_product_runtime
from scripts.backend_contract.product_bridge.server import ProductBridgeConfig
from scripts.triagem_pericial.pje_intake_adapter import PjeIntakeAdapter


def build_pericial_local_api(
    database: str | Path,
    *,
    private_root: str | Path | None = None,
    token: str | None = None,
    config: object | None = None,
):
    """Local API composta com o intake PJe injetado.

    Mesma composicao que a aplicacao usa; existe separada apenas porque a Local
    API pode ser levantada sem o build do frontend.
    """
    return build_local_api(
        database,
        private_root=private_root,
        token=token,
        config=config,
        pje_intake=PjeIntakeAdapter(),
    )


def build_pericial_application(
    database: str | Path,
    frontend_root: str | Path,
    *,
    private_root: str | Path | None = None,
    config: ProductBridgeConfig | None = None,
    token: str | None = None,
):
    """Aplicacao completa: backend local com o intake PJe ja injetado."""
    return build_product_runtime(
        database,
        frontend_root,
        private_root=private_root,
        config=config,
        token=token,
        pje_intake=PjeIntakeAdapter(),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inicia o Sistema Pericial local")
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--frontend", required=True, type=Path)
    parser.add_argument("--private-root", required=True, type=Path)
    parser.add_argument("--port", type=int, default=0)
    arguments = parser.parse_args(argv)
    runtime = build_pericial_application(
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
