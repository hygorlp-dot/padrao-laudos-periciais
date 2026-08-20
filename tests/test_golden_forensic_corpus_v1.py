"""Golden Forensic Corpus V1 runner tests.

Part of POST_TOOLING_MAINTAINABILITY_SEQUENCE_V1 Stage 2 (Issue #78,
docs/stabilization/golden-forensic-corpus-v1-design.md). Exercises
scripts/quality/golden_corpus.py's own comparison/replay/RAISES logic and
drives every registered golden-corpus fixture end to end against its real
hotspot entrypoint, so a behavioral drift in any of the 5 characterized
hotspots (docs/stabilization/hotspot-characterization-v1.md) is caught here
before MAINTAINABILITY_REFACTORING_V1 touches them.

The per-hotspot adapters live here, not in scripts/quality/golden_corpus.py:
QUALITY (scripts/quality/, layer GOVERNANCE) may only depend on AGENTIC
(config/architecture-policy-v1.json) and may not import DOMAIN modules
(MOTOR/TRIAGE/INSPECTION/PJE). tests/ sits outside productionRoots, so it is
free to import domain code directly -- the same pattern every other test
file in this repository already uses.
"""
import json
import tempfile
import unittest
from pathlib import Path

from scripts.extracao_pje.validar_integridade import validar_integridade
from scripts.motor_vicios.autocorrigir import autocorrigir
from scripts.motor_vicios.motor import executar as motor_executar
from scripts.quality.golden_corpus import (
    ROOT,
    _canonical,
    _check_no_real_case_private_data,
    _materialize,
    _pop_path,
    _run_case,
    build_coverage_map,
    load_corpus,
    validate_golden_corpus,
)
from scripts.triagem_pericial.gerar_delimitacao import gerar as gerar_delimitacao
from scripts.vistoria_estruturada.gerar_vistoria import gerar as gerar_vistoria


def _adapter_motor(case_input):
    return motor_executar(**case_input)


def _adapter_vistoria(case_input):
    return gerar_vistoria(**case_input)


def _adapter_delimitacao(case_input):
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        diretorio = base / "casos" / "caso-001" / "derivados"
        diretorio.mkdir(parents=True, exist_ok=True)
        _materialize(diretorio, case_input.get("diretorio_layout", {}))
        private_root = diretorio.parent.parent
        _materialize(private_root, case_input.get("private_root_layout", {}))
        return gerar_delimitacao(diretorio)


def _adapter_validar_integridade(case_input):
    erros, alertas = validar_integridade(case_input["manifesto"])
    return {"erros": erros, "alertas": alertas}


def _adapter_autocorrigir(case_input):
    final, historico = autocorrigir(
        case_input["resultado"], case_input["claims"], case_input["auditorias"], case_input.get("achados")
    )
    return {"final": final, "historico": historico}


ADAPTERS = {
    "HOTSPOT-01": _adapter_motor,
    "HOTSPOT-02": _adapter_vistoria,
    "HOTSPOT-03": _adapter_delimitacao,
    "HOTSPOT-04": _adapter_validar_integridade,
    "HOTSPOT-05": _adapter_autocorrigir,
}


class GoldenCorpusRunnerLogicTest(unittest.TestCase):
    def test_pop_path_removes_nested_dotted_key(self):
        payload = {"a": {"b": {"c": 1, "d": 2}}}
        _pop_path(payload, "a.b.c")
        self.assertEqual(payload, {"a": {"b": {"d": 2}}})

    def test_pop_path_is_a_noop_when_path_absent(self):
        payload = {"a": {"b": 1}}
        _pop_path(payload, "a.x.y")
        self.assertEqual(payload, {"a": {"b": 1}})

    def test_canonical_ignores_declared_non_semantic_fields(self):
        left = {"a": 1, "wall_clock": "2026-01-01T00:00:00Z"}
        right = {"a": 1, "wall_clock": "DIFFERENT"}
        self.assertEqual(_canonical(left, ["wall_clock"]), _canonical(right, ["wall_clock"]))

    def test_canonical_is_sensitive_to_ignored_field_omission(self):
        left = {"a": 1, "wall_clock": "2026-01-01T00:00:00Z"}
        right = {"a": 1, "wall_clock": "DIFFERENT"}
        self.assertNotEqual(_canonical(left, []), _canonical(right, []))

    def test_run_case_exact_match_produces_no_findings(self):
        case = {
            "case_id": "GC-TEST-001", "purpose": "caso de teste", "status": "APPROVED",
            "semantic_families": ["engine_decision"], "invariants_exercised": ["FAIL_CLOSED"],
            "input": {"x": 1}, "expected_output_mode": "EXACT", "expected_output": {"x": 1, "y": 2},
        }
        findings = _run_case(case, "HOTSPOT-TEST", lambda payload: {**payload, "y": 2})
        self.assertEqual(findings, [])

    def test_run_case_exact_mismatch_is_a_finding(self):
        case = {
            "case_id": "GC-TEST-002", "purpose": "caso de teste", "status": "APPROVED",
            "semantic_families": ["engine_decision"], "invariants_exercised": ["FAIL_CLOSED"],
            "input": {"x": 1}, "expected_output_mode": "EXACT", "expected_output": {"x": 1, "y": 99},
        }
        findings = _run_case(case, "HOTSPOT-TEST", lambda payload: {**payload, "y": 2})
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["motivo"], "GOLDEN_OUTPUT_DIVERGENTE")
        self.assertIn("FAIL_CLOSED", findings[0]["invariant"])

    def test_run_case_raises_with_matching_exception_produces_no_findings(self):
        case = {
            "case_id": "GC-TEST-003", "purpose": "caso de teste", "status": "APPROVED",
            "semantic_families": ["engine_decision"], "invariants_exercised": ["FAIL_CLOSED"],
            "input": {}, "expected_output_mode": "RAISES",
            "expected_output": {"raises": {"type": "ValueError", "message_contains": "bloqueada"}},
        }

        def _adapter(_payload):
            raise ValueError("triagem bloqueada")

        self.assertEqual(_run_case(case, "HOTSPOT-TEST", _adapter), [])

    def test_run_case_raises_with_wrong_exception_type_is_a_finding(self):
        case = {
            "case_id": "GC-TEST-004", "purpose": "caso de teste", "status": "APPROVED",
            "semantic_families": ["engine_decision"], "invariants_exercised": ["FAIL_CLOSED"],
            "input": {}, "expected_output_mode": "RAISES",
            "expected_output": {"raises": {"type": "ValueError", "message_contains": None}},
        }

        def _adapter(_payload):
            raise KeyError("campo ausente")

        findings = _run_case(case, "HOTSPOT-TEST", _adapter)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["motivo"], "RAISES_TIPO_DIVERGENTE")

    def test_run_case_raises_expected_but_no_exception_is_a_finding(self):
        case = {
            "case_id": "GC-TEST-005", "purpose": "caso de teste", "status": "APPROVED",
            "semantic_families": ["engine_decision"], "invariants_exercised": ["FAIL_CLOSED"],
            "input": {}, "expected_output_mode": "RAISES",
            "expected_output": {"raises": {"type": "ValueError", "message_contains": None}},
        }
        findings = _run_case(case, "HOTSPOT-TEST", lambda payload: payload)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["motivo"], "RAISES_NAO_OCORREU")

    def test_run_case_rejects_status_outside_the_fixed_vocabulary(self):
        case = {
            "case_id": "GC-TEST-006B", "purpose": "caso de teste", "status": "GOLDEN",
            "semantic_families": ["engine_decision"], "invariants_exercised": ["FAIL_CLOSED"],
            "input": {}, "expected_output_mode": "EXACT", "expected_output": {},
        }
        findings = _run_case(case, "HOTSPOT-TEST", lambda payload: payload)
        self.assertEqual([f["motivo"] for f in findings], ["STATUS_INVALIDO"])

    def test_run_case_flags_missing_semantic_families_invariants_and_purpose(self):
        case = {
            "case_id": "GC-TEST-006", "status": "APPROVED",
            "semantic_families": [], "invariants_exercised": [],
            "input": {}, "expected_output_mode": "EXACT", "expected_output": {},
        }
        findings = _run_case(case, "HOTSPOT-TEST", lambda payload: payload)
        motivos = {f["motivo"] for f in findings}
        self.assertIn("SEMANTIC_FAMILIES_VAZIO", motivos)
        self.assertIn("INVARIANTS_EXERCISED_VAZIO", motivos)
        self.assertIn("PURPOSE_VAZIO", motivos)

    def test_run_case_detects_nondeterministic_replay(self):
        counter = {"n": 0}

        def _adapter(_payload):
            counter["n"] += 1
            return {"call": counter["n"]}

        case = {
            "case_id": "GC-TEST-007", "purpose": "caso de teste", "status": "APPROVED",
            "semantic_families": ["deterministic_replay"], "invariants_exercised": ["IDEMPOTENCE"],
            "input": {}, "expected_output_mode": "EXACT", "expected_output": {"call": 1},
            "check_deterministic_replay": True,
        }
        findings = _run_case(case, "HOTSPOT-TEST", _adapter)
        self.assertEqual([f["motivo"] for f in findings], ["REPLAY_NAO_DETERMINISTICO"])

    def test_no_real_case_private_data_guard_catches_private_reference(self):
        corpus = {"cases": [{"input": {"path": "referencias/privadas/segredo.json"}}]}
        findings = _check_no_real_case_private_data(corpus, "HOTSPOT-TEST")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severidade"], "P0")

    def test_no_real_case_private_data_guard_is_silent_on_clean_corpus(self):
        corpus = {"cases": [{"input": {"path": "tests/fixtures/pje/manifesto-minimo-valido.json"}}]}
        self.assertEqual(_check_no_real_case_private_data(corpus, "HOTSPOT-TEST"), [])


class GoldenCorpusRegistryDrivenTest(unittest.TestCase):
    """Drives every fixture currently registered under GOLDEN_CORPUS_* in
    tests/fixtures/core-fixtures.json through the real hotspot entrypoints."""

    def test_all_registered_golden_corpora_match_current_behavior(self):
        findings = validate_golden_corpus(ROOT, adapters=ADAPTERS)
        self.assertEqual(findings, [], msg=json.dumps(findings, ensure_ascii=False, indent=2))

    def test_validar_integridade_corpus_is_registered_with_golden_cases(self):
        # tests/fixtures/golden_corpus/validar_integridade.json
        corpora = {c["hotspot_id"]: c for c in load_corpus(ROOT)}
        self.assertIn("HOTSPOT-04", corpora)
        approved = [c for c in corpora["HOTSPOT-04"]["cases"] if c["status"] == "APPROVED"]
        self.assertGreaterEqual(len(approved), 10)

    def test_motor_executar_corpus_is_registered_with_approved_cases(self):
        # tests/fixtures/golden_corpus/motor_executar.json
        corpora = {c["hotspot_id"]: c for c in load_corpus(ROOT)}
        self.assertIn("HOTSPOT-01", corpora)
        approved = [c for c in corpora["HOTSPOT-01"]["cases"] if c["status"] == "APPROVED"]
        self.assertGreaterEqual(len(approved), 5)

    def test_gerar_vistoria_corpus_is_registered_with_approved_cases(self):
        # tests/fixtures/golden_corpus/gerar_vistoria.json
        corpora = {c["hotspot_id"]: c for c in load_corpus(ROOT)}
        self.assertIn("HOTSPOT-02", corpora)
        approved = [c for c in corpora["HOTSPOT-02"]["cases"] if c["status"] == "APPROVED"]
        self.assertGreaterEqual(len(approved), 4)
        unreachable = corpora["HOTSPOT-02"].get("known_unreachable", [])
        self.assertTrue(any(entry["golden_execution_case"] is None and entry["reachability_today"] is False for entry in unreachable))

    def test_autocorrigir_corpus_is_registered_with_approved_cases(self):
        # tests/fixtures/golden_corpus/autocorrigir.json
        corpora = {c["hotspot_id"]: c for c in load_corpus(ROOT)}
        self.assertIn("HOTSPOT-05", corpora)
        approved = [c for c in corpora["HOTSPOT-05"]["cases"] if c["status"] == "APPROVED"]
        self.assertGreaterEqual(len(approved), 5)

    def test_gerar_delimitacao_corpus_is_registered_with_approved_cases(self):
        # tests/fixtures/golden_corpus/gerar_delimitacao.json
        corpora = {c["hotspot_id"]: c for c in load_corpus(ROOT)}
        self.assertIn("HOTSPOT-03", corpora)
        approved = [c for c in corpora["HOTSPOT-03"]["cases"] if c["status"] == "APPROVED"]
        self.assertGreaterEqual(len(approved), 8)
        statuses = {c["case_id"]: c["status"] for c in corpora["HOTSPOT-03"]["cases"]}
        self.assertEqual(statuses.get("GC-DELIM-008"), "CHARACTERIZED_NOT_APPROVED")

    def test_all_five_hotspots_are_represented(self):
        corpora = {c["hotspot_id"] for c in load_corpus(ROOT)}
        self.assertEqual(corpora, {"HOTSPOT-01", "HOTSPOT-02", "HOTSPOT-03", "HOTSPOT-04", "HOTSPOT-05"})

    def test_coverage_map_only_counts_approved_status_cases(self):
        coverage = build_coverage_map(ROOT)
        self.assertIn("HOTSPOT-04", coverage["hotspots"])
        integridade_cases = {
            case_id for family_row in coverage["matrix"].values() for case_id in family_row.get("HOTSPOT-04", [])
        }
        self.assertNotIn("GC-INTEGRIDADE-012", integridade_cases)

    def test_coverage_map_surfaces_known_unreachable_paths(self):
        coverage = build_coverage_map(ROOT)
        locations = {entry["location"] for entry in coverage["known_unreachable"]}
        self.assertTrue(any("normalizar(obs.get('elemento'))" in loc for loc in locations))


if __name__ == "__main__":
    unittest.main()
