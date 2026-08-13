import json
from pathlib import Path

from scripts.quality.architecture_gate import analyze_architecture, validate_architecture


ROOT = Path(__file__).resolve().parents[1]


def _registry(**changes):
    data = {
        "schemaVersion": "1.0.0",
        "components": [
            {"id": "DOMAIN", "prefixes": ["scripts/domain/"]},
            {"id": "APPLICATION", "prefixes": ["scripts/application/"]},
            {"id": "GOVERNANCE", "prefixes": ["scripts/quality/"]},
        ],
        "allowedInternalEdges": [],
        "acceptedCurrentDependencies": [],
        "forbiddenComponentEdges": [
            {"source": "DOMAIN", "target": "APPLICATION", "rule": "DOMAIN_INDEPENDENT"},
            {"source": "DOMAIN", "target": "GOVERNANCE", "rule": "CORE_NOT_GOVERNANCE"},
            {"source": "APPLICATION", "target": "GOVERNANCE", "rule": "PRODUCTION_NOT_GOVERNANCE"},
        ],
    }
    data.update(changes)
    return data


def test_current_repository_architecture_is_registered_and_green():
    registry = json.loads((ROOT / "config/core-architecture-v1.json").read_text(encoding="utf-8"))
    report = analyze_architecture(ROOT, registry)
    assert report["findings"] == []
    assert report["modules"]
    assert report["edges"]


def test_forbidden_reverse_dependency_fails_closed(tmp_path):
    (tmp_path / "scripts/domain").mkdir(parents=True)
    (tmp_path / "scripts/application").mkdir(parents=True)
    (tmp_path / "scripts/quality").mkdir(parents=True)
    (tmp_path / "scripts/domain/rule.py").write_text("from scripts.application import use_case\n", encoding="utf-8")
    (tmp_path / "scripts/application/use_case.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "scripts/quality/gate.py").write_text("VALUE = 1\n", encoding="utf-8")
    report = validate_architecture(tmp_path, _registry())
    assert any(item["code"] == "FORBIDDEN_ARCHITECTURE_EDGE" for item in report)


def test_new_cross_component_edge_requires_exact_debt_record(tmp_path):
    (tmp_path / "scripts/domain").mkdir(parents=True)
    (tmp_path / "scripts/application").mkdir(parents=True)
    (tmp_path / "scripts/domain/rule.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "scripts/application/use_case.py").write_text("from scripts.domain import rule\n", encoding="utf-8")
    findings = validate_architecture(tmp_path, _registry())
    assert any(item["code"] == "UNREGISTERED_CROSS_COMPONENT_EDGE" for item in findings)

    registry = _registry(acceptedCurrentDependencies=[{
        "source": "scripts.application.use_case", "target": "scripts.domain.rule",
        "classification": "ACCEPTED_CURRENT_DEPENDENCY", "evidence": "synthetic",
        "disposition": "CHARACTERIZE_BEFORE_REFACTOR",
    }])
    assert validate_architecture(tmp_path, registry) == []


def test_unknown_module_duplicate_owner_and_stale_debt_fail_closed(tmp_path):
    (tmp_path / "scripts/unknown").mkdir(parents=True)
    (tmp_path / "scripts/unknown/x.py").write_text("VALUE = 1\n", encoding="utf-8")
    findings = validate_architecture(tmp_path, _registry())
    assert any(item["code"] == "ARCHITECTURE_OWNER_MISSING" for item in findings)

    duplicate = _registry(components=[
        {"id": "A", "prefixes": ["scripts/unknown/"]},
        {"id": "B", "prefixes": ["scripts/unknown/x.py"]},
    ])
    assert any(item["code"] == "ARCHITECTURE_OWNER_AMBIGUOUS" for item in validate_architecture(tmp_path, duplicate))

    stale = _registry(acceptedCurrentDependencies=[{
        "source": "scripts.application.missing", "target": "scripts.domain.missing",
        "classification": "POTENTIAL_VIOLATION", "evidence": "missing",
        "disposition": "REMOVE_LATER",
    }])
    assert any(item["code"] == "STALE_ARCHITECTURE_EXCEPTION" for item in validate_architecture(tmp_path, stale))


def test_relative_package_imports_resolve_and_dynamic_imports_fail_closed(tmp_path):
    package = tmp_path / "scripts/domain"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("from .rule import VALUE\n", encoding="utf-8")
    (package / "rule.py").write_text("VALUE = 1\n", encoding="utf-8")
    report = analyze_architecture(tmp_path, _registry())
    assert {tuple((edge["source"], edge["target"])) for edge in report["edges"]} >= {
        ("scripts.domain", "scripts.domain.rule")
    }
    (package / "dynamic.py").write_text("import importlib\nimportlib.import_module(name)\n", encoding="utf-8")
    assert any(item["code"] == "DYNAMIC_IMPORT_UNRESOLVED" for item in validate_architecture(tmp_path, _registry()))


def test_parse_failure_is_not_silently_skipped(tmp_path):
    package = tmp_path / "scripts/domain"
    package.mkdir(parents=True)
    (package / "broken.py").write_bytes(b"\xff\xfe")
    assert any(item["code"] == "ARCHITECTURE_SOURCE_UNPARSEABLE" for item in validate_architecture(tmp_path, _registry()))


def test_report_is_deterministic():
    registry = json.loads((ROOT / "config/core-architecture-v1.json").read_text(encoding="utf-8"))
    assert analyze_architecture(ROOT, registry) == analyze_architecture(ROOT, registry)
