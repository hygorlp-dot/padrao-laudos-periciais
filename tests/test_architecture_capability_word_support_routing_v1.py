"""SUPPORT_PATH != TRANSITION_TRIGGER in capability-protected.yml.

The Word scope names what a dedicated Word transition may carry.  Only Word
product bytes, protected trust artifacts and the transition manifests start
one; the Word-scoped tests changed on their own are support, judged by the
ordinary base-owned custody and enforcement route.  The detection step is
executed exactly as the workflow embeds it, against synthetic commits built on
the real HEAD.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.quality.capability_bootstrap import run_protected_capability_gate
from scripts.quality.capability_trust_anchor import validate_inert_trust_anchor


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/capability-protected.yml"
WORD_PARENT = "scripts/backend_contract/infrastructure/office_pdf.py"
WORD_WORKER = "scripts/backend_contract/infrastructure/office_word_worker.py"
ADAPTER = "scripts/quality/capability_gate_adapter.py"
TRUST_ANCHOR = "scripts/quality/capability_trust_anchor.py"
TRANSITION = "config/capability-protected-transition-v1.json"
SUPPORT_TESTS = (
    "tests/test_delivery_foundation_v1.py",
    "tests/test_office_pdf_renderer_v1.py",
    "tests/test_office_word_containment_v1.py",
)
_GIT_IDENTITY = ("-c", "user.name=Routing Fixture", "-c", "user.email=fixture@example.invalid")


def _detection_source() -> str:
    """The detection step as the workflow runs it (pre-repair: the one-liner)."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    lines = workflow.splitlines()
    markers = [i for i, line in enumerate(lines) if line.strip() in {
        "# WORD_SUPPORT_ROUTING_BEGIN", "# WORD_SUPPORT_ROUTING_END",
    }]
    if markers:
        block = lines[markers[0] : markers[1] + 1]
        indent = len(block[0]) - len(block[0].lstrip())
        return "\n".join(line[indent:] for line in block) + "\n"
    step = workflow[workflow.index("- name: Detect dedicated Word scope changes"):]
    return re.search(r'\$state = python -c "(.*?)"\n', step).group(1).replace("; ", "\n") + "\n"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *_GIT_IDENTITY, *args], cwd=repo, check=True, capture_output=True, text=True,
    ).stdout


@pytest.fixture(scope="module")
def repo(tmp_path_factory) -> dict:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout.strip()
    path = tmp_path_factory.mktemp("word-support-routing") / "candidate"
    subprocess.run(
        ["git", "clone", "-q", "--shared", "--no-checkout", str(ROOT), str(path)],
        check=True, capture_output=True,
    )
    _git(path, "checkout", "-q", "--detach", head)
    return {"path": path, "base": head}


def _candidate(repo: dict, edits: dict[str, str | bytes]) -> str:
    """A child commit of the base built with plumbing only (no working-tree checkout)."""
    path, base = repo["path"], repo["base"]
    index = path.parent / "routing-fixture.index"
    env = {**os.environ, "GIT_INDEX_FILE": str(index)}

    def git(*args: str, data: bytes | None = None) -> bytes:
        return subprocess.run(
            ["git", *_GIT_IDENTITY, *args], cwd=path, env=env, input=data, check=True, capture_output=True,
        ).stdout

    git("read-tree", base)
    for name, change in edits.items():
        if isinstance(change, bytes):
            content = change
        else:
            listed = git("ls-tree", base, "--", name).strip()
            original = git("show", f"{base}:{name}") if listed else b""
            content = original + change.encode("utf-8")
        blob = git("hash-object", "-w", "--stdin", data=content).decode().strip()
        git("update-index", "--add", "--cacheinfo", f"100644,{blob},{name}")
    tree = git("write-tree").decode().strip()
    return git("commit-tree", tree, "-p", base, "-m", "routing fixture").decode().strip()


def _route(repo: dict, candidate: str) -> str:
    completed = subprocess.run(
        [sys.executable, "-"], input=_detection_source(), cwd=ROOT, capture_output=True, text=True,
        env={
            **os.environ,
            "CAPABILITY_CANDIDATE_ROOT": str(repo["path"]),
            "CAPABILITY_PROTECTED_BASE_SHA": repo["base"],
            "CAPABILITY_EXPECTED_HEAD_SHA": candidate,
        },
        timeout=600,
    )
    if completed.returncode:
        return "FAILED_CLOSED"
    return {"false": "COMMON", "true": "DEDICATED"}[completed.stdout.strip()]


_NOTE = "\n# routing fixture\n"
_DELIVERY_INTEGRATION = {
    "scripts/backend_contract/delivery_foundation.py": _NOTE,
    "scripts/backend_contract/delivery_renderer.py": _NOTE,
    "scripts/backend_contract/application/delivery_foundation.py": _NOTE,
    "scripts/backend_contract/local_api/composition.py": _NOTE,
    "schemas/delivery-snapshot-v1.schema.json": "\n",
    "frontend/src/workspaces/DeliveryFoundationView.tsx": "\n// routing fixture\n",
    "tests/test_delivery_derived_pdf_v1.py": "X = 1\n",
    "tests/fixtures/word16-routing-fixture.pdf": b"%PDF-1.7\n%synthetic\n",
}


@pytest.mark.parametrize("support", SUPPORT_TESTS)
def test_a_support_test_changed_alone_takes_the_common_route(repo, support) -> None:
    """RED_THIS_REPAIR: on the closed judge this was a dedicated Word transition."""
    candidate = _candidate(repo, {support: _NOTE})

    assert _route(repo, candidate) == "COMMON"
    assert validate_inert_trust_anchor(repo["path"], repo["base"], candidate) == []


def test_support_tests_with_unrelated_delivery_integration_take_the_common_route(repo) -> None:
    """The PR #203 shape, with every Word-scoped support test: one full analysis."""
    candidate = _candidate(repo, {**{path: _NOTE for path in SUPPORT_TESTS}, **_DELIVERY_INTEGRATION})

    assert _route(repo, candidate) == "COMMON"
    assert validate_inert_trust_anchor(repo["path"], repo["base"], candidate) == []
    assert run_protected_capability_gate(repo["path"], repo["base"], candidate) == []


@pytest.mark.parametrize(
    "edits",
    [
        {WORD_PARENT: _NOTE},
        {WORD_WORKER: _NOTE},
        {WORD_PARENT: _NOTE, SUPPORT_TESTS[0]: _NOTE},
        {WORD_WORKER: _NOTE, SUPPORT_TESTS[1]: _NOTE},
    ],
    ids=["office-pdf", "word-worker", "office-pdf+support", "worker+support"],
)
def test_word_product_bytes_still_start_a_dedicated_transition_and_are_refused(repo, edits) -> None:
    """Any byte of a pinned Word product file is judged by the exact contract."""
    candidate = _candidate(repo, edits)

    assert _route(repo, candidate) != "COMMON"
    assert _route(repo, candidate) == "FAILED_CLOSED"


@pytest.mark.parametrize("product", [WORD_PARENT, WORD_WORKER])
def test_a_renamed_word_product_file_is_never_support_only(repo, product) -> None:
    """Rename detection would list only the new path; the old one still triggers."""
    path, base = repo["path"], repo["base"]
    env = {**os.environ, "GIT_INDEX_FILE": str(path.parent / "rename-fixture.index")}

    def git(*args: str, data: bytes | None = None) -> str:
        return subprocess.run(
            ["git", *_GIT_IDENTITY, *args], cwd=path, env=env, input=data,
            check=True, capture_output=True,
        ).stdout.decode()

    git("read-tree", base)
    content = subprocess.run(
        ["git", "show", f"{base}:{product}"], cwd=path, check=True, capture_output=True,
    ).stdout + b"\n# altered after rename\n"
    blob = git("hash-object", "-w", "--stdin", data=content).strip()
    git("update-index", "--force-remove", product)
    git("update-index", "--add", "--cacheinfo", f"100644,{blob},{product}.renamed.py")
    support = subprocess.run(
        ["git", "show", f"{base}:{SUPPORT_TESTS[1]}"], cwd=path, check=True, capture_output=True,
    ).stdout + _NOTE.encode()
    git("update-index", "--add", "--cacheinfo",
        f"100644,{git('hash-object', '-w', '--stdin', data=support).strip()},{SUPPORT_TESTS[1]}")
    candidate = git("commit-tree", git("write-tree").strip(), "-p", base, "-m", "rename fixture").strip()

    assert _route(repo, candidate) != "COMMON"


@pytest.mark.parametrize(
    "edits",
    [
        {ADAPTER: _NOTE},
        {ADAPTER: _NOTE, SUPPORT_TESTS[0]: _NOTE},
        {TRUST_ANCHOR: _NOTE, SUPPORT_TESTS[0]: _NOTE},
    ],
    ids=["adapter", "adapter+support", "trust-anchor+support"],
)
def test_trust_authority_is_never_support_only(repo, edits) -> None:
    candidate = _candidate(repo, edits)

    assert _route(repo, candidate) != "COMMON"
    # Nor could the ordinary custody route admit it.
    assert validate_inert_trust_anchor(repo["path"], repo["base"], candidate) != []


def test_a_transition_manifest_change_stays_on_the_dedicated_route(repo) -> None:
    """The manifest is not a registry artifact; the dedicated route is what judges it."""
    candidate = _candidate(repo, {TRANSITION: "\n", SUPPORT_TESTS[0]: _NOTE})

    assert _route(repo, candidate) == "DEDICATED"


def test_the_common_route_still_refuses_new_process_authority(repo) -> None:
    subprocess_module = "scripts/backend_contract/routing_fixture_subprocess.py"
    shell_module = "scripts/backend_contract/routing_fixture_shell.py"
    candidate = _candidate(repo, {
        SUPPORT_TESTS[0]: _NOTE,
        subprocess_module: "import subprocess\nsubprocess.run(['cmd'])\n",
        shell_module: "import os\nos.system('cmd')\n",
    })

    assert _route(repo, candidate) == "COMMON"
    refused = run_protected_capability_gate(repo["path"], repo["base"], candidate)
    assert {subprocess_module, shell_module} <= {item.get("canonicalPath") for item in refused}


def test_the_routing_block_depends_on_structure_not_names_or_identity() -> None:
    source = _detection_source()
    for forbidden in ("startswith('tests/')", "GITHUB_HEAD_REF", "pull_request", "github.actor", "bbdcaa3"):
        assert forbidden not in source
    assert "_SUPPORT_SCOPES" not in source  # what the scope protects is unchanged
