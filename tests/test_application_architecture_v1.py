import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "scripts" / "backend_contract"
PRODUCTION = ROOT / "scripts"
APPLICATION_PREFIX = "scripts.backend_contract.application"
INFRASTRUCTURE_PREFIX = "scripts.backend_contract.infrastructure"
CORE_FORBIDDEN_IMPORTS = (APPLICATION_PREFIX, INFRASTRUCTURE_PREFIX, "sqlite3")


def _matches_namespace(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(f"{prefix}.")


def test_forbidden_namespace_matching_is_exact_and_core_includes_sqlite():
    assert "sqlite3" in CORE_FORBIDDEN_IMPORTS
    for prefix in CORE_FORBIDDEN_IMPORTS:
        assert _matches_namespace(prefix, prefix)
        assert _matches_namespace(f"{prefix}.child", prefix)
        assert not _matches_namespace(f"{prefix}_helpers", prefix)


def _module_name(path: Path) -> str:
    relative = path.relative_to(ROOT).with_suffix("").parts
    suffix = relative[:-1] if relative[-1] == "__init__" else relative
    return ".".join(suffix)


def _imports(path: Path, module=None) -> set[str]:
    module = _module_name(path) if module is None else module
    package = module.split(".") if path.name == "__init__.py" else module.split(".")[:-1]
    imports = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - node.level + 1]
                target = ".".join([*base, *(node.module or "").split(".")]).rstrip(".")
            else:
                target = node.module or ""
            if node.module or any(alias.name == "*" for alias in node.names):
                imports.add(target)
            imports.update(
                f"{target}.{alias.name}"
                for alias in node.names
                if alias.name != "*"
            )
    return imports


def test_import_resolver_tracks_from_import_aliases_without_package_self_cycle(tmp_path):
    core = tmp_path / "core.py"
    core.write_text(
        "from . import application\n"
        "from scripts.backend_contract import infrastructure\n",
        encoding="utf-8",
    )
    assert _imports(core, "scripts.backend_contract.core") == {
        "scripts.backend_contract",
        APPLICATION_PREFIX,
        INFRASTRUCTURE_PREFIX,
    }

    cycle = tmp_path / "cycle_a.py"
    cycle.write_text("from . import cycle_b\n", encoding="utf-8")
    assert _imports(cycle, f"{APPLICATION_PREFIX}.cycle_a") == {
        f"{APPLICATION_PREFIX}.cycle_b"
    }

    package = tmp_path / "__init__.py"
    package.write_text("from . import harmless\n", encoding="utf-8")
    assert _imports(package, APPLICATION_PREFIX) == {f"{APPLICATION_PREFIX}.harmless"}

    wildcard = tmp_path / "cycle_a.py"
    wildcard.write_text("from . import *\n", encoding="utf-8")
    assert _imports(wildcard, f"{APPLICATION_PREFIX}.cycle_a") == {
        APPLICATION_PREFIX
    }


def _production_files():
    return tuple(path for path in BACKEND.rglob("*.py") if "__pycache__" not in path.parts)


def _core_files(production=PRODUCTION):
    boundaries = {
        ("backend_contract", "application"),
        ("backend_contract", "infrastructure"),
    }
    return tuple(
        path
        for path in production.rglob("*.py")
        if tuple(path.relative_to(production).parts[:2]) not in boundaries
        and "__pycache__" not in path.parts
    )


def test_core_inventory_includes_nested_unknown_packages(tmp_path):
    production = tmp_path / "scripts"
    backend = production / "backend_contract"
    nested = backend / "helpers" / "bridge.py"
    nested.parent.mkdir(parents=True)
    nested.write_text("from .. import infrastructure\n", encoding="utf-8")
    domain = production / "planejamento_pericial" / "bridge.py"
    domain.parent.mkdir(parents=True)
    domain.write_text(
        "from scripts.backend_contract import infrastructure\n", encoding="utf-8"
    )
    assert set(_core_files(production)) == {nested, domain}


def test_core_does_not_import_application_or_infrastructure():
    core_files = _core_files()
    violations = {
        path.relative_to(ROOT).as_posix(): sorted(
            item
            for item in _imports(path)
            if any(_matches_namespace(item, prefix) for prefix in CORE_FORBIDDEN_IMPORTS)
        )
        for path in core_files
    }
    assert not {path: imports for path, imports in violations.items() if imports}


def test_application_does_not_import_sqlite_or_infrastructure():
    application_files = tuple((BACKEND / "application").rglob("*.py"))
    assert application_files
    forbidden = ("sqlite3", INFRASTRUCTURE_PREFIX)
    violations = {
        path.relative_to(ROOT).as_posix(): sorted(
            item
            for item in _imports(path)
            if any(_matches_namespace(item, prefix) for prefix in forbidden)
        )
        for path in application_files
    }
    assert not {path: imports for path, imports in violations.items() if imports}


def test_infrastructure_boundary_exists_and_may_depend_on_application():
    marker = BACKEND / "infrastructure" / "__init__.py"
    assert marker.is_file()
    assert not any(
        _matches_namespace(item, INFRASTRUCTURE_PREFIX)
        for path in (BACKEND / "application").rglob("*.py")
        for item in _imports(path)
    )


def test_backend_internal_dependency_graph_has_no_cycles():
    files = _production_files()
    modules = {_module_name(path): path for path in files}
    graph = {
        module: {target for target in _imports(path) if target in modules}
        for module, path in modules.items()
    }

    def visit(module, active, complete):
        if module in active:
            raise AssertionError(f"dependency cycle: {' -> '.join((*active, module))}")
        if module in complete:
            return
        active = (*active, module)
        for target in graph[module]:
            visit(target, active, complete)
        complete.add(module)

    complete = set()
    for module in graph:
        visit(module, (), complete)
