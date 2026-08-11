"""Taxonomia probatória first-party compartilhada por inferência e auditorias."""
import re
DIMENSOES_CONSTRUTIVAS={"PROJETO_CONSTRUTIVO_DOCUMENTADO","MATERIAL_CONSTRUTIVO_DOCUMENTADO","ESPECIFICACAO_CONSTRUTIVA_DOCUMENTADA","DETALHE_CONSTRUTIVO_DOCUMENTADO","PROCEDIMENTO_EXECUTIVO_DOCUMENTADO","CONTROLE_TECNOLOGICO_DOCUMENTADO","DOCUMENTACAO_OBRA_VERIFICADA"}
DIVERGENCIAS_CONSTRUTIVAS={"EXECUCAO_DIVERGENTE_DOCUMENTADA","NAO_CONFORMIDADE_CONSTRUTIVA_VERIFICADA"}
def aspectos(evidencias):return {a for e in evidencias for a in e.get("aspectos_suportados",[])}
def identidade_fontes(evidencia):
    fontes=set()
    for origem in evidencia.get("proveniencia",[]) or []:
        if isinstance(origem,dict):
            identidade=(origem.get("documento_id") or origem.get("sha256") or
                        origem.get("arquivo") or origem.get("id_pje"))
        else:
            identidade=re.sub(r"(?i):p(?:ag(?:ina)?)?\.?\s*\d+$","",str(origem))
        if identidade:fontes.add(str(identidade))
    return fontes or {str(evidencia.get("id"))}
def fontes_independentes(evidencias,sinais):
    return {fonte for e in evidencias if set(e.get("aspectos_suportados",[]))&set(sinais) for fonte in identidade_fontes(e)}
def suporte_endogeno(evidencias):
    encontrados=aspectos(evidencias)
    return bool(encontrados&DIMENSOES_CONSTRUTIVAS and encontrados&DIVERGENCIAS_CONSTRUTIVAS and len(fontes_independentes(evidencias,DIMENSOES_CONSTRUTIVAS|DIVERGENCIAS_CONSTRUTIVAS))>=2)
