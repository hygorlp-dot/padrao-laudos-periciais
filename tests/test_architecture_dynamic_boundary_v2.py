import json
from pathlib import Path

from scripts.quality.architecture_analyzer import analyze_sources


ROOT = Path(__file__).parents[1]


def _policy():
    return json.loads((ROOT / "config/architecture-policy-v1.json").read_text(encoding="utf-8"))


def test_four_p1_findings_transfer_exactly_without_wildcard_or_severity_loss():
    registry = json.loads((ROOT / "config/architecture-capability-transfers-v2.json").read_text(encoding="utf-8"))
    assert registry["decisionId"] == "ARCHITECTURE_DYNAMIC_BOUNDARY_SEPARATION_V2"
    assert registry["originalHead"] == "9a7815adb6f9bf61dacfff5e9410c5a08307715d"
    assert registry["destinationAnalyzer"] == "CAPABILITY_ANALYZER_V1"
    assert registry["defaultPolicy"] == "DENY"
    assert registry["wildcardExceptionsAllowed"] is False
    assert {item["findingId"] for item in registry["findings"]} == {
        "PR50-HIGHER-ORDER-STRING-EXECUTION-BYPASS",
        "PR50-SYS-MODULES-RETRIEVAL-BYPASS",
        "PR50-IMPORT-HOOK-WRITE-BYPASS",
        "PR50-SYS-9A7815A-001",
    }
    assert all(item["classification"] == "DYNAMIC_CAPABILITY_MATERIAL" for item in registry["findings"])
    assert all(item["severity"] == "P1" and item["reproducers"] and item["closureCondition"] for item in registry["findings"])


def test_architecture_analyzer_does_not_interpret_arbitrary_dynamic_python():
    sources = {"scripts/a.py": "eval(payload)\n"}
    findings = analyze_sources(sources, _policy())["findings"]
    assert all(item["code"] != "DYNAMIC_ARCHITECTURE_BYPASS" for item in findings)


def test_static_architecture_boundary_remains_blocking():
    policy = _policy()
    policy["components"] = [
        {"id": "A", "layer": "DOMAIN", "paths": ["scripts/core/"], "allowedDependencies": []},
        {"id": "B", "layer": "GOVERNANCE", "paths": ["scripts/quality/"], "allowedDependencies": []},
        {"id": "ROOT", "layer": "DOMAIN", "paths": ["scripts/a.py"], "allowedDependencies": []},
    ]
    sources = {
        "scripts/a.py": "import scripts.missing\n",
        "scripts/core/a.py": "import scripts.quality.b\n",
        "scripts/quality/b.py": "import scripts.core.a\n",
    }
    codes = {item["code"] for item in analyze_sources(sources, policy)["findings"]}
    assert {"UNRESOLVED_FIRST_PARTY_IMPORT", "DISALLOWED_COMPONENT_DEPENDENCY", "ARCHITECTURE_CYCLE"} <= codes
