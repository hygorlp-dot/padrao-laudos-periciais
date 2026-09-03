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

from collections.abc import Mapping

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


def _diagnostic_from_error(item) -> dict:
    """`validar_integridade` devolve erros como STRING, nao como registro.

    Tratar os tres canais do manifesto (`erros`, `conflitos`, `pendencias`) com
    a mesma forma quebrava a importacao inteira: `str.get` nao existe, e
    `AttributeError` nao esta em `_NOT_A_READABLE_PJE_EXPORT`, entao a excecao
    escapava da porta como erro interno. O canal `erros` e justamente o que
    marca o export como BLOQUEADO -- ou seja, o caminho que o status BLOCKED
    existe para registrar era o unico que nunca chegava a ser registrado.

    O texto tem a forma "<identidade>: <descricao>"; a identidade e preservada
    como codigo quando existe, porque e ela que diz QUAL documento divergiu.
    """
    text = str(item)
    identity, separator, description = text.partition(": ")
    if separator and identity and " " not in identity:
        return {"code": identity, "detail": description or text}
    return {"code": "PJE_MANIFESTO_ERRO", "detail": text}


def _diagnostic_from_record(item, identity_field: str, fallback: str) -> dict:
    """Conflitos e pendencias sao registros; preserva-se o id que os nomeia."""
    if not isinstance(item, Mapping):
        return _diagnostic_from_error(item)
    code = item.get(identity_field) or item.get("tipo") or item.get("campo") or fallback
    detail = item.get("descricao") or item.get("motivo_ausencia") or item.get("campo")
    return {"code": str(code), "detail": str(detail or "divergencia no manifesto PJe")}


class PjeIntakeAdapter:
    """Le um PDF ja materializado em disco e descreve seu inventario logico."""

    def logical_inventory(self, pdf_path: str | Path, staging_dir: str | Path | None = None) -> dict:
        """`staging_dir` e a area de trabalho de quem chamou.

        O parser do PJe e baseado em caminho e precisa materializar arquivos para
        provar que cada documento logico pode ser produzido. Criar aqui um
        segundo diretorio temporario espalharia conteudo privado por duas raizes
        com dois donos de limpeza; recebendo a area do chamador ha UM dono, e a
        remocao acompanha a do PDF de origem.
        """
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
            *(_diagnostic_from_error(item) for item in errors),
            *(_diagnostic_from_record(item, "conflito_id", "CON-PJE")
              for item in manifesto.get("conflitos", ())),
            *(_diagnostic_from_record(item, "pendencia_id", "PEN-PJE")
              for item in manifesto.get("pendencias", ())),
        ]
        if errors or manifesto.get("status_validacao") != "VALIDADO":
            return {"status": "BLOCKED", "diagnostics": diagnostics or [
                {"code": "PJE_MANIFESTO_BLOQUEADO", "detail": "manifesto PJe nao validado"}
            ]}
        if staging_dir is None:
            with tempfile.TemporaryDirectory(prefix="pje-intake-check-") as fallback:
                report = gerar_documentos(manifesto, pdf, Path(fallback))
        else:
            report = gerar_documentos(manifesto, pdf, Path(staging_dir) / "documentos-verificacao")
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
