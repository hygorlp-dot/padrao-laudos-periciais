"""Utilitários determinísticos para vínculos semânticos auditáveis."""
from __future__ import annotations
import re
import unicodedata

PARADAS={"a","ao","as","com","da","das","de","do","dos","e","em","na","no","o","os","ou","para","por","que","se","um","uma"}
INTENCOES={"JURIDICO":("indenizar","responsavel","responsabilizar","culpa","prescricao","decadencia","legitimidade","obrigacao de pagar"),"ORCAMENTO":("custo","valor do reparo","orcamento","quantificar"),"CAUSALIDADE":("causa","decorre","provocou","motivo","por que"),"ORIGEM":("origem","endogena","exogena","construtiva","funcional"),"MECANISMO":("mecanismo",),"EXISTENCIA":("existe","presente","constatada","há fissura","ha fissura"),"SEGURANCA":("risco","seguranca","estrutural"),"REPARO":("reparo","corrigir","solucao"),"CONFORMIDADE":("norma","conforme","requisito"),"METODOLOGIA":("metodo","procedimento","ensaio")}
def normalizar(texto): return re.sub(r"\s+"," ",unicodedata.normalize("NFKD",texto or "").encode("ascii","ignore").decode().lower()).strip()
def termos(texto): return {x for x in re.findall(r"[a-z0-9]+",normalizar(texto)) if len(x)>2 and x not in PARADAS}
def afinidade(a,b):
    ea,eb=termos(a),termos(b)
    return len(ea&eb)/len(ea|eb) if ea and eb else 0.0
def intencoes(texto):
    n=normalizar(texto);return [nome for nome,padroes in INTENCOES.items() if any(normalizar(p) in n for p in padroes)]
def intencao(texto):
    achados=intencoes(texto)
    return achados[0] if len(achados)==1 else "MISTO" if achados else "CARACTERIZACAO"
def melhores(texto,candidatos,campo="descricao",minimo=.04):
    it=intencao(texto);pontos=[(afinidade(texto,x.get(campo))+(0.35 if it!="CARACTERIZACAO" and intencao(x.get(campo))==it else 0),x["id"]) for x in candidatos]
    maior=max((x[0] for x in pontos),default=0)
    aceitos=[x for x in pontos if x[0]>=minimo and abs(x[0]-maior)<=0.05]
    return [i for _,i in sorted(aceitos,key=lambda x:(-x[0],x[1]))]
