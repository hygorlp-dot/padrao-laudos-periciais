"""Prova arquitetural: BACKEND nao conhece PJE nem TRIAGE.

`config/architecture-policy-v1.json` da a BACKEND `allowedDependencies: []`, e
PJE/TRIAGE sao componentes proprios. A primeira versao do intake PJe importava
`scripts.extracao_pje` de dentro de `scripts/backend_contract/`, o que o
ARCHITECTURE_ANALYZER_V1 acusa como BACKEND->PJE / SUPPORT->INGESTION.

A politica nao foi alterada nem excepcionada: a dependencia foi invertida. O
backend declara uma porta e recebe a implementacao por injecao; a implementacao
vive em TRIAGE (que pode depender de PJE); a composicao vive em PLANNING (que a
politica ja autoriza a depender de BACKEND, TRIAGE e PJE).

Estes testes leem o codigo-fonte, entao valem mesmo que o import esteja dentro
de uma funcao -- que foi exatamente como a violacao original passou despercebida
em revisao de leitura.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "scripts" / "backend_contract"
TRIAGE = ROOT / "scripts" / "triagem_pericial"
FORBIDDEN_FOR_BACKEND = ("scripts.extracao_pje", "scripts.triagem_pericial", "scripts.planejamento_pericial")


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            modules.add(node.module)
    return modules


@pytest.mark.parametrize("source", sorted(BACKEND.rglob("*.py")), ids=lambda p: p.name)
def test_backend_never_imports_an_ingestion_or_domain_component(source: Path) -> None:
    offending = sorted(
        module for module in _imported_modules(source)
        if module.startswith(FORBIDDEN_FOR_BACKEND)
    )
    assert offending == [], f"{source.relative_to(ROOT).as_posix()} depende de {offending}"


def test_the_triage_adapter_never_imports_the_backend() -> None:
    """TRIAGE fornece um objeto compativel por comportamento, sem importar BACKEND."""
    adapter = TRIAGE / "pje_intake_adapter.py"
    assert adapter.is_file(), "adapter de intake PJe ausente em TRIAGE"
    offending = sorted(
        module for module in _imported_modules(adapter)
        if module.startswith("scripts.backend_contract")
    )
    assert offending == [], f"adapter TRIAGE depende de BACKEND: {offending}"


def test_the_planning_composition_root_is_the_only_place_that_knows_both_sides() -> None:
    composition = ROOT / "scripts" / "planejamento_pericial" / "app_composition.py"
    assert composition.is_file(), "composition root ausente em PLANNING"
    modules = _imported_modules(composition)
    assert any(module.startswith("scripts.backend_contract") for module in modules)
    assert any(module.startswith("scripts.triagem_pericial") for module in modules)
