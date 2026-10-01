"""Atribuicao temporal BASE x HEAD do gate completo (V7-4, decisao humana "2-III").

A duracao absoluta do `verify_core --full` depende do runner. Acima da referencia,
este modulo compara a duracao do HEAD com a da BASE medida no MESMO runner, logo em
seguida, e so bloqueia quando o delta material e atribuivel ao candidato.

O modulo nao executa processos: o workflow mede as duas execucoes e entrega os logs.
Qualquer evidencia ausente, duplicada, malformada ou nao finita falha fechada.

Comandos (codigos de saida):
- `requires-base --head-log H`: 0 = dentro da referencia; 3 = atribuicao exigida;
  1 = evidencia invalida.
- `decide --head-log H --base-log B --base-exit-code N --base-sha S`: 0 = sem
  regressao material; 1 = regressao material do candidato ou evidencia invalida.

A BASE so serve de referencia se for semanticamente valida: `RESULT: PASS` com
exit 0 e conjunto fechado de checks todo PASS, ou (politica antiga) uma falha
EXCLUSIVAMENTE temporal: exit 1, `TIMING_STATUS = FAIL` e unico check vermelho
`quality non-regression`, com todo finding `FULL_GATE_DURATION_REGRESSION`.
Qualquer outra BASE (semantica vermelha, relatorio incompleto, exit code
incoerente) e INVALID: ela poderia elevar o limite do candidato.
"""
from __future__ import annotations

import argparse
import math
import re
from pathlib import Path

from .metrics import TIMING_STATUS_ATTRIBUTION_REQUIRED

# Regra autorizada pela decisao humana na #109: o delta do candidato e material
# quando excede max(60 s, BASE * 0.10). O piso absoluto absorve a variancia de
# runner de uma amostra unica, que sozinha passa de 10% no mesmo tree.
MATERIAL_FRACTION = 0.10
MATERIAL_MIN_SECONDS = 60.0
EXIT_WITHIN_REFERENCE = 0
EXIT_INVALID = 1
EXIT_ATTRIBUTION_REQUIRED = 3

_LINE = re.compile(r"^(TARGET_SECONDS|OBSERVED_SECONDS|TIMING_STATUS) = (.+?)\s*$")
_CHECK = re.compile(r"^\[(PASS|FAIL)\] (.+?)\s*$")
_RESULT = re.compile(r"^RESULT: (.+?)\s*$")
# Conjunto fechado de checks impresso por `verify_core --full` (ordem incluida).
GATE_CHECKS = (
    "invariants", "fixtures", "privacy", "property tests", "gate tests", "compileall",
    "historical critical mutation suite", "quality V2", "schemas", "E2E positive",
    "E2E negative", "capability cutover tests", "regression", "coverage report",
    "diff check", "quality non-regression",
)
_TIMING_ONLY_FINDING = ("QUALITY_NON_REGRESSION", "QUALITY_GATE", "FULL_GATE_DURATION_REGRESSION")
_SHA = re.compile(r"[0-9a-f]{40}")


class TimingEvidenceError(ValueError):
    pass


# Da BASE so importa a duracao medida. Uma BASE anterior a esta politica ainda
# imprime os status historicos (PR_ADVISORY/STRICT); INVALID nunca e aceito.
_HEAD_STATUSES = frozenset({"PASS", TIMING_STATUS_ATTRIBUTION_REQUIRED})
_BASE_STATUSES = _HEAD_STATUSES | {"WARNING", "FAIL"}


def parse_timing(text: str, *, allowed_statuses: frozenset[str] = _HEAD_STATUSES) -> dict[str, object]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        match = _LINE.match(line.strip())
        if match is None:
            continue
        if match.group(1) in values:
            raise TimingEvidenceError(f"duplicated {match.group(1)}")
        values[match.group(1)] = match.group(2)
    if set(values) != {"TARGET_SECONDS", "OBSERVED_SECONDS", "TIMING_STATUS"}:
        raise TimingEvidenceError("incomplete timing evidence")
    try:
        target = float(values["TARGET_SECONDS"])
        observed = float(values["OBSERVED_SECONDS"])
    except ValueError as exc:
        raise TimingEvidenceError("non-numeric timing evidence") from exc
    if not (math.isfinite(target) and math.isfinite(observed)) or target <= 0 or observed < 0:
        raise TimingEvidenceError("non-finite timing evidence")
    status = values["TIMING_STATUS"]
    if status not in allowed_statuses:
        raise TimingEvidenceError(f"unknown timing status {status!r}")
    return {"target": target, "observed": observed, "status": status}


def validate_base_semantics(text: str, exit_code: int) -> None:
    """Falha fechada se a BASE nao e semanticamente valida como referencia."""
    lines = [line.rstrip() for line in text.splitlines()]
    checks = [(m.group(2), m.group(1) == "PASS") for m in map(_CHECK.match, lines) if m]
    results = [m.group(1) for m in map(_RESULT.match, lines) if m]
    if tuple(name for name, _ok in checks) != GATE_CHECKS:
        raise TimingEvidenceError("BASE check set is not the closed verify_core --full set")
    if len(results) != 1:
        raise TimingEvidenceError("BASE report must carry exactly one RESULT")
    result = results[0]
    after = lines[next(i for i, line in enumerate(lines) if _RESULT.match(line)) + 1:]
    end = next((i for i, line in enumerate(after) if line.startswith("DURATION_SECONDS:")), None)
    if end is None:
        raise TimingEvidenceError("BASE report has no DURATION_SECONDS after RESULT")
    findings = [line for line in after[:end] if line]
    failing = [name for name, ok in checks if not ok]
    status = parse_timing(text, allowed_statuses=_BASE_STATUSES)["status"]
    if result == "PASS":
        if exit_code != 0 or failing or findings or status == "FAIL":
            raise TimingEvidenceError("BASE PASS report is incoherent with its exit code or findings")
        return
    if result != "FAIL" or exit_code != 1:
        raise TimingEvidenceError("BASE failed or reported an unknown result")
    timing_only = (
        failing == ["quality non-regression"]
        and status == "FAIL"
        and bool(findings)
        and all(tuple(part.strip() for part in finding.split(" | "))[:3] == _TIMING_ONLY_FINDING
                and len(finding.split(" | ")) == 5 for finding in findings)
    )
    if not timing_only:
        raise TimingEvidenceError("BASE failed semantically; it cannot be a timing reference")


def decide(head: dict[str, object], base: dict[str, object]) -> dict[str, object]:
    head_seconds = float(head["observed"])
    base_seconds = float(base["observed"])
    if base_seconds <= 0:
        raise TimingEvidenceError("BASE timing evidence is empty")
    threshold = max(MATERIAL_MIN_SECONDS, base_seconds * MATERIAL_FRACTION)
    delta = head_seconds - base_seconds
    return {
        "head_seconds": head_seconds,
        "base_seconds": base_seconds,
        "delta_seconds": round(delta, 3),
        "material_threshold_seconds": round(threshold, 3),
        "material_limit_seconds": round(base_seconds + threshold, 3),
        "candidate_regression": delta > threshold,
    }


def _read(path: str, *, allowed_statuses: frozenset[str] = _HEAD_STATUSES) -> dict[str, object]:
    return parse_timing(Path(path).read_text(encoding="utf-8", errors="replace"), allowed_statuses=allowed_statuses)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    requires = commands.add_parser("requires-base")
    requires.add_argument("--head-log", required=True)
    decision = commands.add_parser("decide")
    decision.add_argument("--head-log", required=True)
    decision.add_argument("--base-log", required=True)
    decision.add_argument("--base-exit-code", required=True)
    decision.add_argument("--base-sha", required=True)
    args = parser.parse_args(argv)
    try:
        head = _read(args.head_log)
        if args.command == "requires-base":
            required = head["status"] == TIMING_STATUS_ATTRIBUTION_REQUIRED
            print(f"TIMING_ATTRIBUTION = {'REQUIRED' if required else 'NOT_REQUIRED'}")
            return EXIT_ATTRIBUTION_REQUIRED if required else EXIT_WITHIN_REFERENCE
        if _SHA.fullmatch(args.base_sha) is None:
            raise TimingEvidenceError("BASE SHA is not an exact commit")
        if head["status"] != TIMING_STATUS_ATTRIBUTION_REQUIRED:
            raise TimingEvidenceError("attribution requested for HEAD within reference")
        try:
            base_exit = int(args.base_exit_code)
        except ValueError as exc:
            raise TimingEvidenceError("BASE exit code is not an integer") from exc
        base_text = Path(args.base_log).read_text(encoding="utf-8", errors="replace")
        validate_base_semantics(base_text, base_exit)
        result = decide(head, parse_timing(base_text, allowed_statuses=_BASE_STATUSES))
    except (OSError, TimingEvidenceError) as exc:
        print(f"TIMING_ATTRIBUTION = INVALID ({exc})")
        return EXIT_INVALID
    print(f"BASE_SHA = {args.base_sha}")
    for key in ("head_seconds", "base_seconds", "delta_seconds", "material_threshold_seconds", "material_limit_seconds"):
        print(f"{key.upper()} = {result[key]}")
    if result["candidate_regression"]:
        print("TIMING_ATTRIBUTION = CANDIDATE_REGRESSION")
        return EXIT_INVALID
    print("TIMING_ATTRIBUTION = NO_MATERIAL_CANDIDATE_REGRESSION")
    return EXIT_WITHIN_REFERENCE


if __name__ == "__main__":
    raise SystemExit(main())
