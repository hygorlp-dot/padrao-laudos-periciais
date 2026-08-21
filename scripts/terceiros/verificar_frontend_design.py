"""Verifica offline a cópia pinada da skill oficial Frontend Design."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "docs" / "terceiros" / "frontend-design-blobs.json"


def _blob(path: Path) -> str:
    return subprocess.check_output(
        ["git", "hash-object", "--", str(path)], text=True
    ).strip()


def verificar() -> list[str]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    destination = ROOT / manifest["destination"]
    errors: list[str] = []
    expected = set(manifest["blobs"])
    actual = {
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file()
    }
    if actual != expected:
        errors.append(
            f"arquivos divergentes: esperados={sorted(expected)} atuais={sorted(actual)}"
        )
    for relative, expected_blob in manifest["blobs"].items():
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
