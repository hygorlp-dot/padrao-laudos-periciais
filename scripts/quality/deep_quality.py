"""Boundary first-party para a campanha profunda opcional de mutation testing."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys


PILOT_TARGET = "scripts.redacao_pericial.autocorrigir_redacao.x_autocorrigir*"


def run_mutmut(target: str = PILOT_TARGET, *, runner=subprocess.run) -> int:
    executable = shutil.which("mutmut")
    if not executable:
        print("MUTATION_TOOL_UNAVAILABLE: mutmut==3.7.0 não instalado", file=sys.stderr)
        return 2
    completed = runner([executable, "run", target])
    return completed.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default=PILOT_TARGET)
    args = parser.parse_args(argv)
    return run_mutmut(args.target)


if __name__ == "__main__":
    raise SystemExit(main())
