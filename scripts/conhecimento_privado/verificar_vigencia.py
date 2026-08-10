"""Registra a verificação temporal explícita de uma fonte, sem presumir vigência."""
from __future__ import annotations
from datetime import datetime,timezone
def verificar(fonte,indicacao_oficial=None):
    resultado=dict(fonte);resultado["status_vigencia"]=indicacao_oficial or "PENDENTE_VERIFICACAO";resultado["verificado_em"]=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds");return resultado
