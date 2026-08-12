"""Fail-closed preparation of text for an external reviewer."""
from __future__ import annotations

import re
import hashlib

DENIED_EXTENSIONS = {".pdf", ".doc", ".docx", ".docm", ".zip", ".png", ".jpg", ".jpeg"}
PATTERNS = (
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
    safe = []
    reasons = []
    for item in files:
        path = str(item.get("path", "")).replace("\\", "/")
        content = item.get("content")
        suffix = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
        if not path or not isinstance(content, str):
            reasons.append("INVALID_CONTEXT_ITEM")
        elif path.startswith("referencias/privadas/") or suffix in DENIED_EXTENSIONS:
            reasons.append("PRIVATE_OR_BINARY_PATH")
        elif not (path in ALLOWED_FILES or path.startswith(ALLOWED_PREFIXES)):
            reasons.append("PATH_NOT_ALLOWLISTED")
        elif any(pattern.search(content) for pattern in PATTERNS):
            reasons.append("PII_OR_SECRET_DETECTED")
        else:
            safe.append({"path": path, "content": content, "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()})
    if reasons:
        return {"allowed": False, "files": [], "reasons": sorted(set(reasons))}
    return {"allowed": True, "files": safe, "reasons": []}
