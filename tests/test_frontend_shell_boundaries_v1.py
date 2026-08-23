import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
SOURCE = FRONTEND / "src"


def production_sources():
    return tuple(
        path
        for path in SOURCE.rglob("*")
        if path.suffix in {".ts", ".tsx"}
        and ".test." not in path.name
        and "test" not in path.parts
    )


def test_frontend_production_source_is_present_and_confined_to_ui():
    sources = production_sources()

    assert sources, "frontend production source is missing"
    forbidden_imports = re.compile(
        r"(?:from\s+|import\s*\()[\"'][^\"']*"
        r"(?:scripts|backend_contract|infrastructure|sqlite|local_api)",
        re.IGNORECASE,
    )
    for source in sources:
        assert not forbidden_imports.search(source.read_text(encoding="utf-8")), source


def test_frontend_production_source_has_no_secret_or_network_capability():
    forbidden = re.compile(
        r"\b(?:fetch|XMLHttpRequest|WebSocket|EventSource)\s*\(|"
        r"navigator\.sendBeacon|X-Local-API-Token|Bearer\s|"
        r"localStorage|sessionStorage|indexedDB|api[_-]?key",
        re.IGNORECASE,
    )

    for source in production_sources():
        assert not forbidden.search(source.read_text(encoding="utf-8")), source


def test_frontend_runtime_dependencies_stay_minimal():
    package = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))

    assert set(package["dependencies"]) == {"react", "react-dom"}
