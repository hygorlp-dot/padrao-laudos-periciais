"""Normalização e auditoria estrutural de datas autorizadas."""
import re
from datetime import datetime

MESES={"janeiro":1,"fevereiro":2,"marco":3,"março":3,"abril":4,"maio":5,"junho":6,"julho":7,"agosto":8,"setembro":9,"outubro":10,"novembro":11,"dezembro":12}
PADROES=(r"(?<![\d.-])(\d{4}-\d{2}-\d{2})(?:T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?)?",r"(?<!\d)(\d{2}[/-]\d{2}[/-]\d{4})(?!\d)")
def extrair_datas(texto):
    saida=[]
    for padrao in PADROES:
        for valor in re.findall(padrao,texto or ""):
            for formato in ("%Y-%m-%d","%d/%m/%Y","%d-%m-%Y"):
                try:saida.append(datetime.strptime(valor,formato).date().isoformat());break
                except ValueError:pass
    for dia,mes,ano in re.findall(r"\b(\d{1,2})\s+de\s+([a-zç]+)\s+de\s+(\d{4})\b",(texto or "").casefold()):
        if mes in MESES:
            try:saida.append(datetime(int(ano),MESES[mes],int(dia)).date().isoformat())
            except ValueError:pass
    return list(dict.fromkeys(saida))
def auditar_datas(texto,fontes):
    atuais=set(extrair_datas(texto));autorizadas={d for f in fontes for d in extrair_datas(str(f))}
    return [{"tipo":"DATA_INVENTADA" if not autorizadas else "DATA_ALTERADA","severidade":"CRITICO","data":d,"bloqueante":True} for d in sorted(atuais-autorizadas)]
