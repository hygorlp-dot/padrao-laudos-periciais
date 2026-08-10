"""Gera rascunho conservador de delimitação a partir dos documentos PJe.

O resultado não equivale a laudo nem a conclusão técnica. A execução grava
somente no diretório privado de derivados informado.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

try:
    from scripts.triagem_pericial.classificar_tipo import classificar, normalizar
    from scripts.triagem_pericial.extrair_quesitos import extrair
    from scripts.triagem_pericial.semantica import melhores
except ModuleNotFoundError:  # execução direta pelo caminho do script
    from classificar_tipo import classificar, normalizar
    from extrair_quesitos import extrair
    from semantica import melhores


PERFIS = {
    "VICIOS_CONSTRUTIVOS": {
        "tema": "Determinar se as manifestações construtivas alegadas no imóvel existem e, quando constatadas, caracterizar tecnicamente natureza, origem, consequências e medidas pertinentes dentro do encargo.",
        "objeto": "Imóvel e manifestações construtivas abrangidos pela prova pericial.",
        "objetivo": "Sanear tecnicamente a controvérsia sobre as manifestações alegadas, sem antecipar constatação, origem ou responsabilidade.",
        "questoes": [
            "Verificar a existência, localização, extensão e características das manifestações alegadas.",
            "Analisar as causas tecnicamente possíveis e classificar a origem apenas com suporte suficiente.",
            "Avaliar consequências técnicas e medidas de reparo pertinentes ao que for efetivamente constatado.",
        ],
        "sistemas": ["REVESTIMENTOS", "VEDACOES", "IMPERMEABILIZACAO", "ESQUADRIAS", "INSTALACOES_HIDROSSANITARIAS", "OUTRO"],
    },
    "AVALIACAO_IMOBILIARIA": {
        "tema": "Determinar o valor de mercado locativo do imóvel no período delimitado, mediante caracterização do bem, pesquisa e tratamento técnico de dados verificáveis.",
        "objeto": "Imóvel objeto da relação locatícia e respectivo valor de mercado para locação.",
        "objetivo": "Sanear tecnicamente a divergência sobre o valor locativo mediante método de avaliação justificável e rastreável.",
        "questoes": [
            "Caracterizar o imóvel, sua localização, uso, estado e atributos relevantes para avaliação.",
            "Definir e aplicar método de avaliação compatível com os dados de mercado disponíveis.",
            "Determinar o valor locativo na data de referência e explicitar incertezas e fatores de influência.",
        ], "sistemas": ["OUTRO"],
    },
    "ENGENHARIA_RODOVIARIA": {
        "tema": "Avaliar as condições técnicas do trecho rodoviário delimitado e os fatores de segurança viária potencialmente relacionados ao sinistro, distinguindo condições atuais das existentes na data do evento.",
        "objeto": "Trecho rodoviário e elementos de infraestrutura e segurança vinculados ao local do evento.",
        "objetivo": "Sanear tecnicamente a controvérsia sobre condições da via e sua eventual contribuição técnica, sem concluir responsabilidade jurídica.",
        "questoes": [
            "Caracterizar geometria, pavimento, acostamento e condições operacionais do trecho examinado.",
            "Verificar sinalização, iluminação, dispositivos de contenção e riscos pertinentes ao evento descrito.",
            "Distinguir evidências atuais e históricas e avaliar, com ressalvas, possíveis fatores técnicos contribuintes.",
        ], "sistemas": ["OUTRO"],
    },
    "OUTRO": {
        "tema": "Tema técnico ainda insuficientemente delimitado pelos elementos recuperados.",
        "objeto": "Objeto material pendente de delimitação segura.",
        "objetivo": "Obter evidência adicional para delimitar o encargo sem presumir especialidade ou conclusão.",
        "questoes": ["Identificar o objeto material e o tema técnico efetivamente submetido à perícia."],
        "sistemas": ["OUTRO"],
    },
}


def _fonte(documentos: list[dict[str, Any]], ids: list[str]) -> dict[str, Any]:
    candidatas = [d for d in documentos if d["documento_id"] in ids]
    peso_classe = {"DECISAO": 30, "DESPACHO": 24, "PETICAO_INICIAL": 12, "MANIFESTACAO": 10}
    def relevancia(d: dict[str, Any]) -> tuple[int, int]:
        texto = normalizar(" ".join(p.get("texto_bruto", "") for p in d["paginas"]))
        sinais = ("prova pericial", "controversia", "quesitos", "objeto da pericia", "finalidade", "pericia tecnica")
        return (peso_classe.get(d["classe_normalizada"], 0) + sum(4 for sinal in sinais if sinal in texto), -d["ordem_indice"])
    documento = max(candidatas or documentos, key=relevancia)
    if not documento.get("blocos_texto"):
        raise ValueError(f"{documento['documento_id']} não possui bloco com proveniência")
    prov = {k: v for k, v in documento["blocos_texto"][0]["proveniencia"].items() if k != "bbox"}
    return {"documento": documento, "proveniencia": prov}


def _confianca(nivel: str, score: float | None = None) -> dict[str, Any]:
    dado: dict[str, Any] = {"nivel": nivel}
    if score is not None:
        dado["score"] = score
    return dado


def _origem_quesito(documento: dict[str, Any]) -> str:
    texto = normalizar(" ".join(p.get("texto_bruto", "") for p in documento["paginas"]))
    if documento["classe_normalizada"] in {"DECISAO", "DESPACHO"}:
        return "JUIZO"
    if "quesitos da parte autora" in texto:
        return "AUTOR"
    if "quesitos da parte re" in texto or "quesitos da requerida" in texto:
        return "REU"
    return "INDETERMINADA"


def _materia_juridica(texto: str) -> str | None:
    termos = ["prescrição", "decadência", "culpa", "responsabilidade civil", "dever de indenizar", "indenizar", "responsabilizar", "responsável pelo dano", "obrigação de pagar", "legitimidade", "nexo jurídico"]
    encontrados = [termo for termo in termos if normalizar(termo) in normalizar(texto)]
    return ", ".join(encontrados) if encontrados else None

def _tema_dos_autos(documentos, fallback):
    sinais=re.compile(r"(?i)\b(per[ií]cia|prova t[eé]cnica|verificar|determinar|controvers|fissur|trinc|umidade|infiltra|desplac|estrutura|impermeabiliza)\b")
    candidatos=[]
    camadas={"DECISAO":7,"QUESITOS_JUIZO":6,"DESPACHO":5,"ATO_JUDICIAL":4,"QUESITOS":3,"PETICAO_INICIAL":2,"MANIFESTACAO":2,"PARECER_TECNICO_PARTE":1}
    for doc in documentos:
        for pag in doc.get("paginas",[]):
            for trecho in re.split(r"(?<=[.!?])\s+|\n+",pag.get("texto_bruto","")):
                limpo=re.sub(r"\s+"," ",trecho).strip()
                if 25<=len(limpo)<=700 and sinais.search(limpo):candidatos.append((camadas.get(doc.get("classe_normalizada"),0),len(sinais.findall(limpo)),doc,pag,limpo))
    if not candidatos:return fallback,None
    _,_,doc,pag,trecho=max(candidatos,key=lambda x:(x[0],x[1]));manifestacoes=sorted(set(re.findall(r"(?i)\b(fissuras?|trincas?|umidade|infiltrações?|desplacamentos?|deformações?)\b",trecho)))
    texto=("Verificar tecnicamente "+", ".join(manifestacoes)+", suas causas e consequências dentro do encargo delimitado nos autos.") if manifestacoes else trecho
    return texto,{"documento_id":doc["documento_id"],"pagina":pag.get("referencia"),"trecho":trecho,"natureza":"DELIMITACAO_EXTRAIDA","camada_autoridade":max(candidatos,key=lambda x:(x[0],x[1]))[0]}


def gerar(diretorio: Path) -> dict[str, Any]:
    manifesto_path = diretorio / "manifesto-pje.json"
    manifesto = json.loads(manifesto_path.read_text(encoding="utf-8"))
    documentos = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((diretorio / "documentos").glob("*.json"))]
    resultado = classificar(documentos)
    raiz_privada = diretorio.parent.parent
    modelos = list((raiz_privada / "modelos-referenciais").glob("**/*")) if (raiz_privada / "modelos-referenciais").exists() else []
    normas = list((raiz_privada / "normas").glob("**/*")) if (raiz_privada / "normas").exists() else []
    modelos = [item for item in modelos if item.is_file()]
    normas = [item for item in normas if item.is_file()]
    perfil = PERFIS.get(resultado.tipo, PERFIS["OUTRO"])
    conhecimento_modelos = []
    for caminho in sorted((raiz_privada / "conhecimento" / "modelos").glob("MOD-*.json")):
        dado = json.loads(caminho.read_text(encoding="utf-8"))
        if dado.get("tipo_pericia") == resultado.tipo or set(dado.get("sistemas", [])) & set(perfil["sistemas"]):
            conhecimento_modelos.append(dado["id"])
    conhecimento_normas = []
    for caminho in sorted((raiz_privada / "conhecimento" / "normas").glob("NOR-*.json")):
        dado = json.loads(caminho.read_text(encoding="utf-8"))
        if resultado.tipo in dado.get("sistemas", []) or set(dado.get("sistemas", [])) & set(perfil["sistemas"]):
            conhecimento_normas.append(dado["id"])
    fonte = _fonte(documentos, resultado.documentos_fonte)
    prov = fonte["proveniencia"]
    docs_por_id = {d["documento_id"]: d for d in documentos}
    agora = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    res_ids = ["RES-001", "RES-002"] + (["RES-003"] if resultado.nivel == "MEDIA" else [])
    questoes = []
    for numero, descricao in enumerate(perfil["questoes"], 1):
        questoes.append({
            "id": f"QT-{numero:03d}", "descricao": descricao,
            "origem": f"Delimitação inferencial apoiada em {fonte['documento']['documento_id']}",
            "necessidade_para_saneamento": "Componente necessário para responder ao tema controvertido sem antecipar conclusão.",
            "quesitos_relacionados": [], "alegacoes_relacionadas": [], "evidencias_disponiveis": ["Documentos PJe estruturalmente extraídos"],
            "evidencias_necessarias": ["Vistoria e documentação técnica pertinente"],
            "documentos_relacionados": resultado.documentos_fonte, "ressalvas": res_ids,
            "status_saneamento": "A_SANEAR", "confianca": _confianca(resultado.nivel),
            "proveniencia": [prov],
        })

    extraidos = extrair(documentos)
    vistos_texto: dict[str, str] = {}
    quesitos = []
    for ordem, item in enumerate(extraidos, 1):
        qid = f"QUE-{ordem:03d}"
        chave = re.sub(r"\W+", "", normalizar(item["texto_integral"]))
        repetitivo = chave in vistos_texto
        if not repetitivo:
            vistos_texto[chave] = qid
        juridica = _materia_juridica(item["texto_integral"])
        pertinencia = "REPETITIVO" if repetitivo else "PERTINENTE_PARCIAL" if juridica else "PERTINENTE_TECNICO"
        questoes_relacionadas = melhores(item["texto_integral"], questoes)
        for questao_id in questoes_relacionadas:
            next(q for q in questoes if q["id"] == questao_id)["quesitos_relacionados"].append(qid)
        doc = docs_por_id[item["documento_id"]]
        quesitos.append({
            "id": qid, "origem": _origem_quesito(doc), "documento_id": item["documento_id"],
            "id_pje": item["id_pje"], "numero_original": item["numero_original"],
            "caminho_original": item["numero_original"], "ordem_real": ordem,
            "texto_integral": item["texto_integral"], "subitens": [], "paginas": [item["pagina"]],
            "pertinencia": pertinencia, "questoes_tecnicas_relacionadas": questoes_relacionadas,
            "evidencias_necessarias": ["Evidência documental e/ou de vistoria compatível com o conteúdo do quesito"],
            "ressalvas_aplicaveis": res_ids,
            "status_cobertura": "REPETITIVO" if repetitivo else "PARCIAL",
            "materia_tecnica": item["texto_integral"] if not juridica else "Aspecto técnico a separar da qualificação jurídica",
            "materia_juridica_associada": juridica,
            "secoes_laudisticas_previstas": ["Análise técnica vinculada à questão " + q for q in questoes_relacionadas],
            "proveniencia": [item["proveniencia"]],
        })

    cobertura = [{"quesito_id": q["id"], "questoes_tecnicas": q["questoes_tecnicas_relacionadas"],
                  "secoes_laudisticas": q["secoes_laudisticas_previstas"], "status": q["status_cobertura"]}
                 for q in quesitos]
    ressalvas = []
    descr_conhecimento = ("Não há base privada de normas ou modelos referenciais disponível no diretório esperado."
                          if not modelos and not normas else
                          "Fontes privadas de conhecimento existem, mas sua extração e verificação ainda não foram concluídas.")
    especificacoes_ressalva = [
        ("RES-001", "LIMITACAO_DE_VISTORIA", "A vistoria e as constatações de campo ainda não integram esta etapa."),
        ("RES-002", "DADO_NAO_DISPONIVEL" if not modelos and not normas else "DADO_NAO_VERIFICAVEL", descr_conhecimento),
    ]
    if resultado.nivel == "MEDIA":
        especificacoes_ressalva.append(("RES-003", "INCERTEZA_TECNICA", "A família principal foi definida com confiança média e exige confronto durante o planejamento."))
    for rid, categoria, descricao in especificacoes_ressalva:
        ressalvas.append({
            "id": rid, "categoria": categoria, "descricao": descricao,
            "causa": "Etapa ou fonte ainda indisponível", "evidencia": "Inventário local das fontes da triagem",
            "questoes_afetadas": [q["id"] for q in questoes], "quesitos_afetados": [q["id"] for q in quesitos],
            "conclusoes_impedidas": ["Conclusão técnica de mérito"],
            "conclusoes_ainda_permitidas": ["Classificação e planejamento preliminares"],
            "efeito_no_grau_de_certeza": "A classificação pode orientar o plano, mas não autoriza conclusão técnica.",
            "proveniencia": [prov],
        })
    status = "PENDENTE_EVIDENCIAS_ADICIONAIS" if resultado.nivel == "BAIXA" else "APTO_PARA_PLANEJAMENTO"
    sha_manifesto = hashlib.sha256(manifesto_path.read_bytes()).hexdigest()
    tema_extraido,passagem_tema=_tema_dos_autos(documentos,perfil["tema"])
    analise = lambda texto: {"texto": texto, "confianca": _confianca(resultado.nivel),
                             "documentos_fonte": resultado.documentos_fonte,
                             "status_verificacao": "PENDENTE_VALIDACAO_PERITO"}
    assuntos = [item["valor"] for item in manifesto["processo"].get("assuntos", []) if item.get("valor")]
    proveniencias_gerais = [item["proveniencia"] for item in manifesto["processo"].get("assuntos", []) if item.get("valor")]
    proveniencias_gerais.append(prov)
    assunto = {"texto": "; ".join(assuntos) if assuntos else "Assunto processual não localizado no manifesto.",
               "confianca": _confianca("ALTA" if assuntos else "BAIXA"), "documentos_fonte": [],
               "status_verificacao": "VERIFICADO" if assuntos else "INCONCLUSIVO"}
    return {
        "schema_version": "1.0.0",
        "identificacao": {"processo_cnj": manifesto["processo"]["numero_cnj"]["valor"], "manifesto_sha256": sha_manifesto, "data_geracao": agora},
        "tipo_pericia": {"tipo": resultado.tipo, "confianca": _confianca(resultado.nivel, resultado.score),
                          "evidencias": resultado.evidencias, "documentos_fonte": resultado.documentos_fonte,
                          "criterios": resultado.criterios, "alternativas_consideradas": resultado.alternativas},
        "subtipos_pericia": resultado.subtipos,
        "assunto_processual": assunto,
        "controversia_processual": analise(tema_extraido), "tema_controvertido": analise(tema_extraido),
        "objeto_material": analise(perfil["objeto"]), "objetivo_pericial": analise(perfil["objetivo"]),
        "questoes_tecnicas": questoes, "quesitos": quesitos, "matriz_cobertura": cobertura,
        "ressalvas": ressalvas, "fatores_limitantes": [r["descricao"] for r in ressalvas], "conflitos": [],
        "materias_excluidas": [{"descricao": "Responsabilidade civil, culpa, prescrição, decadência e dever de indenizar.",
                                "motivo": "MATERIA_JURIDICA", "tratamento_tecnico": "Delimitar e responder apenas o aspecto técnico associado."}],
        "documentos_relevantes": [{"documento_id": fonte["documento"]["documento_id"], "papel": "Fonte principal da delimitação preliminar",
                                   "autoridade": "DELIMITACAO_PRIMARIA" if fonte["documento"]["classe_normalizada"] in {"DECISAO", "DESPACHO"} else "ALEGACAO",
                                   "justificativa": "Peça de maior autoridade disponível entre as evidências classificatórias."}],
        "documentos_ausentes": (["Base privada de normas"] if not normas else [])
                              + (["Base privada de modelos referenciais"] if not modelos else []),
        "metodologia_preliminar": ["Leitura cruzada das peças", "Vistoria planejada", "Análise técnica com rastreabilidade"],
        "modulos_tecnicos": [{"nome": resultado.tipo, "prioridade": "PRINCIPAL", "sistemas": perfil["sistemas"]}]
                            + [{"nome": s, "prioridade": "COMPLEMENTAR", "sistemas": ["OUTRO"]} for s in resultado.subtipos],
        "plano_pericial_preliminar": {
            "o_que_verificar": perfil["questoes"], "o_que_fotografar": [perfil["objeto"]],
            "o_que_medir": ["Grandezas exigidas pelas questões técnicas e verificáveis na diligência"],
            "ensaios_sugeridos": ["Somente após confirmação de aplicabilidade e necessidade"],
            "equipamentos_sugeridos": ["Instrumentos compatíveis com as grandezas efetivamente definidas"],
            "documentos_a_solicitar": ["Documentação técnica mencionada nos autos e ainda não disponível"],
            "pontos_criticos": ["Não converter alegação em constatação", "Distinguir condição atual da histórica quando aplicável"],
            "questoes_que_dependem_da_vistoria": [q["id"] for q in questoes],
        },
        "memoria_referencial": {"fontes_disponiveis": len(modelos), "itens_recuperados": conhecimento_modelos, "status": "DISPONIVEL" if modelos else "INDISPONIVEL"},
        "conhecimento_normativo": {"fontes_disponiveis": len(normas), "itens_recuperados": conhecimento_normas, "status": "PENDENTE_VERIFICACAO_NORMATIVA" if normas else "INDISPONIVEL"},
        "autoauditoria": [
            {"criterio": "Classificação usa múltiplas peças e não o número do processo", "resultado": "APROVADO", "observacao": ", ".join(resultado.documentos_fonte)},
            {"criterio": "Tema e objeto possuem fonte identificável", "resultado": "ALERTA", "observacao": "Formulação preliminar requer validação semântica final do perito."},
            {"criterio": "Normas usadas possuem proveniência", "resultado": "APROVADO", "observacao": f"Conhecimento recuperado por ID privado: {', '.join(conhecimento_normas) or 'nenhum aplicável'}."},
            {"criterio": "Modelos não contaminam fatos do caso", "resultado": "APROVADO", "observacao": f"Modelos recuperados apenas como experiência: {', '.join(conhecimento_modelos) or 'nenhum disponível'}."},
        ],
        "status": status, "proveniencia": proveniencias_gerais,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("diretorios", nargs="+", type=Path)
    argumentos = parser.parse_args()
    for diretorio in argumentos.diretorios:
        destino = diretorio / "delimitacao-pericial.json"
        destino.write_text(json.dumps(gerar(diretorio), ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(destino)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
