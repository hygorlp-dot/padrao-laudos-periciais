"""Configuração comum da suíte.

O único ajuste aqui é de HARNESS, não de produto: as propriedades Hypothesis
deste repositório são puras e em memória, então o prazo de parede padrão (200 ms
por exemplo) não mede invariante nenhuma — só mede quanta CPU o resto da suíte
está consumindo no momento. Mantê-lo transformava a suíte em fonte de falhas
intermitentes sem significado de produto. O número de exemplos permanece o
padrão: nada de cobertura é abdicado.
"""

from __future__ import annotations

import json
import sys

from hypothesis import HealthCheck, settings

_FAILED_NODEIDS: set[str] = set()


def _failure_summary_line(nodeids: set[str]) -> str:
    payload = json.dumps(sorted(nodeids), ensure_ascii=True, separators=(",", ":"))
    return f"PYTEST_FAILED_NODEIDS={payload}"


def pytest_runtest_logreport(report: object) -> None:
    """Retain only repository-owned test identities, never failure payloads."""

    if getattr(report, "failed", False):
        nodeid = getattr(report, "nodeid", None)
        if type(nodeid) is str and nodeid:
            _FAILED_NODEIDS.add(nodeid)


def pytest_unconfigure(config: object) -> None:
    """Make failed identities the last stderr line captured by verify_core."""

    if _FAILED_NODEIDS:
        print(_failure_summary_line(_FAILED_NODEIDS), file=sys.stderr, flush=True)


settings.register_profile(
    "pericial",
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile("pericial")
