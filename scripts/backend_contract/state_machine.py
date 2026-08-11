from dataclasses import dataclass
from datetime import datetime, timezone
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


@dataclass(frozen=True, slots=True)
class TransitionRecord:
    origin: CaseState
    destination: CaseState
    reason: str
    timestamp: str
    operation: str


class CaseStateMachine:
    def __init__(self, state: CaseState = CaseState.CRIADO):
        self.state = state
        self._history = []

    @property
    def history(self):
        return tuple(self._history)

    def _record(self, origin, target, reason, operation):
        self._history.append(TransitionRecord(
            origin, target, reason, datetime.now(timezone.utc).isoformat(), operation,
        ))

    def transition(self, target: CaseState):
        if target not in _TRANSITIONS[self.state]:
            raise DomainError(f"Transição inválida: {self.state} -> {target}")
        origin = self.state
        self.state = target
        self._record(origin, target, "AVANCO_NORMAL", "ADVANCE")
        return self.state

    def reopen(self, target: CaseState, reason: str):
        if not reason or not reason.strip():
            raise DomainError("Reabertura exige motivo")
        index = _ORDER.index(self.state)
        expected = _ORDER[index - 1] if index else None
        if target is not expected:
            raise DomainError(f"Retorno inválido: {self.state} -> {target}")
        origin = self.state
        self.state = target
        self._record(origin, target, reason.strip(), "REOPEN")
        return self.state

    def snapshot(self):
        return self.state, list(self._history)

    def restore(self, snapshot):
        self.state, self._history = snapshot
