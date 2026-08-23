import ast
import subprocess
import sys
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from pathlib import Path
from typing import get_type_hints
from uuid import UUID

import pytest
from hypothesis import given, strategies as st

from scripts.backend_contract.application.models import (
    ArtifactRevision,
    PericiaWorkspace,
    WorkspaceId,
    thaw_payload,
)
from scripts.backend_contract.application.ports import (
    ArtifactRevisionRepository,
    Clock,
    IdGenerator,
    WorkspaceRepository,
)


WORKSPACE_ID = "11111111-1111-4111-8111-111111111111"
JSON_SCALARS = (
    st.none()
    | st.booleans()
    | st.integers(min_value=-(10**12), max_value=10**12)
    | st.floats(allow_nan=False, allow_infinity=False, width=64)
    | st.text(max_size=64)
)
JSON_VALUES = st.recursive(
    JSON_SCALARS,
    lambda children: st.lists(children, max_size=5)
    | st.dictionaries(st.text(max_size=32), children, max_size=5),
    max_leaves=20,
)


def test_workspace_id_is_canonical_and_rejects_invalid_input():
    workspace_id = WorkspaceId.parse(WORKSPACE_ID)
    assert workspace_id.value == UUID(WORKSPACE_ID)
    assert str(workspace_id) == WORKSPACE_ID
    for invalid in ("", "not-a-uuid", 123, None):
        with pytest.raises((TypeError, ValueError)):
            WorkspaceId.parse(invalid)


def test_workspace_is_immutable_and_requires_explicit_technical_metadata():
    workspace = PericiaWorkspace(
        workspace_id=WorkspaceId.parse(WORKSPACE_ID),
        name="Perícia sintética",
        created_at="2026-08-21T12:00:00+00:00",
    )
    assert workspace.name == "Perícia sintética"
    with pytest.raises(FrozenInstanceError):
        workspace.name = "alterado"
    for name in ("", "   "):
        with pytest.raises(ValueError, match="name"):
            PericiaWorkspace(workspace.workspace_id, name, workspace.created_at)


def test_workspace_rejects_naive_or_malformed_timestamp():
    workspace_id = WorkspaceId.parse(WORKSPACE_ID)
    for created_at in ("", "not-a-date", "2026-08-21T12:00:00"):
        with pytest.raises(ValueError, match="created_at"):
            PericiaWorkspace(workspace_id, "Sintético", created_at)


def test_artifact_revision_deep_freezes_payload_without_mutating_caller():
    payload = {
        "descricao": "Fissuração não constatada",
        "avisos": ["INCONCLUSIVO", None],
        "proveniencia": {"fonte": "SINTETICA", "ordem": [2, 1]},
        "valor": 1.25,
    }
    revision = ArtifactRevision(
        workspace_id=WorkspaceId.parse(WORKSPACE_ID),
        artifact_kind="VISTORIA",
        artifact_id="VIS-001",
        revision_id="22222222-2222-4222-8222-222222222222",
        revision=1,
        created_at="2026-08-21T12:00:00+00:00",
        checksum_sha256="a" * 64,
        payload=payload,
    )
    payload["avisos"].append("ALTERADO")
    payload["proveniencia"]["ordem"].reverse()
    assert thaw_payload(revision.payload) == {
        "descricao": "Fissuração não constatada",
        "avisos": ["INCONCLUSIVO", None],
        "proveniencia": {"fonte": "SINTETICA", "ordem": [2, 1]},
        "valor": 1.25,
    }
    with pytest.raises(TypeError):
        revision.payload["novo"] = True


@given(JSON_VALUES)
def test_artifact_revision_preserves_arbitrary_canonical_json(payload):
    revision = ArtifactRevision(
        workspace_id=WorkspaceId.parse(WORKSPACE_ID),
        artifact_kind="ARTEFATO_SINTETICO",
        artifact_id="ART-001",
        revision_id="22222222-2222-4222-8222-222222222222",
        revision=1,
        created_at="2026-08-21T12:00:00+00:00",
        checksum_sha256="a" * 64,
        payload=payload,
    )
    assert thaw_payload(revision.payload) == payload


def test_artifact_revision_rejects_cyclic_payload_explicitly():
    cyclic = []
    cyclic.append(cyclic)
    with pytest.raises(ValueError, match="cíclico"):
        ArtifactRevision(
            workspace_id=WorkspaceId.parse(WORKSPACE_ID),
            artifact_kind="ARTEFATO_SINTETICO",
            artifact_id="ART-001",
            revision_id="22222222-2222-4222-8222-222222222222",
            revision=1,
            created_at="2026-08-21T12:00:00+00:00",
            checksum_sha256="a" * 64,
            payload=cyclic,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("artifact_kind", ""),
        ("artifact_id", " "),
        ("revision_id", "not-a-uuid"),
        ("revision", 0),
        ("created_at", "2026-08-21T12:00:00"),
        ("checksum_sha256", "ABC"),
    ),
)
def test_artifact_revision_rejects_invalid_identity(field, value):
    values = {
        "workspace_id": WorkspaceId.parse(WORKSPACE_ID),
        "artifact_kind": "LAUDO",
        "artifact_id": "LAU-001",
        "revision_id": "22222222-2222-4222-8222-222222222222",
        "revision": 1,
        "created_at": datetime(2026, 8, 21, tzinfo=UTC).isoformat(),
        "checksum_sha256": "a" * 64,
        "payload": {"status": "INCONCLUSIVO"},
    }
    values[field] = value
    with pytest.raises((TypeError, ValueError)):
        ArtifactRevision(**values)


def test_artifact_revision_normalizes_revision_id_to_canonical_uuid():
    revision = ArtifactRevision(
        workspace_id=WorkspaceId.parse(WORKSPACE_ID),
        artifact_kind="LAUDO",
        artifact_id="LAU-001",
        revision_id="{22222222222242228222222222222222}",
        revision=1,
        created_at="2026-08-21T12:00:00+00:00",
        checksum_sha256="a" * 64,
        payload={},
    )
    assert revision.revision_id == "22222222-2222-4222-8222-222222222222"


def test_ports_expose_only_explicit_application_operations():
    workspace_methods = {
        name for name in WorkspaceRepository.__dict__ if not name.startswith("_")
    }
    revision_methods = {
        name for name in ArtifactRevisionRepository.__dict__ if not name.startswith("_")
    }
    assert workspace_methods == {"create", "get", "list_all"}
    assert revision_methods == {"append", "latest", "get_revision", "list_all"}
    assert get_type_hints(WorkspaceRepository.get)["return"] == PericiaWorkspace | None
    assert get_type_hints(ArtifactRevisionRepository.latest)["return"] == ArtifactRevision | None


def test_technical_generators_have_narrow_deterministic_ports():
    assert {name for name in Clock.__dict__ if not name.startswith("_")} == {"now"}
    assert {name for name in IdGenerator.__dict__ if not name.startswith("_")} == {
        "new_uuid"
    }
    assert get_type_hints(Clock.now)["return"] is datetime
    assert get_type_hints(IdGenerator.new_uuid)["return"] is UUID


def test_application_services_do_not_import_infrastructure_or_sqlite():
    services = Path("scripts/backend_contract/application/services.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(services)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert "sqlite3" not in imported
    assert not any("infrastructure" in module for module in imported)


def _imports_in(path):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    return {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }


def _canonical_import_targets(source_module, source):
    tree = ast.parse(source)
    package = source_module.split(".")[:-1]
    targets = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                keep = len(package) - (node.level - 1)
                base = package[:keep]
                if node.module:
                    base.extend(node.module.split("."))
                module = ".".join(base)
            else:
                module = node.module or ""
            targets.update(
                f"{module}.{alias.name}" if module else alias.name
                for alias in node.names
            )
    return targets


def _unapproved_backend_dependencies(source_module, source, allowed):
    backend = "scripts.backend_contract"
    return {
        target
        for target in _canonical_import_targets(source_module, source)
        if (target == backend or target.startswith(f"{backend}."))
        and not any(
            target == prefix or target.startswith(f"{prefix}.")
            for prefix in allowed
        )
    }


def _local_api_module_inventory(package):
    package = Path(package)
    return {
        ".".join(path.relative_to(package).with_suffix("").parts): path
        for path in package.rglob("*.py")
        if "__pycache__" not in path.parts
    }


def _local_api_persistence_imports(source_module, source):
    infrastructure = "scripts.backend_contract.infrastructure"
    return {
        target
        for target in _canonical_import_targets(source_module, source)
        if target == "sqlite3"
        or target.startswith("sqlite3.")
        or target == infrastructure
        or target.startswith(f"{infrastructure}.")
    }


def test_local_api_inventory_is_recursive_and_uses_canonical_module_names(tmp_path):
    package = tmp_path / "local_api"
    nested = package / "internal"
    nested.mkdir(parents=True)
    (package / "transport.py").write_text("", encoding="utf-8")
    (nested / "bridge.py").write_text("import sqlite3\n", encoding="utf-8")

    inventory = _local_api_module_inventory(package)

    assert set(inventory) == {"transport", "internal.bridge"}
    assert inventory["internal.bridge"] == nested / "bridge.py"


def test_direct_sqlite_import_is_forbidden_outside_composition():
    assert _local_api_persistence_imports(
        "scripts.backend_contract.local_api.internal.bridge",
        "import sqlite3",
    ) == {"sqlite3"}


def test_local_api_layers_use_only_their_explicit_backend_dependencies():
    policies = {
        "__init__": (),
        "transport": ("scripts.backend_contract.application",),
        "server": ("scripts.backend_contract.local_api.transport",),
        "composition": (
            "scripts.backend_contract.application",
            "scripts.backend_contract.infrastructure",
            "scripts.backend_contract.local_api.server",
            "scripts.backend_contract.local_api.transport",
        ),
    }
    inventory = _local_api_module_inventory(
        Path("scripts/backend_contract/local_api")
    )
    assert set(inventory) == set(policies)
    for module, path in inventory.items():
        allowed = policies[module]
        source_module = f"scripts.backend_contract.local_api.{module}"
        assert not _unapproved_backend_dependencies(
            source_module,
            path.read_text(encoding="utf-8"),
            allowed,
        )


@pytest.mark.parametrize(
    "statement",
    (
        "from ..revisions import append_revision",
        "from scripts.backend_contract import revisions",
        "import scripts.backend_contract.motor",
    ),
)
def test_local_api_dependency_allowlist_rejects_every_core_module(statement):
    violations = _unapproved_backend_dependencies(
        "scripts.backend_contract.local_api.transport",
        statement,
        ("scripts.backend_contract.application",),
    )
    assert violations


def test_local_api_sqlite_wiring_is_confined_to_composition_root():
    inventory = _local_api_module_inventory(
        Path("scripts/backend_contract/local_api")
    )
    importers = {
        module
        for module, path in inventory.items()
        if _local_api_persistence_imports(
            f"scripts.backend_contract.local_api.{module}",
            path.read_text(encoding="utf-8"),
        )
    }
    assert importers == {"composition"}


def test_local_api_production_modules_have_no_outbound_network_clients():
    forbidden = {
        "aiohttp",
        "http.client",
        "requests",
        "urllib.request",
        "urllib3",
    }
    for path in Path("scripts/backend_contract/local_api").rglob("*.py"):
        assert _imports_in(path).isdisjoint(forbidden)


def test_importing_local_api_transport_does_not_load_sqlite_or_infrastructure():
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import scripts.backend_contract.local_api.transport; "
            "print('sqlite3' in sys.modules); "
            "print(any(name.startswith('scripts.backend_contract.infrastructure') "
            "for name in sys.modules))",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert probe.stdout.splitlines() == ["False", "False"]
