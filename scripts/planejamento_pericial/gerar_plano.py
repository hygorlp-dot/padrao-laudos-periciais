"""Gera plano-vistoria.json específico ao tipo pericial e ficha de campo."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


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
    return {"atividades": [
        ("Localizar e caracterizar objetivamente cada manifestação alegada, sem presumir origem.", "Inspeção visual sistemática"),
        ("Examinar interfaces, extensão e sinais associados relevantes à análise causal futura.", "Inspeção visual e medição pertinente"),
        ("Confrontar alegações, condições observáveis e documentação construtiva disponível.", "Rastreabilidade documental e de campo")],
        "medicoes": [("extensão e dimensão das manifestações identificáveis", "trena, régua ou fissurômetro conforme a grandeza")],
        "fotos": ["contexto do ambiente e sistema", "aproximação da manifestação alegada", "detalhe com escala e interface correlata"],
        "equip": [("trena", "extensão e localização"), ("régua/fissurômetro", "dimensões compatíveis com fissuras"), ("medidor de umidade", "indícios de umidade quando alegados"), ("câmera", "registro probatório")],
        "seguranca": ["Confirmar acesso aos ambientes e elementos abrangidos"]}


def gerar(diretorio: Path) -> dict[str, Any]:
    processo_path, delimitacao_path = diretorio / "processo.json", diretorio / "delimitacao-pericial.json"
    processo = json.loads(processo_path.read_text(encoding="utf-8")); delimitacao = json.loads(delimitacao_path.read_text(encoding="utf-8"))
    tipo = delimitacao["tipo_pericia"]["tipo"]; perfil = _perfil(tipo)
    qts = [q["id"] for q in delimitacao["questoes_tecnicas"]]
    quesitos = [q for q in delimitacao["quesitos"] if q["pertinencia"] in {"PERTINENTE_TECNICO", "PERTINENTE_PARCIAL"}]
    algs = [a["id"] for a in processo["alegacoes"]]
    sistemas = {a["sistema_alegado"] for a in processo["alegacoes"] if a["sistema_alegado"]}
    raiz_privada = diretorio.parent.parent
    conhecimento = _conhecimento(raiz_privada, tipo, sistemas)
    fundamentos = [c["fonte"] for c in conhecimento]
    atividades = []
    for i, (verificar, metodo) in enumerate(perfil["atividades"], 1):
        qt = qts[(i - 1) % len(qts)]
        relacionados = [q["id"] for q in quesitos if qt in q["questoes_tecnicas_relacionadas"]]
        atividades.append({"id": f"ATV-{i:03d}", "verificar": verificar, "justificativa": "Obter evidência necessária ao saneamento do tema e dos quesitos pertinentes.",
                           "questoes_tecnicas": [qt], "quesitos": relacionados, "alegacoes": algs[:30], "metodo": metodo,
                           "fundamentos": fundamentos, "evidencia_esperada": "Registro objetivo, rastreável e sem conclusão causal antecipada.",
                           "obrigatoriedade": "OBRIGATORIA", "consequencia_se_nao_realizada": "Limitação da questão técnica e dos quesitos vinculados."})
    medicoes = [{"id": f"MED-PLANO-{i:03d}", "grandeza": grandeza, "local": delimitacao["objeto_material"]["texto"],
                 "motivo": "Produzir dado objetivo pertinente às questões técnicas.", "instrumento_sugerido": instrumento,
                 "precisao_necessaria": None, "questoes_tecnicas": qts, "quesitos": [q["id"] for q in quesitos],
                 "criterio": fundamentos[0] if fundamentos else None, "obrigatoriedade": "CONDICIONAL",
                 "consequencia_ausencia": "A conclusão quantitativa correspondente poderá ficar limitada."}
                for i, (grandeza, instrumento) in enumerate(perfil["medicoes"], 1)]
    fotografias = [{"id": f"FOT-PLANO-{i:03d}", "finalidade": finalidade, "enquadramento": finalidade,
                    "questoes_tecnicas": qts, "quesitos": [q["id"] for q in quesitos], "alegacoes": algs[:30]}
                   for i, finalidade in enumerate(perfil["fotos"], 1)]
    cobertura = []
    for q in quesitos:
        atvs = [a["id"] for a in atividades if any(qt in a["questoes_tecnicas"] for qt in q["questoes_tecnicas_relacionadas"])]
        cobertura.append({"quesito": q["id"], "questoes_tecnicas": q["questoes_tecnicas_relacionadas"], "alegacoes": algs[:30],
                          "atividades": atvs, "medicoes": [m["id"] for m in medicoes], "fotografias": [f["id"] for f in fotografias],
                          "ensaios": [], "documentos": processo["documentos_tecnicos"], "planejada": bool(atvs or medicoes or fotografias)})
    bloqueante = any(c["classificacao"] == "BLOQUEANTE" and c["status"] == "ABERTO" for c in delimitacao["conflitos"])
    lacuna_cobertura = any(not c["planejada"] for c in cobertura)
    status = "BLOQUEADO_PARA_VISTORIA" if bloqueante or lacuna_cobertura else "APTO_PARA_VISTORIA_COM_RESSALVAS" if delimitacao["ressalvas"] or delimitacao["documentos_ausentes"] else "APTO_PARA_VISTORIA"
    return {"schema_version": "1.0.0", "identificacao": {"gerado_em": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"), "processo_sha256": _hash(processo_path), "delimitacao_sha256": _hash(delimitacao_path)},
            "processo_cnj": processo["numero_processo"], "tipo_pericia": tipo, "tema_controvertido": delimitacao["tema_controvertido"]["texto"], "objeto": delimitacao["objeto_material"]["texto"],
            "questoes_tecnicas": qts, "quesitos_relacionados": [q["id"] for q in quesitos], "alegacoes_relacionadas": algs,
            "documentos_relevantes": [d["documento_id"] for d in delimitacao["documentos_relevantes"]], "documentos_ausentes": delimitacao["documentos_ausentes"],
            "conhecimento_recuperado": conhecimento, "ressalvas": [r["id"] for r in delimitacao["ressalvas"]], "conflitos": [c["id"] for c in delimitacao["conflitos"]],
            "atividades": atividades, "equipamentos": [{"nome": n, "finalidade": f, "questoes_tecnicas": qts} for n, f in perfil["equip"]],
            "medicoes": medicoes, "fotografias": fotografias, "ensaios": [], "documentos_a_solicitar": delimitacao["documentos_ausentes"],
            "seguranca_e_acesso": perfil["seguranca"], "pontos_criticos": ["Não converter alegação em constatação", "Não concluir origem antes da análise pós-vistoria"],
            "pendencias": delimitacao["fatores_limitantes"], "cobertura": cobertura,
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
