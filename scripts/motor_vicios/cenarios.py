"""Executor observável dos cenários de risco do Motor V1."""
from .evidencias import construir_catalogo,pontuar_associacao
from .normas import avaliar_conformidade_normativa
from .regras import situacao,inferir_origem,classificacoes,avaliar_consequencias,derivar_criticidade,tipo_vicio

def _catalogo_textos(textos):
    obs=[{"id":f"OBS-{i:03d}","descricao_objetiva":t,"resultado":"OBSERVADO","proveniencia":[f"FONTE-{i:03d}"]} for i,t in enumerate(textos,1)]
    return construir_catalogo({"observacoes":obs})

def executar_cenario(entrada):
    op=entrada["operacao"]
    if op=="situacao":return situacao(entrada["observacoes"])
    if op=="origem":return inferir_origem(entrada["causa"],_catalogo_textos(entrada["textos"]))
    if op=="norma":
        evidencias=[{"id":m["id"],"tipo":"MEDICAO",**m} for m in entrada["medicoes"]];return avaliar_conformidade_normativa(entrada["norma"],evidencias)["resultado"]
    if op=="aspectos_foto":
        f={"id":"FOT-001",**entrada,"proveniencia":["ARQ-001"]};return sorted(construir_catalogo({"fotografias":[f]})[0]["aspectos_suportados"])
    if op=="associacao":return pontuar_associacao(entrada["evidencia"],entrada["contexto"])["confianca"]
    if op=="elegibilidade":return classificacoes("ANOMALIA",entrada["causalidade"])[3]
    if op=="criticidade":return derivar_criticidade("ANOMALIA",avaliar_consequencias("ANOMALIA",_catalogo_textos([entrada["texto"]])))[0]
    if op=="tipo_vicio":return tipo_vicio(_catalogo_textos([entrada["texto"]]),True)
    raise ValueError(f"operação de cenário desconhecida: {op}")
