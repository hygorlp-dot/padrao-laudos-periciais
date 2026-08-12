"""Fail-closed preparation of text for an external reviewer."""
from __future__ import annotations

import re
import hashlib
import subprocess
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]

DENIED_EXTENSIONS = {".pdf", ".doc", ".docx", ".docm", ".zip", ".png", ".jpg", ".jpeg"}
PATTERNS = (
    re.compile(r"(?i)\b(?:requerente|requerido|autor(?:a)?|reu|proprietari[oa])\b[^\n]{0,120}\b(?:imovel|lide|processo|parte)\b"),
    re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"),
    re.compile(r"\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b"),
    re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"\b(?:ghp_|github_pat_|sk-)[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\(\d{2}\)\s*\d{4,5}-\d{4}"),
    re.compile(r"(?i)\b(?:endere[cç]o|rua|avenida|travessa)\b[^\n]{0,80}\d+"),
    re.compile(r"(?i)\b(?:peti[cç][aã]o inicial|dados das partes|autos do processo)\b"),
)
ALLOWED_PREFIXES = ("scripts/", "tests/", "schemas/", "docs/", ".agents/", "config/", ".github/")
ALLOWED_FILES = {"AGENTS.md", "README.md", "requirements.txt", "requirements-dev.txt"}


def sanitize_external_context(files: list[dict]) -> dict:
    root = ROOT
    safe = []
    reasons = []
    for item in files:
        raw_path = str(item.get("path", "")).replace("\\", "/")
        candidate = PurePosixPath(raw_path)
        unsafe_path = candidate.is_absolute() or ".." in candidate.parts
        path = candidate.as_posix()
        content = item.get("content")
        suffix = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
        if unsafe_path:
            reasons.append("UNSAFE_PATH")
        elif not path or not isinstance(content, str):
            reasons.append("INVALID_CONTEXT_ITEM")
        elif path.casefold().startswith("referencias/privadas/") or suffix in DENIED_EXTENSIONS:
            reasons.append("PRIVATE_OR_BINARY_PATH")
        elif not (path in ALLOWED_FILES or path.startswith(ALLOWED_PREFIXES)):
            reasons.append("PATH_NOT_ALLOWLISTED")
        elif any(pattern.search(content) for pattern in PATTERNS):
            reasons.append("PII_OR_SECRET_DETECTED")
        else:
            source = (root / path).resolve()
            try:
                source.relative_to(root.resolve())
            except ValueError:
                reasons.append("PATH_OUTSIDE_REPOSITORY")
                continue
            if not source.is_file():
                reasons.append("SOURCE_NOT_FOUND")
                continue
            tracked = subprocess.run(
                ["git", "ls-files", "--error-unmatch", "--", path], cwd=root,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            if tracked.returncode != 0:
                reasons.append("SOURCE_NOT_TRACKED")
                continue
            actual = source.read_text(encoding="utf-8")
            if actual != content:
                reasons.append("CONTENT_NOT_BOUND_TO_SOURCE")
                continue
            safe.append({"path": path, "content": content, "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()})
    if reasons:
        return {"allowed": False, "files": [], "reasons": sorted(set(reasons))}
    return {"allowed": True, "files": safe, "reasons": []}
