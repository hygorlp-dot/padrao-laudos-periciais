import json
from pathlib import Path

import pytest

from scripts.backend_contract.errors import DomainError
from scripts.conhecimento_privado.pesquisa_online import EgressPolicy, MockSearchProvider, buscar_seguro, cache_valido
from scripts.planejamento_pericial.gerar_processo import gerar as gerar_processo
from scripts.planejamento_pericial.migracoes import migrar_plano
from scripts.planejamento_pericial.validar_plano import recalcular_execucao, validar
from scripts.quality.verify_core import run_gate


ROOT = Path(__file__).resolve().parents[1]


def test_truncated_json_never_yields_partial_approval(tmp_path):
    path = tmp_path / "plano.json"
    path.write_text('{"schema_version": "2.0.0",', encoding="utf-8")
    errors = validar(path)
    assert errors and "JSON inválido" in errors[0]


def test_structurally_valid_but_semantically_empty_coverage_fails_closed(tmp_path):
    plan = json.loads((ROOT / "tests/fixtures/planejamento/plano-vistoria-valido.json").read_text(encoding="utf-8"))
    plan["requisitos_cobertura"] = []
    path = tmp_path / "plano.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    assert validar(path)


def test_unknown_schema_version_and_migration_failure_are_explicit():
    plan = json.loads((ROOT / "tests/fixtures/planejamento/plano-vistoria-valido.json").read_text(encoding="utf-8"))
    plan["schema_version"] = "999.0.0"
    with pytest.raises(DomainError):
        migrar_plano(plan)


def test_missing_required_artifact_does_not_create_process_output(tmp_path):
    with pytest.raises(FileNotFoundError):
        gerar_processo(tmp_path)
    assert not (tmp_path / "processo.json").exists()


def test_missing_reference_or_partial_catalog_never_satisfies_coverage():
    plan = {"medicoes":[{"id":"MED-PLANO-001","grandeza":"abertura","local":"Sala","criterio":"mm","questoes_tecnicas":["QT-001"]}],
            "requisitos_cobertura":[{"questao_tecnica":"QT-001","tipo":"MEDICAO","obrigatoriedade":"OBRIGATORIA","item_planejado":"MED-PLANO-001"}]}
    inspection = {"medicoes":[],"cobertura":[{"planejado":"MED-PLANO-001","status":"EXECUTADO","executado":["MED-INEXISTENTE"]}]}
    result = recalcular_execucao(plan, inspection)
    assert result["apto"] is False
    assert result["faltantes"]


def test_subprocess_failure_makes_safety_gate_fail_closed(tmp_path):
    (tmp_path / "config").mkdir()
    # Direct checks fail before subprocesses too; the important invariant is never PASS.
    result = run_gate("fast", tmp_path, runner=lambda *args, **kwargs: type("R", (), {"returncode": 1, "stdout": "", "stderr": "fault"})(), tracked_files=[])
    assert result.result == "FAIL"
    assert result.exit_code == 1


@pytest.mark.parametrize("error,status", [(TimeoutError(), "TIMEOUT"), (OSError(), "SEARCH_PROVIDER_INDISPONIVEL"), (RuntimeError(), "ERRO_PROVIDER")])
def test_external_provider_fault_is_explicit_and_leaks_no_query(error, status):
    provider = MockSearchProvider(erro=error)
    result = buscar_seguro("consulta pública", provider, EgressPolicy(permitir_egress=True))
    assert result["status"] == status
    assert result["consulta"] is None
    assert result["resultados"] == []


@pytest.mark.parametrize("metadata", [{}, {"acessado_em":"corrompido"}, {"acessado_em":None}])
def test_corrupt_cache_never_becomes_valid(metadata):
    assert cache_valido(metadata) is False


def test_producer_blocked_state_is_not_trusted_as_partial_success():
    plan = {"requisitos_cobertura": []}
    result = recalcular_execucao(plan, {"cobertura": [{"status":"EXECUTADO"}]})
    assert result == {"apto": False, "faltantes": [{"questao_tecnica": None, "tipo": None, "item_planejado": None, "motivo": "SEM_REQUISITOS_COBERTURA"}]}
