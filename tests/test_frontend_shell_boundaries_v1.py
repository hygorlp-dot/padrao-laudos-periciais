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


def test_frontend_production_source_has_no_secret_or_unbounded_network_capability():
    forbidden = re.compile(
        r"\b(?:XMLHttpRequest|WebSocket|EventSource)\s*\(|"
        r"navigator\.sendBeacon|X-Local-API-Token|Bearer\s|https?://|"
        r"localStorage|sessionStorage|indexedDB|api[_-]?key",
        re.IGNORECASE,
    )

    fetch_sources = []
    for source in production_sources():
        text = source.read_text(encoding="utf-8")
        assert not forbidden.search(text), source
        if re.search(r"\bfetch\s*\(", text):
            fetch_sources.append(source.relative_to(ROOT).as_posix())

    assert sorted(fetch_sources) == [
        "frontend/src/data/processCase.ts",
        "frontend/src/data/workspaces.ts",
    ]


def test_frontend_runtime_dependencies_stay_minimal():
    package = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))

    assert set(package["dependencies"]) == {"react", "react-dom"}


def _relative_luminance(hex_color):
    channels = [int(hex_color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        channel / 12.92
        if channel <= 0.04045
        else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def test_sidebar_focus_indicator_has_non_text_contrast():
    tokens = (SOURCE / "styles" / "tokens.css").read_text(encoding="utf-8")
    shell = (SOURCE / "styles" / "shell.css").read_text(encoding="utf-8")
    focus = re.search(r"--color-focus-on-dark:\s*(#[0-9a-f]{6})", tokens)
    background = re.search(r"--color-graphite:\s*(#[0-9a-f]{6})", tokens)

    assert focus, "a dark-surface focus token is required"
    assert background
    assert ".workflow-link:focus-visible" in shell
    lighter = max(_relative_luminance(focus.group(1)), _relative_luminance(background.group(1)))
    darker = min(_relative_luminance(focus.group(1)), _relative_luminance(background.group(1)))
    assert (lighter + 0.05) / (darker + 0.05) >= 3


def test_persisted_workspace_names_cannot_force_shell_overflow():
    shell = (SOURCE / "styles" / "shell.css").read_text(encoding="utf-8")

    assert re.search(
        r"\.workspace-list li > div\s*\{[^}]*min-width:\s*0",
        shell,
        re.DOTALL,
    )
    assert re.search(
        r"\.workspace-list strong,[^{]*\.topbar strong,[^{]*\.sidebar-note\s*"
        r"\{[^}]*overflow-wrap:\s*anywhere",
        shell,
        re.DOTALL,
    )


def test_frontend_shell_does_not_infer_an_unauthorized_product_brand():
    fixed_surfaces = (
        ROOT / "PRODUCT.md",
        ROOT / "DESIGN.md",
        ROOT / ".impeccable" / "design.json",
        ROOT / "docs" / "superpowers" / "plans" / "2026-08-23-frontend-shell-v1.md",
    )
    frontend_surfaces = production_sources() + tuple(
        FRONTEND / relative
        for relative in (
            "eslint.config.js",
            "index.html",
            "package-lock.json",
            "package.json",
            "tsconfig.app.json",
            "tsconfig.json",
            "tsconfig.node.json",
            "vite.config.ts",
        )
    )

    for surface in (*fixed_surfaces, *frontend_surfaces):
        assert not re.search(r"\barcd\b", surface.read_text(encoding="utf-8"), re.IGNORECASE), surface
