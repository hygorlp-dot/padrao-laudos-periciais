import json
from pathlib import Path

from scripts.quality.historical_mutations import _copy_workspace, execute_historical_suite, load_mutants, validate_mutant_definitions
from scripts.redacao_pericial.autocorrigir_redacao import autocorrigir
from scripts.triagem_pericial.gerar_delimitacao import _classificar_pertinencia


ROOT = Path(__file__).resolve().parents[1]


def test_historical_sandbox_ignores_unrelated_temporary_artifacts(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    (source / "tracked").mkdir(parents=True)
    (source / "tracked/module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (source / "untracked-temp").mkdir()
    (source / "untracked-temp/probe.txt").write_text("must not be read\n", encoding="utf-8")
    _copy_workspace(source, target)

    assert (target / "tracked/module.py").is_file()
    assert not (target / "untracked-temp").exists()


def test_historical_mutant_definitions_are_complete_and_applicable():
    mutants = load_mutants(ROOT)
    assert {item["id"] for item in mutants} == {f"MUT-{number:03d}" for number in range(1, 11)}
    assert validate_mutant_definitions(mutants, ROOT) == []


def test_historical_critical_mutants_are_all_killed():
    result = execute_historical_suite(ROOT)
    assert result["total"] == 10
    assert result["killed"] == 10
    assert result["survived"] == []
    assert result["invalid"] == []


def test_historical_suite_fails_closed_for_survivor(tmp_path):
    source = tmp_path / "sample.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_sample.py").write_text("def test_unrelated(): assert True\n", encoding="utf-8")
    mutant = [{"id":"MUT-999","source":"sample.py","search":"VALUE = 1","replacement":"VALUE = 2","test":"tests/test_sample.py"}]
    result = execute_historical_suite(tmp_path, mutants=mutant)
    assert result["survived"] == ["MUT-999"]
    assert result["killed"] == 0


def test_mutant_definition_requires_real_unique_replacement():
    mutants = load_mutants(ROOT)
    broken = json.loads(json.dumps(mutants))
    broken[0]["search"] = "texto inexistente"
    findings = validate_mutant_definitions(broken, ROOT)
    assert any(item["code"] == "MUTATION_SEARCH_NOT_UNIQUE" for item in findings)


def test_classificacao_title_is_immutable_without_claim_metadata():
    text = "É importante destacar que Classificação: CRÍTICA."
    redaction = {"blocos": [{"pat_id": "PAT-001", "titulos": ["Classificação"], "textos": [text], "claim_ids": []}], "claims": []}
    corrected, changes = autocorrigir(redaction, [{"tipo": "ABERTURA_GENERICA", "severidade": "EDITORIAL"}])
    assert corrected["blocos"][0]["textos"] == [text]
    assert changes == []


def test_valor_da_causa_is_juridical_without_other_legal_marker():
    assert _classificar_pertinencia("Qual é o valor da causa?", False) == "MATERIA_JURIDICA"
