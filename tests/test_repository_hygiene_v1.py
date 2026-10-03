"""REPOSITORY_HYGIENE_V1 (#279): classification without false dead-code verdicts.

Every synthetic repository here is built in tmp_path with `git init`/`git add`;
the auditor itself never spawns a process and never deletes anything.
"""
from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path

import pytest

from scripts.quality import git_worktree, product_maturity, repository_hygiene
from scripts.quality.repository_hygiene import audit, validate_output

ROOT = Path(__file__).resolve().parents[1]
REAL_CONFIG = json.loads((ROOT / "config/repository-authority-v1.json").read_text(encoding="utf-8"))


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def _repo(tmp_path: Path, files: dict[str, str], *, commit: bool = False) -> Path:
    for path, content in files.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    if commit:
        _git(tmp_path, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-qm", "synthetic")
    return tmp_path


def _config(**overrides) -> dict:
    config = {
        "current_authority": [{"path": "AGENTS.md", "role": "HOW_TO_WORK"}],
        "agent_wrappers": {"target": "AGENTS.md", "max_bytes": 2048, "paths": []},
        "historical": [],
        "status_markers": {},
        "generated_evidence": [],
        "file_classes": [{"prefix": "tests/", "class": "ASSURANCE"}],
        "durable_documents": [],
        "stale_markers": [],
        "durable_document_forbidden": [],
        "python": {
            "runtime_roots": ["app.main"],
            "product_layer_prefixes": ["app/"],
            "legacy_core_prefixes": ["core/"],
            "gate_text_prefixes": [".github/", "config/"],
            "gate_text_paths": [],
            "skill_text_prefixes": [".agents/"],
            "test_text_prefixes": ["tests/"],
            "documentation_text_prefixes": ["docs/", "README.md"],
        },
        "frontend": {
            "root": "web/",
            "entrypoints": ["web/src/main.tsx"],
            "build_files": ["web/index.html"],
            "test_support_prefixes": ["web/src/test/"],
        },
        "generated_patterns": ["(^|/)__pycache__/", "\\.py[cod]$"],
        "large_file_bytes": 1048576,
    }
    config.update(overrides)
    return config


ROUTER = json.dumps({
    "material_bundle": ["bundle-skill"],
    "profiles": {"ui": {"required": [], "conditional": {"polish_requested": ["conditional-skill"]}}},
    "reference_only": ["reference-skill"],
})

BASE = {
    "AGENTS.md": "# agents\n",
    ".agents/skill-router.json": ROUTER,
    ".agents/skills/bundle-skill/SKILL.md": "bundle\n",
    ".agents/skills/conditional-skill/SKILL.md": "conditional\n",
    ".agents/skills/reference-skill/SKILL.md": "reference\n",
    "web/index.html": '<script type="module" src="/src/main.tsx"></script>\n',
    "web/src/main.tsx": 'import { App } from "./App";\nApp();\n',
    "web/src/App.tsx": "export function App() { return null; }\n",
}


def _python(report: dict, path: str) -> str:
    return report["python"]["modules"][path]["status"]


def test_python_reachability_has_no_false_dead_code(tmp_path):
    repo = _repo(tmp_path, {
        **BASE,
        "app/__init__.py": "",
        "app/main.py": "from . import relative_dep\nimport app.absolute_dep\nfrom app.pkg import thing\n",
        "app/relative_dep.py": "X = 1\n",
        "app/absolute_dep.py": "Y = 1\n",
        "app/pkg/__init__.py": "from .thing import thing\n",
        "app/pkg/thing.py": "thing = 1\n",
        "app/cli_tool/__init__.py": "",
        "app/cli_tool/__main__.py": "print('run')\n",
        "gates/__init__.py": "",
        "gates/ci_only.py": "if __name__ == '__main__':\n    pass\n",
        ".github/workflows/ci.yml": "run: python -m gates.ci_only && python -m app.cli_tool\n",
        "skilltools/__init__.py": "",
        "skilltools/helper.py": "Z = 1\n",
        ".agents/skills/bundle-skill/SKILL.md": "Run `python skilltools/helper.py`.\n",
        "testlib/__init__.py": "",
        "testlib/only_tests.py": "W = 1\n",
        "tests/test_something.py": "from testlib.only_tests import W\n",
        "core/__init__.py": "",
        "core/engine.py": "import sibling\n",
        "core/sibling.py": "S = 1\n",
        "tests/test_core.py": "import subprocess\nsubprocess.run(['python', 'core/engine.py'])\n",
        "orphan/__init__.py": "",
        "orphan/truly_dead.py": "def unused():\n    return 1\n",
    })
    report = audit(repo, config=_config())
    assert _python(report, "app/main.py") == "PRODUCTION_REACHABLE"
    assert _python(report, "app/relative_dep.py") == "PRODUCTION_REACHABLE"
    assert _python(report, "app/absolute_dep.py") == "PRODUCTION_REACHABLE"
    assert _python(report, "app/pkg/__init__.py") == "PRODUCTION_REACHABLE"
    assert _python(report, "app/pkg/thing.py") == "PRODUCTION_REACHABLE"
    assert _python(report, "app/cli_tool/__main__.py") == "GATE_ONLY"
    assert _python(report, "gates/ci_only.py") == "GATE_ONLY"
    assert _python(report, "skilltools/helper.py") == "SKILL_ONLY"
    assert _python(report, "testlib/only_tests.py") == "TEST_ONLY"
    assert _python(report, "core/engine.py") == "LEGACY_BUT_LIVE"
    assert _python(report, "core/sibling.py") == "LEGACY_BUT_LIVE"
    assert _python(report, "orphan/truly_dead.py") == "UNREACHABLE_CANDIDATE"
    dead = [item for item in report["findings"] if item["classification"] == "DEAD_CODE_CANDIDATE"]
    assert [item["path"] for item in dead] == ["orphan/__init__.py", "orphan/truly_dead.py"]
    assert {item["confidence"] for item in dead} <= {"STRONG_CANDIDATE", "NEEDS_REVIEW"}
    assert all("REMOVE_IN_SEPARATE_PR" in item["recommended_action"] for item in dead)
    assert validate_output(report, ROOT) == []


def test_a_document_mention_is_not_a_consumer_but_lowers_confidence(tmp_path):
    repo = _repo(tmp_path, {
        **BASE,
        "app/__init__.py": "",
        "app/main.py": "",
        "tools/__init__.py": "",
        "tools/manual.py": "if __name__ == '__main__':\n    print(1)\n",
        "tools/forgotten.py": "V = 1\n",
        "docs/manual.md": "Run `python -m tools.manual`. The old tools/forgotten.py is mentioned here.\n",
    })
    report = audit(repo, config=_config())
    assert _python(report, "tools/manual.py") == "MANUAL_ENTRYPOINT"
    forgotten = next(item for item in report["findings"] if item["path"] == "tools/forgotten.py")
    assert forgotten["classification"] == "DEAD_CODE_CANDIDATE"
    assert forgotten["confidence"] == "NEEDS_REVIEW"
    assert "docs/manual.md" in forgotten["known_consumers"]


def test_product_layer_alive_only_through_tests_is_reported_not_condemned(tmp_path):
    repo = _repo(tmp_path, {
        **BASE,
        "app/__init__.py": "",
        "app/main.py": "",
        "app/unwired.py": "U = 1\n",
        "tests/test_unwired.py": "from app.unwired import U\n",
    })
    report = audit(repo, config=_config())
    finding = next(item for item in report["findings"] if item["path"] == "app/unwired.py")
    assert finding["classification"] == "PRODUCTION_UNREACHABLE"
    assert finding["recommended_action"].startswith("KEEP")
    assert report["files"]["app/unwired.py"] == "TEST_ONLY"


def test_frontend_reachability_follows_ts_tsx_and_barrels(tmp_path):
    repo = _repo(tmp_path, {
        **BASE,
        "app/__init__.py": "",
        "app/main.py": "",
        "web/src/main.tsx": 'import { App } from "./App";\nimport "./styles/global.css";\nApp();\n',
        "web/src/App.tsx": 'import { Panel } from "./ui";\nimport type { Shape } from "./types";\nexport function App() { return Panel; }\n',
        "web/src/ui/index.ts": 'export * from "./Panel";\nexport { helper } from "../lib/helper.js";\n',
        "web/src/ui/Panel.tsx": "export const Panel = 1;\n",
        "web/src/lib/helper.ts": "export const helper = 1;\n",
        "web/src/types.ts": "export type Shape = { a: 1 };\n",
        "web/src/styles/global.css": '@import "./tokens.css";\n',
        "web/src/styles/tokens.css": ":root{}\n",
        "web/src/test/setup.ts": 'import "./matchers";\n',
        "web/src/test/matchers.ts": "export {};\n",
        "web/src/fixtures/TestOnlyWidget.tsx": "export const W = 1;\n",
        "web/src/App.test.tsx": 'import { W } from "./fixtures/TestOnlyWidget";\nimport { App } from "./App";\n',
        "web/src/Abandoned.tsx": "export const Abandoned = 1;\n",
    })
    modules = audit(repo, config=_config())["frontend"]["modules"]
    for path in ("web/src/main.tsx", "web/src/App.tsx", "web/src/ui/index.ts", "web/src/ui/Panel.tsx",
                 "web/src/lib/helper.ts", "web/src/types.ts", "web/src/styles/global.css", "web/src/styles/tokens.css"):
        assert modules[path]["status"] == "RUNTIME", path
    assert modules["web/src/App.test.tsx"]["status"] == "TEST"
    assert modules["web/src/test/matchers.ts"]["status"] == "TEST"
    assert modules["web/src/fixtures/TestOnlyWidget.tsx"]["status"] == "TEST_ONLY"
    assert modules["web/src/Abandoned.tsx"]["status"] == "UNREACHABLE_CANDIDATE"


def test_schema_consumers_are_counted_before_any_orphan_verdict(tmp_path):
    schema = lambda name: json.dumps({"$id": f"https://x.local/schemas/{name}", "type": "object"})  # noqa: E731
    repo = _repo(tmp_path, {
        **BASE,
        "app/__init__.py": "",
        "app/main.py": "",
        "schemas/base.schema.json": schema("base.schema.json"),
        "schemas/child.schema.json": json.dumps({"$id": "https://x.local/schemas/child.schema.json", "$ref": "base.schema.json"}),
        "schemas/versioned.schema.json": schema("versioned.schema.json"),
        "config/schema-versions.json": json.dumps({"schemas": [{"schema": "versioned.schema.json"}]}),
        "schemas/validated.schema.json": schema("validated.schema.json"),
        "app/validator.py": "SCHEMA = 'validated.schema.json'\n",
        "schemas/fixtured.schema.json": schema("fixtured.schema.json"),
        "tests/fixtures/core-fixtures.json": json.dumps({"fixtures": [{"arquivo": "tests/fixtures/x.json", "schema": "fixtured.schema.json"}]}),
        "schemas/documented.schema.json": schema("documented.schema.json"),
        "docs/contracts.md": "See documented.schema.json.\n",
        "schemas/orphan.schema.json": schema("orphan.schema.json"),
    })
    schemas = audit(repo, config=_config())["schemas"]
    assert schemas["schemas/base.schema.json"]["consumer_kinds"] == ["SCHEMA_REF"]
    assert "SCHEMA_VERSIONS" in schemas["schemas/versioned.schema.json"]["consumer_kinds"]
    assert "RUNTIME_VALIDATOR" in schemas["schemas/validated.schema.json"]["consumer_kinds"]
    assert "FIXTURE_REGISTRY" in schemas["schemas/fixtured.schema.json"]["consumer_kinds"]
    for path in ("base", "versioned", "validated", "fixtured"):
        assert schemas[f"schemas/{path}.schema.json"]["status"] == "LIVE"
    assert schemas["schemas/documented.schema.json"]["status"] == "SCHEMA_ORPHAN_CANDIDATE"
    assert schemas["schemas/orphan.schema.json"]["status"] == "SCHEMA_ORPHAN_CANDIDATE"


def test_fixture_states_come_from_the_existing_registry(tmp_path):
    repo = _repo(tmp_path, {
        **BASE,
        "app/__init__.py": "",
        "app/main.py": "",
        "tests/fixtures/core-fixtures.json": json.dumps({"fixtures": [{
            "arquivo": "tests/fixtures/gone.json", "dominio": "X", "schema": None, "consumer": "tests/test_x.py::test_x",
            "finalidade": "x", "expected": "VALID", "provenance": "SYNTHETIC"}]}),
        "tests/fixtures/stray.json": "{}",
        "tests/test_x.py": "def test_x():\n    'gone.json'\n",
    })
    findings = audit(repo, config=_config())["findings"]
    codes = {(item["path"], item["registry_code"]) for item in findings if "registry_code" in item}
    assert ("tests/fixtures/stray.json", "FIXTURE_ORFA") in codes
    assert ("tests/fixtures/gone.json", "REGISTRY_STALE") in codes


def test_skill_routing_audit_separates_installed_from_integrated(tmp_path):
    repo = _repo(tmp_path, {
        **BASE,
        "app/__init__.py": "",
        "app/main.py": "",
        ".agents/skills/vendored-unrouted/SKILL.md": "new\n",
        "AGENTS.md": "# agents\nUse reference-skill sometimes.\n",
    })
    report = audit(repo, config=_config())
    status = {item["skill"]: item["status"] for item in report["skills"]}
    assert status == {
        "bundle-skill": "SKILL_REQUIRED",
        "conditional-skill": "SKILL_CONDITIONAL",
        "reference-skill": "SKILL_REFERENCE_ONLY",
        "vendored-unrouted": "SKILL_UNROUTED",
    }
    assert next(item for item in report["skills"] if item["skill"] == "reference-skill")["referenced_by"] == ["AGENTS.md"]
    assert report["summary"]["skill_unrouted"] == 1
    assert report["invariant_violations"] == []

    (repo / ".agents/skill-router.json").write_text(json.dumps({**json.loads(ROUTER), "reference_only": ["ghost-skill"]}), encoding="utf-8")
    violations = audit(repo, config=_config())["invariant_violations"]
    assert {(item["code"], item["detail"]) for item in violations} == {
        ("ROUTER_SKILL_MISSING", "router names skill not installed: ghost-skill")
    }


def test_document_authority_history_and_stale_markers(tmp_path):
    files = {
        **BASE,
        "app/__init__.py": "",
        "app/main.py": "",
        "PRODUCT.md": "This milestone provides only the application shell.\n",
        "README.md": "Validated on main `27175535933a`.\n",
        "docs/plans/README.md": "STATUS: HISTORICAL ENGINEERING RECORDS\n",
        "docs/plans/2026-01-01-old.md": "old plan\n",
        "CLAUDE.md": "Read `AGENTS.md`.\n",
        "CODEX.md": "Read `AGENTS.md`.\n",
    }
    config = _config(
        current_authority=[{"path": "AGENTS.md", "role": "HOW_TO_WORK"}, {"path": "PRODUCT.md", "role": "WHAT"},
                           {"path": "DESIGN.md", "role": "LOOK"}],
        agent_wrappers={"target": "AGENTS.md", "max_bytes": 2048, "paths": ["CLAUDE.md", "CODEX.md"]},
        historical=[{"prefix": "docs/plans/", "status_readme": "docs/plans/README.md", "role": "PLANS"}],
        status_markers={"docs/plans/README.md": "STATUS: HISTORICAL ENGINEERING RECORDS"},
        durable_documents=["README.md", "PRODUCT.md"],
        stale_markers=[{"paths": ["PRODUCT.md"], "pattern": "provides only the application shell", "reason": "shell"}],
        durable_document_forbidden=REAL_CONFIG["durable_document_forbidden"],
    )
    report = audit(_repo(tmp_path, files), config=config)
    codes = sorted((item["code"], item["path"]) for item in report["invariant_violations"])
    assert codes == [
        ("AUTHORITY_MISSING", "DESIGN.md"),
        ("AUTHORITY_STALE_MARKER", "PRODUCT.md"),
        ("DURABLE_DOCUMENT_TEMPORAL_COUPLING", "README.md"),
    ]
    assert report["files"]["docs/plans/2026-01-01-old.md"] == "HISTORICAL"
    assert report["files"]["AGENTS.md"] == "CURRENT_AUTHORITY"
    assert {"CLAUDE.md", "CODEX.md"} <= {path for group in report["duplicates"] for path in group["paths"]}
    assert all(group["classification"] == "INTENTIONAL_WRAPPER_DUPLICATION" for group in report["duplicates"])
    assert report["summary"]["stale_documents"] == ["PRODUCT.md", "README.md"]


def test_unintended_duplicates_and_generated_files_are_flagged_not_removed(tmp_path):
    body = "def same():\n    return 'identical content long enough to count as a duplicate'\n"
    repo = _repo(tmp_path, {
        **BASE,
        "app/__init__.py": "",
        "app/main.py": "import app.one\nimport app.two\n",
        "app/one.py": body,
        "app/two.py": body,
        "app/__pycache__/main.cpython-313.pyc": "x",
    })
    before = sorted(str(path) for path in repo.rglob("*") if ".git" not in path.parts)
    report = audit(repo, config=_config())
    after = sorted(str(path) for path in repo.rglob("*") if ".git" not in path.parts)
    assert before == after
    assert any(item["classification"] == "DUPLICATE_CONTENT" and item["group"] == ["app/one.py", "app/two.py"] for item in report["findings"])
    assert any(item["classification"] == "GENERATED_FILE_TRACKED" for item in report["findings"])
    assert report["auto_delete"] is False


def test_auditor_source_has_no_delete_or_process_capability():
    for module in (repository_hygiene, git_worktree, product_maturity):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
                    for alias in node.names} | {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
        assert not imported & {"subprocess", "shutil", "importlib", "os"}, module.__name__
        called = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        assert not called & {"unlink", "rmtree", "remove", "rmdir", "write_text", "write_bytes", "rename", "replace_file"}, module.__name__


def test_index_reader_matches_git_for_v2_v4_and_symlink_entries(tmp_path):
    repo = _repo(tmp_path, {"a.txt": "a", "dir/b.txt": "b", "dir/sub/c.txt": "c"})
    try:
        (repo / "link").symlink_to("a.txt")
    except OSError:
        pytest.skip("symlinks unavailable on this platform")
    _git(repo, "add", "link")
    for version in ("2", "3", "4"):
        _git(repo, "update-index", "--index-version", version)
        expected = _git(repo, "ls-files", "-z").split("\0")[:-1]
        entries = git_worktree.read_index(repo)
        assert [entry.path for entry in entries] == expected
        assert [entry.path for entry in entries if entry.is_symlink] == ["link"]
    report = audit(repo, config=_config(current_authority=[]))
    assert any(item["classification"] == "SYMLINK_TRACKED" and item["path"] == "link" for item in report["findings"])


def test_live_repository_contract_holds():
    report = audit(ROOT)
    assert validate_output(report, ROOT) == []
    assert report["invariant_violations"] == [], report["invariant_violations"]
    assert report["auto_delete"] is False
    assert report["summary"]["files"] == len(report["files"])
    assert report["summary"]["unclassified"] == 0, [path for path, value in report["files"].items() if value == "UNCLASSIFIED"]
    legacy = tuple(REAL_CONFIG["python"]["legacy_core_prefixes"])
    for path, record in report["python"]["modules"].items():
        if path.startswith(legacy):
            assert record["status"] in {"LEGACY_BUT_LIVE", "PRODUCTION_REACHABLE"}, (path, record["status"])
    assert all(record["status"] == "LIVE" for record in report["schemas"].values())
    assert report["files"]["PRODUCT.md"] == "CURRENT_AUTHORITY"
    assert report["files"]["docs/superpowers/plans/2026-08-23-frontend-shell-v1.md"] == "HISTORICAL"


def test_maturity_declaration_is_evidence_not_live_head():
    declaration = json.loads((ROOT / "config/product-maturity-v1.json").read_text(encoding="utf-8"))
    assert product_maturity.contract_errors(declaration) == []
    assert "current_main_sha" not in declaration
    sha = declaration["evidence_base_sha"]
    assert product_maturity.evaluate(declaration, sha)["declaration_status"] == "CURRENT_EVIDENCE"
    assert product_maturity.evaluate(declaration, "f" * 40)["declaration_status"] == "HISTORICAL_EVIDENCE"
    assert product_maturity.evaluate(declaration, None)["declaration_status"] == "LIVE_HEAD_UNAVAILABLE"
    legacy = {**declaration, "current_main_sha": sha}
    assert "forbidden live-state key: current_main_sha" in product_maturity.contract_errors(legacy)


def test_maturity_status_is_not_self_referential_across_commits(tmp_path):
    repo = _repo(tmp_path, {"README.md": "x"}, commit=True)
    first = _git(repo, "rev-parse", "HEAD").strip()
    declaration = {"evidence_base_sha": first, "evidence_base_semantics": product_maturity.EVIDENCE_SEMANTICS}
    (repo / "config").mkdir()
    (repo / "config/product-maturity-v1.json").write_text(json.dumps(declaration), encoding="utf-8")
    assert git_worktree.live_head(repo) == first
    assert product_maturity.live_status(repo)["declaration_status"] == "CURRENT_EVIDENCE"
    # Committing the declaration creates a new HEAD: the same declaration is now
    # honest historical evidence, never a claim about the live HEAD.
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-qm", "declare")
    second = product_maturity.live_status(repo)
    assert second["observed_repository_head"] != first
    assert second["declaration_status"] == "HISTORICAL_EVIDENCE"
    assert second["contract_errors"] == []
    _git(repo, "pack-refs", "--all")
    assert product_maturity.live_status(repo)["observed_repository_head"] == second["observed_repository_head"]
