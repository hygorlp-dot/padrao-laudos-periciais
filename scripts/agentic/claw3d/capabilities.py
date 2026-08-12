"""Fail-closed discovery of supported local Codex invocation capabilities."""
from __future__ import annotations
import subprocess
from dataclasses import dataclass

@dataclass(frozen=True)
class CodexCapability:
    available: bool
    version: str | None
    non_interactive: bool
    command: tuple[str, ...] | None

def detect_codex_capability(*, executable: str = "codex") -> CodexCapability:
    try:
        version = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=10, check=False)
        help_result = subprocess.run([executable, "--help"], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return CodexCapability(False, None, False, None)
    if version.returncode != 0 or help_result.returncode != 0:
        return CodexCapability(False, None, False, None)
    non_interactive = "exec" in f"{help_result.stdout}\n{help_result.stderr}".casefold()
    return CodexCapability(True, version.stdout.strip() or version.stderr.strip(), non_interactive,
                           (executable, "exec") if non_interactive else None)
