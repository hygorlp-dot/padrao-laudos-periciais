"""Gera hipóteses e testa cadeias de aspectos observáveis independentes."""
from __future__ import annotations

CATALOGO={
 "IMPERMEABILIZACAO":[("ingresso de água por interface","falha de vedação",{"INTERFACE_IDENTIFICADA","VEDACAO_DETERIORADA","PRECIPITACAO_REGISTRADA"},{"VEDACAO_INTEGRA"}),("aporte por instalação","vazamento hidrossanitário",{"VAZAMENTO_OBSERVADO","RESULTADO_ENSAIO"},{"AUSENCIA_VAZAMENTO_NO_ENSAIO"})],
 "REVESTIMENTOS":[("perda de aderência","deficiência na interface de assentamento",{"REGISTRO_VISUAL_INTERPRETADO","CONSTATACAO_DE_VISTORIA","INTERFACE_IDENTIFICADA"},{"IMPACTO_REGISTRADO"}),("solicitação mecânica","impacto ou intervenção posterior",{"IMPACTO_REGISTRADO","INTERVENCAO_TERCEIRO_DOCUMENTADA"},set())],
 "ESQUADRIAS":[("perda funcional","desgaste, ajuste ou manutenção",{"PERDA_FUNCIONAL_REGISTRADA","MANUTENCAO_AUSENTE_DOCUMENTADA"},set())],
 "ESTRUTURA":[("deformação ou fissuração estrutural","solicitação ou movimentação estrutural",{"RISCO_SEGURANCA_REGISTRADO","MEDICAO_REGISTRADA"},set())],
 "OUTRO":[(None,None,set(),set())],
}

SISTEMAS_AUDITADOS=("IMPERMEABILIZACAO","REVESTIMENTOS","ESQUADRIAS","ESTRUTURA","VEDACOES","PINTURA","COBERTURA","FORROS","INSTALACOES_ELETRICAS","INSTALACOES_HIDROSSANITARIAS","DRENAGEM","OUTRO")
def capacidade_causal(sistema):
    especificas=CATALOGO.get(sistema,[])
    implementado=bool(especificas and any(x[0] and x[1] and x[2] for x in especificas))
    nivel="SUPORTE_CAUSAL_PARCIAL" if implementado else "MOTOR_CAUSAL_NAO_IMPLEMENTADO"
    return {"sistema":sistema or "OUTRO","manifestacoes_especificas":[],"hipoteses_especificas":[x[1] for x in especificas if x[1]],"mecanismos":[x[0] for x in especificas if x[0]],"evidencias_uteis":sorted({a for x in especificas for a in x[2]|x[3]}),"nivel_de_capacidade":nivel}

def candidatos(sistema,manifestacao):
    return CATALOGO.get(sistema,CATALOGO["OUTRO"])

def relacionar_evidencias(catalogo,hipotese):
    favor=[];contra=[];requeridos=set(hipotese[2]);contrarios=set(hipotese[3])
    for e in catalogo:
        aspectos=set(e.get("aspectos_suportados",[]))
        if aspectos&requeridos:favor.append(e["id"])
        if aspectos&contrarios:contra.append(e["id"])
    cobertura=set().union(*(set(e.get("aspectos_suportados",[])) for e in catalogo if e["id"] in favor)) if favor else set()
    return sorted(set(favor)),sorted(set(contra)),sorted(requeridos&cobertura)

def _independentes(ids,catalogo):
    mapa={e["id"]:e for e in catalogo};return len({tuple(mapa[i].get("proveniencia",[])) or (i,) for i in ids if i in mapa})

def gerar(manifestacao,man_id,evidencias=None,ausentes=None,inicio=1,*,sistema=None,catalogo=None,normas=None):
    catalogo=catalogo or [];saida=[]
    if capacidade_causal(sistema)["nivel_de_capacidade"]=="MOTOR_CAUSAL_NAO_IMPLEMENTADO":return saida
    man_num=int(man_id.split("-",1)[1]) if man_id.split("-",1)[1].isdigit() else inicio
    for ordem,hip in enumerate(candidatos(sistema,manifestacao),1):
        i=man_num*100+ordem
        mec,causa,requeridos,_=hip;favor,contra,cobertos=relacionar_evidencias(catalogo,hip) if catalogo else ([],[],[]);fi=_independentes(favor,catalogo);ci=_independentes(contra,catalogo);cobertura=len(set(cobertos))/max(1,len(requeridos))
        if ci>=1 and not fi:status="AFASTADA";comp="INCOMPATIVEL"
        elif ci and fi:status="POSSIVEL";comp="PARCIALMENTE_COMPATIVEL"
        elif fi>=2 and cobertura==1:status="MAIS_PROVAVEL";comp="COMPATIVEL"
        elif fi and cobertura>=.5:status="FORTALECIDA";comp="COMPATIVEL"
        else:status="NAO_TESTAVEL";comp="NAO_AVALIAVEL"
        saida.append({"id":f"HIP-{i:03d}","manifestacao":man_id,"descricao":f"Hipótese de {causa or 'mecanismo ainda não determinado'}","mecanismo":mec,"causa_candidata":causa,"aspectos_requeridos":sorted(requeridos),"aspectos_cobertos":cobertos,"evidencias_favoraveis":favor,"evidencias_contrarias":contra,"evidencias_ausentes":sorted(set(requeridos)-set(cobertos)) or list(ausentes or []),"normas":[n["id"] for n in normas or [] if n.get("aplicabilidade_temporal")!="NAO_APLICAVEL"],"literatura":[],"modelos_referenciais":[],"compatibilidade_tecnica":comp,"confianca":{"nivel":"ALTA" if status=="MAIS_PROVAVEL" else "MEDIA" if status in {"FORTALECIDA","AFASTADA"} else "BAIXA"},"status":status,"motivo_status":"Cobertura dos aspectos observáveis, independência e contradições foram confrontadas.","proveniencia":sorted(set(favor+contra))})
    return saida
