"""Autoauditoria causal e relacional do resultado do motor."""
import re

def auditar(resultado, vistoria=None):
    achados=[]
    def add(tipo,desc,evid,bloq=True):
        achados.append({"id":f"AUD-{len(achados)+1:03d}","severidade":"BLOQUEANTE" if bloq else "RELEVANTE","tipo":tipo,"descricao":desc,"evidencias":evid,"bloqueante":bloq})
    hips={h["id"]:h for h in resultado.get("hipoteses",[])}
    vistoria=vistoria or {};medicoes={m["id"] for m in vistoria.get("medicoes",[])};fotos={f["id"] for f in vistoria.get("fotografias",[])};observacoes={o["id"] for o in vistoria.get("observacoes",[])}
    for p in resultado.get("patologias",[]):
        pid=p["id"]
        if p["causa"] and not p["analise_causal"]["fundamentos"]:add("CAUSA_SEM_EVIDENCIA","Causa registrada sem fundamento rastreável.",[pid])
        if p["mecanismo"] and not p["hipoteses"]:add("MECANISMO_SEM_HIPOTESE","Mecanismo registrado sem hipótese testada.",[pid])
        if p["vicio_construtivo"]["caracterizado"] and p["origem"]!="ENDOGENA_CONSTRUTIVA":add("VICIO_SEM_ORIGEM_ENDOGENA","Vício incompatível com origem.",[pid])
        if p["origem"] not in {"INCONCLUSIVA","NAO_APLICAVEL"} and not p["causa"]:add("ORIGEM_SEM_ANALISE_CAUSAL","Origem definida sem causa sustentada.",[pid])
        if p["criticidade"] not in {"NAO_APLICAVEL","INCONCLUSIVA"} and not any(p["consequencias"].values()):add("CRITICIDADE_SEM_FUNDAMENTACAO","Criticidade definida sem consequência técnica registrada.",[pid])
        if p["constatacao"]["situacao"]=="NAO_CONSTATADA" and "inexist" in p["conclusao_tecnica"].lower():add("NAO_CONSTATADA_COMO_INEXISTENTE","Ausência de constatação foi convertida em inexistência.",[pid])
        if p["elegibilidade_orcamento"]=="ELEGIVEL_ORCAMENTO_VICIO" and not p["vicio_construtivo"]["caracterizado"]:add("ORCAMENTO_SEM_VICIO","Elegibilidade sem requisitos cumulativos.",[pid])
        if p["constatacao"]["situacao"]=="CONFORME" and p["elegibilidade_orcamento"]!="NAO_ELEGIVEL":add("CONFORMIDADE_ELEGIVEL_ORCAMENTO","Conformidade não pode gerar item de vício.",[pid])
        if p["constatacao"]["situacao"]=="INCONCLUSIVA" and p["vicio_construtivo"]["caracterizado"]:add("INCONCLUSIVA_COM_VICIO","Inconclusividade incompatível com vício confirmado.",[pid])
        faltam_med=set(p["medicoes"])-medicoes if vistoria else set();faltam_fot=set(p["constatacao"]["fotografias"])-fotos if vistoria else set();faltam_obs=set(p["constatacoes"])-observacoes if vistoria else set()
        if faltam_med:add("PAT_MEDICAO_INEXISTENTE","PAT referencia medição ausente da vistoria.",[pid]+sorted(faltam_med))
        if faltam_fot:add("PAT_FOTOGRAFIA_INEXISTENTE","PAT referencia fotografia ausente da vistoria.",[pid]+sorted(faltam_fot))
        if faltam_obs:add("PAT_OBSERVACAO_INEXISTENTE","PAT referencia observação ausente da vistoria.",[pid]+sorted(faltam_obs))
        if any(n.get("item") and not n.get("verificada") for n in p["normas_relacionadas"]):add("NORMA_NAO_VERIFICADA_COMO_FUNDAMENTO","Item normativo não verificado foi associado ao PAT.",[pid])
        if any(str(f).startswith("MOD-") for f in p["analise_causal"]["fundamentos"]):add("CONTAMINACAO_REFERENCIAL","Caso anterior foi usado como fundamento factual da causa atual.",[pid])
        if p["vicio_construtivo"]["caracterizado"] and p["vicio_construtivo"].get("tipo")=="NAO_APLICAVEL":add("TIPO_VICIO_INVALIDO","Vício caracterizado não pode possuir tipo não aplicável.",[pid])
        texto=" ".join(filter(None,[p.get("conclusao_tecnica"),p.get("constatacao",{}).get("descricao")]))
        for mid in p.get("medicoes",[]):
            med=next((m for m in vistoria.get("medicoes",[]) if m["id"]==mid),None)
            if not med or med.get("valor") is None:continue
            valores=[float(x.replace(",",".")) for x in re.findall(r"(?<!\w)(\d+(?:[.,]\d+)?)\s*"+re.escape(str(med.get("unidade") or ""))+r"\b",texto,re.I)]
            if valores and all(abs(v-float(med["valor"]))>1e-9 for v in valores):add("CONTRADICAO_MEDICAO","Valor textual do PAT diverge da medição referenciada.",[pid,mid])
        baixo=texto.lower()
        for oid in p.get("constatacoes",[]):
            ob=next((o for o in vistoria.get("observacoes",[]) if o["id"]==oid),None)
            if ob and "abriu e fechou normalmente" in ob.get("descricao_objetiva","").lower() and any(x in baixo for x in ("falha funcional","não funciona","nao funciona")):add("PAT_OBS_CONTRADICAO","Conclusão contradiz a observação objetiva.",[pid,oid])
        if any("não foi possível determinar a causa" in str(x).lower() or "causalidade inconclusiva" in str(x).lower() for x in p.get("ressalvas",[])) and any(x in baixo for x in ("definitivamente","causa é","causa e")):add("CONCLUSAO_RESSALVA_CONTRADICAO","Conclusão absoluta contradiz ressalva causal.",[pid])
        for hid in p["hipoteses"]:
            if hid not in hips:add("HIPOTESE_INEXISTENTE","PAT referencia hipótese inexistente.",[pid,hid])
    return achados
