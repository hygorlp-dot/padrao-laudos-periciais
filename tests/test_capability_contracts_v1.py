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
    for token in ["CUTOVER_MUST_BE_ATOMIC", "NEW_GATE_BLOCKS_ON_INTRODUCTION", "ROLLBACK_PER_PR", "NO_REDUCED_PROTECTION_WINDOW"]:
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
    for invalid_path in ["scripts/*", "/scripts/x.py", r"C:\scripts\x.py", "scripts/../x.py", "scripts/./x.py", "scripts//x.py", "tests/x.py"]:
        invalid = dict(exception, canonicalPath=invalid_path)
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid, schema)
    for field, value in [("capabilityClass", "ARBITRARY"), ("findingCode", "ARBITRARY")]:
        invalid = dict(exception, **{field: value})
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid, schema)
    mismatched = dict(exception, findingCode="DYNAMIC_IMPORT_ACQUISITION", capabilityClass="PROCESS_NAMESPACE_ACQUISITION")
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(mismatched, schema)


def test_p0_p1_fixture_matrix_covers_boundaries_and_positive_controls():
    matrix = _json("tests/fixtures/capability-boundary-v1.json")
    classes = {case["capabilityClass"] for case in matrix["cases"] if case["expected"] == "BLOCK"}
    assert classes == set(_json("config/capability-policy-v1.json")["capabilityClasses"])
    safe = {case["id"] for case in matrix["cases"] if case["expected"] == "ALLOW"}
    assert {"SAFE-OS-PATH", "SAFE-OS-ENVIRON", "SAFE-NON-SENSITIVE-REFLECTION"} <= safe
    historical = {case["id"] for case in matrix["cases"]}
    assert {"P0-DYNAMIC-IMPORT-LITERAL", "P1-OS-DICT-ESCAPE", "P1-HIGHER-ORDER-REFLECTION", "P1-POSIX-FORK"} <= historical
    required_families = {
        "IMPORT_HOOK", "IMPORT_LOADER", "SUBPROCESS", "ASYNCIO_SUBPROCESS", "PTY",
        "POSIX", "WINDOWS_PROCESS", "MULTIPROCESSING_MANAGER", "MULTIPROCESSING_POOL",
        "MULTIPROCESSING_CONTEXT", "CONCURRENT_PROCESS_POOL", "OS_MEMBER_IMPORT",
        "GETATTR_ESCAPE", "GETATTRIBUTE_ESCAPE", "DICT_ESCAPE", "DYNAMIC_MAPPING_ESCAPE",
        "INVENTORY_FAILURE", "READ_FAILURE", "PARSE_FAILURE", "NONREGULAR_FILE",
        "SYMLINK_ESCAPE", "COMMIT_TREE_MISMATCH", "EXCEPTION_DUPLICATE", "EXCEPTION_STALE", "EXCEPTION_EXPIRED",
        "EXCEPTION_BLOB_MISMATCH", "EXCEPTION_BASELINE_MISMATCH", "DUAL_FINDING",
        "ANALYZER_INDEPENDENCE",
        "ASYNCIO_PUBLIC_PROCESS", "CONCURRENT_PUBLIC_PROCESS_POOL", "EXECUTABLE_DESERIALIZER_CLASS",
        "EXCEPTION_MODULE_PATH_MISMATCH", "BOOTSTRAP_ANALYZER_DIGEST_MISMATCH",
        "BOOTSTRAP_POLICY_DIGEST_MISMATCH", "BOOTSTRAP_SCHEMA_DIGEST_MISMATCH", "BOOTSTRAP_PIN_REGISTRY_TAMPER",
        "BOOTSTRAP_VERIFIER_TAMPER", "BOOTSTRAP_INVENTORY_PARSER_TAMPER", "BOOTSTRAP_BLOCKING_ADAPTER_TAMPER",
        "BOOTSTRAP_PROTECTED_BASE_VERIFIER_ABSENT", "BOOTSTRAP_PROTECTED_WORKFLOW_ABSENT", "BOOTSTRAP_UNTRUSTED_CANDIDATE_VERIFIER",
    }
    assert required_families <= {case["boundaryFamily"] for case in matrix["cases"]}


def test_policy_closes_namespace_member_and_bootstrap_contracts():
    policy = _json("config/capability-policy-v1.json")
    assert policy["candidateIdentity"]["inventorySource"] == "EXACT_GIT_TREE"
    assert policy["candidateIdentity"]["contentSource"] == "SAME_EXACT_GIT_TREE"
    assert policy["candidateIdentity"]["commitTreeRelation"] == "COMMIT_TREE_MATCH_REQUIRED"
    roots = policy["processNamespaces"]
    for root in ["subprocess", "asyncio.subprocess", "pty", "posix", "multiprocessing.managers", "multiprocessing.pool", "multiprocessing.context", "concurrent.futures.process"]:
        assert root in roots
    assert {"system", "fork", "posix_spawn", "posix_spawnp", "spawnl", "spawnv", "startfile", "execl", "execle", "execlp", "execlpe"} <= set(policy["mixedNamespaceMembers"]["os"])
    assert set(policy["mixedNamespaceMembers"]["asyncio"]) == {"create_subprocess_exec", "create_subprocess_shell"}
    assert policy["mixedNamespaceMembers"]["concurrent.futures"] == ["ProcessPoolExecutor"]
    assert "Unpickler" in policy["mixedNamespaceMembers"]["pickle"]
    assert {item["findingCode"] for item in policy["ruleMappings"]} == set(policy["capabilityClasses"])
    assert all(item["findingCode"] == item["capabilityClass"] for item in policy["ruleMappings"])
    bootstrap = policy["integrityBootstrap"]
    assert bootstrap["failurePolicy"] == "FAIL_CLOSED"
    assert bootstrap["ordinaryExceptionsMayAuthorizeBootstrap"] is False
    assert bootstrap["verifierProvenance"] == "PROTECTED_BASE_BLOB_NOT_CANDIDATE"
    assert bootstrap["workflowProvenance"] == "PROTECTED_BASE_WORKFLOW"
    required_tcb = {
        "scripts/quality/capability_bootstrap.py", "scripts/quality/repository_inventory.py",
        "scripts/quality/ast_inventory.py", "scripts/quality/capability_analyzer.py",
        "scripts/quality/capability_gate_adapter.py", "scripts/quality/verify_core.py",
        "config/capability-policy-v1.json", "schemas/capability-policy-v1.schema.json",
        "schemas/capability-exception-v1.schema.json", "schemas/quality-finding-v1.schema.json",
    }
    assert required_tcb <= set(bootstrap["candidateEnforcementArtifacts"])


def test_exception_lifecycle_and_atomic_topology_are_fail_closed():
    contract = (ROOT / "docs/arquitetura/contratos/analisadores-arquitetura-capability-v1.md").read_text(encoding="utf-8")
    migration = (ROOT / "docs/arquitetura/planos/migracao-capability-boundary-v1.md").read_text(encoding="utf-8")
    for token in ["BASELINE_MUST_BE_ANCESTOR", "EXCEPTION_MUST_PREEXIST_IN_BASELINE", "EXPIRED_EXCEPTION_BLOCKS", "DUPLICATE_EXCEPTION_BLOCKS", "SAME_CANDIDATE_TREE_BYTES", "COMMIT_TREE_MATCH_REQUIRED", "MODULE_PATH_CONSISTENCY_REQUIRED"]:
        assert token in contract
    for token in ["NO_DEPLOYED_LEGACY_ORACLE", "NEW_GATE_BLOCKS_ON_INTRODUCTION", "REVERSE_ORDER_ROLLBACK", "TRUST_ANCHOR_MUST_PREEXIST_CUTOVER", "PR-T"]:
        assert token in migration


def test_pre_cutover_stages_contain_no_capability_enforcement():
    assert not (ROOT / "scripts/quality/capability_analyzer.py").exists()
    assert not (ROOT / "scripts/quality/capability_bootstrap.py").exists()
    assert not (ROOT / "scripts/quality/capability_gate_adapter.py").exists()
    architecture = ROOT / "scripts/quality/architecture_analyzer.py"
    if architecture.exists():
        source = architecture.read_text(encoding="utf-8")
        assert "ARCHITECTURE_ANALYZER_V1" in source
        assert "CAPABILITY_ANALYZER_V1" not in source
