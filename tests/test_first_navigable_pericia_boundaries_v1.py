import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "scripts" / "backend_contract" / "product_bridge"
FRONTEND = ROOT / "frontend" / "src"


def imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    result = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            result.add(("." * node.level) + (node.module or ""))
    return result


def production_frontend_sources():
    return tuple(
        path
        for path in FRONTEND.rglob("*")
        if path.suffix in {".ts", ".tsx"}
        and ".test." not in path.name
        and "test" not in path.parts
    )


def test_product_bridge_has_no_domain_or_persistence_bypass():
    assert BRIDGE.is_dir()
    forbidden_import_fragments = (
        "sqlite3",
        "backend_contract.application",
        "backend_contract.infrastructure",
        "motor_vicios",
        "planejamento_pericial",
        "vistoria_estruturada",
    )
    for path in BRIDGE.glob("*.py"):
        module_imports = imports(path)
        assert not any(
            fragment in imported
            for imported in module_imports
            for fragment in forbidden_import_fragments
        ), path
        assert not re.search(
            r"\b(?:SELECT|INSERT|UPDATE|DELETE|CREATE\s+TABLE|PRAGMA)\b",
            path.read_text(encoding="utf-8"),
            re.IGNORECASE,
        ), path


def test_only_product_bridge_composition_imports_local_api_composition():
    importers = {
        path.name
        for path in BRIDGE.glob("*.py")
        if any("local_api.composition" in imported for imported in imports(path))
    }
    assert importers == {"composition.py"}


def test_frontend_network_access_is_narrow_and_never_contains_local_api_token():
    network_sources = []
    for path in production_frontend_sources():
        source = path.read_text(encoding="utf-8")
        if re.search(r"\bfetch\s*\(", source):
            network_sources.append(path.relative_to(ROOT).as_posix())
        assert "X-Local-API-Token" not in source
        assert not re.search(r"\b(?:localStorage|sessionStorage|indexedDB)\b", source)
        assert not re.search(r"https?://", source)
    assert sorted(network_sources) == [
        "frontend/src/data/materials.ts",
        "frontend/src/data/processCase.ts",
        "frontend/src/data/workspaces.ts",
    ]


def test_process_case_domain_fields_stay_out_of_bridge_and_in_exact_frontend_modules():
    forbidden = re.compile(
        r"\b(?:numero_processo|tribunal|vara|comarca_municipio|uf|parte_requerente|parte_requerida)\b",
        re.IGNORECASE,
    )
    for path in BRIDGE.glob("*.py"):
        assert not forbidden.search(path.read_text(encoding="utf-8")), path
    frontend_domain_sources = {
        path.relative_to(ROOT).as_posix()
        for path in production_frontend_sources()
        if forbidden.search(path.read_text(encoding="utf-8"))
    }
    assert frontend_domain_sources == {
        "frontend/src/data/processCase.ts",
        "frontend/src/workspaces/ProcessCaseView.tsx",
    }
