"""Propõe QT específicas por manifestação/local/sistema, sem duplicar alegações equivalentes."""
from __future__ import annotations
import re,unicodedata

def _n(s):return re.sub(r"\W+"," ",unicodedata.normalize("NFKD",s or "").encode("ascii","ignore").decode().lower()).strip()
def granularizar(processo,delimitacao):
    existentes=list(delimitacao.get("questoes_tecnicas",[])); grupos={}
    for a in processo.get("alegacoes",[]):
        man=a.get("manifestacao_alegada")
        if not man:continue
        chave=(_n(man),_n(a.get("ambiente_alegado")),_n(a.get("sistema_alegado")))
        grupos.setdefault(chave,[]).append(a["id"])
    saida=[];inicio=len(existentes)+1
    for i,((man,amb,sis),algs) in enumerate(grupos.items(),inicio):
        local=f" em {amb}" if amb else ""; sistema=f" no sistema {sis}" if sis else ""
        saida.append({"id":f"QT-{i:03d}","descricao":f"A manifestação {man}{local}{sistema} está presente e, se confirmada, qual mecanismo e causa são tecnicamente sustentáveis?","alegacoes_relacionadas":sorted(set(algs))})
    return saida
