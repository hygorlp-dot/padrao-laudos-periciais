import json
import subprocess
from pathlib import Path

import pytest

from scripts.quality.capability_analyzer import analyze_capabilities, analyze_source


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config/capability-policy-v1.json"
TRANSFERS = ROOT / "config/architecture-capability-transfers-v2.json"


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def _candidate_repo(tmp_path: Path, source: str) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "config", "user.name", "Capability Tests"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "capability-tests@example.invalid"], cwd=repo, check=True)
    (repo / "scripts" / "target.py").write_text(source, encoding="utf-8")
    subprocess.run(["git", "add", "scripts/target.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "candidate"], cwd=repo, check=True)
    commit = _git(repo, "rev-parse", "HEAD")
    tree = _git(repo, "rev-parse", "HEAD^{tree}")
    return repo, commit, tree


def _analyze(tmp_path: Path, source: str) -> list[dict]:
    return analyze_source("scripts/target.py", source, policy_path=POLICY)


@pytest.fixture(scope="module")
def candidate_repo(tmp_path_factory):
    source = "import subprocess\n"
    repo, commit, tree = _candidate_repo(tmp_path_factory.mktemp("capability-candidate"), source)
    return repo, commit, tree, source


def test_exact_git_tree_analysis_matches_pure_source_analysis(candidate_repo):
    repo, commit, tree, source = candidate_repo

    assert analyze_capabilities(repo, commit, tree, policy_path=POLICY) == analyze_source(
        "scripts/target.py", source, policy_path=POLICY
    )


@pytest.mark.parametrize(
    ("finding_id", "source", "expected_code"),
    [
        (
            "PR50-HIGHER-ORDER-STRING-EXECUTION-BYPASS",
            "payload = '1 + 1'\n__builtins__['eval'](payload)\n",
            "DYNAMIC_EXECUTION_ACQUISITION",
        ),
        (
            "PR50-SYS-MODULES-RETRIEVAL-BYPASS",
            "import sys\nname = 'scripts.quality.target'\nsys.modules.__getitem__('importlib').import_module(name)\n",
            "DYNAMIC_IMPORT_ACQUISITION",
        ),
        (
            "PR50-IMPORT-HOOK-WRITE-BYPASS",
            "import sys\nsys.meta_path = [finder]\n",
            "SENSITIVE_NAMESPACE_ESCAPE",
        ),
        (
            "PR50-SYS-9A7815A-001",
            "payload = '1 + 1'\ndef execute(operation=eval):\n    return operation(payload)\nexecute()\n",
            "DYNAMIC_EXECUTION_ACQUISITION",
        ),
    ],
)
def test_every_transferred_p1_reproducer_is_blocked(tmp_path, finding_id, source, expected_code):
    transfer_ids = {row["findingId"] for row in json.loads(TRANSFERS.read_text(encoding="utf-8"))["findings"]}
    assert finding_id in transfer_ids

    findings = _analyze(tmp_path, source)

    assert expected_code in {finding["code"] for finding in findings}
    assert all(finding["analyzer"] == "CAPABILITY_ANALYZER_V1" for finding in findings)
    assert all(finding["canonicalPath"] == "scripts/target.py" for finding in findings)
    assert all(finding["module"] == "scripts.target" for finding in findings)


@pytest.mark.parametrize(
    "source",
    [
        "import os\nvalue = os.path.join('a', 'b')\n",
        "import os\nvalue = os.environ.get('X')\n",
        "import json\nvalue = json.loads('{}')\n",
        "class Local:\n    value = 1\nvalue = getattr(Local(), 'value')\n",
    ],
)
def test_contract_safe_sources_are_allowed(tmp_path, source):
    assert _analyze(tmp_path, source) == []


def test_candidate_commit_tree_mismatch_blocks_before_analysis(candidate_repo):
    repo, commit, _, _source = candidate_repo
    other_tree = "0" * 40

    with pytest.raises(ValueError, match="commit/tree mismatch"):
        analyze_capabilities(repo, commit, other_tree, policy_path=POLICY)


def _all_transferred_reproducers():
    rows = json.loads(TRANSFERS.read_text(encoding="utf-8"))["findings"]
    for row in rows:
        code = "DYNAMIC_IMPORT_ACQUISITION" if "IMPORT" in row["findingId"] or "MODULES" in row["findingId"] else "DYNAMIC_EXECUTION_ACQUISITION"
        if row["findingId"] == "PR50-IMPORT-HOOK-WRITE-BYPASS":
            code = "SENSITIVE_NAMESPACE_ESCAPE"
        for index, source in enumerate(row["reproducers"]):
            yield pytest.param(source + "\n", code, id=f"{row['findingId']}-{index}")


@pytest.mark.parametrize(("source", "expected_code"), list(_all_transferred_reproducers()))
def test_all_recorded_transfer_reproducers_block(tmp_path, source, expected_code):
    findings = _analyze(tmp_path, source)
    assert expected_code in {finding["code"] for finding in findings}


@pytest.mark.parametrize(("source", "expected_code"), [
    ("import subprocess\n", "PROCESS_NAMESPACE_ACQUISITION"),
    ("from multiprocessing.pool import Pool\n", "PROCESS_NAMESPACE_ACQUISITION"),
    ("import pickle\nvalue = pickle.loads(payload)\n", "EXECUTABLE_DESERIALIZATION_OR_NATIVE_LOADING"),
    ("import os\nos.system('tool')\n", "OS_PROCESS_MEMBER_ACQUISITION"),
    ("from os import posix_spawn\n", "OS_PROCESS_MEMBER_ACQUISITION"),
    ("import os\nvalue = getattr(os, name)\n", "SENSITIVE_NAMESPACE_ESCAPE"),
    ("import os\nvalue = os.__dict__\n", "SENSITIVE_NAMESPACE_ESCAPE"),
    ("import os\nvalue = itemgetter(name)(vars(os))\n", "UNKNOWN_SENSITIVE_REFLECTION"),
])
def test_closed_policy_taxonomy_blocks_representative_acquisitions(tmp_path, source, expected_code):
    assert expected_code in {finding["code"] for finding in _analyze(tmp_path, source)}


@pytest.mark.parametrize(("source", "expected_code"), [
    (
        "from importlib import import_module\nimport_module(name)\n",
        "DYNAMIC_IMPORT_ACQUISITION",
    ),
    (
        "import importlib as i\ni.import_module(name)\n",
        "DYNAMIC_IMPORT_ACQUISITION",
    ),
    (
        "from builtins import eval as e\ne(payload)\n",
        "DYNAMIC_EXECUTION_ACQUISITION",
    ),
    (
        "import os as safe\nsafe.system('tool')\n",
        "OS_PROCESS_MEMBER_ACQUISITION",
    ),
    (
        "import pickle as serializer\nserializer.loads(payload)\n",
        "EXECUTABLE_DESERIALIZATION_OR_NATIVE_LOADING",
    ),
    (
        "import os as safe\nvalue = getattr(safe, name)\n",
        "SENSITIVE_NAMESPACE_ESCAPE",
    ),
    (
        "import sys as runtime\nruntime.meta_path = [finder]\n",
        "SENSITIVE_NAMESPACE_ESCAPE",
    ),
])
def test_sensitive_acquisition_aliases_remain_blocked(source, expected_code):
    assert expected_code in {
        finding["code"] for finding in analyze_source("scripts/target.py", source, policy_path=POLICY)
    }
