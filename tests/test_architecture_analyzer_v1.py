import ast
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import jsonschema

from scripts.quality.architecture_analyzer import (
    PROTECTED_ARCHITECTURE_ARTIFACTS,
    _cycles,
    _protected_artifact_findings,
    analyze_sources,
    apply_exact_baseline,
    run_architecture_gate,
)
from scripts.quality.repository_inventory import canonical_python_path, candidate_tree, tree_python_sources


ROOT = Path(__file__).parents[1]


@pytest.fixture(autouse=True)
def _deterministic_git_identity(monkeypatch):
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.invalid")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.invalid")


def _policy():
    return json.loads((ROOT / "config/architecture-policy-v1.json").read_text(encoding="utf-8"))


def test_canonical_python_path_rejects_aliases_and_non_production_paths():
    assert canonical_python_path("scripts/pkg/module.py", ("scripts/",)) == "scripts/pkg/module.py"
    for value in ("/scripts/x.py", r"scripts\x.py", "scripts/./x.py", "scripts/a/../x.py", "scripts//x.py", "tests/x.py"):
        with pytest.raises(ValueError):
            canonical_python_path(value, ("scripts/",))


def test_static_edges_and_relative_imports_are_deterministic():
    sources = {
        "scripts/a/__init__.py": "from .service import run\n",
        "scripts/a/service.py": "from scripts.b import helper\n",
        "scripts/b/__init__.py": "",
        "scripts/b/helper.py": "VALUE = 1\n",
    }
    result = analyze_sources(sources, _policy())
    assert result["modules"] == sorted(result["modules"], key=lambda item: item["module"])
    assert {tuple((edge["source"], edge["target"])) for edge in result["edges"]} == {
        ("scripts.a", "scripts.a.service"), ("scripts.a.service", "scripts.b.helper")
    }


def test_unresolved_first_party_import_blocks():
    result = analyze_sources({"scripts/a.py": "from scripts.missing import value\n"}, _policy())
    assert any(item["code"] == "UNRESOLVED_FIRST_PARTY_IMPORT" and item["severity"] == "P1" for item in result["findings"])


def test_cycle_and_disallowed_component_edge_block():
    policy = _policy()
    policy["components"] = [
        {"id": "A", "layer":"DOMAIN", "paths": ["scripts/a/"], "allowedConsumers": []},
        {"id": "B", "layer":"DOMAIN", "paths": ["scripts/b/"], "allowedConsumers": []},
    ]
    sources = {"scripts/a/x.py": "import scripts.b.y\n", "scripts/b/y.py": "import scripts.a.x\n"}
    result = analyze_sources(sources, policy)
    codes = [item["code"] for item in result["findings"]]
    assert "ARCHITECTURE_CYCLE" in codes
    assert "DISALLOWED_COMPONENT_DEPENDENCY" in codes


def test_overlapping_ownership_fails_closed():
    policy = _policy()
    policy["components"] = [
        {"id": "ROOT", "layer":"DOMAIN", "paths": ["scripts/a/"], "allowedConsumers": []},
        {"id": "FILE", "layer":"DOMAIN", "paths": ["scripts/a/x.py"], "allowedConsumers": []},
    ]
    result = analyze_sources({"scripts/a/x.py": "VALUE=1\n"}, policy)
    assert any(item["code"] == "AMBIGUOUS_COMPONENT_OWNERSHIP" for item in result["findings"])


def test_dynamic_capability_is_outside_static_architecture_boundary():
    sources = {"scripts/a.py": "import importlib\nname='scripts.b'\nimportlib.import_module(name)\n"}
    findings = analyze_sources(sources, _policy())["findings"]
    assert all(item["code"] != "DYNAMIC_ARCHITECTURE_BYPASS" for item in findings)
    assert all("CAPABILITY" not in item["code"] for item in findings)


@pytest.mark.parametrize("source", [
    "import importlib as il\nil.import_module(name)\n",
    "from importlib import import_module as load\nload(name)\n",
    "import runpy as r\nr.run_module(name)\n",
    "import builtins\nbuiltins.__import__(name)\n",
])
def test_import_alias_capabilities_are_not_interpreted(source):
    assert all(item["code"] != "DYNAMIC_ARCHITECTURE_BYPASS" for item in analyze_sources({"scripts/a.py": source}, _policy())["findings"])


def test_loader_and_import_hook_capabilities_are_not_interpreted():
    sources = {"scripts/a.py": "spec.loader.exec_module(module)\nsys.meta_path.append(finder)\n"}
    findings = analyze_sources(sources, _policy())["findings"]
    assert all(item["code"] != "DYNAMIC_ARCHITECTURE_BYPASS" for item in findings)


@pytest.mark.parametrize("source", [
    "import sys\nmp = sys.meta_path\nmp.append(finder)\n",
    "execute = spec.loader.exec_module\nexecute(module)\n",
    "from importlib import import_module\nload = import_module\nload(name)\n",
    "from importlib import import_module\nload: object = import_module\nload(name)\n",
    "from importlib import import_module\nfirst = second = import_module\nsecond(name)\n",
    "from importlib import import_module\nif (load := import_module):\n    load(name)\n",
    "from importlib import import_module\n(load,) = (import_module,)\nload(name)\n",
    "from importlib import import_module\nloads = [import_module]\nload = loads[0]\nload(name)\n",
    "from importlib import import_module\nload = import_module if enabled else safe\nload(name)\n",
    "from importlib import import_module\nholder.load = import_module\nholder.load(name)\n",
])
def test_assignment_alias_capabilities_are_not_interpreted(source):
    findings = analyze_sources({"scripts/a.py": source}, _policy())["findings"]
    assert all(item["code"] != "DYNAMIC_ARCHITECTURE_BYPASS" for item in findings)


@pytest.mark.parametrize("source", [
    "from importlib import import_module\nimport_module(name)\nimport_module = safe\n",
    "from importlib import import_module as load\nload(name)\nload = safe\n",
])
def test_binding_time_capabilities_are_not_interpreted(source):
    findings = analyze_sources({"scripts/a.py": source}, _policy())["findings"]
    assert all(item["code"] != "DYNAMIC_ARCHITECTURE_BYPASS" for item in findings)


@pytest.mark.parametrize("source", [
    "import importlib\nload = getattr(importlib, 'import_module')\nload(name)\n",
    "from importlib import import_module\ndef factory():\n    return import_module\nload = factory()\nload(name)\n",
    "import importlib\ngetattr(importlib, 'import_' + 'module')(name)\n",
    "import importlib\nvars(importlib)['import_module'](name)\n",
    "import builtins\ngetattr(builtins, '__' + 'import__')(name)\n",
    "import importlib\nvars(importlib).get('import_' + 'module')(name)\n",
    "import builtins\nvars(builtins).get('__' + 'import__')(name)\n",
    "import importlib\ngetattr(vars(importlib), 'g' + 'et')('import_module')(name)\n",
    "import builtins\nbuiltins.__dict__['__import__'](name)\n",
    "import importlib\nimportlib.__dict__['import_module'](name)\n",
    "import importlib\ngetattr(importlib, ''.join(['import_', 'module']))(name)\n",
])
def test_reflection_and_factory_capabilities_are_not_interpreted(source):
    findings = analyze_sources({"scripts/a.py": source}, _policy())["findings"]
    assert all(item["code"] != "DYNAMIC_ARCHITECTURE_BYPASS" for item in findings)


@pytest.mark.parametrize("source", [
    "import importlib\nimportlib.util.find_spec(name).loader.exec_module(module)\n",
    "__builtins__['__import__'](name)\n",
    "globals()['__builtins__']['__import__'](name)\n",
    "import sys\nsys.modules['importlib'].import_module(name)\n",
    "import importlib\nimport operator\noperator.attrgetter('import_module')(importlib)(name)\n",
    "getattr(spec.loader, 'exec_module')(module)\n",
    "vars(spec.loader)['exec_module'](module)\n",
    "import importlib\nimportlib.__getattribute__('import_module')(name)\n",
])
def test_inline_reflection_capabilities_are_not_interpreted(source):
    findings = analyze_sources({"scripts/a.py": source}, _policy())["findings"]
    assert all(item["code"] != "DYNAMIC_ARCHITECTURE_BYPASS" for item in findings)


@pytest.mark.parametrize("source", [
    "import importlib\nimportlib.import_module.__call__(name)\n",
    "import builtins\nbuiltins.__import__.__call__(name)\n",
    "spec.loader.exec_module.__call__(module)\n",
    "import importlib\nobject.__getattribute__(importlib, 'import_module')(name)\n",
])
def test_descriptor_dispatch_capabilities_are_not_interpreted(source):
    findings = analyze_sources({"scripts/a.py": source}, _policy())["findings"]
    assert all(item["code"] != "DYNAMIC_ARCHITECTURE_BYPASS" for item in findings)


@pytest.mark.parametrize("source", [
    "import importlib\nobject.__getattribute__.__call__(object.__getattribute__, importlib, 'import_module')(name)\n",
    "import builtins\nobject.__dict__['__getattribute__'](builtins, '__import__')(name)\n",
    "import importlib, types\ntypes.ModuleType.__getattribute__(importlib, 'import_module')(name)\n",
    "import importlib, operator\noperator.methodcaller('__getattribute__', 'import_module')(importlib)(name)\n",
])
def test_unbound_descriptor_capabilities_are_not_interpreted(source):
    findings = analyze_sources({"scripts/a.py": source}, _policy())["findings"]
    assert all(item["code"] != "DYNAMIC_ARCHITECTURE_BYPASS" for item in findings)


@pytest.mark.parametrize("source", [
    "invoke(__import__)\n",
    "loader = lambda fn: fn(name)\nloader(__import__)\n",
    "list(map(__import__, names))\n",
    "import builtins\ntype(builtins).__getattribute__(builtins, '__import__')(name)\n",
    "def factory():\n    import importlib as il\n    return il.import_module\nload = factory()\nload(name)\n",
    "import importlib\ntype(importlib).__getattribute__(importlib, 'import_module')(name)\n",
    "import importlib, types\ntype.__getattribute__(types.ModuleType, '__getattribute__')(importlib, 'import_module')(name)\n",
])
def test_higher_order_capabilities_are_not_interpreted(source):
    findings = analyze_sources({"scripts/a.py": source}, _policy())["findings"]
    assert all(item["code"] != "DYNAMIC_ARCHITECTURE_BYPASS" for item in findings)


@pytest.mark.parametrize("source", [
    "from importlib import import_module\nload = import_module\nif disabled:\n    load = safe\nload(name)\n",
    "from importlib import import_module\nload = import_module\ntry:\n    operation()\nexcept Exception:\n    load = safe\nload(name)\n",
    "from importlib import import_module\nload = import_module\nfor item in []:\n    load = safe\nload(name)\n",
])
def test_control_flow_capabilities_are_not_interpreted(source):
    findings = analyze_sources({"scripts/a.py": source}, _policy())["findings"]
    assert all(item["code"] != "DYNAMIC_ARCHITECTURE_BYPASS" for item in findings)


@pytest.mark.parametrize("source", [
    "import importlib\nmember = supplied\nobject.__getattribute__(importlib, member)(name)\n",
    "import importlib\nmember = supplied\ntype(importlib).__getattribute__(importlib, member)(name)\n",
    "import importlib, types\nmember = supplied\ntypes.ModuleType.__getattribute__(importlib, member)(name)\n",
    "import importlib, operator\nmember = supplied\noperator.attrgetter(member)(importlib)(name)\n",
])
def test_variable_descriptor_capabilities_are_not_interpreted(source):
    findings = analyze_sources({"scripts/a.py": source}, _policy())["findings"]
    assert all(item["code"] != "DYNAMIC_ARCHITECTURE_BYPASS" for item in findings)


@pytest.mark.parametrize("source", [
    "import sys\nsys.modules.get('importlib').import_module(name)\n",
    "eval(\"__import__('scripts.quality.target')\")\n",
    "exec(\"import scripts.quality.target\")\n",
    "evaluate = eval\nevaluate(compile(source, '<dynamic>', 'exec'))\n",
    "runner = eval\nif disabled:\n    runner = safe\nrunner(payload)\n",
    "invoke(eval, payload)\n",
    "runner = exec\nif disabled:\n    runner = safe\nrunner(payload)\n",
])
def test_mapping_and_string_execution_capabilities_are_not_interpreted(source):
    findings = analyze_sources({"scripts/a.py": source}, _policy())["findings"]
    assert all(item["code"] != "DYNAMIC_ARCHITECTURE_BYPASS" for item in findings)


@pytest.mark.parametrize("source", [
    "__builtins__['len'](items)\n",
    "globals()['ordinary'](value)\n",
    "import sys\nsys.modules['decimal'].Decimal('1')\n",
    "import operator\noperator.attrgetter('ordinary')(holder)(value)\n",
    "ordinary.__call__(value)\n",
    "object.__getattribute__(holder, 'ordinary')(value)\n",
    "object.__dict__['__getattribute__'](holder, 'ordinary')(value)\n",
    "import types\ntypes.ModuleType.__getattribute__(holder, 'ordinary')(value)\n",
    "import operator\noperator.methodcaller('__getattribute__', 'ordinary')(holder)(value)\n",
    "invoke(ordinary)\n",
    "list(map(str, values))\n",
    "type(holder).__getattribute__(holder, 'ordinary')(value)\n",
    "def factory():\n    import math as local_math\n    return local_math.sqrt\nroot = factory()\nroot(value)\n",
    "from importlib import import_module\nload = import_module\nload = safe\nload(name)\n",
    "import importlib\nmember = 'ordinary'\nobject.__getattribute__(importlib, member)(value)\n",
    "import sys\nsys.modules.get('decimal').Decimal('1')\n",
])
def test_ordinary_reflection_remains_outside_static_architecture_boundary(source):
    findings = analyze_sources({"scripts/a.py": source}, _policy())["findings"]
    assert all(item["code"] != "DYNAMIC_ARCHITECTURE_BYPASS" for item in findings)


def test_cycle_analysis_is_iterative_for_deep_graphs():
    graph = {f"m{index}": {f"m{index + 1}"} for index in range(1500)}
    graph["m1500"] = {"m0"}
    assert len(_cycles(graph)[0]) == 1501


def test_nonexistent_import_does_not_fall_back_to_package():
    sources = {"scripts/quality/__init__.py": "", "scripts/a.py": "import scripts.quality.nonexistent\n"}
    assert any(item["code"] == "UNRESOLVED_FIRST_PARTY_IMPORT" for item in analyze_sources(sources, _policy())["findings"])


def test_layer_policy_is_executable():
    policy = _policy()
    policy["components"] = [
        {"id":"LOW","layer":"DOMAIN","paths":["scripts/low/"],"allowedDependencies":["HIGH"]},
        {"id":"HIGH","layer":"GOVERNANCE","paths":["scripts/high/"],"allowedDependencies":[]},
    ]
    result = analyze_sources({"scripts/low/a.py":"import scripts.high.b\n", "scripts/high/b.py":""}, policy)
    assert any(item["code"] == "DISALLOWED_LAYER_DEPENDENCY" for item in result["findings"])


def test_candidate_commit_tree_relation_is_verified():
    commit, tree = candidate_tree(ROOT, "HEAD")
    assert len(commit) == 40 and len(tree) == 40
    with pytest.raises(ValueError):
        candidate_tree(ROOT, "HEAD", expected_tree="0" * 40)


def test_architecture_baseline_schema_is_closed():
    baseline = json.loads((ROOT / "config/architecture-baseline-v1.json").read_text())
    schema = json.loads((ROOT / "schemas/architecture-baseline-v1.schema.json").read_text())
    jsonschema.validate(baseline, schema)
    baseline["unknown"] = True
    with pytest.raises(jsonschema.ValidationError): jsonschema.validate(baseline, schema)


def test_architecture_baseline_is_validated_at_runtime():
    baseline = json.loads(subprocess.check_output(["git", "show", "HEAD:config/architecture-baseline-v1.json"], cwd=ROOT, text=True))
    baseline["unknown"] = True
    result = {"candidateCommitSha": "HEAD", "policyVersion": "1.0.0", "findings": [], "modules": []}
    checked = apply_exact_baseline(ROOT, result, baseline)
    assert any(item["code"] == "ARCHITECTURE_BASELINE_INVALID" and "schema" in item["detail"] for item in checked["findings"])


def test_architecture_baseline_cannot_self_bootstrap_from_candidate():
    baseline = json.loads((ROOT / "config/architecture-baseline-v1.json").read_text())
    candidate, _tree = candidate_tree(ROOT, "HEAD")
    baseline["baselineCommit"] = candidate
    result = {"candidateCommitSha": candidate, "policyVersion": "1.0.0", "findings": [], "modules": []}
    checked = apply_exact_baseline(ROOT, result, baseline)
    assert any(item["code"] == "ARCHITECTURE_BASELINE_INVALID" for item in checked["findings"])


def test_architecture_baseline_is_authorized_by_protected_base():
    baseline = json.loads((ROOT / "config/architecture-baseline-v1.json").read_text())
    result = {"candidateCommitSha": candidate_tree(ROOT, "HEAD")[0], "policyVersion": "1.0.0", "findings": [], "modules": []}
    checked = apply_exact_baseline(ROOT, result, baseline, protected_base="c1dda7b34ab6c68475f1992029203554205a2ec7")
    assert any(item["code"] == "ARCHITECTURE_BASELINE_INVALID" and "protected base" in item["detail"] for item in checked["findings"])


def test_parse_failure_and_invalid_input_fail_closed():
    result = analyze_sources({"scripts/broken.py": "def broken("}, _policy())
    assert result["findings"][0]["code"] == "ARCHITECTURE_SOURCE_PARSE_FAILURE"
    with pytest.raises(TypeError):
        analyze_sources({"scripts/a.py": b"not text"}, _policy())


def test_analyzer_modules_are_independent():
    source = (ROOT / "scripts/quality/architecture_analyzer.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert not any("capability" in name for name in imported)


def test_exact_baseline_rejects_duplicate_or_blob_mismatch(tmp_path):
    baseline = {"baselineCommit": "0" * 40, "exceptions": []}
    result = {"findings": []}
    checked = apply_exact_baseline(tmp_path, result, baseline)
    assert checked["findings"][0]["code"] == "ARCHITECTURE_BASELINE_INVALID"


def test_exact_baseline_rejects_stale_exception_on_real_repository():
    result = {"findings": []}
    baseline = {
        "baselineCommit": "c1dda7b34ab6c68475f1992029203554205a2ec7",
        "exceptions": [{
            "code": "DYNAMIC_ARCHITECTURE_BYPASS", "canonicalPath": "scripts/quality/fixture_registry.py",
            "line": 30, "normalizedAstSha256": "0" * 64,
            "wholeFileSha256": "cbb0454d2895cf47e0b6842e610fda327074edf6e86c684612bd3ef74cf1e97e",
            "owner": "QUALITY", "justification": "stale exact exception must fail closed",
            "disposition": "REMOVE", "reviewBy": "2099-01-01",
        }],
    }
    checked = apply_exact_baseline(ROOT, result, baseline)
    assert any(item["code"] == "ARCHITECTURE_BASELINE_INVALID" for item in checked["findings"])


def test_repository_is_clean_in_protected_mode(monkeypatch):
    candidate, _tree = candidate_tree(ROOT, "HEAD")
    monkeypatch.setenv("ARCHITECTURE_EXPECTED_HEAD_SHA", candidate)
    monkeypatch.setenv("ARCHITECTURE_PROTECTED_BASE_SHA", candidate)
    assert run_architecture_gate(ROOT, candidate) == []


def test_protected_artifact_identity_is_loaded_in_one_query_per_commit(monkeypatch):
    candidate, _tree = candidate_tree(ROOT, "HEAD")
    real_run = subprocess.run
    artifact_queries = []

    def recording_run(command, *args, **kwargs):
        if command[:2] == ["git", "ls-tree"] or command[:2] == ["git", "rev-parse"]:
            artifact_queries.append(command)
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr("scripts.quality.architecture_analyzer.subprocess.run", recording_run)

    assert _protected_artifact_findings(ROOT, candidate, candidate) == []
    assert artifact_queries == [
        ["git", "ls-tree", candidate, "--", *PROTECTED_ARCHITECTURE_ARTIFACTS],
        ["git", "ls-tree", candidate, "--", *PROTECTED_ARCHITECTURE_ARTIFACTS],
    ]


def test_protected_artifact_malformed_git_tree_output_fails_closed(monkeypatch):
    candidate, _tree = candidate_tree(ROOT, "HEAD")
    real_run = subprocess.run

    def malformed_tree(command, *args, **kwargs):
        if command[:2] == ["git", "ls-tree"]:
            return SimpleNamespace(returncode=0, stdout="malformed\n", stderr="")
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr("scripts.quality.architecture_analyzer.subprocess.run", malformed_tree)

    findings = _protected_artifact_findings(ROOT, candidate, candidate)
    assert any(item["code"] == "ARCHITECTURE_PROTECTED_ARTIFACT_UNAVAILABLE" for item in findings)


def test_python_blobs_are_loaded_in_one_batch_query(monkeypatch):
    _candidate, tree = candidate_tree(ROOT, "HEAD")
    real_run = subprocess.run
    blob_queries = []

    def recording_run(command, *args, **kwargs):
        if command[:3] == ["git", "cat-file", "blob"] or command[:3] == ["git", "cat-file", "--batch"]:
            blob_queries.append(command)
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr("scripts.quality.repository_inventory.subprocess.run", recording_run)

    sources = tree_python_sources(ROOT, tree)
    assert "scripts/quality/architecture_analyzer.py" in sources
    assert blob_queries == [["git", "cat-file", "--batch"]]


@pytest.mark.parametrize("batch_output", [b"", b"0" * 40 + b" tree 1\nx\n"])
def test_python_blob_batch_fails_closed_on_invalid_output(monkeypatch, batch_output):
    _candidate, tree = candidate_tree(ROOT, "HEAD")
    real_run = subprocess.run

    def invalid_batch(command, *args, **kwargs):
        if command == ["git", "cat-file", "--batch"]:
            return SimpleNamespace(returncode=0, stdout=batch_output, stderr=b"")
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr("scripts.quality.repository_inventory.subprocess.run", invalid_batch)

    with pytest.raises(RuntimeError):
        tree_python_sources(ROOT, tree)


@pytest.mark.parametrize("mutation", [
    "delete_workflow",
    "change_policy",
    "delete_transfer_ledger",
    "weaken_transfer_ledger",
])
def test_protected_enforcement_artifacts_cannot_be_removed_or_changed(tmp_path, mutation):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    workflow = tmp_path / ".github/workflows/architecture-protected.yml"
    policy = tmp_path / "config/architecture-policy-v1.json"
    transfer_ledger = tmp_path / "config/architecture-capability-transfers-v2.json"
    workflow.parent.mkdir(parents=True)
    policy.parent.mkdir(parents=True)
    workflow.write_text("name: protected\n", encoding="utf-8")
    policy.write_text('{"policyVersion":"1.0.0"}\n', encoding="utf-8")
    transfer_ledger.write_text(
        '{"defaultPolicy":"DENY","wildcardExceptionsAllowed":false,"findings":[{"severity":"P1"}]}\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "protected base"], cwd=tmp_path, check=True)
    protected_base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()

    if mutation == "delete_workflow":
        workflow.unlink()
    elif mutation == "change_policy":
        policy.write_text('{"policyVersion":"disabled"}\n', encoding="utf-8")
    elif mutation == "delete_transfer_ledger":
        transfer_ledger.unlink()
    else:
        transfer_ledger.write_text(
            '{"defaultPolicy":"ALLOW","wildcardExceptionsAllowed":true,"findings":[]}\n',
            encoding="utf-8",
        )
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "candidate mutation"], cwd=tmp_path, check=True)
    candidate = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()

    findings = _protected_artifact_findings(tmp_path, protected_base, candidate)
    assert any(item["code"] == "ARCHITECTURE_PROTECTED_ARTIFACT_MISMATCH" for item in findings)


def _commit_protected_transition(
    tmp_path, protected_base, *, schema_version="1.0.0", row_mutation=None, transition_mutation=None,
    mixed_production_change=False, delete_artifact=False, create_artifact=False,
):
    analyzer = tmp_path / "scripts/quality/architecture_analyzer.py"
    analyzer.parent.mkdir(parents=True, exist_ok=True)
    if create_artifact:
        artifact_path = "scripts/quality/capability_trust_anchor.py"
        artifact = tmp_path / artifact_path
        artifact.write_text("# inert capability trust anchor\n", encoding="utf-8")
    else:
        artifact_path = "scripts/quality/architecture_analyzer.py"
    if delete_artifact:
        analyzer.unlink()
    elif not create_artifact:
        analyzer.write_text("# rotated trust anchor\n", encoding="utf-8")
    if mixed_production_change:
        production = tmp_path / "scripts/domain.py"
        production.write_text("VALUE = 1\n", encoding="utf-8")
    base_blob = None if create_artifact else subprocess.check_output(
        ["git", "rev-parse", f"{protected_base}:{artifact_path}"], cwd=tmp_path, text=True,
    ).strip()
    base_mode = None if create_artifact else subprocess.check_output(
        ["git", "ls-tree", protected_base, "--", artifact_path], cwd=tmp_path, text=True,
    ).split()[0]
    candidate_blob = None if delete_artifact else subprocess.check_output(
        ["git", "hash-object", artifact_path], cwd=tmp_path, text=True,
    ).strip()
    transition = tmp_path / "config/architecture-protected-transition-v1.json"
    transition.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "path": artifact_path,
        "baseBlobSha": base_blob,
        "candidateBlobSha": candidate_blob,
    }
    if schema_version == "2.0.0":
        row = {
            "path": artifact_path,
            "baseMode": None if create_artifact else "100644",
            "baseObjectType": None if create_artifact else "blob",
            "baseBlobSha": base_blob,
            "candidateMode": "100644",
            "candidateObjectType": "blob",
            "candidateBlobSha": candidate_blob,
        }
    if row_mutation:
        row_mutation(row)
    transition_payload = {
        "schemaVersion": schema_version,
        "transitionId": "ARCHITECTURE_TRUST_ANCHOR_ROTATION_V1",
        "protectedBaseSha": protected_base,
        "artifacts": [row],
    }
    if transition_mutation:
        transition_mutation(transition_payload)
    transition.write_text(json.dumps(transition_payload), encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "rotate protected anchor"], cwd=tmp_path, check=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()


def test_exact_dedicated_transition_can_rotate_protected_artifact(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    analyzer = tmp_path / "scripts/quality/architecture_analyzer.py"
    analyzer.parent.mkdir(parents=True)
    analyzer.write_text("# protected base\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "protected base"], cwd=tmp_path, check=True)
    protected_base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()

    candidate = _commit_protected_transition(tmp_path, protected_base)

    assert _protected_artifact_findings(tmp_path, protected_base, candidate) == []


def test_exact_v2_transition_can_rotate_protected_artifact_with_mode_identity(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    analyzer = tmp_path / "scripts/quality/architecture_analyzer.py"
    analyzer.parent.mkdir(parents=True)
    analyzer.write_text("# protected base\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "protected base"], cwd=tmp_path, check=True)
    protected_base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()

    candidate = _commit_protected_transition(tmp_path, protected_base, schema_version="2.0.0")

    assert _protected_artifact_findings(tmp_path, protected_base, candidate) == []


def test_exact_v2_transition_can_create_already_custodied_artifact(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    analyzer = tmp_path / "scripts/quality/architecture_analyzer.py"
    analyzer.parent.mkdir(parents=True)
    analyzer.write_text("# protected base\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "protected base"], cwd=tmp_path, check=True)
    protected_base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()

    candidate = _commit_protected_transition(
        tmp_path, protected_base, schema_version="2.0.0", create_artifact=True,
    )

    assert _protected_artifact_findings(tmp_path, protected_base, candidate) == []


def test_protected_git_mode_identity_is_exact_in_both_directions(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    artifact_path = "scripts/quality/architecture_analyzer.py"
    analyzer = tmp_path / artifact_path
    analyzer.parent.mkdir(parents=True)
    analyzer.write_text("# protected base\n", encoding="utf-8")
    subprocess.run(["git", "add", artifact_path], cwd=tmp_path, check=True)
    subprocess.run(["git", "update-index", "--chmod=-x", artifact_path], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "protected base"], cwd=tmp_path, check=True)
    transition = tmp_path / "config/architecture-protected-transition-v1.json"
    transition.parent.mkdir(parents=True)
    for base_mode, candidate_mode in (("100644", "100755"), ("100755", "100644")):
        protected_base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
        blob = subprocess.check_output(["git", "rev-parse", f"{protected_base}:{artifact_path}"], cwd=tmp_path, text=True).strip()
        subprocess.run(["git", "update-index", "--chmod=+x" if candidate_mode == "100755" else "--chmod=-x", artifact_path], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-qm", "mutate protected mode"], cwd=tmp_path, check=True)
        undeclared = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
        findings = _protected_artifact_findings(tmp_path, protected_base, undeclared)
        assert any(item["code"] == "ARCHITECTURE_PROTECTED_TRANSITION_INVALID" for item in findings)

        transition.write_text(json.dumps({
            "schemaVersion": "2.0.0",
            "transitionId": "ARCHITECTURE_TRUST_ANCHOR_ROTATION_V1",
            "protectedBaseSha": protected_base,
            "artifacts": [{
                "path": artifact_path,
                "baseMode": base_mode,
                "baseObjectType": "blob",
                "baseBlobSha": blob,
                "candidateMode": candidate_mode,
                "candidateObjectType": "blob",
                "candidateBlobSha": blob,
            }],
        }), encoding="utf-8")
        subprocess.run(["git", "add", "config/architecture-protected-transition-v1.json"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-qm", "authorize protected mode"], cwd=tmp_path, check=True)
        candidate = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
        assert _protected_artifact_findings(tmp_path, protected_base, candidate) == []


@pytest.mark.parametrize("mode,object_type", [("160000", "commit"), ("120000", "blob")])
def test_creation_transition_rejects_non_regular_git_objects(tmp_path, mode, object_type):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    analyzer = tmp_path / "scripts/quality/architecture_analyzer.py"
    analyzer.parent.mkdir(parents=True)
    analyzer.write_text("# protected base\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "protected base"], cwd=tmp_path, check=True)
    protected_base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()

    if object_type == "commit":
        object_id = protected_base
    else:
        object_id = subprocess.check_output(
            ["git", "hash-object", "-w", "--stdin"], cwd=tmp_path, input="target\n", text=True,
        ).strip()
    artifact_path = "scripts/quality/capability_trust_anchor.py"
    subprocess.run(
        ["git", "update-index", "--add", "--cacheinfo", f"{mode},{object_id},{artifact_path}"],
        cwd=tmp_path,
        check=True,
    )
    transition = tmp_path / "config/architecture-protected-transition-v1.json"
    transition.parent.mkdir(parents=True, exist_ok=True)
    transition.write_text(json.dumps({
        "schemaVersion": "2.0.0",
        "transitionId": "ARCHITECTURE_TRUST_ANCHOR_ROTATION_V1",
        "protectedBaseSha": protected_base,
        "artifacts": [{
            "path": artifact_path,
            "baseMode": None,
            "baseObjectType": None,
            "baseBlobSha": None,
            "candidateMode": mode,
            "candidateObjectType": object_type,
            "candidateBlobSha": object_id,
        }],
    }), encoding="utf-8")
    subprocess.run(["git", "add", "config/architecture-protected-transition-v1.json"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "invalid protected object"], cwd=tmp_path, check=True)
    candidate = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()

    findings = _protected_artifact_findings(tmp_path, protected_base, candidate)
    assert any(item["code"] == "ARCHITECTURE_PROTECTED_TRANSITION_INVALID" for item in findings)


def test_creation_transition_rejects_tree_at_protected_path(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    analyzer = tmp_path / "scripts/quality/architecture_analyzer.py"
    analyzer.parent.mkdir(parents=True)
    analyzer.write_text("# protected base\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "protected base"], cwd=tmp_path, check=True)
    protected_base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()

    artifact_path = "scripts/quality/capability_trust_anchor.py"
    payload = tmp_path / artifact_path / "payload.py"
    payload.mkdir(parents=True)
    (payload / "content.txt").write_text("not a regular protected artifact\n", encoding="utf-8")
    subprocess.run(["git", "add", artifact_path], cwd=tmp_path, check=True)
    object_id = subprocess.check_output(
        ["git", "write-tree", "--prefix", f"{artifact_path}/"], cwd=tmp_path, text=True,
    ).strip()
    transition = tmp_path / "config/architecture-protected-transition-v1.json"
    transition.parent.mkdir(parents=True, exist_ok=True)
    transition.write_text(json.dumps({
        "schemaVersion": "2.0.0",
        "transitionId": "ARCHITECTURE_TRUST_ANCHOR_ROTATION_V1",
        "protectedBaseSha": protected_base,
        "artifacts": [{
            "path": artifact_path,
            "baseMode": None,
            "baseObjectType": None,
            "baseBlobSha": None,
            "candidateMode": "040000",
            "candidateObjectType": "tree",
            "candidateBlobSha": object_id,
        }],
    }), encoding="utf-8")
    subprocess.run(["git", "add", "config/architecture-protected-transition-v1.json"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "invalid protected tree"], cwd=tmp_path, check=True)
    candidate = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()

    findings = _protected_artifact_findings(tmp_path, protected_base, candidate)
    assert any(item["code"] == "ARCHITECTURE_PROTECTED_TRANSITION_INVALID" for item in findings)


def test_v1_transition_cannot_authorize_undeclared_mode_change(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    artifact_path = "scripts/quality/architecture_analyzer.py"
    analyzer = tmp_path / artifact_path
    analyzer.parent.mkdir(parents=True)
    analyzer.write_text("# protected base\n", encoding="utf-8")
    subprocess.run(["git", "add", artifact_path], cwd=tmp_path, check=True)
    subprocess.run(["git", "update-index", "--chmod=-x", artifact_path], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "protected base"], cwd=tmp_path, check=True)
    protected_base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    blob = subprocess.check_output(["git", "rev-parse", f"{protected_base}:{artifact_path}"], cwd=tmp_path, text=True).strip()

    subprocess.run(["git", "update-index", "--chmod=+x", artifact_path], cwd=tmp_path, check=True)
    transition = tmp_path / "config/architecture-protected-transition-v1.json"
    transition.parent.mkdir(parents=True)
    transition.write_text(json.dumps({
        "schemaVersion": "1.0.0",
        "transitionId": "ARCHITECTURE_TRUST_ANCHOR_ROTATION_V1",
        "protectedBaseSha": protected_base,
        "artifacts": [{"path": artifact_path, "baseBlobSha": blob, "candidateBlobSha": blob}],
    }), encoding="utf-8")
    subprocess.run(["git", "add", "config/architecture-protected-transition-v1.json"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "attempt legacy mode authorization"], cwd=tmp_path, check=True)
    candidate = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()

    findings = _protected_artifact_findings(tmp_path, protected_base, candidate)
    assert any(item["code"] == "ARCHITECTURE_PROTECTED_TRANSITION_INVALID" for item in findings)


@pytest.mark.parametrize("schema_version,row_mutation", [
    ("3.0.0", None),
    ("1.0.0", lambda row: row.update(baseMode="100644")),
    ("2.0.0", lambda row: row.pop("candidateMode")),
    ("2.0.0", lambda row: row.update(candidateMode="100755")),
    ("2.0.0", lambda row: row.update(candidateObjectType="tree")),
    ("2.0.0", lambda row: row.update(candidateBlobSha="0" * 40)),
])
def test_transition_schema_dispatch_rejects_unknown_hybrid_malformed_and_mismatch(
    tmp_path, schema_version, row_mutation,
):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    analyzer = tmp_path / "scripts/quality/architecture_analyzer.py"
    analyzer.parent.mkdir(parents=True)
    analyzer.write_text("# protected base\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "protected base"], cwd=tmp_path, check=True)
    protected_base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()

    candidate = _commit_protected_transition(
        tmp_path, protected_base, schema_version=schema_version, row_mutation=row_mutation,
    )

    findings = _protected_artifact_findings(tmp_path, protected_base, candidate)
    assert any(item["code"] == "ARCHITECTURE_PROTECTED_TRANSITION_INVALID" for item in findings)


@pytest.mark.parametrize("transition_mutation", [
    lambda transition: transition.update(unknown=True),
    lambda transition: transition.update(protectedBaseSha="0" * 40),
    lambda transition: transition.update(artifacts=[]),
    lambda transition: transition.update(artifacts=transition["artifacts"] * 2),
])
def test_transition_rejects_unknown_wrong_base_omitted_and_duplicate_rows(tmp_path, transition_mutation):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    analyzer = tmp_path / "scripts/quality/architecture_analyzer.py"
    analyzer.parent.mkdir(parents=True)
    analyzer.write_text("# protected base\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "protected base"], cwd=tmp_path, check=True)
    protected_base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()

    candidate = _commit_protected_transition(
        tmp_path, protected_base, schema_version="2.0.0", transition_mutation=transition_mutation,
    )

    findings = _protected_artifact_findings(tmp_path, protected_base, candidate)
    assert any(item["code"] == "ARCHITECTURE_PROTECTED_TRANSITION_INVALID" for item in findings)


def test_transition_cannot_mix_protected_rotation_with_production_change(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    analyzer = tmp_path / "scripts/quality/architecture_analyzer.py"
    analyzer.parent.mkdir(parents=True)
    analyzer.write_text("# protected base\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "protected base"], cwd=tmp_path, check=True)
    protected_base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()

    candidate = _commit_protected_transition(tmp_path, protected_base, mixed_production_change=True)

    findings = _protected_artifact_findings(tmp_path, protected_base, candidate)
    assert any(item["code"] == "ARCHITECTURE_PROTECTED_TRANSITION_INVALID" for item in findings)


def test_transition_cannot_authorize_protected_artifact_deletion(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    analyzer = tmp_path / "scripts/quality/architecture_analyzer.py"
    analyzer.parent.mkdir(parents=True)
    analyzer.write_text("# protected base\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "protected base"], cwd=tmp_path, check=True)
    protected_base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()

    candidate = _commit_protected_transition(tmp_path, protected_base, delete_artifact=True)

    findings = _protected_artifact_findings(tmp_path, protected_base, candidate)
    assert any(item["code"] == "ARCHITECTURE_PROTECTED_TRANSITION_INVALID" for item in findings)


def test_protected_base_must_be_candidate_ancestor(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    policy = tmp_path / "config/architecture-policy-v1.json"
    policy.parent.mkdir(parents=True)
    policy.write_text('{"policyVersion":"1.0.0"}\n', encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "protected base"], cwd=tmp_path, check=True)
    protected_base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()

    subprocess.run(["git", "checkout", "--orphan", "divergent", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "divergent candidate"], cwd=tmp_path, check=True)
    candidate = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()

    findings = _protected_artifact_findings(tmp_path, protected_base, candidate)
    assert any(item["code"] == "ARCHITECTURE_PROTECTED_BASE_INVALID" for item in findings)


def test_staging_does_not_self_activate_in_verify_core():
    source = (ROOT / "scripts/quality/verify_core.py").read_text(encoding="utf-8")
    assert "run_architecture_gate" not in source
    assert "architecture analyzer" not in source


def test_architecture_anchor_custodies_inert_capability_trust_root():
    assert {
        ".github/workflows/capability-protected.yml",
        "config/capability-protected-artifacts-v1.json",
        "scripts/quality/capability_trust_anchor.py",
    } <= set(PROTECTED_ARCHITECTURE_ARTIFACTS)
