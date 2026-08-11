"""Extração determinística de campos da capa inicial do PJe."""
import re

CNJ=re.compile(r"\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b")
def _prov(leitor,pagina,trecho,encontrado=True):
    return {"arquivo":leitor.caminho.name,"sha256":leitor.sha256,"documento_id":None,"id_pje":None,"pagina_pdf":pagina,"pagina_documento":None,"pagina_original":None,"trecho":trecho,"natureza":"DOCUMENTADO" if encontrado else "INCONCLUSIVO","metodo_extracao":"CAMPO_ESTRUTURADO","confianca":{"nivel":"ALTA" if encontrado else "BAIXA"},"status_verificacao":"VERIFICADO" if encontrado else "INCONCLUSIVO"}
def _ocorrencias(textos,rotulos):
    return [(m.group(1).strip(),pagina,m.group(0)) for pagina,texto in textos for rotulo in rotulos for m in [re.search(rf"{rotulo}\s*:?\s*([^\n|]+)",texto,re.I)] if m and m.group(1).strip()]
def _campo(leitor,textos,rotulos):
    achados=_ocorrencias(textos,rotulos);por={}
    for valor,pagina,trecho in achados:por.setdefault(valor,[]).append(_prov(leitor,pagina,trecho))
    if len(por)>1:
        fontes=[f for grupo in por.values() for f in grupo];return {"valor":None,"motivo_ausencia":"CONFLITANTE","status":"CONFLITANTE","fontes":fontes,"proveniencia":_prov(leitor,None,None,False)}
    if por:
        valor=next(iter(por));fontes=por[valor];return {"valor":valor,"motivo_ausencia":None,"proveniencia":fontes[0],"fontes":fontes}
    return {"valor":None,"motivo_ausencia":"NAO_LOCALIZADO","proveniencia":_prov(leitor,None,None,False)}
def _flag(leitor,textos,rotulo):
    achados=[]
    for pagina,texto in textos:
        m=re.search(rf"{rotulo}\s*:?\s*(SIM|NÃO|NAO)",texto,re.I)
        if m:achados.append((m.group(1).upper()=="SIM",_prov(leitor,pagina,m.group(0))))
    valores={v for v,_ in achados}
    if len(valores)>1:return {"valor":None,"motivo_ausencia":"CONFLITANTE","status":"CONFLITANTE","fontes":[f for _,f in achados],"proveniencia":_prov(leitor,None,None,False)}
    if achados:return {"valor":achados[0][0],"motivo_ausencia":None,"proveniencia":achados[0][1]}
    return {"valor":None,"motivo_ausencia":"NAO_LOCALIZADO","proveniencia":_prov(leitor,None,None,False)}
def extrair_capa(leitor,paginas_iniciais):
    textos=[(p,leitor.texto(p)) for p in paginas_iniciais]
    cnjs=[(m.group(0),p,m.group(0)) for p,t in textos for m in CNJ.finditer(t)];numeros=list(dict.fromkeys(x for x,_,_ in cnjs));cnj=cnjs[0] if len(numeros)==1 else None
    numero=cnj[0] if cnj else "0000000-00.0000.0.00.0000"
    valor_achados=[(p,m) for p,t in textos for m in [re.search(r"Valor\s+da\s+causa\s*:?\s*R\$\s*([\d.]+,\d{2})",t,re.I)] if m];valores_causa={m.group(1) for _,m in valor_achados};valor_match=valor_achados[0][1] if len(valores_causa)==1 else None
    valor=float(valor_match.group(1).replace(".","").replace(",",".")) if valor_match else None
    valor_causa={"valor":valor,"moeda":"BRL" if valor is not None else None,"motivo_ausencia":None if valor is not None else "CONFLITANTE" if len(valores_causa)>1 else "NAO_LOCALIZADO","proveniencia":_prov(leitor,valor_achados[0][0] if valor_match else None,valor_match.group(0) if valor_match else None,bool(valor_match))}
    if len(valores_causa)>1:valor_causa.update(status="CONFLITANTE",fontes=[_prov(leitor,p,m.group(0)) for p,m in valor_achados])
    por_assunto={}
    for valor,pagina,trecho in _ocorrencias(textos,["Assunto(?:s)?"]):por_assunto.setdefault(valor,[]).append(_prov(leitor,pagina,trecho))
    assuntos=[{"valor":v,"motivo_ausencia":None,"proveniencia":fs[0],"fontes":fs} for v,fs in por_assunto.items()]
    campos={"tribunal":_campo(leitor,textos,["Tribunal"]),"secao":_campo(leitor,textos,["Seção","Secao"]),"subsecao":_campo(leitor,textos,["Subseção","Subsecao"]),"orgao_julgador":_campo(leitor,textos,["Órgão julgador","Orgao julgador"]),"classe":_campo(leitor,textos,["Classe judicial","Classe"])}
    flags={"segredo_justica":_flag(leitor,textos,"Segredo de justiça"),"justica_gratuita":_flag(leitor,textos,"Justiça gratuita"),"pedido_liminar":_flag(leitor,textos,"Pedido liminar")}
    conflitos=[]
    ultima=_campo(leitor,textos,["Última Distribuição","Ultima Distribuicao"])
    candidatos=[("processo.numero_cnj",{"status":"CONFLITANTE","fontes":[_prov(leitor,p,t) for _,p,t in cnjs],"valores":numeros} if len(numeros)>1 else {}),("processo.valor_causa",valor_causa),("ultima_distribuicao",ultima),*((f"processo.{k}",v) for k,v in campos.items()),*((f"processo.flags.{k}",v) for k,v in flags.items())]
    for campo,dado in candidatos:
        if dado.get("status")=="CONFLITANTE":conflitos.append({"campo":campo,"valores":dado.get("valores") or [f["trecho"] for f in dado["fontes"]],"fontes":dado["fontes"],"bloqueante":campo in {"processo.numero_cnj","processo.flags.segredo_justica"}})
    return {"processo":{"numero_cnj":{"valor":numero,"proveniencia":_prov(leitor,cnj[1] if cnj else None,numero if cnj else None,bool(cnj))},**campos,"assuntos":assuntos,"valor_causa":valor_causa,"flags":flags},"ultima_distribuicao":ultima,"cnj_localizado":bool(cnj),"conflitos":conflitos}
