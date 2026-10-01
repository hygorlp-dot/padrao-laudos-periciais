"""Atribuicao temporal BASE x HEAD do gate completo (V7-4, decisao humana "2-III").

A duracao absoluta do `verify_core --full` depende do runner. Acima da referencia,
este modulo compara a duracao do HEAD com a da BASE medida no MESMO runner, logo em
seguida, e so bloqueia quando o delta material e atribuivel ao candidato.

O modulo nao executa processos: o workflow mede as duas execucoes e entrega os logs.
Qualquer evidencia ausente, duplicada, malformada ou nao finita falha fechada.

Comandos (codigos de saida):
- `requires-base --head-log H`: 0 = dentro da referencia; 3 = atribuicao exigida;
  1 = evidencia invalida.
- `decide --head-log H --base-log B --base-sha S`: 0 = sem regressao material;
  1 = regressao material do candidato ou evidencia invalida.
"""
from __future__ import annotations

import argparse
import math
import re
from pathlib import Path

from .metrics import TIMING_STATUS_ATTRIBUTION_REQUIRED

# Delta relativo a partir do qual o aumento de duracao e material e atribuido ao
# candidato (mesmo criterio de 10% do desenho pareado da #109).
MATERIAL_FRACTION = 0.10
EXIT_WITHIN_REFERENCE = 0
EXIT_INVALID = 1
EXIT_ATTRIBUTION_REQUIRED = 3

_LINE = re.compile(r"^(TARGET_SECONDS|OBSERVED_SECONDS|TIMING_STATUS) = (.+?)\s*$")
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


def decide(head: dict[str, object], base: dict[str, object]) -> dict[str, object]:
    head_seconds = float(head["observed"])
    base_seconds = float(base["observed"])
    if base_seconds <= 0:
        raise TimingEvidenceError("BASE timing evidence is empty")
    limit = base_seconds * (1 + MATERIAL_FRACTION)
    return {
        "head_seconds": head_seconds,
        "base_seconds": base_seconds,
        "delta_seconds": round(head_seconds - base_seconds, 3),
        "material_limit_seconds": round(limit, 3),
        "candidate_regression": head_seconds > limit,
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
        result = decide(head, _read(args.base_log, allowed_statuses=_BASE_STATUSES))
    except (OSError, TimingEvidenceError) as exc:
        print(f"TIMING_ATTRIBUTION = INVALID ({exc})")
        return EXIT_INVALID
    print(f"BASE_SHA = {args.base_sha}")
    for key in ("head_seconds", "base_seconds", "delta_seconds", "material_limit_seconds"):
        print(f"{key.upper()} = {result[key]}")
    if result["candidate_regression"]:
        print("TIMING_ATTRIBUTION = CANDIDATE_REGRESSION")
        return EXIT_INVALID
    print("TIMING_ATTRIBUTION = NO_MATERIAL_CANDIDATE_REGRESSION")
    return EXIT_WITHIN_REFERENCE


if __name__ == "__main__":
    raise SystemExit(main())
