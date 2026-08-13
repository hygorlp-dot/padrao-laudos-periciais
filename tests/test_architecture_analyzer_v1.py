import ast
import json
from pathlib import Path

import pytest

from scripts.quality.architecture_analyzer import analyze_sources, apply_exact_baseline, run_architecture_gate
from scripts.quality.repository_inventory import canonical_python_path


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
        {"id": "A", "paths": ["scripts/a/"], "allowedConsumers": []},
        {"id": "B", "paths": ["scripts/b/"], "allowedConsumers": []},
    ]
    sources = {"scripts/a/x.py": "import scripts.b.y\n", "scripts/b/y.py": "import scripts.a.x\n"}
    result = analyze_sources(sources, policy)
    codes = [item["code"] for item in result["findings"]]
    assert "ARCHITECTURE_CYCLE" in codes
    assert "DISALLOWED_COMPONENT_DEPENDENCY" in codes


def test_overlapping_ownership_fails_closed():
    policy = _policy()
    policy["components"] = [
        {"id": "ROOT", "paths": ["scripts/a/"], "allowedConsumers": []},
        {"id": "FILE", "paths": ["scripts/a/x.py"], "allowedConsumers": []},
    ]
    result = analyze_sources({"scripts/a/x.py": "VALUE=1\n"}, policy)
    assert any(item["code"] == "AMBIGUOUS_COMPONENT_OWNERSHIP" for item in result["findings"])


def test_dynamic_architecture_bypass_is_reported_but_no_capability_code_exists():
    sources = {"scripts/a.py": "import importlib\nname='scripts.b'\nimportlib.import_module(name)\n"}
    findings = analyze_sources(sources, _policy())["findings"]
    assert any(item["code"] == "DYNAMIC_ARCHITECTURE_BYPASS" for item in findings)
    assert all("CAPABILITY" not in item["code"] for item in findings)


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
    assert any(item["detail"] == "stale exception without matching finding" for item in checked["findings"])


def test_repository_architecture_gate_is_clean():
    assert run_architecture_gate(ROOT) == []
