"""Verifica offline as Skills de terceiros pinadas da PROFESSIONAL_UX_V1 (#276).

Mesmo contrato de `verificar_frontend_design.py`: cópia pinada por commit,
conjunto de arquivos fechado e blob Git de cada arquivo conferido sem rede e sem
processo. O próprio manifesto é pinado por SHA-256: mudar um blob, um commit ou
uma licença exige mudar este verificador na mesma revisão.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "docs" / "terceiros" / "professional-ux-v1-blobs.json"
ROUTER = ROOT / ".agents" / "skill-router.json"
MANIFEST_SHA256 = "3e2743718d9835748ad24710c1c6f333b07f515d3ac6c8aef2fcd7e70063ab7d"
PINNED_COMMITS = {
    "https://github.com/vercel-labs/agent-skills": "063bee94c3f4df8453406c830b0a7df0f2860278",
    "https://github.com/vercel-labs/skills": "18f96ea131dab3b0fcc9b27cf7c6f6cbb6174680",
    "https://github.com/microsoft/playwright-cli": "b85c7a736bb473bf55b584e54a09ffa698d6d871",
}
EXECUTABLE_SUFFIXES = {".py", ".js", ".cjs", ".mjs", ".ts", ".sh", ".ps1", ".exe", ".bat", ".cmd"}
NETWORK_SKILLS = {"find-skills", "web-design-guidelines"}


def _blob(path: Path) -> str:
    content = path.read_bytes()
    git_object = f"blob {len(content)}\0".encode("ascii") + content
    return hashlib.sha1(git_object, usedforsecurity=False).hexdigest()


def _routable(router: dict) -> set[str]:
    skills = set(router.get("material_bundle", []))
    for profile in router.get("profiles", {}).values():
        skills.update(profile.get("required", []))
        for selected in profile.get("conditional", {}).values():
            skills.update(selected)
    return skills


def verificar(root: Path | None = None) -> list[str]:
    base = ROOT if root is None else Path(root)
    manifest_path = base / MANIFEST.relative_to(ROOT)
    errors: list[str] = []
    try:
        raw = manifest_path.read_bytes()
    except OSError:
        return ["MANIFEST ausente"]
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        errors.append("MANIFEST divergente do contrato pinado")
    manifest = json.loads(raw.decode("utf-8"))
    for entry in manifest.get("skills", []):
        name = entry.get("name", "?")
        if PINNED_COMMITS.get(entry.get("repo")) != entry.get("commit"):
            errors.append(f"COMMIT {name}")
        destination = base / entry["destination"]
        expected = set(entry.get("blobs", {}))
        actual = {path.relative_to(destination).as_posix() for path in destination.rglob("*") if path.is_file()}
        if actual != expected:
            errors.append(f"FILE_SET {name} esperados={sorted(expected)} atuais={sorted(actual)}")
        for relative, expected_blob in entry.get("blobs", {}).items():
            path = destination / relative
            if not path.is_file() or _blob(path) != expected_blob:
                errors.append(f"BLOB {name}/{relative}")
            if path.suffix.lower() in EXECUTABLE_SUFFIXES:
                errors.append(f"EXECUTABLE {name}/{relative}")
        if "license_file" in entry:
            license_path = base / entry["license_file"]
            if not license_path.is_file() or _blob(license_path) != entry.get("license_blob"):
                errors.append(f"LICENSE {name}")
    try:
        router = json.loads((base / ROUTER.relative_to(ROOT)).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        errors.append("ROUTER ilegível")
    else:
        for name in sorted(NETWORK_SKILLS & _routable(router)):
            errors.append(f"NETWORK_SKILL_ROUTED {name}")
        for name in sorted(NETWORK_SKILLS - set(router.get("reference_only", []))):
            errors.append(f"NETWORK_SKILL_NOT_REFERENCE_ONLY {name}")
    return errors


if __name__ == "__main__":
    failures = verificar()
    if failures:
        raise SystemExit("PROFESSIONAL_UX_SKILLS_INTEGRITY_FAILED\n" + "\n".join(failures))
    print("PROFESSIONAL_UX_SKILLS_INTEGRITY=100%")
