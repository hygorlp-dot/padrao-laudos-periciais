from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_gitleaks_wrapper_is_pinned_verified_redacted_and_dual_mode():
    wrapper = (ROOT / "scripts/quality/run_gitleaks.ps1").read_text(encoding="utf-8")

    assert 'Version = "8.30.1"' in wrapper
    assert "d29144deff3a68aa93ced33dddf84b7fdc26070add4aa0f4513094c8332afc4e" in wrapper
    assert "gitleaks_$Version`_windows_x64.zip" in wrapper
    assert "Get-FileHash" in wrapper
    assert '"dir"' in wrapper
    assert '"git"' in wrapper
    assert '"--log-opts=--all"' in wrapper
    assert '"--redact=100"' in wrapper
    assert "Remove-Item" in wrapper
    assert "latest" not in wrapper.casefold()


def test_gitleaks_config_extends_defaults_and_has_first_party_privacy_rules():
    config = (ROOT / ".gitleaks.toml").read_text(encoding="utf-8")

    assert "useDefault = true" in config
    assert 'id = "private-reference-path"' in config
    assert 'id = "real-case-fixture-derivation"' in config
    assert "referencias" in config
    assert "REAL_CASE_DERIVED" in config


def test_lint_workflow_keeps_gitleaks_advisory_and_fetches_reachable_history():
    workflow = (ROOT / ".github/workflows/lint.yml").read_text(encoding="utf-8")

    assert "fetch-depth: 0" in workflow
    assert "run_gitleaks.ps1 -Advisory" in workflow
    assert "continue-on-error: true" in workflow
