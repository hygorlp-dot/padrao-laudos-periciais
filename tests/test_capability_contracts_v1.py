import json
from pathlib import Path

import jsonschema
import pytest


ROOT = Path(__file__).parents[1]


def _json(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def test_v1_contract_artifacts_exist_and_are_versioned():
    required = [
        "docs/arquitetura/decisoes/ADR-capability-acquisition-boundary-v1.md",
        "docs/arquitetura/contratos/analisadores-arquitetura-capability-v1.md",
        "docs/arquitetura/planos/migracao-capability-boundary-v1.md",
        "config/capability-policy-v1.json",
        "schemas/quality-finding-v1.schema.json",
        "schemas/capability-policy-v1.schema.json",
        "schemas/capability-exception-v1.schema.json",
        "tests/fixtures/capability-boundary-v1.json",
    ]
    assert all((ROOT / path).is_file() for path in required)
    assert _json("config/capability-policy-v1.json")["policyVersion"] == "1.0.0"


def test_analyzer_contracts_are_independent_and_cutover_is_atomic():
    contract = (ROOT / "docs/arquitetura/contratos/analisadores-arquitetura-capability-v1.md").read_text(encoding="utf-8")
    migration = (ROOT / "docs/arquitetura/planos/migracao-capability-boundary-v1.md").read_text(encoding="utf-8")
    for token in ["ARCHITECTURE_ANALYZER_V1", "CAPABILITY_ANALYZER_V1", "POLICY_FREE_SHARED_INFRASTRUCTURE", "DUAL_FINDINGS_ALLOWED"]:
        assert token in contract
    for token in ["CUTOVER_MUST_BE_ATOMIC", "LEGACY_GATE_REMAINS_BLOCKING", "ROLLBACK_PER_PR", "NO_REDUCED_PROTECTION_WINDOW"]:
        assert token in migration


def test_closed_taxonomy_and_scan_universe_are_explicit():
    policy = _json("config/capability-policy-v1.json")
    assert set(policy["capabilityClasses"]) == {
        "DYNAMIC_IMPORT_ACQUISITION", "DYNAMIC_EXECUTION_ACQUISITION",
        "EXECUTABLE_DESERIALIZATION_OR_NATIVE_LOADING", "PROCESS_NAMESPACE_ACQUISITION",
        "OS_PROCESS_MEMBER_ACQUISITION", "SENSITIVE_NAMESPACE_ESCAPE",
        "UNKNOWN_SENSITIVE_REFLECTION",
    }
    assert policy["scanUniverse"]["inventoryFailurePolicy"] == "FAIL_CLOSED"
    assert policy["scanUniverse"]["candidateHeadNewFilesIncluded"] is True
    assert policy["inlineSuppressionsAllowed"] is False


def test_contract_schemas_accept_exact_examples_and_reject_wildcard_exception():
    policy = _json("config/capability-policy-v1.json")
    jsonschema.validate(policy, _json("schemas/capability-policy-v1.schema.json"))
    exception = _json("tests/fixtures/capability-exception-v1-valid.json")
    schema = _json("schemas/capability-exception-v1.schema.json")
    jsonschema.validate(exception, schema)
    exception["canonicalPath"] = "scripts/*"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(exception, schema)


def test_p0_p1_fixture_matrix_covers_boundaries_and_positive_controls():
    matrix = _json("tests/fixtures/capability-boundary-v1.json")
    classes = {case["capabilityClass"] for case in matrix["cases"] if case["expected"] == "BLOCK"}
    assert classes == set(_json("config/capability-policy-v1.json")["capabilityClasses"])
    safe = {case["id"] for case in matrix["cases"] if case["expected"] == "ALLOW"}
    assert {"SAFE-OS-PATH", "SAFE-OS-ENVIRON", "SAFE-NON-SENSITIVE-REFLECTION"} <= safe
    historical = {case["id"] for case in matrix["cases"]}
    assert {"P0-DYNAMIC-IMPORT-LITERAL", "P1-OS-DICT-ESCAPE", "P1-HIGHER-ORDER-REFLECTION", "P1-POSIX-FORK"} <= historical


def test_pr_a_contains_no_production_analyzer_implementation():
    assert not (ROOT / "scripts/quality/architecture_analyzer.py").exists()
    assert not (ROOT / "scripts/quality/capability_analyzer.py").exists()
