"""REPOSITORY_HYGIENE_V1: classify every tracked file; never delete anything.

    python -m scripts.quality.repository_hygiene [--format json|markdown] [--check]

The auditor answers, for any tracked file: what it is, whether it still
governs the product, who consumes it and whether it is runtime, assurance,
reference or history. It is read-only by construction: it reads the Git index
and the worktree bytes of indexed paths and writes only to stdout.

Two kinds of output:
- `invariant_violations` (DETERMINISTIC_INVARIANT): breaks of this auditor's own
  contract or of declared authority (missing authority file, router naming a
  skill that does not exist, unreadable fixture registry, stale marker in a
  durable document). `--check` fails only on these.
- `findings` (ADVISORY_FINDING): heuristic candidates. They never fail a gate.
  Anything that looks unused is a `*_CANDIDATE`: UNREFERENCED != SAFE_TO_DELETE.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import jsonschema

from .ast_inventory import module_name, parse_source
from .fixture_registry import validate_fixture_registry
from .git_worktree import GitWorktreeError, live_head, read_index

ROOT = Path(__file__).resolve().parents[2]
AUTHORITY_CONFIG = "config/repository-authority-v1.json"
OUTPUT_SCHEMA = "schemas/repository-hygiene-v1.schema.json"
SKILL_ROUTER = ".agents/skill-router.json"
SKILLS_DIR = ".agents/skills/"
SCHEMA_VERSION = "1.0.0"
TEXT_SUFFIXES = {
    ".py", ".md", ".json", ".yml", ".yaml", ".toml", ".cfg", ".txt", ".ts", ".tsx", ".js", ".jsx",
    ".mjs", ".cjs", ".css", ".html", ".ps1", ".sh", ".csv", ".lock", ".toml", ".ini", ".xml", "",
}
FRONTEND_CODE_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".css")
FRONTEND_ASSET_SUFFIXES = (".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".woff", ".woff2", ".ttf", ".otf")

# Python reachability classes, strongest first.
PRODUCTION_REACHABLE = "PRODUCTION_REACHABLE"
GATE_ONLY = "GATE_ONLY"
SKILL_ONLY = "SKILL_ONLY"
TEST_ONLY = "TEST_ONLY"
TEST_SUPPORT = "TEST_SUPPORT"
LEGACY_BUT_LIVE = "LEGACY_BUT_LIVE"
MANUAL_ENTRYPOINT = "MANUAL_ENTRYPOINT"
TEST_MODULE = "TEST_MODULE"
UNREACHABLE_CANDIDATE = "UNREACHABLE_CANDIDATE"
_ROOT_PRECEDENCE = ("RUNTIME", "GATE", "SKILL", "TEST", "DOCUMENTED")

# Frontend reachability classes.
RUNTIME = "RUNTIME"
TEST = "TEST"
STORY_DEMO_ONLY = "STORY_DEMO_ONLY"
BUILD_CONFIG = "BUILD_CONFIG"

# Confidence classes; deliberately no percentages.
PROVEN = "PROVEN"
STRONG_CANDIDATE = "STRONG_CANDIDATE"
NEEDS_REVIEW = "NEEDS_REVIEW"

_TOKEN = r"[A-Za-z0-9_][A-Za-z0-9_./\\-]*[A-Za-z0-9_]"
_IMPORT_FROM = r"""(?:import|export)\s+(?:type\s+)?[^'";]*?\sfrom\s*['"]([^'"]+)['"]"""
_IMPORT_BARE = r"""(?:^|[\s;])import\s*['"]([^'"]+)['"]"""
_IMPORT_DYNAMIC = r"""(?:import|require)\(\s*['"]([^'"]+)['"]\s*\)"""
_CSS_IMPORT = r"""@import\s+(?:url\()?\s*['"]([^'"]+)['"]"""
_HTML_SRC = r"""(?:src|href)\s*=\s*['"]([^'"]+)['"]"""


@dataclass
class Repository:
    root: Path
    files: tuple[str, ...]
    symlinks: tuple[str, ...]
    head: str | None
    _text: dict[str, str | None] = field(default_factory=dict)

    def exists(self, path: str) -> bool:
        return path in self._file_set

    @property
    def _file_set(self) -> frozenset[str]:
        cached = self.__dict__.get("_files_frozen")
        if cached is None:
            cached = frozenset(self.files)
            self.__dict__["_files_frozen"] = cached
        return cached

    def text(self, path: str) -> str | None:
        if path not in self._text:
            value: str | None = None
            if PurePosixPath(path).suffix.lower() in TEXT_SUFFIXES and path not in self.symlinks:
                try:
                    value = (self.root / path).read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    value = None
            self._text[path] = value
        return self._text[path]

    def raw(self, path: str) -> bytes | None:
        try:
            return (self.root / path).read_bytes()
        except OSError:
            return None


def load_repository(root: Path, files: tuple[str, ...] | None = None) -> Repository:
    root = Path(root)
    symlinks: tuple[str, ...] = ()
    if files is None:
        entries = read_index(root)
        files = tuple(entry.path for entry in entries if not entry.is_gitlink)
        symlinks = tuple(entry.path for entry in entries if entry.is_symlink)
    try:
        head = live_head(root)
    except (GitWorktreeError, OSError):
        head = None
    present = tuple(sorted(path for path in files if (root / path).is_file() or path in symlinks))
    return Repository(root, present, symlinks, head)


def _starts(path: str, prefixes) -> bool:
    return any(path == prefix or path.startswith(prefix) for prefix in prefixes)


def _match_entry(path: str, entry: dict) -> bool:
    if "path" in entry:
        return path == entry["path"]
    return path.startswith(entry["prefix"])


def _finding(path, classification, evidence, known=(), unknown=(), risk="LOW", action="KEEP", confidence=NEEDS_REVIEW, **extra) -> dict:
    record = {
        "path": path,
        "classification": classification,
        "evidence": evidence,
        "known_consumers": sorted(set(known)),
        "unknown_consumers": list(unknown),
        "risk": risk,
        "recommended_action": action,
        "confidence": confidence,
    }
    record.update(extra)
    return record


def _violation(code: str, path: str, detail: str) -> dict:
    return {"code": code, "path": path, "detail": detail}


# --------------------------------------------------------------------------- Python


def package_mains(modules: dict[str, str]) -> dict[str, str]:
    """`python -m package` runs package/__main__.py: only the NAME of the package reaches it."""
    return {name: modules[f"{name}.__main__"] for name in modules if f"{name}.__main__" in modules}


def python_module_names(files) -> dict[str, str]:
    """Importable module name -> path for tracked Python under identifier-only directories."""
    modules: dict[str, str] = {}
    for path in files:
        if not path.endswith(".py"):
            continue
        parts = path[:-3].split("/")
        if all(part.isidentifier() for part in parts):
            modules[module_name(path)] = path
    return modules


def _package_of(module: str, path: str) -> str:
    return module if path.endswith("/__init__.py") else module.rpartition(".")[0]


def _ancestors(name: str):
    parts = name.split(".")
    for index in range(1, len(parts) + 1):
        yield ".".join(parts[:index])


def _resolve_python_import(name: str, path: str, modules: dict[str, str]) -> list[str]:
    """Resolve an absolute dotted name the way the repository actually runs it."""
    candidates = [name, f"scripts.{name}"]
    directory = path.rpartition("/")[0].replace("/", ".")
    if directory:
        candidates.append(f"{directory}.{name}")  # sibling import of a script run by path
    for candidate in candidates:
        if candidate in modules:
            return [ancestor for ancestor in _ancestors(candidate) if ancestor in modules]
    return []


def python_edges(repo: Repository, modules: dict[str, str]) -> tuple[dict[str, set[str]], dict[str, bool], list[dict]]:
    """Static import edges plus string-literal references (subprocess `-m`, paths)."""
    by_path = {path: name for name, path in modules.items()}
    known_strings = set(modules) | set(modules.values())
    mains = package_mains(modules)
    edges: dict[str, set[str]] = defaultdict(set)
    has_main: dict[str, bool] = {}
    violations: list[dict] = []
    for path in repo.files:
        if not path.endswith(".py"):
            continue
        source = repo.text(path)
        if source is None:
            violations.append(_violation("PYTHON_UNREADABLE", path, "not UTF-8 text"))
            continue
        try:
            tree = parse_source(path, source)
        except SyntaxError as exc:
            violations.append(_violation("PYTHON_UNPARSEABLE", path, f"line {exc.lineno}"))
            continue
        module = by_path.get(path)
        targets = edges[path]
        has_main[path] = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    targets.update(modules[name] for name in _resolve_python_import(alias.name, path, modules))
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    if module is None:
                        continue
                    base = _package_of(module, path).split(".")
                    if node.level > 1:
                        base = base[: len(base) - (node.level - 1)]
                    prefix = ".".join(base)
                    name = f"{prefix}.{node.module}" if node.module else prefix
                    resolved = [ancestor for ancestor in _ancestors(name) if ancestor in modules]
                else:
                    name = node.module or ""
                    resolved = _resolve_python_import(name, path, modules)
                    if resolved:
                        name = resolved[-1] if name not in modules else name
                targets.update(modules[item] for item in resolved)
                for alias in node.names:
                    child = f"{name}.{alias.name}"
                    if child in modules:
                        targets.update(modules[item] for item in _ancestors(child) if item in modules)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                for token in _string_tokens(node.value):
                    if token in known_strings:
                        targets.add(modules.get(token, token))
                    if token in mains:
                        targets.add(mains[token])
            elif isinstance(node, ast.If) and _is_main_guard(node.test):
                has_main[path] = True
        # Importing or running a module imports every package above it.
        if module is not None:
            targets.update(modules[item] for item in list(_ancestors(module))[:-1] if item in modules)
        targets.discard(path)
    return edges, has_main, violations


def _is_main_guard(test: ast.AST) -> bool:
    return (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and test.left.id == "__name__"
        and any(isinstance(item, ast.Constant) and item.value == "__main__" for item in test.comparators)
    )


def _string_tokens(text: str):
    for token in re.findall(_TOKEN, text):
        normalized = token.replace("\\", "/")
        yield normalized
        if normalized.endswith("::") or "::" in normalized:
            yield normalized.split("::", 1)[0]


def _text_references(repo: Repository, known: set[str], prefixes, paths=()) -> dict[str, set[str]]:
    """Known module names/paths mentioned in non-Python text files under `prefixes`."""
    references: dict[str, set[str]] = defaultdict(set)
    for path in repo.files:
        if path.endswith(".py") or not (_starts(path, prefixes) or path in paths):
            continue
        text = repo.text(path)
        if text is None:
            continue
        for token in _string_tokens(text):
            for candidate in (token, token.split("::", 1)[0]):
                if candidate in known:
                    references[candidate].add(path)
    return references


def python_reachability(repo: Repository, config: dict) -> tuple[dict[str, dict], list[dict]]:
    settings = config["python"]
    modules = python_module_names(repo.files)
    edges, has_main, violations = python_edges(repo, modules)
    known = set(modules) | set(modules.values())
    to_path = lambda token: modules.get(token, token)  # noqa: E731

    roots: dict[str, set[str]] = {kind: set() for kind in _ROOT_PRECEDENCE}
    consumers: dict[str, set[str]] = defaultdict(set)
    for name in settings["runtime_roots"]:
        if name not in modules:
            violations.append(_violation("RUNTIME_ROOT_MISSING", name, "declared Python runtime root is not tracked"))
        else:
            roots["RUNTIME"].add(modules[name])
            consumers[modules[name]].add(f"runtime-root:{AUTHORITY_CONFIG}")
    for path in repo.files:
        name = PurePosixPath(path).name
        if path.endswith(".py") and path.startswith("tests/") and (name.startswith("test_") or name == "conftest.py"):
            roots["TEST"].add(path)
    for kind, prefixes, extra in (
        ("GATE", settings["gate_text_prefixes"], settings.get("gate_text_paths", ())),
        ("SKILL", settings["skill_text_prefixes"], ()),
        ("TEST", settings["test_text_prefixes"], ()),
        ("DOCUMENTED", settings["documentation_text_prefixes"], ()),
    ):
        for token, sources in _text_references(repo, known, prefixes, extra).items():
            for target in {to_path(token), package_mains(modules).get(token)} - {None}:
                roots[kind].add(target)
                consumers[target].update(sources)
    # Gate code is itself a gate root once a workflow names it (closure below).
    for source, targets in edges.items():
        for target in targets:
            consumers[target].add(source)

    reached: dict[str, set[str]] = defaultdict(set)
    for kind in _ROOT_PRECEDENCE:
        queue = deque(sorted(roots[kind]))
        seen: set[str] = set()
        while queue:
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            reached[current].add(kind)
            if kind == "DOCUMENTED":
                continue  # a document naming a file proves documentation, not imports
            queue.extend(sorted(edges.get(current, ())))

    legacy = settings["legacy_core_prefixes"]
    result: dict[str, dict] = {}
    for path in repo.files:
        if not path.endswith(".py"):
            continue
        kinds = reached.get(path, set())
        name = PurePosixPath(path).name
        if path.startswith("tests/") and (name.startswith("test_") or name == "conftest.py"):
            status = TEST_MODULE
        elif "RUNTIME" in kinds:
            status = PRODUCTION_REACHABLE
        elif _starts(path, legacy) and kinds - {"DOCUMENTED"}:
            status = LEGACY_BUT_LIVE
        elif "GATE" in kinds:
            status = GATE_ONLY
        elif "SKILL" in kinds:
            status = SKILL_ONLY
        elif "TEST" in kinds:
            status = TEST_SUPPORT if path.startswith("tests/") else TEST_ONLY
        elif "DOCUMENTED" in kinds and has_main.get(path):
            status = MANUAL_ENTRYPOINT
        else:
            status = UNREACHABLE_CANDIDATE
        result[path] = {
            "module": next((key for key, value in modules.items() if value == path), None),
            "status": status,
            "reached_by": sorted(kinds),
            "has_main": bool(has_main.get(path)),
            "consumers": sorted(consumers.get(path, ())),
        }
    return result, violations


# --------------------------------------------------------------------------- Frontend


def _frontend_specifiers(path: str, text: str) -> list[str]:
    patterns = [_IMPORT_FROM, _IMPORT_BARE, _IMPORT_DYNAMIC]
    if path.endswith(".css"):
        patterns = [_CSS_IMPORT]
    elif path.endswith(".html"):
        patterns = [_HTML_SRC]
    found: list[str] = []
    for pattern in patterns:
        found.extend(re.findall(pattern, text, flags=re.MULTILINE))
    return found


def _resolve_frontend(specifier: str, importer: str, files: frozenset[str], frontend_root: str) -> str | None:
    if specifier.startswith("/"):
        base = PurePosixPath(frontend_root.rstrip("/")) / specifier.lstrip("/")
    elif specifier.startswith("."):
        base = PurePosixPath(importer).parent / specifier
    else:
        return None  # package import
    parts: list[str] = []
    for part in base.parts:
        if part == "..":
            if parts:
                parts.pop()
        elif part != ".":
            parts.append(part)
    candidate = "/".join(parts)
    options = [candidate]
    options += [candidate + suffix for suffix in FRONTEND_CODE_SUFFIXES]
    if candidate.endswith((".js", ".jsx")):
        options += [candidate.rsplit(".", 1)[0] + suffix for suffix in (".ts", ".tsx")]
    options += [f"{candidate}/index{suffix}" for suffix in FRONTEND_CODE_SUFFIXES]
    return next((option for option in options if option in files), None)


def frontend_reachability(repo: Repository, config: dict) -> tuple[dict[str, dict], list[dict], list[dict]]:
    settings = config["frontend"]
    root = settings["root"]
    files = repo._file_set
    code = [path for path in repo.files if path.startswith(root) and path.endswith(FRONTEND_CODE_SUFFIXES)]
    violations: list[dict] = []
    edges: dict[str, set[str]] = defaultdict(set)
    sources = code + [path for path in settings["build_files"] if path.endswith(".html") and path in files]
    for path in sources:
        text = repo.text(path) or ""
        for specifier in _frontend_specifiers(path, text):
            target = _resolve_frontend(specifier, path, files, root)
            if target:
                edges[path].add(target)
    for path in settings["entrypoints"] + settings["build_files"]:
        if path not in files:
            violations.append(_violation("FRONTEND_ENTRYPOINT_MISSING", path, "declared frontend entrypoint/build file is not tracked"))

    def closure(starts):
        seen: set[str] = set()
        queue = deque(sorted(starts))
        while queue:
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            queue.extend(sorted(edges.get(current, ())))
        return seen

    is_test = lambda path: bool(re.search(r"\.(test|spec)\.[cm]?[jt]sx?$", path))  # noqa: E731
    is_story = lambda path: bool(re.search(r"\.stories\.[cm]?[jt]sx?$", path))  # noqa: E731
    runtime = closure(settings["entrypoints"] + [path for path in settings["build_files"] if path.endswith(".html")])
    tests = closure([path for path in code if is_test(path) or _starts(path, settings["test_support_prefixes"])])
    stories = closure([path for path in code if is_story(path)])
    consumers: dict[str, set[str]] = defaultdict(set)
    for source, targets in edges.items():
        for target in targets:
            consumers[target].add(source)
    result: dict[str, dict] = {}
    for path in code:
        if path in settings["build_files"] or PurePosixPath(path).name.startswith(("vite.config", "eslint.config", "vitest.config")):
            status = BUILD_CONFIG
        elif is_test(path) or _starts(path, settings["test_support_prefixes"]):
            status = TEST
        elif path in runtime:
            status = RUNTIME
        elif path in tests:
            status = TEST_ONLY
        elif path in stories:
            status = STORY_DEMO_ONLY
        else:
            status = UNREACHABLE_CANDIDATE
        result[path] = {"status": status, "consumers": sorted(consumers.get(path, ()))}

    assets: list[dict] = []
    texts = [path for path in repo.files if path.startswith(root) and not path.endswith(FRONTEND_ASSET_SUFFIXES)]
    for path in repo.files:
        if not (path.startswith(root) and path.lower().endswith(FRONTEND_ASSET_SUFFIXES)):
            continue
        name = PurePosixPath(path).name
        users = [other for other in texts if name in (repo.text(other) or "")]
        if not users:
            assets.append(_finding(
                path, "ASSET_UNREFERENCED", "asset file name not found in any tracked frontend text file",
                unknown=["CSS url() built from variables", "runtime-constructed URL"],
                action="REVIEW_BEFORE_ANY_REMOVAL", confidence=NEEDS_REVIEW,
            ))
    return result, violations, assets


# --------------------------------------------------------------------------- Schemas


def _consumer_kind(path: str, schema_path: str) -> str:
    if path == "tests/fixtures/core-fixtures.json":
        return "FIXTURE_REGISTRY"
    if path == "config/schema-versions.json":
        return "SCHEMA_VERSIONS"
    if path in {"config/core-boundaries.json", "config/core-stable-baseline-v1.json"}:
        return "CORE_BOUNDARY"
    if path.startswith("schemas/") and path.endswith(".schema.json"):
        return "SCHEMA_REF"
    if path.startswith((".github/", "config/", "scripts/quality/", "scripts/agentic/")):
        return "GATE"
    if path.startswith("tests/fixtures/"):
        return "FIXTURE"
    if path.startswith("tests/"):
        return "TEST"
    if path.startswith(".agents/"):
        return "SKILL"
    if path.endswith(".py"):
        return "RUNTIME_VALIDATOR"
    if path.endswith(FRONTEND_CODE_SUFFIXES):
        return "FRONTEND"
    return "DOCUMENTATION"


def schema_reachability(repo: Repository) -> tuple[dict[str, dict], list[dict]]:
    schemas = [path for path in repo.files if path.startswith("schemas/") and path.endswith(".schema.json")]
    identities: dict[str, tuple[str, ...]] = {}
    violations: list[dict] = []
    for path in schemas:
        try:
            document = json.loads(repo.text(path) or "")
        except json.JSONDecodeError as exc:
            violations.append(_violation("SCHEMA_UNREADABLE", path, str(exc)))
            continue
        names = [PurePosixPath(path).name]
        if isinstance(document, dict) and isinstance(document.get("$id"), str):
            names.append(document["$id"])
        identities[path] = tuple(names)
    texts = [(path, repo.text(path)) for path in repo.files if not path.endswith(FRONTEND_ASSET_SUFFIXES)]
    result: dict[str, dict] = {}
    for path, names in identities.items():
        kinds: dict[str, set[str]] = defaultdict(set)
        for other, text in texts:
            if other == path or text is None or other == "schemas/README.md":
                continue
            if any(name in text and re.search(rf"(?<![A-Za-z0-9_.-]){re.escape(name)}", text) for name in names):
                kinds[_consumer_kind(other, path)].add(other)
        if "schemas/README.md" in repo._file_set and names[0] in (repo.text("schemas/README.md") or ""):
            kinds["DOCUMENTATION"].add("schemas/README.md")
        live = sorted(kind for kind in kinds if kind != "DOCUMENTATION")
        result[path] = {
            "consumer_kinds": sorted(kinds),
            "consumers": {kind: sorted(paths) for kind, paths in sorted(kinds.items())},
            "status": "LIVE" if live else "SCHEMA_ORPHAN_CANDIDATE",
        }
    return result, violations


# --------------------------------------------------------------------------- Fixtures

_FIXTURE_CODES = {
    "FIXTURE_ORFA": "FIXTURE_ORPHAN",
    "REGISTRY_STALE": "FIXTURE_REGISTRY_STALE",
    "FIXTURE_NAO_EXERCITADA": "FIXTURE_NOT_EXERCISED",
    "SCHEMA_STALE": "FIXTURE_SCHEMA_STALE",
    "REGISTRY_INVALIDO": "FIXTURE_REGISTRY_INVALID",
    "FIXTURE_PROVENIENCIA_NAO_SINTETICA": "FIXTURE_PROVENANCE_NOT_SYNTHETIC",
}


def fixture_findings(repo: Repository) -> tuple[list[dict], list[dict]]:
    """Reuses `fixture_registry.validate_fixture_registry`; never re-implements it."""
    if not repo.exists("tests/fixtures/core-fixtures.json"):
        return [], []
    findings: list[dict] = []
    violations: list[dict] = []
    for item in validate_fixture_registry(repo.root):
        code = item["motivo"]
        if code == "FIXTURE_ORFA" and not repo.exists(item["teste"]):
            continue  # untracked local file: outside WORKTREE_BYTES_OF_GIT_INDEX_PATHS
        classification = _FIXTURE_CODES.get(code, "FIXTURE_REGISTRY_INVALID")
        if code == "REGISTRY_INVALIDO" and item["teste"].endswith("core-fixtures.json"):
            violations.append(_violation("FIXTURE_REGISTRY_UNREADABLE", item["teste"], item["detalhe"]))
            continue
        findings.append(_finding(
            item["teste"], classification, f"fixture_registry: {code} ({item['detalhe']})",
            known=["tests/fixtures/core-fixtures.json"], risk="MEDIUM",
            action="RECONCILE_REGISTRY", confidence=PROVEN, registry_code=code,
        ))
    return findings, violations


# --------------------------------------------------------------------------- Skills


def skill_audit(repo: Repository) -> tuple[list[dict], list[dict]]:
    installed = sorted({
        path[len(SKILLS_DIR):].split("/", 1)[0]
        for path in repo.files
        if path.startswith(SKILLS_DIR) and path.endswith("/SKILL.md") and path.count("/") == 3
    })
    violations: list[dict] = []
    try:
        router = json.loads(repo.text(SKILL_ROUTER) or "")
    except json.JSONDecodeError as exc:
        return [], [_violation("SKILL_ROUTER_UNREADABLE", SKILL_ROUTER, str(exc))]
    routes: dict[str, set[str]] = defaultdict(set)
    for skill in router.get("material_bundle", []):
        routes[skill].add("REQUIRED:material_bundle")
    for profile, spec in router.get("profiles", {}).items():
        for skill in spec.get("required", []):
            routes[skill].add(f"REQUIRED:{profile}")
        for condition, skills in spec.get("conditional", {}).items():
            for skill in skills:
                routes[skill].add(f"CONDITIONAL:{profile}:{condition}")
    for skill in router.get("reference_only", []):
        routes[skill].add("REFERENCE_ONLY")
    for skill in sorted(set(routes) - set(installed)):
        violations.append(_violation("ROUTER_SKILL_MISSING", SKILL_ROUTER, f"router names skill not installed: {skill}"))
    reference_texts = [
        path for path in repo.files
        if path == "AGENTS.md" or path.startswith("docs/padroes/") or (path.startswith(SKILLS_DIR) and path.endswith(".md"))
    ]
    records: list[dict] = []
    for skill in installed:
        routed = sorted(routes.get(skill, ()))
        pattern = rf"(?<![A-Za-z0-9-]){re.escape(skill)}(?![A-Za-z0-9-])"
        referenced = sorted(
            path for path in reference_texts
            if not path.startswith(f"{SKILLS_DIR}{skill}/") and re.search(pattern, repo.text(path) or "")
        )
        if any(route.startswith("REQUIRED") for route in routed):
            status = "SKILL_REQUIRED"
        elif any(route.startswith("CONDITIONAL") for route in routed):
            status = "SKILL_CONDITIONAL"
        elif routed:
            status = "SKILL_REFERENCE_ONLY"
        else:
            status = "SKILL_UNROUTED"
        records.append({
            "skill": skill,
            "installed": True,
            "routed": bool(routed),
            "routes": routed,
            "referenced": bool(referenced),
            "referenced_by": referenced,
            "status": status,
        })
    return records, violations


# --------------------------------------------------------------------------- Documents


def document_audit(repo: Repository, config: dict) -> tuple[list[dict], list[dict]]:
    violations: list[dict] = []
    stale: list[dict] = []
    for entry in config["current_authority"]:
        if "path" in entry and not repo.exists(entry["path"]):
            violations.append(_violation("AUTHORITY_MISSING", entry["path"], entry["role"]))
        if "prefix" in entry and not any(path.startswith(entry["prefix"]) for path in repo.files):
            violations.append(_violation("AUTHORITY_MISSING", entry["prefix"], entry["role"]))
    for entry in config["historical"]:
        readme = entry.get("status_readme")
        if readme:
            marker = config["status_markers"].get(readme, "")
            if not repo.exists(readme) or marker not in (repo.text(readme) or ""):
                violations.append(_violation("HISTORICAL_STATUS_MISSING", readme, f"missing marker: {marker}"))
    wrappers = config["agent_wrappers"]
    for path in wrappers["paths"]:
        raw = repo.raw(path) if repo.exists(path) else None
        if raw is None or len(raw) > wrappers["max_bytes"] or wrappers["target"].encode() not in raw:
            violations.append(_violation("AGENT_WRAPPER_DRIFT", path, f"must be a small pointer to {wrappers['target']}"))
    for marker in config["stale_markers"]:
        for path in marker["paths"]:
            if marker["pattern"] in (repo.text(path) or ""):
                violations.append(_violation("AUTHORITY_STALE_MARKER", path, marker["reason"]))
                stale.append(_finding(path, "DOCUMENTATION_STALE", f"contains stale marker: {marker['pattern']}",
                                      risk="HIGH", action="REWRITE_FROM_LIVE_PRODUCT", confidence=PROVEN))
    for path in config["durable_documents"]:
        text = repo.text(path) or ""
        for rule in config["durable_document_forbidden"]:
            for match in re.findall(rule["pattern"], text):
                violations.append(_violation("DURABLE_DOCUMENT_TEMPORAL_COUPLING", path, f"{match}: {rule['reason']}"))
                stale.append(_finding(path, "DOCUMENTATION_STALE", f"durable document carries {match}",
                                      risk="MEDIUM", action="POINT_TO_TEMPORAL_AUTHORITY", confidence=PROVEN))
    return stale, violations


# --------------------------------------------------------------------------- Duplicates and generated files


def duplicate_findings(repo: Repository, config: dict) -> tuple[list[dict], list[dict]]:
    exact: dict[str, list[str]] = defaultdict(list)
    normalized: dict[str, list[str]] = defaultdict(list)
    for path in repo.files:
        raw = repo.raw(path)
        if not raw:
            continue
        exact[hashlib.sha256(raw).hexdigest()].append(path)
        text = repo.text(path)
        if text is not None:
            collapsed = " ".join(text.split())
            if len(collapsed) >= 64:
                normalized[hashlib.sha256(collapsed.encode()).hexdigest()].append(path)
    wrappers = set(config["agent_wrappers"]["paths"])
    groups: list[dict] = []
    findings: list[dict] = []
    seen_groups: set[tuple[str, ...]] = set()
    for kind, table in (("EXACT_SHA256", exact), ("NORMALIZED_TEXT", normalized)):
        for paths in table.values():
            group = tuple(sorted(paths))
            if len(group) < 2 or group in seen_groups:
                continue
            seen_groups.add(group)
            intentional = set(group) <= wrappers
            classification = "INTENTIONAL_WRAPPER_DUPLICATION" if intentional else "DUPLICATE_CONTENT"
            groups.append({"kind": kind, "classification": classification, "paths": list(group)})
            if not intentional:
                findings.append(_finding(
                    group[0], "DUPLICATE_CONTENT", f"{kind} identical across {len(group)} files",
                    known=group[1:], unknown=["each copy may serve a distinct consumer or layer"],
                    action="REVIEW_SAME_CONTENT_DIFFERENT_ROLE", confidence=NEEDS_REVIEW, group=list(group),
                ))
    return groups, findings


def generated_findings(repo: Repository, config: dict) -> list[dict]:
    findings = []
    for path in repo.files:
        if any(re.search(pattern, path) for pattern in config["generated_patterns"]):
            findings.append(_finding(path, "GENERATED_FILE_TRACKED", "path matches a generated-file pattern",
                                     action="UNTRACK_IN_SEPARATE_PR", confidence=STRONG_CANDIDATE))
    for path in repo.symlinks:
        findings.append(_finding(path, "SYMLINK_TRACKED", "symlinks are not portable to Windows checkouts",
                                 risk="MEDIUM", action="REPLACE_WITH_REGULAR_FILE", confidence=PROVEN))
    return findings


# --------------------------------------------------------------------------- Assembly


def _primary_class(path: str, config: dict, python: dict, frontend: dict, schemas: dict) -> str:
    # An exact-path historical entry overrides a broader authority prefix
    # (for example an expired protocol inside docs/padroes/).
    for entry in config["historical"]:
        if "path" in entry and _match_entry(path, entry):
            return "HISTORICAL"
    for entry in config["current_authority"]:
        if _match_entry(path, entry):
            return "CURRENT_AUTHORITY"
    if path in config["agent_wrappers"]["paths"]:
        return "CURRENT_AUTHORITY"
    for entry in config["historical"]:
        if _match_entry(path, entry):
            return "HISTORICAL"
    if path in python:
        status = python[path]["status"]
        return {
            PRODUCTION_REACHABLE: "RUNTIME", GATE_ONLY: "ASSURANCE", TEST_MODULE: "ASSURANCE", TEST_SUPPORT: "ASSURANCE",
            SKILL_ONLY: "REFERENCE", TEST_ONLY: "TEST_ONLY", LEGACY_BUT_LIVE: "LEGACY_BUT_LIVE",
            MANUAL_ENTRYPOINT: "MANUAL_TOOL", UNREACHABLE_CANDIDATE: "UNREACHABLE_CANDIDATE",
        }[status]
    if path in frontend:
        status = frontend[path]["status"]
        return {RUNTIME: "RUNTIME", BUILD_CONFIG: "RUNTIME", TEST: "ASSURANCE", TEST_ONLY: "TEST_ONLY",
                STORY_DEMO_ONLY: "TEST_ONLY", UNREACHABLE_CANDIDATE: "UNREACHABLE_CANDIDATE"}[status]
    if path in config["frontend"]["build_files"]:
        return "RUNTIME"
    for entry in config["generated_evidence"]:
        if _match_entry(path, entry):
            return "GENERATED_EVIDENCE"
    if path in schemas:
        kinds = set(schemas[path]["consumer_kinds"])
        if kinds & {"RUNTIME_VALIDATOR", "FRONTEND"}:
            return "RUNTIME"
        return "ASSURANCE" if kinds - {"DOCUMENTATION"} else "UNREACHABLE_CANDIDATE"
    for entry in config["file_classes"]:
        if _match_entry(path, entry):
            return entry["class"]
    if path.startswith(("scripts/", "frontend/")):
        return "RUNTIME"
    return "UNCLASSIFIED"


def _python_candidates(python: dict, repo: Repository) -> list[dict]:
    findings = []
    for path, record in sorted(python.items()):
        if record["status"] != UNREACHABLE_CANDIDATE:
            continue
        stem = PurePosixPath(path).stem
        mentions = sorted(
            other for other in repo.files
            if other != path and not other.endswith(FRONTEND_ASSET_SUFFIXES) and stem != "__init__"
            and re.search(rf"(?<![A-Za-z0-9_]){re.escape(stem)}(?![A-Za-z0-9_])", repo.text(other) or "")
        )
        confidence = NEEDS_REVIEW if mentions or record["has_main"] else STRONG_CANDIDATE
        findings.append(_finding(
            path, "DEAD_CODE_CANDIDATE",
            "no import, -m/path reference or root reaches this module (runtime, gate, skill, test, documented CLI)",
            known=mentions, unknown=["manual invocation outside the repository", "dynamic name construction"],
            risk="MEDIUM", action="PROVE_ABSENCE_THEN_REMOVE_IN_SEPARATE_PR", confidence=confidence,
            reachability=record["status"],
        ))
    return findings


def _production_unreachable(python: dict, config: dict) -> list[dict]:
    """Product-layer modules alive only through tests/gates: NO_RUNTIME_CONSUMER != NO_CONSUMER."""
    prefixes = config["python"]["product_layer_prefixes"]
    return [
        _finding(path, "PRODUCTION_UNREACHABLE",
                 f"not reachable from the product runtime roots; alive through {', '.join(record['reached_by'])}",
                 known=record["consumers"], unknown=["future wiring decided by an accepted roadmap item"],
                 risk="LOW", action="KEEP_LIVE_FOR_ASSURANCE_REVIEW_WIRING", confidence=PROVEN,
                 reachability=record["status"])
        for path, record in sorted(python.items())
        if _starts(path, prefixes) and record["status"] in {GATE_ONLY, TEST_ONLY, SKILL_ONLY, MANUAL_ENTRYPOINT}
        and not path.endswith("/__main__.py")
    ]


def _frontend_candidates(frontend: dict) -> list[dict]:
    return [
        _finding(path, "PRODUCTION_UNREACHABLE" if record["status"] == UNREACHABLE_CANDIDATE else "TEST_ONLY",
                 f"frontend reachability: {record['status']}", known=record["consumers"],
                 unknown=["file referenced by tooling outside the import graph"],
                 risk="LOW", action="REVIEW_BEFORE_ANY_REMOVAL", confidence=NEEDS_REVIEW, reachability=record["status"])
        for path, record in sorted(frontend.items())
        if record["status"] in {UNREACHABLE_CANDIDATE, TEST_ONLY}
    ]


def _schema_candidates(schemas: dict) -> list[dict]:
    return [
        _finding(path, "SCHEMA_ORPHAN_CANDIDATE", "no validator, fixture, schema-versions, boundary, $ref, test or skill consumer",
                 known=[item for paths in record["consumers"].values() for item in paths],
                 unknown=["external consumer of the published contract"], risk="MEDIUM",
                 action="PROVE_ABSENCE_THEN_REMOVE_IN_SEPARATE_PR",
                 confidence=NEEDS_REVIEW if record["consumers"] else STRONG_CANDIDATE)
        for path, record in sorted(schemas.items()) if record["status"] == "SCHEMA_ORPHAN_CANDIDATE"
    ]


def _skill_candidates(skills: list[dict]) -> list[dict]:
    return [
        _finding(f"{SKILLS_DIR}{item['skill']}/SKILL.md", "SKILL_UNROUTED",
                 "installed skill has no route in .agents/skill-router.json (SKILL_INSTALLED != SKILL_INTEGRATED)",
                 known=item["referenced_by"], risk="MEDIUM", action="ROUTE_OR_MARK_REFERENCE_ONLY", confidence=PROVEN)
        for item in skills if item["status"] == "SKILL_UNROUTED"
    ]


def audit(root: Path = ROOT, *, files: tuple[str, ...] | None = None, config: dict | None = None) -> dict:
    repo = load_repository(root, files)
    if config is None:
        config = json.loads((Path(root) / AUTHORITY_CONFIG).read_text(encoding="utf-8"))
    python, python_violations = python_reachability(repo, config)
    frontend, frontend_violations, asset_findings = frontend_reachability(repo, config)
    schemas, schema_violations = schema_reachability(repo)
    fixtures, fixture_violations = fixture_findings(repo)
    skills, skill_violations = skill_audit(repo)
    stale_docs, document_violations = document_audit(repo, config)
    duplicate_groups, duplicate_list = duplicate_findings(repo, config)
    generated = generated_findings(repo, config)

    classes = {path: _primary_class(path, config, python, frontend, schemas) for path in repo.files}
    counts: dict[str, int] = defaultdict(int)
    for value in classes.values():
        counts[value] += 1
    findings = (
        _python_candidates(python, repo) + _production_unreachable(python, config) + _frontend_candidates(frontend) + _schema_candidates(schemas)
        + fixtures + _skill_candidates(skills) + asset_findings + stale_docs + duplicate_list + generated
    )
    findings.sort(key=lambda item: (item["classification"], item["path"]))
    violations = sorted(
        python_violations + frontend_violations + schema_violations + fixture_violations
        + skill_violations + document_violations,
        key=lambda item: (item["code"], item["path"], item["detail"]),
    )
    large = [
        {"path": path, "bytes": (repo.root / path).stat().st_size}
        for path in repo.files
        if path not in repo.symlinks and (repo.root / path).stat().st_size >= config["large_file_bytes"]
    ]
    python_status: dict[str, int] = defaultdict(int)
    for record in python.values():
        python_status[record["status"]] += 1
    frontend_status: dict[str, int] = defaultdict(int)
    for record in frontend.values():
        frontend_status[record["status"]] += 1
    extensions: dict[str, int] = defaultdict(int)
    for path in repo.files:
        extensions[PurePosixPath(path).suffix.lower() or "(none)"] += 1
    by_top: dict[str, int] = defaultdict(int)
    for path in repo.files:
        by_top[path.split("/", 1)[0] if "/" in path else "/"] += 1
    summary = {
        "files": len(repo.files),
        "current_authority": counts["CURRENT_AUTHORITY"],
        "historical": counts["HISTORICAL"],
        "runtime": counts["RUNTIME"],
        "assurance": counts["ASSURANCE"],
        "test_only": counts["TEST_ONLY"],
        "legacy_but_live": counts["LEGACY_BUT_LIVE"],
        "reference": counts["REFERENCE"],
        "configuration": counts["CONFIGURATION"],
        "generated_evidence": counts["GENERATED_EVIDENCE"],
        "manual_tool": counts["MANUAL_TOOL"],
        "unclassified": counts["UNCLASSIFIED"],
        "unreachable_candidates": counts["UNREACHABLE_CANDIDATE"],
        "schema_candidates": sum(1 for item in schemas.values() if item["status"] == "SCHEMA_ORPHAN_CANDIDATE"),
        "fixture_findings": len(fixtures),
        "skill_unrouted": sum(1 for item in skills if item["status"] == "SKILL_UNROUTED"),
        "asset_candidates": len(asset_findings),
        "stale_documents": sorted({item["path"] for item in stale_docs}),
        "duplicate_groups": sum(1 for group in duplicate_groups if group["classification"] == "DUPLICATE_CONTENT"),
        "generated_files_tracked": sum(1 for item in generated if item["classification"] == "GENERATED_FILE_TRACKED"),
        "invariant_violations": len(violations),
    }
    return {
        "report": "REPOSITORY_HYGIENE_V1",
        "schema_version": SCHEMA_VERSION,
        "basis": "WORKTREE_BYTES_OF_GIT_INDEX_PATHS",
        "observed_head": repo.head,
        "auto_delete": False,
        "summary": summary,
        "inventory": {
            "by_top_level": dict(sorted(by_top.items())),
            "by_extension": dict(sorted(extensions.items())),
            "by_class": dict(sorted(counts.items())),
            "large_files": sorted(large, key=lambda item: (-item["bytes"], item["path"])),
        },
        "python": {"by_status": dict(sorted(python_status.items())), "modules": python},
        "frontend": {"by_status": dict(sorted(frontend_status.items())), "modules": frontend},
        "schemas": schemas,
        "skills": skills,
        "duplicates": duplicate_groups,
        "files": dict(sorted(classes.items())),
        "findings": findings,
        "invariant_violations": violations,
    }


def validate_output(report: dict, root: Path = ROOT) -> list[str]:
    schema = json.loads((Path(root) / OUTPUT_SCHEMA).read_text(encoding="utf-8"))
    return [error.message for error in jsonschema.Draft202012Validator(schema).iter_errors(report)]


def render_markdown(report: dict) -> str:
    summary = report["summary"]
    lines = [
        "# REPOSITORY_HYGIENE_V1",
        "",
        f"Basis: `{report['basis']}` · observed HEAD: `{report['observed_head']}` · auto_delete: `{str(report['auto_delete']).lower()}`",
        "",
        "| Pergunta | Resposta |",
        "|---|---|",
    ]
    for key in ("files", "current_authority", "historical", "runtime", "assurance", "test_only", "legacy_but_live",
                "reference", "configuration", "generated_evidence", "manual_tool", "unclassified",
                "unreachable_candidates", "schema_candidates", "fixture_findings", "skill_unrouted",
                "asset_candidates", "duplicate_groups", "generated_files_tracked", "invariant_violations"):
        lines.append(f"| {key} | {summary[key]} |")
    lines.append(f"| stale_documents | {', '.join(summary['stale_documents']) or 'nenhum'} |")
    lines += ["", "## Python", "", "| Status | Módulos |", "|---|---|"]
    lines += [f"| {key} | {value} |" for key, value in report["python"]["by_status"].items()]
    lines += ["", "## Frontend", "", "| Status | Arquivos |", "|---|---|"]
    lines += [f"| {key} | {value} |" for key, value in report["frontend"]["by_status"].items()]
    lines += ["", "## Skills", "", "| Skill | Status | Rotas |", "|---|---|---|"]
    lines += [f"| {item['skill']} | {item['status']} | {', '.join(item['routes']) or '—'} |" for item in report["skills"]]
    lines += ["", "## Candidatos e achados (advisory)", "",
              "| PATH | CLASSIFICATION | CONFIDENCE | RISK | RECOMMENDED_ACTION | EVIDENCE | KNOWN_CONSUMERS |",
              "|---|---|---|---|---|---|---|"]
    for item in report["findings"]:
        known = ", ".join(item["known_consumers"][:5]) + (" …" if len(item["known_consumers"]) > 5 else "")
        lines.append(f"| `{item['path']}` | {item['classification']} | {item['confidence']} | {item['risk']} | "
                     f"{item['recommended_action']} | {item['evidence']} | {known or '—'} |")
    lines += ["", "## Violações de invariante (bloqueantes)", ""]
    lines += [f"- `{item['code']}` `{item['path']}`: {item['detail']}" for item in report["invariant_violations"]] or ["- nenhuma"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="REPOSITORY_HYGIENE_V1 read-only auditor")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    parser.add_argument("--check", action="store_true", help="exit 1 on invariant violations or invalid output")
    arguments = parser.parse_args(argv)
    report = audit(arguments.root)
    errors = validate_output(report, arguments.root)
    if arguments.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print(render_markdown(report), end="")
    if errors:
        print("\n".join(f"OUTPUT_SCHEMA_INVALID: {error}" for error in errors), file=sys.stderr)
    if arguments.check and (errors or report["invariant_violations"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
