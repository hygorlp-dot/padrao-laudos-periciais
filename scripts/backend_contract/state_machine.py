from enum import StrEnum
from types import MappingProxyType

from .errors import DomainError


class CaseState(StrEnum):
    CRIADO = "CRIADO"
    AUTOS_IMPORTADOS = "AUTOS_IMPORTADOS"
    AUTOS_ANALISADOS = "AUTOS_ANALISADOS"
    DELIMITADO = "DELIMITADO"
    PLANO_GERADO = "PLANO_GERADO"
    VISTORIA_EM_ANDAMENTO = "VISTORIA_EM_ANDAMENTO"
    VISTORIA_CONCLUIDA = "VISTORIA_CONCLUIDA"
    ANALISE_TECNICA = "ANALISE_TECNICA"
    PAT_FINAL = "PAT_FINAL"
    REDACAO = "REDACAO"
    REVISAO = "REVISAO"
    ORCAMENTO = "ORCAMENTO"
    DOCUMENTO_FINAL = "DOCUMENTO_FINAL"
    ENCERRADO = "ENCERRADO"


_ORDER = tuple(CaseState)
_TRANSITIONS = MappingProxyType({
    **{state: frozenset({_ORDER[index + 1]}) for index, state in enumerate(_ORDER[:-1])},
    CaseState.ENCERRADO: frozenset(),
})


class CaseStateMachine:
    def __init__(self, state: CaseState = CaseState.CRIADO):
        self.state = state

    def transition(self, target: CaseState):
        if target not in _TRANSITIONS[self.state]:
            raise DomainError(f"Transição inválida: {self.state} -> {target}")
        self.state = target
        return self.state

    def snapshot(self):
        return self.state

    def restore(self, snapshot):
        self.state = snapshot
