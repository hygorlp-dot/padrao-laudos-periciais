"""Verifica offline a cópia pinada de Design Motion Principles."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
MANIFESTO = RAIZ / "docs" / "terceiros" / "design-motion-principles-blobs.json"


def _blob(path: Path) -> str:
    return subprocess.check_output(
        ["git", "hash-object", "--", str(path)], text=True
    ).strip()


def verificar() -> list[str]:
    dados = json.loads(MANIFESTO.read_text(encoding="utf-8"))
    destino = RAIZ / dados["destination"]
    erros: list[str] = []
    esperados = set(dados["blobs"])
    atuais = {
        p.relative_to(destino).as_posix()
        for p in destino.rglob("*")
        if p.is_file()
    }
    if atuais != esperados:
        erros.append(f"arquivos divergentes: esperados={sorted(esperados)} atuais={sorted(atuais)}")
    for relativo, esperado in dados["blobs"].items():
        path = destino / relativo
        if path.is_file() and _blob(path) != esperado:
            erros.append(f"blob divergente: {relativo}")
    padrao = re.compile(r"\[[^\]]+\]\(([^)#]+)(?:#[^)]+)?\)")
    for path in destino.rglob("*.md"):
        for alvo in padrao.findall(path.read_text(encoding="utf-8")):
            if not alvo.startswith(("http://", "https://", "mailto:")) and not (path.parent / alvo).exists():
                erros.append(f"referência quebrada: {path.relative_to(destino)} -> {alvo}")
    return erros


if __name__ == "__main__":
    falhas = verificar()
    if falhas:
        raise SystemExit("\n".join(falhas))
    print("DESIGN_MOTION_PRINCIPLES_INTEGRITY=100%")
