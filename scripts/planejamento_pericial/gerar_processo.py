"""Gera processo.json conservador a partir do manifesto e dos documentos PJe."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path: sys.path.insert(0, str(RAIZ))
from scripts.triagem_pericial.gerar_delimitacao import gerar as gerar_delimitacao


TERMOS_ALEGACAO = re.compile(r"(?i)\b(alega|relata|sustenta|afirma|infiltra|fissura|trinca|umidade|descolamento|defeito|animal\s+solto|sinaliza[cç][aã]o|valor\s+(?:de\s+)?aluguel)\b")
SISTEMAS = {"REVESTIMENTOS": (r"\bcerâm", r"\brevestimento", r"\bdescolamento"), "VEDACOES": (r"\bfissura", r"\btrinca", r"\bparede(?:s)?\b"),
            "IMPERMEABILIZACAO": (r"\bumidade\b", r"\binfiltra"), "ESQUADRIAS": (r"\bporta(?:s)?\b", r"\bjanela(?:s)?\b", r"\besquadria"),
            "ENGENHARIA_RODOVIARIA": (r"\brodovia", r"\bpista\b", r"\bacostamento", r"\bsinalização"),
            "AVALIACAO_IMOBILIARIA": (r"\bvalor de mercado\b", r"\baluguel\b", r"\blocativo")}

MANIFESTACOES = re.compile(r"(?i)\b(infiltra(?:ção|ções)?|fissura(?:s)?|trinca(?:s)?|umidade|descolamento(?:s)?|defeito(?:s)?|vazamento(?:s)?|mofo|bolor|eflorescência(?:s)?)\b")
CAUSAS = re.compile(r"(?i)(?:devido\s+a|decorrente\s+de|causad[oa]\s+por|em\s+razão\s+de|por\s+falta\s+de)\s+([^.;]{3,160})")


def _campos_alegacao(texto: str) -> tuple[str | None, str | None]:
    manifestacoes = list(dict.fromkeys(m.group(0).strip() for m in MANIFESTACOES.finditer(texto)))
    causa = CAUSAS.search(texto)
    return (", ".join(manifestacoes) or None, causa.group(1).strip() if causa else None)


def _prov(documento: dict, trecho: str) -> dict:
    for bloco in documento.get("blocos_texto", []):
        if trecho[:30].lower() in bloco["texto"].lower():
            return {k: v for k, v in bloco["proveniencia"].items() if k != "bbox"}
    return {k: v for k, v in documento["blocos_texto"][0]["proveniencia"].items() if k != "bbox"}


def _sistema(texto: str) -> str | None:
    baixo = texto.lower()
    return next((nome for nome, termos in SISTEMAS.items() if any(re.search(t, baixo) for t in termos)), None)


def _partes(documentos: list[dict]) -> list[dict]:
    nomes: dict[tuple[str, str], str] = {}
    for documento in documentos:
        if documento["classe_normalizada"] not in {"DECISAO", "DESPACHO", "PETICAO_INICIAL"}: continue
        texto = "\n".join(p["texto_bruto"] for p in documento["paginas"][:3])
        for rotulo, polo in (("AUTOR", "ATIVO"), ("AUTORA", "ATIVO"), ("REU", "PASSIVO"), ("RÉU", "PASSIVO"), ("RÉ", "PASSIVO")):
            for m in re.finditer(rf"(?im)^\s*{rotulo}(?:\([^)]*\))?\s*:\s*([^\n]+)", texto):
                nome = re.split(r"\s+ADVOGAD", m.group(1))[0].strip(" ,")
                if 2 < len(nome) < 300: nomes[(polo, nome)] = documento["documento_id"]
    return [{"polo": polo, "nome": nome, "cpf_cnpj": None, "qualificacao": None, "representantes": [], "advogados": []}
            for polo, nome in nomes]


def gerar(diretorio: Path, *, data_laudo: str | None = None) -> dict[str, Any]:
    manifesto = json.loads((diretorio / "manifesto-pje.json").read_text(encoding="utf-8"))
    delimitacao = gerar_delimitacao(diretorio)
    fontes = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((diretorio / "documentos").glob("*.json"))]
    mapa = {d["documento_id"]: f"DOC-{i:03d}" for i, d in enumerate(fontes, 1)}
    documentos = [{"id": mapa[d["documento_id"]], "tipo": d["classe_normalizada"], "descricao": d["titulo_original"],
                   "id_processual": d["id_pje"], "data": d["data_hora"][:10] if d.get("data_hora") else None,
                   "autor_origem": None, "status": "PRESENTE", "paginas": [p["referencia"]["pagina_pdf"] for p in d["paginas"]],
                   "observacoes": f"Origem estrutural: {d['documento_id']}"} for d in fontes]
    alegacoes = []
    for d in fontes:
        if d["classe_normalizada"] not in {"PETICAO_INICIAL", "CONTESTACAO", "REPLICA", "MANIFESTACAO", "PARECER_TECNICO_PARTE", "OUTRO"}: continue
        texto = "\n".join(p["texto_bruto"] for p in d["paginas"])
        for trecho in re.split(r"(?<=[.!?])\s+|\n+", texto):
            limpo = re.sub(r"\s+", " ", trecho).strip()
            if not (30 <= len(limpo) <= 650 and TERMOS_ALEGACAO.search(limpo)): continue
            natureza = "INFORMADO_PELA_RE" if d["classe_normalizada"] == "CONTESTACAO" else "CONSTATADO_POR_TECNICO_DA_PARTE" if d["classe_normalizada"] == "PARECER_TECNICO_PARTE" else "ALEGADO_PELA_PARTE"
            prov = _prov(d, limpo)
            manifestacao, causa = _campos_alegacao(limpo)
            alegacoes.append({"id": f"ALG-{len(alegacoes)+1:03d}", "origem": d["classe_normalizada"], "parte": None,
                              "documento_fonte": mapa[d["documento_id"]], "id_processual": d["id_pje"],
                              "texto": {"conteudo": limpo, "tipo_registro": "ORIGINAL"},
                              "manifestacao_alegada": manifestacao, "causa_alegada": causa, "consequencia_alegada": None,
                              "ambiente_alegado": None, "sistema_alegado": _sistema(limpo), "data_alegada": None,
                              "paginas": [{"pagina_pdf": prov["pagina_pdf"], "pagina_documento": prov["pagina_documento"], "pagina_original": prov["pagina_original"]}],
                              "natureza": natureza, "proveniencia": [prov], "observacoes": "Não representa constatação do perito judicial.", "status_verificacao": "NAO_VERIFICADO"})
    quesitos = [{"id": q["id"], "origem": {"AUTOR": "PARTE_AUTORA", "REU": "PARTE_RE", "INDETERMINADA": "OUTRO"}.get(q["origem"], q["origem"]),
                 "parte_origem_textual": q["origem"], "numero_original": q["numero_original"] or q["caminho_original"] or str(q["ordem_real"]),
                 "texto_integral": q["texto_integral"], "documento_fonte": mapa.get(q["documento_id"]), "id_processual": q["id_pje"], "status": "IDENTIFICADO"}
                for q in delimitacao["quesitos"]]
    decisoes = []
    for d in fontes:
        if d["classe_normalizada"] not in {"DECISAO", "DESPACHO"}: continue
        texto = re.sub(r"\s+", " ", "\n".join(p["texto_bruto"] for p in d["paginas"])).strip()
        if not re.search(r"(?i)per[ií]ci|vistoria|quesit|prova t[eé]cnica", texto): continue
        decisoes.append({"id": f"DEC-{len(decisoes)+1:03d}", "documento": mapa[d["documento_id"]], "id_processual": d["id_pje"],
                         "data": d["data_hora"][:10] if d.get("data_hora") else None, "sintese": texto[:1000],
                         "determinacoes_relevantes_pericia": [s for s in re.split(r"(?<=[.!?])\s+", texto) if re.search(r"(?i)per[ií]ci|vistoria|quesit", s)][:10]})
    eventos = [{"id": f"EVT-{i:03d}", "data": e.get("data"), "descricao": e["descricao"], "natureza": "DOCUMENTADO", "documento_fonte": None, "proveniencia": [e["proveniencia"]]}
               for i, e in enumerate(manifesto.get("eventos", []), 1)]
    principal = fontes[0]["blocos_texto"][0]["proveniencia"]
    principal = {k: v for k, v in principal.items() if k != "bbox"}
    processo = manifesto["processo"]
    valor = lambda k: processo[k].get("valor") if isinstance(processo.get(k), dict) else None
    assuntos = [i["valor"] for i in processo.get("assuntos", []) if i.get("valor")]
    return {"schema_version": "2.0.0", "numero_processo": processo["numero_cnj"]["valor"], "data_laudo": data_laudo, "tipo_acao": valor("classe"),
            "assunto": "; ".join(assuntos) or None, "juizo": valor("orgao_julgador"), "vara": valor("orgao_julgador"),
            "subsecao": valor("subsecao"), "tribunal": valor("tribunal"), "partes": _partes(fontes),
            "perito": {"nome": None, "profissao": None, "crea": None, "crea_regional": None, "ibape": None},
            "imovel": {"endereco": {"logradouro": None, "numero": None, "complemento": None, "bairro": None, "municipio": None, "uf": None, "cep": None},
                       "matricula": None, "area": None, "tipologia": None, "empreendimento": None, "unidade": None, "bloco": None, "quadra": None,
                       "coordenadas": None, "caracterizacao_construtiva": {"descricao": None, "status_confirmacao": "NAO_CONFIRMADA", "fontes": []}},
            "contrato": None, "datas_relevantes": {"contrato": None, "entrega": None, "inicio_utilizacao": None, "habite_se": None,
                "surgimento_alegado_manifestacoes": None, "primeira_reclamacao": None, "primeira_comprovacao_documental": None,
                "ajuizamento": None, "nomeacao": None, "vistoria": None}, "documentos": documentos, "alegacoes": alegacoes,
            "quesitos": quesitos, "decisoes": decisoes, "conflitos": [], "pendencias": [],
            "objeto_material": {"descricao": delimitacao["objeto_material"]["texto"], "natureza": "INFERIDO_TECNICAMENTE",
                                "documento_fonte": mapa.get(delimitacao["tipo_pericia"]["documentos_fonte"][0]), "proveniencia": delimitacao["proveniencia"]},
            "eventos": eventos, "documentos_tecnicos": [mapa[d["documento_id"]] for d in fontes if d["classe_normalizada"] in {"PARECER_TECNICO_PARTE", "LAUDO_PERICIAL"}],
            "assistentes_tecnicos": [], "dados_vistoria_determinados": [], "honorarios_prazos": [], "proveniencia": [principal]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("diretorios", nargs="+", type=Path)
    for diretorio in parser.parse_args().diretorios:
        destino = diretorio / "processo.json"; destino.write_text(json.dumps(gerar(diretorio), ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"); print(destino)
    return 0


if __name__ == "__main__": raise SystemExit(main())
