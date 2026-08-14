import ast
import json
import subprocess
from pathlib import Path

import pytest
import jsonschema

from scripts.quality.architecture_analyzer import _cycles, analyze_sources, apply_exact_baseline, run_architecture_gate
from scripts.quality.repository_inventory import canonical_python_path, candidate_tree


ROOT = Path(__file__).parents[1]


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


def test_dynamic_architecture_bypass_is_reported_but_no_capability_code_exists():
    sources = {"scripts/a.py": "import importlib\nname='scripts.b'\nimportlib.import_module(name)\n"}
    findings = analyze_sources(sources, _policy())["findings"]
    assert any(item["code"] == "DYNAMIC_ARCHITECTURE_BYPASS" for item in findings)
    assert all("CAPABILITY" not in item["code"] for item in findings)


@pytest.mark.parametrize("source", [
    "import importlib as il\nil.import_module(name)\n",
    "from importlib import import_module as load\nload(name)\n",
    "import runpy as r\nr.run_module(name)\n",
    "import builtins\nbuiltins.__import__(name)\n",
])
def test_dynamic_architecture_bypass_import_aliases(source):
    assert any(item["code"] == "DYNAMIC_ARCHITECTURE_BYPASS" for item in analyze_sources({"scripts/a.py": source}, _policy())["findings"])


def test_loader_and_import_hook_surfaces_block_class_wide():
    sources = {"scripts/a.py": "spec.loader.exec_module(module)\nsys.meta_path.append(finder)\n"}
    findings = analyze_sources(sources, _policy())["findings"]
    assert [item["code"] for item in findings].count("DYNAMIC_ARCHITECTURE_BYPASS") == 2


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
def test_dynamic_architecture_bypass_assignment_aliases(source):
    findings = analyze_sources({"scripts/a.py": source}, _policy())["findings"]
    assert any(item["code"] == "DYNAMIC_ARCHITECTURE_BYPASS" for item in findings)


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


def test_repository_is_clean_before_protected_activation():
    assert run_architecture_gate(ROOT) == []


def test_staging_does_not_self_activate_in_verify_core():
    source = (ROOT / "scripts/quality/verify_core.py").read_text(encoding="utf-8")
    assert "run_architecture_gate" not in source
    assert "architecture analyzer" not in source


def test_protected_mode_uses_protected_base_artifacts(monkeypatch):
    candidate, _tree = candidate_tree(ROOT, "HEAD")
    monkeypatch.setenv("ARCHITECTURE_EXPECTED_HEAD_SHA", candidate)
    monkeypatch.setenv("ARCHITECTURE_PROTECTED_BASE_SHA", "663b2f9122f46bd5f06a6c3b2fb943b25aa7c869")
    assert run_architecture_gate(ROOT, candidate) == []
