"""Plano de execução derivado do gate protegido ``verify_core`` (V7-4A, #259).

Este módulo é NÃO-DISPOSITIVO: nunca executa comando, nunca decide PASS/FAIL
e nunca substitui ``core-safety``. Ele apenas extrai, do próprio
``scripts/quality/verify_core.py`` (sem copiar sua lista de comandos), a
sequência exata de estágios que o gate executaria. Ferramentas de profiling e
a orquestração da CI consomem esse plano para não divergirem do juiz.

A extração usa o ponto de injeção ``runner`` que o gate já expõe: um runner
gravador devolve, para cada chamada, um código de saída não-zero com um marcador
único no stderr. O gate então registra um finding cujo ``motivo`` é esse
marcador e cujo ``teste`` é o nome do estágio, o que liga cada nome ao seu
comando sem depender da ordem de agendamento das threads do gate.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from . import verify_core

ROOT = Path(__file__).resolve().parents[2]
_MARKER = "CORE_SAFETY_PLAN_CALL_"


class PlanExtractionError(RuntimeError):
    """O plano não pôde ser derivado de forma completa e inequívoca."""


@dataclass(frozen=True)
class Stage:
    name: str
    argv: tuple[str, ...]


def gate_plan(mode: str = "full", root: Path = ROOT) -> tuple[Stage, ...]:
    """Devolve os estágios-comando do gate, na ordem em que ele os reporta."""
    calls: list[tuple[str, ...]] = []
    lock = threading.Lock()

    def recording_runner(command, **_kwargs):
        with lock:
            index = len(calls)
            calls.append(tuple(str(part) for part in command))
        return SimpleNamespace(returncode=1, stdout="", stderr=f"{_MARKER}{index}")

    with contextlib.redirect_stdout(io.StringIO()):
        result = verify_core.run_gate(mode, root, runner=recording_runner, tracked_files=[])

    by_reason = {
        item["motivo"]: item["teste"]
        for item in result.findings
        if str(item.get("motivo", "")).startswith(_MARKER)
    }
    stages: list[Stage] = []
    for index, argv in enumerate(calls):
        name = by_reason.get(f"{_MARKER}{index}")
        if name is None:
            raise PlanExtractionError(f"comando sem estágio identificável: {argv!r}")
        stages.append(Stage(name, argv))
    reported = [name for name, _passed in result.checks]
    order = {name: position for position, name in enumerate(reported)}
    if len({stage.name for stage in stages}) != len(stages) or any(stage.name not in order for stage in stages):
        raise PlanExtractionError("plano ambíguo: nomes de estágio repetidos ou ausentes")
    return tuple(sorted(stages, key=lambda stage: order[stage.name]))


def stage(name: str, plan: tuple[Stage, ...]) -> Stage:
    matches = [item for item in plan if item.name == name]
    if len(matches) != 1:
        raise PlanExtractionError(f"estágio {name!r} ausente ou repetido no plano")
    return matches[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=("fast", "full"), default="full")
    parser.add_argument("--stage", help="emitir somente o argv deste estágio")
    args = parser.parse_args(argv)
    try:
        plan = gate_plan(args.mode)
        payload = (
            list(stage(args.stage, plan).argv)
            if args.stage
            else [{"name": item.name, "argv": list(item.argv)} for item in plan]
        )
    except PlanExtractionError as exc:
        print(f"PLAN_INVALID: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
