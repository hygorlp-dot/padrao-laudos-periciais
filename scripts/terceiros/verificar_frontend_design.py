"""Verifica offline a cópia pinada da skill oficial Frontend Design."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "docs" / "terceiros" / "frontend-design-blobs.json"
EXPECTED_MANIFEST = {
    "name": "Frontend Design",
    "repo": "https://github.com/anthropics/claude-plugins-official",
    "commit": "67a666efc8524ff7abaa266f84e514aa77aee48f",
    "upstream_path": "plugins/frontend-design/skills/frontend-design",
    "license": "Apache-2.0",
    "retrieval_date": "2026-08-21",
    "mode": "THIRD_PARTY_SKILL_PINNED_BYTE_EXACT",
    "destination": ".agents/skills/frontend-design",
    "local_modifications": "NONE",
    "first_party_precedence": [
        "AGENTS.md",
        ".agents/skills/ui-pericial/SKILL.md",
    ],
    "blobs": {
        "LICENSE.txt": "f433b1a53f5b830a205fd2df78e2b34974656c7b",
        "SKILL.md": "decdff43d05908b4c1fc2cfd2d80fc5743440934",
    },
}


def _blob(path: Path) -> str:
    content = path.read_bytes()
    git_object = f"blob {len(content)}\0".encode("ascii") + content
    return hashlib.sha1(git_object, usedforsecurity=False).hexdigest()


def verificar() -> list[str]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    errors: list[str] = []
    if manifest != EXPECTED_MANIFEST:
        errors.append("manifesto divergente do contrato pinado")
    destination = ROOT / EXPECTED_MANIFEST["destination"]
    expected = set(EXPECTED_MANIFEST["blobs"])
    actual = {
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file()
    }
    if actual != expected:
        errors.append(
            f"arquivos divergentes: esperados={sorted(expected)} atuais={sorted(actual)}"
        )
    for relative, expected_blob in EXPECTED_MANIFEST["blobs"].items():
        path = destination / relative
        if path.is_file() and _blob(path) != expected_blob:
            errors.append(f"blob divergente: {relative}")
    link_pattern = re.compile(r"\[[^\]]+\]\(([^)#]+)(?:#[^)]+)?\)")
    for path in destination.rglob("*.md"):
        for target in link_pattern.findall(path.read_text(encoding="utf-8")):
            if not target.startswith(("http://", "https://", "mailto:")) and not (
                path.parent / target
            ).exists():
                errors.append(
                    f"referência quebrada: {path.relative_to(destination)} -> {target}"
                )
    return errors


if __name__ == "__main__":
    failures = verificar()
    if failures:
        raise SystemExit("\n".join(failures))
    print("FRONTEND_DESIGN_INTEGRITY=100%")
