"""Gera plano-vistoria.json específico ao tipo pericial e ficha de campo."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any
from .validar_plano import recalcular_cobertura
from scripts.triagem_pericial.semantica import melhores


def _hash(caminho: Path) -> str: return hashlib.sha256(caminho.read_bytes()).hexdigest()


def _conhecimento(raiz_privada: Path, tipo: str, sistemas: set[str]) -> list[dict]:
    resultados = []
    for pasta, prefixo in (("normas", "NOR"), ("modelos", "MOD")):
        for caminho in sorted((raiz_privada / "conhecimento" / pasta).glob(f"{prefixo}-*.json")):
            dado = json.loads(caminho.read_text(encoding="utf-8"))
            termos = set(dado.get("sistemas", [])) | set(dado.get("assuntos", []))
            relevante = tipo in termos or (tipo == "VICIOS_CONSTRUTIVOS" and bool(sistemas & termos))
            if relevante:
                resultados.append({"fonte": dado["id"], "motivo_da_relevancia": f"Relacionada ao tipo {tipo} ou aos sistemas planejados.",
                                   "tipo_de_uso": "REFERENCIA_NORMATIVA" if prefixo == "NOR" else "PLANEJAMENTO",
                                   "confianca": dado.get("proveniencia", dado.get("fonte", {})).get("confianca", {"nivel": "BAIXA"})})
    return resultados[:12]


def _perfil(tipo: str) -> dict[str, Any]:
    if tipo == "AVALIACAO_IMOBILIARIA":
        return {"atividades": [
            ("Caracterizar fisicamente o imóvel, uso, ocupação, padrão e estado de conservação.", "Inspeção e registro objetivo"),
            ("Levantar áreas e atributos relevantes ao método de avaliação.", "Medição e confronto documental"),
            ("Registrar localização, entorno e elementos valorizantes ou desvalorizantes verificáveis.", "Inspeção do entorno")],
            "medicoes": [("dimensões e áreas", "trena ou instrumento compatível")],
            "fotos": ["fachadas e acessos", "ambientes e padrão de acabamento", "entorno e inserção urbana"],
            "equip": [("trena", "levantamento dimensional"), ("câmera", "registro do bem e entorno")],
            "seguranca": ["Confirmar autorização e acesso a todos os ambientes relevantes"]}
    if tipo == "ENGENHARIA_RODOVIARIA":
        return {"atividades": [
            ("Georreferenciar e caracterizar geometria, pavimento, acostamento e drenagem do trecho.", "Inspeção rodoviária e medições"),
            ("Verificar sinalização, iluminação, visibilidade e dispositivos laterais.", "Inspeção de segurança viária"),
            ("Confrontar condições atuais com registros contemporâneos ao evento.", "Análise temporal documentada")],
            "medicoes": [("coordenadas e geometria do trecho", "receptor GNSS e trena compatível"), ("distâncias de visibilidade", "instrumento de distância compatível")],
            "fotos": ["contexto do trecho e sentidos de circulação", "sinalização e visibilidade", "pavimento, acostamento, drenagem e dispositivos laterais"],
            "equip": [("receptor GNSS", "localização do trecho"), ("trena", "geometria e distâncias"), ("câmera", "registro técnico do trecho")],
            "seguranca": ["Planejar proteção operacional junto à rodovia", "Usar apoio e sinalização da diligência quando exigidos"]}
    if tipo == "VICIOS_CONSTRUTIVOS": return {"atividades": [
        ("Localizar e caracterizar objetivamente cada manifestação alegada, sem presumir origem.", "Inspeção visual sistemática"),
        ("Examinar interfaces, extensão e sinais associados relevantes à análise causal futura.", "Inspeção visual e medição pertinente"),
        ("Confrontar alegações, condições observáveis e documentação construtiva disponível.", "Rastreabilidade documental e de campo")],
        "medicoes": [("extensão e dimensão das manifestações identificáveis", "trena, régua ou fissurômetro conforme a grandeza")],
        "fotos": ["contexto do ambiente e sistema", "aproximação da manifestação alegada", "detalhe com escala e interface correlata"],
        "equip": [("trena", "extensão e localização"), ("régua/fissurômetro", "dimensões compatíveis com fissuras"), ("medidor de umidade", "indícios de umidade quando alegados"), ("câmera", "registro probatório")],
        "seguranca": ["Confirmar acesso aos ambientes e elementos abrangidos"]}
    return {"atividades":[("Caracterizar o objeto e registrar somente fatos observáveis pertinentes ao encargo.","Inspeção genérica controlada"),("Identificar documentos e grandezas indispensáveis sem aplicar método especializado não implementado.","Registro documental")],"medicoes":[],"fotos":["contexto geral do objeto pericial"],"equip": [("câmera","registro geral rastreável")],"seguranca":["Confirmar acesso seguro ao objeto da diligência"]}


def gerar(diretorio: Path) -> dict[str, Any]:
    processo_path, delimitacao_path = diretorio / "processo.json", diretorio / "delimitacao-pericial.json"
    processo = json.loads(processo_path.read_text(encoding="utf-8")); delimitacao = json.loads(delimitacao_path.read_text(encoding="utf-8"))
    from scripts.triagem_pericial.validar_delimitacao import validar_instancia,status_derivado
    erros_delimitacao=validar_instancia(delimitacao)
    if erros_delimitacao or status_derivado(delimitacao)!="APTO_PARA_PLANEJAMENTO":raise ValueError("delimitação inválida ou bloqueada no boundary de planejamento: "+"; ".join(erros_delimitacao+[status_derivado(delimitacao)]))
    tipo = delimitacao["tipo_pericia"]["tipo"]; perfil = _perfil(tipo)
    from scripts.triagem_pericial.capabilities import pode_planejar
    if not pode_planejar(tipo):raise ValueError("PERFIL_ESPECIALIZADO_NAO_IMPLEMENTADO: planejamento bloqueado para "+tipo)
    qts = [q["id"] for q in delimitacao["questoes_tecnicas"]]
    quesitos = [q for q in delimitacao["quesitos"] if q["pertinencia"] in {"PERTINENTE_TECNICO", "PERTINENTE_PARCIAL"}]
    algs = [a["id"] for a in processo["alegacoes"]];qt_por_id={q["id"]:q for q in delimitacao["questoes_tecnicas"]}
    sistemas = {a["sistema_alegado"] for a in processo["alegacoes"] if a["sistema_alegado"]}
    raiz_privada = diretorio.parent.parent
    conhecimento = _conhecimento(raiz_privada, tipo, sistemas)
    fundamentos = [c["fonte"] for c in conhecimento]
    atividades = []
    for i, qt_obj in enumerate(sorted(delimitacao["questoes_tecnicas"],key=lambda x:x["id"]), 1):
        qt=qt_obj["id"];verificar=qt_obj.get("descricao","");baixo=verificar.lower()
        metodo="Medição objetiva e inspeção visual" if any(t in baixo for t in ("abertura","extens","dimens","medir","quant")) else "Inspeção causal, confronto documental e teste de hipóteses" if any(t in baixo for t in ("causa","origem","mecanismo","decorre")) else "Inspeção visual sistemática"
        relacionados = [q["id"] for q in quesitos if qt in q["questoes_tecnicas_relacionadas"]]
        alg_qt=qt_por_id[qt].get("alegacoes_relacionadas",[])
        atividades.append({"id": f"ATV-{i:03d}", "verificar": verificar, "justificativa": "Obter evidência necessária ao saneamento do tema e dos quesitos pertinentes.",
                           "questoes_tecnicas": [qt], "quesitos": relacionados, "alegacoes": alg_qt, "metodo": metodo,
                           "fundamentos": fundamentos, "evidencia_esperada": "Registro objetivo, rastreável e sem conclusão causal antecipada.",
                           "obrigatoriedade": "OBRIGATORIA", "consequencia_se_nao_realizada": "Limitação da questão técnica e dos quesitos vinculados."})
    medicoes=[];fotografias=[]
    for qt in sorted(delimitacao["questoes_tecnicas"],key=lambda x:x["id"]):
        qid=qt["id"];descricao=qt.get("descricao","");baixo=descricao.lower();relacionados=[q["id"] for q in quesitos if qid in q["questoes_tecnicas_relacionadas"]]
        fotografias.append({"id":f"FOT-PLANO-{len(fotografias)+1:03d}","finalidade":f"Registrar evidência visual para {descricao}","enquadramento":"Contexto, aproximação e detalhe pertinente à QT.","questoes_tecnicas":[qid],"quesitos":relacionados,"alegacoes":qt.get("alegacoes_relacionadas",[])})
        if any(t in baixo for t in ("abertura","extens","dimens","medir","medição","quant")):
            medicoes.append({"id":f"MED-PLANO-{len(medicoes)+1:03d}","grandeza":"Grandeza indicada pela questão técnica","local":delimitacao["objeto_material"]["texto"],"motivo":descricao,"instrumento_sugerido":"Instrumento compatível com a grandeza","precisao_necessaria":None,"questoes_tecnicas":[qid],"quesitos":relacionados,"criterio":fundamentos[0] if fundamentos else None,"obrigatoriedade":"OBRIGATORIA","consequencia_ausencia":"Sem medição ou substituto equivalente, a conclusão quantitativa fica bloqueada."})
    ensaios=[]
    for qt in sorted(delimitacao["questoes_tecnicas"],key=lambda x:x["id"]):
        if any(t in qt.get("descricao","").lower() for t in ("ensaio","teste de")):
            ensaios.append({"id":f"ENS-PLANO-{len(ensaios)+1:03d}","nome":f"Ensaio requerido por {qt['id']}","classificacao":"INDISPENSAVEL","justificativa":qt["descricao"],"fundamento":None,"questoes_tecnicas":[qt["id"]],"conclusoes_limitadas_se_ausente":[qt["id"]]})
    documentos_caso=[d for d in delimitacao["documentos_ausentes"] if not str(d).casefold().startswith("base privada")]
    documentos_planejados=[]
    for d in documentos_caso:
        ligados=melhores(str(d),delimitacao["questoes_tecnicas"])
        if ligados:documentos_planejados.append({"id":f"DOC-PLANO-{len(documentos_planejados)+1:03d}","descricao":str(d),"questoes_tecnicas":ligados,"criterio_satisfacao":"Identidade documental e pertinência material verificadas para as QTs indicadas."})
    requisitos_cobertura=[]
    for tipo_req,chave in (("ATIVIDADE",atividades),("FOTOGRAFIA",fotografias),("MEDICAO",medicoes),("ENSAIO",ensaios),("DOCUMENTO",documentos_planejados)):
        for item in chave:
            for qt in item.get("questoes_tecnicas",[]):
                requisitos_cobertura.append({"questao_tecnica":qt,"tipo":tipo_req,"obrigatoriedade":"OBRIGATORIA","item_planejado":item["id"]})
    cobertura = []
    for q in quesitos:
        atvs = [a["id"] for a in atividades if any(qt in a["questoes_tecnicas"] for qt in q["questoes_tecnicas_relacionadas"])]
        alg_q={a for qt in q["questoes_tecnicas_relacionadas"] if qt in qt_por_id for a in qt_por_id[qt].get("alegacoes_relacionadas",[])}
        cobertura.append({"quesito": q["id"], "questoes_tecnicas": q["questoes_tecnicas_relacionadas"], "alegacoes": sorted(alg_q),
                          "atividades": atvs, "medicoes": [m["id"] for m in medicoes if any(qt in m["questoes_tecnicas"] for qt in q["questoes_tecnicas_relacionadas"])], "fotografias": [f["id"] for f in fotografias if any(qt in f["questoes_tecnicas"] for qt in q["questoes_tecnicas_relacionadas"])],
                          "ensaios": [e["id"] for e in ensaios if any(qt in e["questoes_tecnicas"] for qt in q["questoes_tecnicas_relacionadas"])], "documentos": [d["id"] for d in documentos_planejados if any(qt in d["questoes_tecnicas"] for qt in q["questoes_tecnicas_relacionadas"])], "planejada": False})
    calculada=recalcular_cobertura({"cobertura":cobertura,"requisitos_cobertura":requisitos_cobertura,"atividades":atividades,"medicoes":medicoes,"fotografias":fotografias,"ensaios":ensaios,"documentos_a_solicitar":documentos_planejados})
    for item in cobertura:item["planejada"]=calculada["cobertura"].get(item["quesito"],False)
    bloqueante = any(c["classificacao"] == "BLOQUEANTE" and c["status"] == "ABERTO" for c in delimitacao["conflitos"])
    lacuna_cobertura = any(not c["planejada"] for c in cobertura)
    status = "BLOQUEADO_PARA_VISTORIA" if bloqueante or lacuna_cobertura else "APTO_PARA_VISTORIA_COM_RESSALVAS" if delimitacao["ressalvas"] or delimitacao["documentos_ausentes"] else "APTO_PARA_VISTORIA"
    return {"schema_version": "2.0.0", "identificacao": {"gerado_em": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"), "processo_sha256": _hash(processo_path), "delimitacao_sha256": _hash(delimitacao_path)},
            "processo_cnj": processo["numero_processo"], "tipo_pericia": tipo, "tema_controvertido": delimitacao["tema_controvertido"]["texto"], "objeto": delimitacao["objeto_material"]["texto"],
            "questoes_tecnicas": qts, "quesitos_relacionados": [q["id"] for q in quesitos], "alegacoes_relacionadas": algs,
            "documentos_relevantes": [d["documento_id"] for d in delimitacao["documentos_relevantes"]], "documentos_ausentes": delimitacao["documentos_ausentes"],
            "conhecimento_recuperado": conhecimento, "ressalvas": [r["id"] for r in delimitacao["ressalvas"]], "conflitos": [c["id"] for c in delimitacao["conflitos"]],
            "atividades": atividades, "equipamentos": [{"nome": n, "finalidade": f, "questoes_tecnicas": qts} for n, f in perfil["equip"]],
            "medicoes": medicoes, "fotografias": fotografias, "ensaios": ensaios, "documentos_a_solicitar": documentos_planejados,
            "seguranca_e_acesso": perfil["seguranca"], "pontos_criticos": ["Não converter alegação em constatação", "Não concluir origem antes da análise pós-vistoria"],
            "pendencias": delimitacao["fatores_limitantes"], "cobertura": cobertura,"requisitos_cobertura":requisitos_cobertura,
            "autonomia": {"decisoes_autonomas": len(atividades)+len(medicoes)+len(fotografias), "ressalvas_autonomas": len(delimitacao["ressalvas"]),
                          "lacunas_resolvidas_sem_perguntar": len(delimitacao["documentos_ausentes"]),
                          "perguntas_evitadas_autonomamente": ["tipo de perícia", "tema controvertido", "quesitos", "atividades", "fotografias", "medições", "equipamentos"],
                          "perguntas_realmente_necessarias": []}, "status": status, "proveniencia": delimitacao["proveniencia"]}


def ficha(plano: dict) -> str:
    linhas = ["# Ficha pré-vistoria", "", f"**PROCESSO:** {plano['processo_cnj']}", f"**TIPO DE PERÍCIA:** {plano['tipo_pericia']}",
              f"**TEMA CONTROVERTIDO:** {plano['tema_controvertido']}", f"**OBJETO:** {plano['objeto']}", "", "## Questões técnicas a sanear", ""]
    linhas += [f"- {qt}" for qt in plano["questoes_tecnicas"]]
    for titulo, chave in (("Ressalvas importantes", "ressalvas"), ("Conflitos a verificar", "conflitos"), ("Documentos importantes", "documentos_relevantes")):
        linhas += ["", f"## {titulo}", ""] + ([f"- {x}" for x in plano[chave]] or ["- Nenhum registro nesta etapa."])
    linhas += ["", "## Verificações por local/sistema", ""]
    for a in plano["atividades"]:
        linhas += [f"### {a['id']}", "", f"- Verificar: {a['verificar']}", f"- Método: {a['metodo']}", f"- QT: {', '.join(a['questoes_tecnicas'])}", f"- Quesitos: {', '.join(a['quesitos']) or 'nenhum'}", f"- Alegações: {', '.join(a['alegacoes']) or 'nenhuma'}", ""]
    for titulo, chave, formato in (("Medições", "medicoes", lambda x: f"{x['id']}: {x['grandeza']} — {x['instrumento_sugerido']}"), ("Fotografias", "fotografias", lambda x: f"{x['id']}: {x['finalidade']}"), ("Equipamentos", "equipamentos", lambda x: f"{x['nome']}: {x['finalidade']}")):
        linhas += [f"## {titulo}", ""] + [f"- {formato(x)}" for x in plano[chave]] + [""]
    linhas += ["## Documentos a solicitar", ""] + ([f"- {x}" for x in plano["documentos_a_solicitar"]] or ["- Nenhum identificado."])
    linhas += ["", "## Pontos que não podem ser esquecidos", ""] + [f"- {x}" for x in plano["pontos_criticos"]]
    linhas += ["", "## Pendências", ""] + ([f"- {x}" for x in plano["pendencias"]] or ["- Nenhuma."])
    linhas += ["", f"**GATE:** {plano['status']}", "", "> Esta ficha orienta obtenção de evidências; não contém constatações ou conclusões antecipadas.", ""]
    return "\n".join(linhas)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("diretorios", nargs="+", type=Path)
    for diretorio in parser.parse_args().diretorios:
        plano = gerar(diretorio); (diretorio / "plano-vistoria.json").write_text(json.dumps(plano, ensure_ascii=False, indent=2)+"\n", encoding="utf-8", newline="\n")
        (diretorio / "ficha-pre-vistoria.md").write_text(ficha(plano), encoding="utf-8", newline="\n"); print(diretorio)
    return 0


if __name__ == "__main__": raise SystemExit(main())
