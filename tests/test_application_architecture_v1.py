import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "scripts" / "backend_contract"
APPLICATION_PREFIX = "scripts.backend_contract.application"
INFRASTRUCTURE_PREFIX = "scripts.backend_contract.infrastructure"


def _module_name(path: Path) -> str:
    relative = path.relative_to(BACKEND).with_suffix("").parts
    suffix = relative[:-1] if relative[-1] == "__init__" else relative
    return ".".join(("scripts", "backend_contract", *suffix))


def _imports(path: Path) -> set[str]:
    module = _module_name(path)
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
            imports.add(target)
    return imports


def _production_files():
    return tuple(path for path in BACKEND.rglob("*.py") if "__pycache__" not in path.parts)


def test_core_does_not_import_application_or_infrastructure():
    core_files = tuple(path for path in BACKEND.glob("*.py"))
    forbidden = (APPLICATION_PREFIX, INFRASTRUCTURE_PREFIX)
    violations = {
        path.relative_to(ROOT).as_posix(): sorted(
            item for item in _imports(path) if item.startswith(forbidden)
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
            item for item in _imports(path) if item.startswith(forbidden)
        )
        for path in application_files
    }
    assert not {path: imports for path, imports in violations.items() if imports}


def test_infrastructure_boundary_exists_and_may_depend_on_application():
    marker = BACKEND / "infrastructure" / "__init__.py"
    assert marker.is_file()
    assert not any(
        item.startswith(INFRASTRUCTURE_PREFIX)
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
