"""CLI do parser estrutural determinístico do PJe."""

import argparse
import re
import time
from pathlib import Path

from .gerar_manifesto import construir_manifesto, salvar_manifesto


def _identificador(manifesto, pdf):
    cnj = manifesto["processo"]["numero_cnj"]["valor"]
    if cnj != "0000000-00.0000.0.00.0000":
        return cnj
    return re.sub(r"[^A-Za-z0-9._-]+", "-", pdf.stem).strip("-")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Extrai manifesto estrutural de PDF consolidado do PJe")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--saida", type=Path)
    parser.add_argument("--sobrescrever", action="store_true")
    args = parser.parse_args(argv)
    inicio = time.perf_counter()
    manifesto, erros, alertas = construir_manifesto(args.pdf)
    raiz = Path(__file__).resolve().parents[2]
    saida = args.saida or raiz / "referencias" / "privadas" / "derivados" / _identificador(manifesto, args.pdf)
    destino = salvar_manifesto(manifesto, saida, args.sobrescrever)
    estados = {s: 0 for s in ("CONFIRMADO", "PROVAVEL", "CONFLITANTE", "NAO_LOCALIZADO", "SEM_ITEM_NO_INDICE")}
    for documento in manifesto["documentos"]:
        estados[documento["status_reconciliacao"]["status"]] += 1
    paginas_documentais = set(range(min(manifesto["indice"]["paginas"][-1] + 1, manifesto["arquivo"]["total_paginas"]), manifesto["arquivo"]["total_paginas"] + 1))
    associadas = {p for d in manifesto["documentos"] for p in range(d["pagina_pdf_inicio"], d["pagina_pdf_fim"] + 1)}
    print(f"Manifesto: {destino}")
    print(f"Páginas: {manifesto['arquivo']['total_paginas']} | Índice: {len(manifesto['indice']['itens'])} | IDs por rodapé: {len(set(p['id_pje_detectado'] for p in manifesto['paginas'] if p['id_pje_detectado']))}")
    print(f"Documentos: {len(manifesto['documentos'])} | " + " | ".join(f"{k}: {v}" for k, v in estados.items()))
    print(f"Páginas documentais não associadas: {sorted(paginas_documentais - associadas)}")
    print(f"Erros de integridade/paginação: {len(erros)} | Alertas: {len(alertas)} | Tempo: {time.perf_counter()-inicio:.3f}s")
    return 1 if erros else 0


if __name__ == "__main__":
    raise SystemExit(main())
