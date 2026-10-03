"""Product maturity declaration versus the live repository HEAD.

`config/product-maturity-v1.json` is a tracked DECLARATION. Its
`evidence_base_sha` names the commit whose fresh post-main evidence (CI and
oracle) supports the declaration. A tracked file can never carry the SHA of
the commit that contains it, so the live HEAD is never stored: it is read from
`.git` when this command runs.

    python -m scripts.quality.product_maturity

answers three questions without self-reference:
- which commit was validated (`evidence_base_sha`);
- which commit is HEAD now (`observed_repository_head`, live);
- whether the declaration was validated on this exact HEAD
  (`CURRENT_EVIDENCE`) or is evidence from an earlier commit
  (`HISTORICAL_EVIDENCE`).
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from .git_worktree import GitWorktreeError, live_head

ROOT = Path(__file__).resolve().parents[2]
DECLARATION = Path("config/product-maturity-v1.json")
EVIDENCE_SEMANTICS = "HISTORICAL_VALIDATED_COMMIT_NOT_LIVE_HEAD"
FORBIDDEN_KEYS = ("current_main_sha", "current_head_sha", "live_head")
CURRENT_EVIDENCE = "CURRENT_EVIDENCE"
HISTORICAL_EVIDENCE = "HISTORICAL_EVIDENCE"
LIVE_HEAD_UNAVAILABLE = "LIVE_HEAD_UNAVAILABLE"


def contract_errors(declaration: dict) -> list[str]:
    """Violations of the non-self-referential contract of the tracked file."""
    errors = [f"forbidden live-state key: {key}" for key in FORBIDDEN_KEYS if key in declaration]
    evidence = declaration.get("evidence_base_sha")
    if not isinstance(evidence, str) or not re.fullmatch(r"[0-9a-f]{40}", evidence):
        errors.append("evidence_base_sha must be a full commit SHA")
    if declaration.get("evidence_base_semantics") != EVIDENCE_SEMANTICS:
        errors.append(f"evidence_base_semantics must be {EVIDENCE_SEMANTICS}")
    return errors


def evaluate(declaration: dict, head: str | None) -> dict:
    errors = contract_errors(declaration)
    evidence = declaration.get("evidence_base_sha")
    if head is None:
        status = LIVE_HEAD_UNAVAILABLE
    elif head == evidence:
        status = CURRENT_EVIDENCE
    else:
        status = HISTORICAL_EVIDENCE
    return {
        "report": "PRODUCT_MATURITY_LIVE_STATUS_V1",
        "evidence_base_sha": evidence,
        "observed_repository_head": head,
        "declaration_status": status,
        "contract_errors": errors,
    }


def live_status(root: Path = ROOT) -> dict:
    declaration = json.loads((root / DECLARATION).read_text(encoding="utf-8"))
    try:
        head = live_head(root)
    except (GitWorktreeError, OSError):
        head = None
    return evaluate(declaration, head)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT)
    arguments = parser.parse_args(argv)
    result = live_status(arguments.root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result["contract_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
