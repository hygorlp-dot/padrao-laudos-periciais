import json
from pathlib import Path
import pytest

from scripts.quality import architecture_gate
from scripts.quality.architecture_gate import analyze_architecture, load_and_validate, validate_architecture


ROOT = Path(__file__).resolve().parents[1]


def _registry(**changes):
    data = {
        "schemaVersion": "1.0.0",
        "components": [
            {"id": "DOMAIN", "layer": "DOMAIN_CORE", "prefixes": ["scripts/domain/"]},
            {"id": "APPLICATION", "layer": "APPLICATION", "prefixes": ["scripts/application/"]},
            {"id": "GOVERNANCE", "layer": "QUALITY_GOVERNANCE", "prefixes": ["scripts/quality/"]},
            {"id": "INFRA", "layer": "INFRASTRUCTURE", "prefixes": ["scripts/infra/"]},
        ],
        "baselineSha": "0" * 40,
        "allowedLayerEdges": [
            {"source": "DOMAIN_CORE", "target": "DOMAIN_CORE"},
            {"source": "APPLICATION", "target": "APPLICATION"},
            {"source": "APPLICATION", "target": "DOMAIN_CORE"},
            {"source": "QUALITY_GOVERNANCE", "target": "QUALITY_GOVERNANCE"},
            {"source": "INFRASTRUCTURE", "target": "INFRASTRUCTURE"},
        ],
        "allowedInternalEdges": [],
        "acceptedCurrentDependencies": [],
        "forbiddenComponentEdges": [
            {"source": "DOMAIN", "target": "APPLICATION", "rule": "DOMAIN_INDEPENDENT"},
            {"source": "DOMAIN", "target": "GOVERNANCE", "rule": "CORE_NOT_GOVERNANCE"},
            {"source": "DOMAIN", "target": "GOVERNANCE", "rule": "CORE_NOT_GOVERNANCE"},
            {"source": "APPLICATION", "target": "GOVERNANCE", "rule": "PRODUCTION_NOT_GOVERNANCE"},
        ],
    }
    data.update(changes)
    return data


def test_current_repository_architecture_is_registered_and_green():
    registry = json.loads((ROOT / "config/core-architecture-v1.json").read_text(encoding="utf-8"))
    assert validate_architecture(ROOT, registry) == []


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
    assert any(item["code"] == "ARCHITECTURE_EXCEPTION_NOT_IN_BASELINE" for item in validate_architecture(tmp_path, registry))


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
    assert any(item["code"] == "DYNAMIC_IMPORT_CAPABILITY" for item in validate_architecture(tmp_path, _registry()))


@pytest.mark.parametrize("statement", [
    "import scripts.domain.does_not_exist",
    "import scripts.domain.does_not_exist as missing",
    "import scripts.domain, scripts.domain.does_not_exist",
])
def test_plain_import_requires_the_full_first_party_module(monkeypatch, statement):
    sources = {
        "scripts/domain/__init__.py": "",
        "scripts/domain/consumer.py": f"{statement}\n",
    }
    monkeypatch.setattr(architecture_gate, "_python_files", lambda _root: sorted(sources))
    original_read_text = Path.read_text
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda path, **kwargs: sources[path.relative_to(ROOT).as_posix()]
        if path.is_relative_to(ROOT) and path.relative_to(ROOT).as_posix() in sources
        else original_read_text(path, **kwargs),
    )

    findings = analyze_architecture(ROOT, _registry())["findings"]

    assert any(
        item["code"] == "FIRST_PARTY_IMPORT_UNRESOLVED"
        and item["target"] == "scripts.domain.does_not_exist"
        for item in findings
    )


def test_from_import_can_resolve_an_attribute_from_an_existing_package(monkeypatch):
    sources = {
        "scripts/domain/__init__.py": "EXPORTED = 1\n",
        "scripts/domain/consumer.py": "from scripts.domain import EXPORTED\n",
    }
    monkeypatch.setattr(architecture_gate, "_python_files", lambda _root: sorted(sources))
    original_read_text = Path.read_text
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda path, **kwargs: sources[path.relative_to(ROOT).as_posix()]
        if path.is_relative_to(ROOT) and path.relative_to(ROOT).as_posix() in sources
        else original_read_text(path, **kwargs),
    )

    report = analyze_architecture(ROOT, _registry())

    assert not any(item["code"] == "FIRST_PARTY_IMPORT_UNRESOLVED" for item in report["findings"])
    assert any(edge["target"] == "scripts.domain" for edge in report["edges"])


def test_parse_failure_is_not_silently_skipped(tmp_path):
    package = tmp_path / "scripts/domain"
    package.mkdir(parents=True)
    (package / "broken.py").write_bytes(b"\xff\xfe")
    assert any(item["code"] == "ARCHITECTURE_SOURCE_UNPARSEABLE" for item in validate_architecture(tmp_path, _registry()))


def test_inventory_failure_is_returned_as_architecture_finding(monkeypatch):
    def fail_inventory(_root):
        raise RuntimeError("git ls-files failed: metadata unavailable")

    monkeypatch.setattr(architecture_gate, "_python_files", fail_inventory)
    monkeypatch.setattr(
        architecture_gate.subprocess,
        "run",
        lambda *_args, **_kwargs: architecture_gate.subprocess.CompletedProcess([], 0, "", ""),
    )

    findings = load_and_validate(ROOT)

    assert findings == [{
        "code": "ARCHITECTURE_INVENTORY_INVALID",
        "detail": "git ls-files failed: metadata unavailable",
    }]


def test_report_is_deterministic(tmp_path):
    package = tmp_path / "scripts/domain"; package.mkdir(parents=True)
    (package / "a.py").write_text("VALUE=1\n", encoding="utf-8")
    first = analyze_architecture(tmp_path, _registry())
    assert first == analyze_architecture(tmp_path, _registry())


def test_registry_cannot_collapse_the_constitution(tmp_path):
    (tmp_path / "scripts/domain").mkdir(parents=True)
    (tmp_path / "scripts/domain/rule.py").write_text("VALUE=1\n", encoding="utf-8")
    collapsed = {"schemaVersion": "evil", "components": [{"id": "ALL", "prefixes": ["scripts/"]}],
                 "forbiddenComponentEdges": [], "acceptedCurrentDependencies": []}
    assert any(item["code"] == "ARCHITECTURE_REGISTRY_POLICY_INVALID" for item in validate_architecture(tmp_path, collapsed))


@pytest.mark.parametrize("mutation", ["remove", "change-disposition"])
def test_architecture_debt_exceptions_require_a_new_pinned_policy(mutation):
    registry = json.loads((ROOT / "config/core-architecture-v1.json").read_text(encoding="utf-8"))
    if mutation == "remove":
        registry["acceptedCurrentDependencies"].pop()
    else:
        registry["acceptedCurrentDependencies"][0]["disposition"] = "REINTRODUCED_WITHOUT_DECISION"

    findings = architecture_gate._registry_findings(registry)

    assert findings == [{"code": "ARCHITECTURE_REGISTRY_POLICY_INVALID"}]


def test_relative_dynamic_import_and_sys_path_mutation_fail_closed(tmp_path):
    package = tmp_path / "scripts/domain"; package.mkdir(parents=True)
    (package / "rule.py").write_text("VALUE=1\n", encoding="utf-8")
    (package / "dynamic.py").write_text(
        "import importlib,sys\nimportlib.import_module('.rule','scripts.domain')\nsys.path.insert(0,'x')\n",
        encoding="utf-8",
    )
    codes = {item["code"] for item in validate_architecture(tmp_path, _registry())}
    assert {"DYNAMIC_IMPORT_CAPABILITY", "RUNTIME_IMPORT_CAPABILITY"} <= codes


def test_debt_evidence_and_component_cycles_are_mechanically_checked(tmp_path):
    for package in ("domain", "application", "infra", "quality"):
        (tmp_path / f"scripts/{package}").mkdir(parents=True)
    (tmp_path / "scripts/domain/a.py").write_text("from scripts.application import b\n", encoding="utf-8")
    (tmp_path / "scripts/application/b.py").write_text("from scripts.domain import a\n", encoding="utf-8")
    (tmp_path / "scripts/infra/x.py").write_text("VALUE=1\n", encoding="utf-8")
    (tmp_path / "scripts/quality/q.py").write_text("VALUE=1\n", encoding="utf-8")
    registry = _registry(acceptedCurrentDependencies=[
        {"source": "scripts.domain.a", "target": "scripts.application.b", "classification": "POTENTIAL_VIOLATION", "evidence": "wrong:99", "disposition": "REMOVE"},
        {"source": "scripts.application.b", "target": "scripts.domain.a", "classification": "POTENTIAL_VIOLATION", "evidence": "scripts/application/b.py:1", "disposition": "REMOVE"},
    ])
    codes = {item["code"] for item in validate_architecture(tmp_path, registry)}
    assert "ARCHITECTURE_EXCEPTION_EVIDENCE_MISMATCH" in codes
    assert "NEW_ARCHITECTURE_CYCLE" in codes


ALIAS_CAPABILITY_ATTACKS = [
    "import sys as s\ns.path.insert(0,'x')\n",
    "import site\nsite.addsitedir('x')\n",
    "import os\nos.environ['PYTHONPATH']='x'\n",
    "import importlib as il\nf=il.import_module\nf(name)\n",
    "import builtins\nbuiltins.exec(code)\n",
    "runner=exec\nrunner(code)\n",
    "runner=eval\nrunner(expr)\n",
    "def run(code, runner=exec):\n    return runner(code)\n",
    "runner=[exec][0]\nrunner(code)\n",
]
def test_import_capability_aliases_fail_closed(tmp_path):
    package = tmp_path / "scripts/domain"; package.mkdir(parents=True)
    for index, source in enumerate(ALIAS_CAPABILITY_ATTACKS):
        (package / f"x{index}.py").write_text(source, encoding="utf-8")
    findings = validate_architecture(tmp_path, _registry())
    paths = {item.get("path") for item in findings if item["code"] in {"DYNAMIC_IMPORT_CAPABILITY", "PROCESS_EXECUTION_CAPABILITY"}}
    assert {f"scripts/domain/x{index}.py" for index in range(len(ALIAS_CAPABILITY_ATTACKS))} <= paths


SUBPROCESS_FROM_IMPORT_ATTACKS = [
    "from subprocess import run\nrun(['tool'])\n",
    "from subprocess import Popen\nPopen(['tool'])\n",
    "from subprocess import call\ncall(['tool'])\n",
    "from subprocess import check_call\ncheck_call(['tool'])\n",
    "from subprocess import check_output\ncheck_output(['tool'])\n",
    "from subprocess import run as execute\nexecute(['tool'])\n",
    "from subprocess import Popen as process\nlaunch = process\nlaunch(['tool'])\n",
]
def test_subprocess_from_import_apis_aliases_and_indirect_calls_fail_closed(monkeypatch):
    sources = {
        f"scripts/domain/process{index}.py": source
        for index, source in enumerate(SUBPROCESS_FROM_IMPORT_ATTACKS)
    }
    monkeypatch.setattr(architecture_gate, "_python_files", lambda _root: sorted(sources))
    original_read_text = Path.read_text
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda path, **kwargs: sources[path.relative_to(ROOT).as_posix()]
        if path.is_relative_to(ROOT) and path.relative_to(ROOT).as_posix() in sources
        else original_read_text(path, **kwargs),
    )

    findings = validate_architecture(ROOT, _registry())

    paths = {item.get("path") for item in findings if item["code"] == "PROCESS_EXECUTION_CAPABILITY"}
    assert {f"scripts/domain/process{index}.py" for index in range(len(SUBPROCESS_FROM_IMPORT_ATTACKS))} <= paths


REFLECTIVE_OS_PROCESS_ATTACKS = [
    "import os\nvars(os)['system']('tool')\n",
    "import os\nos.__dict__['popen']('tool')\n",
    "import os as operating_system\nvars(operating_system)['spawn' + 'l'](0, 'tool')\n",
    "import os as operating_system\noperating_system.__dict__['ex' + 'ecl']('tool', 'tool')\n",
    "import os as operating_system\ngetattr(operating_system, 'sys' + 'tem')('tool')\n",
    "import os\nvars(os).get('sys' + 'tem')('tool')\n",
    "import os\nos.__dict__.get('system')('tool')\n",
    "import os\ngetattr(vars(os), 'system')('tool')\n",
    "import os\ngetattr(os, capability_name)('tool')\n",
    "import os\nvars(os)[capability_name]('tool')\n",
    "import os\nos.__dict__[capability_name]('tool')\n",
    "import os\nvars(os).get(capability_name)('tool')\n",
    "import os\nos.__dict__.get(capability_name)('tool')\n",
    "from os import __dict__ as d\nd['system']('tool')\n",
    "from os import __dict__ as d\nd.get('system')('tool')\n",
    "import os\nd = os.__dict__\nd['system']('tool')\n",
    "import os\nd = os.__dict__\nd.get('system')('tool')\n",
]
def test_reflective_os_process_apis_aliases_and_constant_names_fail_closed(monkeypatch):
    sources = {
        f"scripts/domain/reflective_process{index}.py": source
        for index, source in enumerate(REFLECTIVE_OS_PROCESS_ATTACKS)
    }
    monkeypatch.setattr(architecture_gate, "_python_files", lambda _root: sorted(sources))
    original_read_text = Path.read_text
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda path, **kwargs: sources[path.relative_to(ROOT).as_posix()]
        if path.is_relative_to(ROOT) and path.relative_to(ROOT).as_posix() in sources
        else original_read_text(path, **kwargs),
    )

    findings = validate_architecture(ROOT, _registry())

    paths = {item.get("path") for item in findings if item["code"] == "PROCESS_EXECUTION_CAPABILITY"}
    assert {f"scripts/domain/reflective_process{index}.py" for index in range(len(sources))} <= paths


@pytest.mark.parametrize("source", [
    "import os\nd, = (os.__dict__,)\nd['system']('tool')\n",
    "import os\nf, = [os.system]\nf('tool')\n",
    "import os\nfrom operator import attrgetter\nattrgetter('system')(os)('tool')\n",
    "import os\nimport operator as op\nop.attrgetter('system')(os)('tool')\n",
])
def test_process_capability_acquisition_transformations_fail_closed(source):
    tree = architecture_gate.ast.parse(source)
    _, findings = architecture_gate._imports(tree, "scripts.domain.transformed", False, set())

    assert any(item["code"] == "PROCESS_EXECUTION_CAPABILITY" for item in findings)


def test_platform_os_named_expression_process_capability_fails_closed():
    tree = architecture_gate.ast.parse(
        "import platform\n(p := platform.os).system('tool')\n"
    )

    _, findings = architecture_gate._imports(
        tree, "scripts.domain.indirect_process", False, set()
    )

    assert any(item["code"] == "PROCESS_EXECUTION_CAPABILITY" for item in findings)


@pytest.mark.parametrize("source", [
    "import os\nos.__getattribute__('system')('tool')\n",
    "import asyncio\nasyncio.__getattribute__('create_' + 'subprocess_shell')('tool')\n",
    "import os as operating_system\nname = 'sys' + 'tem'\noperating_system.__getattribute__(name)('tool')\n",
    "import os\nobject.__getattribute__(os, 'popen')('tool')\n",
    "import asyncio as aio\nname = 'create_subprocess_exec'\nobject.__getattribute__(aio, name)('tool')\n",
    "import os\nrun = os.__getattribute__('system')\nrun('tool')\n",
    "import asyncio as aio\nname = 'create_' + 'subprocess_exec'\nrun = object.__getattribute__(aio, name)\nrun('tool')\n",
    "import os\nrun = os.__getattribute__(capability_name)\nrun('tool')\n",
    "import asyncio\nrun = object.__getattribute__(asyncio, capability_name)\nrun('tool')\n",
])
def test_getattribute_process_capability_acquisition_fails_closed(source):
    tree = architecture_gate.ast.parse(source)
    _, findings = architecture_gate._imports(tree, "scripts.domain.getattribute", False, set())

    assert any(item["code"] == "PROCESS_EXECUTION_CAPABILITY" for item in findings)


@pytest.mark.parametrize("source", [
    "import os\nos.__getattribute__('getcwd')()\n",
    "import asyncio\nasyncio.__getattribute__('sleep')(0)\n",
    "class Local:\n    system = object()\nlocal = Local()\nlocal.__getattribute__('system')\n",
    "class Local:\n    system = object()\nlocal = Local()\nobject.__getattribute__(local, 'system')\n",
])
def test_benign_getattribute_does_not_claim_process_capability(source):
    tree = architecture_gate.ast.parse(source)
    _, findings = architecture_gate._imports(tree, "scripts.domain.benign_getattribute", False, set())

    assert not any(item["code"] == "PROCESS_EXECUTION_CAPABILITY" for item in findings)


@pytest.mark.parametrize("source", [
    "label, = ('os.system',)\n",
    "class Local:\n    system = object()\nos = Local()\nvalue, = (os.system,)\n",
    "import os\nclass Local:\n    system = object()\nos = Local()\nvalue, = (os.system,)\n",
    "import os as operating_system\nclass Local:\n    system = object()\noperating_system = Local()\nvalue, = (operating_system.system,)\n",
])
def test_benign_destructuring_does_not_claim_process_capability(source):
    tree = architecture_gate.ast.parse(source)
    _, findings = architecture_gate._imports(tree, "scripts.domain.benign", False, set())

    assert not any(item["code"] == "PROCESS_EXECUTION_CAPABILITY" for item in findings)


@pytest.mark.parametrize("source", [
    "from os import __dict__ as d\nd = {}\n",
    "import os\nd = os.__dict__\nd = {}\n",
])
@pytest.mark.parametrize("call", ["d['system']('tool')", "d.get('system')('tool')"])
def test_reflective_os_dictionary_provenance_is_invalidated_on_reassignment(source, call):
    tree = architecture_gate.ast.parse(f"{source}{call}\n")
    _, findings = architecture_gate._imports(tree, "scripts.domain.shadowed", False, set())

    assert not any(item["code"] == "PROCESS_EXECUTION_CAPABILITY" for item in findings)


@pytest.mark.parametrize("source", [
    "import os as operating_system\nif False:\n    operating_system = {}\noperating_system.system('tool')\n",
    "from os import __dict__ as d\nif False:\n    d = {}\nd['system']('tool')\n",
])
def test_conditional_reassignment_cannot_erase_process_provenance(source):
    tree = architecture_gate.ast.parse(source)
    _, findings = architecture_gate._imports(tree, "scripts.domain.conditional", False, set())

    assert any(item["code"] == "PROCESS_EXECUTION_CAPABILITY" for item in findings)


@pytest.mark.parametrize("call", ["d['system']('tool')", "d.get('system')('tool')"])
def test_later_reassignment_cannot_erase_earlier_process_capability(call):
    tree = architecture_gate.ast.parse(f"from os import __dict__ as d\n{call}\nd = {{}}\n")
    _, findings = architecture_gate._imports(tree, "scripts.domain.earlier", False, set())

    assert any(item["code"] == "PROCESS_EXECUTION_CAPABILITY" for item in findings)


@pytest.mark.parametrize("source", [
    "from os import __dict__ as d; d['system']('tool')",
    "from os import __dict__ as d; d.get('system')('tool')",
    "import os; d = os.__dict__; d['system']('tool')",
    "import os; d = os.__dict__; d.get('system')('tool')",
])
def test_same_line_reflective_process_provenance_fails_closed(source):
    tree = architecture_gate.ast.parse(source)
    _, findings = architecture_gate._imports(tree, "scripts.domain.same_line", False, set())

    assert any(item["code"] == "PROCESS_EXECUTION_CAPABILITY" for item in findings)


def test_exact_head_check_includes_the_referenced_architecture_constitution(monkeypatch):
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return architecture_gate.subprocess.CompletedProcess(command, 0, " M docs/arquitetura/constituicao-core-pericial-v1.md\n", "")

    monkeypatch.setattr(architecture_gate.subprocess, "run", fake_run)

    findings = load_and_validate(ROOT)

    assert findings == [{"code": "ARCHITECTURE_WORKTREE_NOT_EXACT_HEAD"}]
    assert "docs/arquitetura/constituicao-core-pericial-v1.md" in calls[0]


def test_governance_code_cannot_hide_dynamic_import_capabilities(tmp_path):
    package = tmp_path / "scripts/quality"; package.mkdir(parents=True)
    (package / "evil.py").write_text(
        "import importlib\ngetattr(importlib, 'import_module')(name)\n",
        encoding="utf-8",
    )
    assert any(item["code"] == "DYNAMIC_IMPORT_CAPABILITY" for item in validate_architecture(tmp_path, _registry()))


def test_duplicate_architecture_debt_is_rejected(tmp_path):
    package = tmp_path / "scripts/domain"; package.mkdir(parents=True)
    (package / "x.py").write_text("VALUE=1\n", encoding="utf-8")
    row = {"source": "scripts.application.a", "target": "scripts.domain.x",
           "classification": "POTENTIAL_VIOLATION", "evidence": "x:1", "disposition": "REMOVE"}
    findings = validate_architecture(tmp_path, _registry(acceptedCurrentDependencies=[row, row]))
    assert any(item["code"] == "DUPLICATE_ARCHITECTURE_EXCEPTION" for item in findings)


REFLECTIVE_LOADER_ATTACKS = [
    "import importlib\nvars(importlib)['import_module'](name)\n",
    "import importlib\nimportlib.__dict__['import_module'](name)\n",
    "import importlib\ngetattr(importlib, 'import_' + 'module')(name)\n",
    "import runpy\nrunpy.run_module(name)\n",
    "import importlib\ngetattr(importlib, capability_name)(module_name)\n",
    "import sys\ngetattr(sys, field).insert(0, 'x')\n",
    "import sys\nsetattr(sys, attr, [])\n",
    "import builtins\nbuiltins.__dict__['__import__'](name)\n",
    "__builtins__['__import__'](name)\n",
    "globals()['__builtins__']['__import__'](name)\n",
    "import importlib as il\nvars(il)[name](target)\n",
    "import runpy as r\ngetattr(r, method)(name)\n",
    "import sys as s\nvars(s)[field].insert(0, 'x')\n",
    "import builtins as b\nvars(b)[key](code)\n",
    "import pkgutil\npkgutil.resolve_name(name)\n",
    "import pydoc\npydoc.locate(name)\n",
    "import zipimport\nzipimport.zipimporter(path).load_module(name)\n",
    "import pkg_resources\npkg_resources.load_entry_point(dist, group, name)\n",
    "import sys\nsys.meta_path.insert(0, finder)\n",
    "import sys\ngetattr(sys.modules[key], method)(name)\n",
    "__loader__.load_module(name)\n",
    "__spec__.loader.exec_module(module)\n",
    "import ctypes\nctypes.pythonapi.PyImport_ImportModule(name)\n",
    "import pickle\npickle.loads(payload)\n",
    "globals()['__buil'+'tins__']['__im'+'port__'](name)\n",
    "getattr(globals()['__buil'+'tins__'], '__im'+'port__')(name)\n",
    "globals()['__buil'+'tins__']['ex'+'ec']('import scripts.motor_vicios.motor')\n",
    "import subprocess, sys\nsubprocess.run([sys.executable, '-m', 'scripts.motor_vicios.motor'])\n",
    "import types\ntypes.FunctionType(compile('import scripts.motor_vicios.motor', 'x', 'exec'), globals())()\n",
    "import os, sys\nos.system(f'{sys.executable} -m scripts.motor_vicios.motor')\n",
    "import subprocess\nsubprocess.run(['python', '-m', 'scripts.motor_vicios.motor'])\n",
    "import subprocess, sys\nexe = sys.executable\nsubprocess.run([exe, '-m', 'scripts.motor_vicios.motor'])\n",
]


@pytest.mark.parametrize("source", [
    """\
a = ''.join(map(chr, [95,95,98,117,105,108,116,105,110,115,95,95]))
b = ''.join(map(chr, [95,95,105,109,112,111,114,116,95,95]))
c = globals()
d = c[a]
e = d[b]
e("scripts.quality.verify_core")
""",
    """\
key = decode_external_value()
namespace = globals()
namespace[key]
""",
])
def test_computed_reflective_global_acquisition_fails_closed(source):

    _, findings = architecture_gate._imports(
        architecture_gate.ast.parse(source),
        "scripts.domain.computed_reflection",
        False,
        set(),
    )

    assert any(item["code"] == "DYNAMIC_IMPORT_CAPABILITY" for item in findings)


def test_globals_iteration_without_reflective_lookup_remains_allowed():
    source = "__all__ = [name for name in globals() if not name.startswith('_')]\n"

    _, findings = architecture_gate._imports(
        architecture_gate.ast.parse(source),
        "scripts.backend_contract",
        False,
        set(),
    )

    assert not any(item["code"] == "DYNAMIC_IMPORT_CAPABILITY" for item in findings)


def test_reflective_stdlib_import_execution_fails_closed(tmp_path):
    package = tmp_path / "scripts/domain"; package.mkdir(parents=True)
    for index, source in enumerate(REFLECTIVE_LOADER_ATTACKS):
        (package / f"r{index}.py").write_text(source, encoding="utf-8")
    findings = validate_architecture(tmp_path, _registry())
    paths = {item.get("path") for item in findings if item["code"] in {"DYNAMIC_IMPORT_CAPABILITY", "PROCESS_EXECUTION_CAPABILITY"}}
    assert {f"scripts/domain/r{index}.py" for index in range(len(REFLECTIVE_LOADER_ATTACKS))} <= paths


EXECUTION_CAPABILITY_ATTACKS = [
    "import codeop, types\ntypes.FunctionType(\n    codeop.compile_command('import scripts.motor_vicios.motor'),\n    globals(),\n)()\n",
    "import asyncio\nasyncio.create_subprocess_exec('tool')\n",
    "import os\nos.startfile('tool')\n",
    "import asyncio\nlaunch = asyncio.create_subprocess_exec\nlaunch('tool')\n",
    "import os\nlaunch = os.startfile\nlaunch('tool')\n",
    "import os\ngetattr(os, 'startfile')('tool')\n",
    "import os\nvars(os)['startfile']('tool')\n",
    "import os\nos.__dict__.get('startfile')('tool')\n",
]


def test_additional_stdlib_execution_capabilities_fail_closed(monkeypatch):
    sources = {
        f"scripts/domain/process_runtime{index}.py": source
        for index, source in enumerate(EXECUTION_CAPABILITY_ATTACKS)
    }
    monkeypatch.setattr(architecture_gate, "_python_files", lambda _root: sorted(sources))
    original_read_text = Path.read_text
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda path, **kwargs: sources[path.relative_to(ROOT).as_posix()]
        if path.is_relative_to(ROOT) and path.relative_to(ROOT).as_posix() in sources
        else original_read_text(path, **kwargs),
    )

    findings = validate_architecture(ROOT, _registry())

    capabilities = {(item["code"], item.get("path")) for item in findings}
    assert {
        ("DYNAMIC_IMPORT_CAPABILITY", "scripts/domain/process_runtime0.py"),
        ("PROCESS_EXECUTION_CAPABILITY", "scripts/domain/process_runtime1.py"),
        ("PROCESS_EXECUTION_CAPABILITY", "scripts/domain/process_runtime2.py"),
        ("PROCESS_EXECUTION_CAPABILITY", "scripts/domain/process_runtime3.py"),
        ("PROCESS_EXECUTION_CAPABILITY", "scripts/domain/process_runtime4.py"),
        ("PROCESS_EXECUTION_CAPABILITY", "scripts/domain/process_runtime5.py"),
        ("PROCESS_EXECUTION_CAPABILITY", "scripts/domain/process_runtime6.py"),
        ("PROCESS_EXECUTION_CAPABILITY", "scripts/domain/process_runtime7.py"),
    } <= capabilities
