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
ALLOWED_PREFIXES = (
    "scripts/agentic/", "tests/test_agentic_", "schemas/review-",
    "docs/padroes/protocolo-", "docs/arquitetura/decisoes/ADR-",
    ".agents/skills/reviewer-independente/", ".agents/skills/systemic-auditor/",
    ".agents/skills/external-diversity-review/", "config/core-",
)
ALLOWED_FILES = {"AGENTS.md"}


def sanitize_external_context(files: list[dict], *, expected_head: str | None = None) -> dict:
    root = ROOT
    actual_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if expected_head is not None and expected_head != actual_head:
        return {"allowed": False, "files": [], "reasons": ["HEAD_MISMATCH"], "head_sha": actual_head}
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
            try:
                committed = subprocess.check_output(
                    ["git", "show", f"{actual_head}:{path}"], cwd=root, text=True,
                    encoding="utf-8", errors="strict",
                )
            except (subprocess.CalledProcessError, UnicodeError):
                reasons.append("HEAD_BLOB_NOT_AVAILABLE")
                continue
            actual = source.read_text(encoding="utf-8")
            if actual != content or committed != content:
                reasons.append("CONTENT_NOT_BOUND_TO_SOURCE")
                continue
            # External packages receive only an exact-HEAD manifest.  Raw file
            # bytes stay in the isolated checkout and are never copied into an
            # egress payload, avoiding lexical PII-detection as a trust claim.
            safe.append({
                "path_sha256": hashlib.sha256(path.encode("utf-8")).hexdigest(),
                "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            })
    if reasons:
        return {"allowed": False, "files": [], "reasons": sorted(set(reasons)), "head_sha": actual_head}
    return {"allowed": True, "files": safe, "reasons": [], "head_sha": actual_head}
