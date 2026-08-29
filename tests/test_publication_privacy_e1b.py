from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.quality import publication_privacy
from scripts.quality.publication_privacy import scan_current_tree, scan_reachable_history


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    )
    return completed.stdout.strip()


def _repository(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "synthetic@example.invalid")
    _git(root, "config", "user.name", "Synthetic Test")


def _commit(root: Path, message: str) -> str:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)
    return _git(root, "rev-parse", "HEAD")


def test_current_tree_rejects_tracked_private_reference_without_reading_it(tmp_path):
    _repository(tmp_path)
    private = tmp_path / "referencias/privadas/synthetic-marker.txt"
    private.parent.mkdir(parents=True)
    private.write_text("must-not-appear-in-finding", encoding="utf-8")
    _commit(tmp_path, "synthetic private path")

    findings = scan_current_tree(tmp_path, runner=subprocess.run)

    assert {item["rule"] for item in findings} == {"PRIVATE_PATH_TRACKED"}
    assert all("must-not-appear" not in str(item) for item in findings)


def test_current_tree_rejects_real_case_fixture_derivation_marker(tmp_path):
    _repository(tmp_path)
    fixture = tmp_path / "tests/fixtures/case.json"
    fixture.parent.mkdir(parents=True)
    fixture.write_text('{"fixture_origin":"REAL_CASE_DERIVED"}', encoding="utf-8")
    _commit(tmp_path, "synthetic forbidden provenance")

    findings = scan_current_tree(tmp_path, runner=subprocess.run)

    assert {item["rule"] for item in findings} == {"REAL_CASE_FIXTURE_DERIVATION"}
    assert all("REAL_CASE_DERIVED" not in str(item) for item in findings)


def test_current_tree_accepts_explicitly_synthetic_fixture(tmp_path):
    _repository(tmp_path)
    fixture = tmp_path / "tests/fixtures/case.json"
    fixture.parent.mkdir(parents=True)
    fixture.write_text('{"fixture_origin":"SYNTHETIC"}', encoding="utf-8")
    _commit(tmp_path, "synthetic fixture")

    assert scan_current_tree(tmp_path, runner=subprocess.run) == []


def test_reachable_history_detects_deleted_forbidden_fixture_without_content(tmp_path):
    _repository(tmp_path)
    fixture = tmp_path / "tests/fixtures/deleted.json"
    fixture.parent.mkdir(parents=True)
    fixture.write_text('{"fixture_origin":"REAL_CASE_DERIVED"}', encoding="utf-8")
    introducing_commit = _commit(tmp_path, "synthetic history violation")
    fixture.unlink()
    _commit(tmp_path, "remove synthetic violation")

    findings = scan_reachable_history(tmp_path, runner=subprocess.run)

    assert any(
        item["rule"] == "REAL_CASE_FIXTURE_DERIVATION"
        and item["commit"] == introducing_commit
        for item in findings
    )
    assert all("REAL_CASE_DERIVED" not in str(item) for item in findings)


def test_reachable_history_scans_non_default_reachable_branch(tmp_path):
    _repository(tmp_path)
    (tmp_path / "README.md").write_text("synthetic", encoding="utf-8")
    _commit(tmp_path, "base")
    _git(tmp_path, "switch", "-q", "-c", "synthetic-branch")
    private = tmp_path / "referencias/privadas/branch.txt"
    private.parent.mkdir(parents=True)
    private.write_text("synthetic", encoding="utf-8")
    branch_commit = _commit(tmp_path, "synthetic branch violation")
    _git(tmp_path, "switch", "-q", "master")

    findings = scan_reachable_history(tmp_path, runner=subprocess.run)

    assert any(
        item["rule"] == "PRIVATE_PATH_TRACKED" and item["commit"] == branch_commit
        for item in findings
    )


def test_reachable_history_ignores_unreachable_objects(tmp_path):
    _repository(tmp_path)
    (tmp_path / "README.md").write_text("synthetic", encoding="utf-8")
    base = _commit(tmp_path, "base")
    _git(tmp_path, "switch", "-q", "--detach")
    fixture = tmp_path / "tests/fixtures/unreachable.json"
    fixture.parent.mkdir(parents=True)
    fixture.write_text('{"fixture_origin":"REAL_CASE_DERIVED"}', encoding="utf-8")
    _commit(tmp_path, "unreachable synthetic violation")
    _git(tmp_path, "reset", "-q", "--hard", base)

    assert scan_reachable_history(tmp_path, runner=subprocess.run) == []


def test_reachable_history_fails_closed_when_historical_blob_cannot_be_read(monkeypatch, tmp_path):
    commit = "a" * 40
    calls = iter((
        subprocess.CompletedProcess([], 0, b"\x1e" + commit.encode() + b"\0tests/fixtures/case.json\0", b""),
        subprocess.CompletedProcess([], 128, b"", b"synthetic unreadable blob"),
    ))
    monkeypatch.setattr(publication_privacy, "_git", lambda *_args, **_kwargs: next(calls))

    findings = scan_reachable_history(tmp_path, runner=subprocess.run)

    assert len(findings) == 1
    assert findings[0]["rule"] == "GIT_SCAN_UNAVAILABLE"
    assert findings[0]["severidade"] == "P0"
    assert "synthetic unreadable blob" not in str(findings[0])
