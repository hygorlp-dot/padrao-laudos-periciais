"""Produto real com a derivacao PJe retida, para o oraculo de ingestao (#266).

Usa a MESMA composicao do produto (`build_product_runtime` com o adaptador PJe de
producao); a unica diferenca e que a leitura do export so prossegue quando o
arquivo-portao existe. O oraculo sobe este processo, importa, confirma o estado
PROCESSING e mata o processo no meio da derivacao -- a interrupcao real que um
documento grande produz quando o perito fecha o produto.

Somente teste: nenhum codigo de producao conhece este modulo.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path
from threading import Event

from scripts.backend_contract.product_bridge.composition import build_product_runtime
from scripts.backend_contract.product_bridge.server import ProductBridgeConfig
from scripts.planejamento_pericial.construction_defect_analysis_adapter import ConstructionDefectAnalysisAdapter
from scripts.triagem_pericial.pje_intake_adapter import PjeIntakeAdapter


class _GatedPjeIntake:
    def __init__(self, gate: Path):
        self._inner = PjeIntakeAdapter()
        self._gate = gate

    def logical_inventory(self, pdf, workdir):
        while not self._gate.exists():
            time.sleep(0.05)
        return self._inner.logical_inventory(pdf, workdir)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--frontend", required=True, type=Path)
    parser.add_argument("--private-root", required=True, type=Path)
    parser.add_argument("--gate", required=True, type=Path)
    arguments = parser.parse_args()
    runtime = build_product_runtime(
        arguments.database, arguments.frontend, private_root=arguments.private_root,
        pje_intake=_GatedPjeIntake(arguments.gate),
        construction_defect_analysis=ConstructionDefectAnalysisAdapter(),
        # Janela curta: a resposta "aceito, processando" chega logo.
        config=ProductBridgeConfig(port=0, upstream_timeout_seconds=3.0),
    )
    try:
        runtime.start()
        print(f"Sistema Pericial disponível em {runtime.origin}/", flush=True)
        Event().wait()
    finally:
        runtime.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
