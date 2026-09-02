"""Adaptador de triagem que le um PDF e devolve o inventario logico do PJe.

Este modulo existe para inverter a dependencia que o backend nao pode ter:
`config/architecture-policy-v1.json` da a BACKEND `allowedDependencies: []`,
enquanto TRIAGE pode depender de PJE. O backend declara a porta e recebe esta
implementacao por injecao; aqui nao se importa nada de `scripts.backend_contract`,
a compatibilidade e estrutural.

O resultado e discriminado em vez de excepcional para que a taxonomia de falha
atravesse a porta sem exigir tipos de excecao compartilhados entre componentes:

    {"status": "NOT_PJE"}                       nao e (ou nao e legivel como) PJe
    {"status": "BLOCKED", "diagnostics": [...]}  e PJe, com pendencia/conflito aberto
    {"status": "OK", "instance_label": str, "documents": [...]}

`NOT_PJE` cobre deliberadamente o PDF que nenhuma das duas bibliotecas de leitura
consegue abrir: todo material importado passa por aqui, e um PDF cifrado ou
truncado nao pode derrubar a importacao de quem nunca quis um PJe.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from pdfminer.pdfexceptions import PDFException
from pdfminer.psexceptions import PSException
from pdfplumber.utils.exceptions import MalformedPDFException, PdfminerException
from pypdf.errors import PyPdfError

from scripts.extracao_pje.gerar_documentos import gerar_documentos
from scripts.extracao_pje.gerar_manifesto import construir_manifesto

# `LeitorPdf` abre o mesmo arquivo com pypdf E com pdfplumber; nomear so uma das
# familias deixa a outra escapar como erro interno.
_NOT_A_READABLE_PJE_EXPORT = (
    PyPdfError,
    PDFException,
    PSException,
    PdfminerException,
    MalformedPDFException,
    OSError,
)


class PjeIntakeAdapter:
    """Le um PDF ja materializado em disco e descreve seu inventario logico."""

    def logical_inventory(self, pdf_path: str | Path) -> dict:
        pdf = Path(pdf_path)
        try:
            manifesto, errors, _alerts = construir_manifesto(pdf)
        except _NOT_A_READABLE_PJE_EXPORT:
            return {"status": "NOT_PJE"}
        if not manifesto.get("indice", {}).get("itens"):
            return {"status": "NOT_PJE"}
        # Um export com pendencia ou conflito em aberto continua sendo um export
        # do PJe: `pendencias` existe no manifesto justamente porque isso e
        # esperado, nao corrupcao. Registrar o diagnostico preserva a informacao
        # sem afirmar um inventario que o parser nao pode sustentar.
        diagnostics = [
            {"code": str(item.get("codigo") or item.get("tipo") or "PJE_ERRO"),
             "detail": str(item.get("descricao") or item.get("campo") or "divergencia no manifesto PJe")}
            for item in (*errors, *manifesto.get("conflitos", ()), *manifesto.get("pendencias", ()))
        ]
        if errors or manifesto.get("status_validacao") != "VALIDADO":
            return {"status": "BLOCKED", "diagnostics": diagnostics or [
                {"code": "PJE_MANIFESTO_BLOQUEADO", "detail": "manifesto PJe nao validado"}
            ]}
        with tempfile.TemporaryDirectory(prefix="pje-intake-check-") as staging:
            report = gerar_documentos(manifesto, pdf, Path(staging))
        if report["documentos_validos"] != report["documentos_esperados"]:
            return {"status": "BLOCKED", "diagnostics": [{
                "code": "PJE_DOCUMENTOS_INVALIDOS",
                "detail": f"{report['documentos_validos']} de {report['documentos_esperados']} documentos validos",
            }]}
        process = manifesto.get("processo", {})
        judicial_unit = process.get("orgao_julgador", {})
        instance_label = judicial_unit.get("valor") if isinstance(judicial_unit, dict) else None
        return {
            "status": "OK",
            "instance_label": instance_label or "NÃO CLASSIFICADA",
            "documents": [
                {
                    "document_id": row["documento_id"],
                    "id_pje": row["id_pje"],
                    "title": row["titulo_original"],
                    "raw_type": row["tipo_original"],
                    "normalized_type": row["classe_normalizada"],
                    "page_start": row["pagina_pdf_inicio"],
                    "page_end": row["pagina_pdf_fim"],
                }
                for row in manifesto["documentos"]
            ],
        }
