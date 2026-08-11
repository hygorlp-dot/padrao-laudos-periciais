from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InvariantViolation:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class Invariant:
    code: str
    message: str
    predicate: object


class InvariantRegistry:
    def __init__(self, invariants=()):
        self._invariants = {item.code: item for item in invariants}

    def validate(self, context):
        return tuple(
            InvariantViolation(item.code, item.message)
            for item in self._invariants.values() if not item.predicate(context)
        )

    def require(self, context):
        violations = self.validate(context)
        if violations:
            from .errors import DomainError
            raise DomainError("; ".join(item.code for item in violations))


def default_invariants():
    rules = (
        ("ALEGACAO_NAO_E_CONSTATACAO", "Alegação não pode ser promovida a constatação.", "allegation_as_observation"),
        ("DECLARACAO_NAO_E_OBS", "Declaração de terceiro não é observação pericial.", "declaration_as_observation"),
        ("NORMA_NAO_E_EVIDENCIA_FISICA", "Norma não é evidência física.", "norm_as_physical_evidence"),
        ("NAO_CONSTATADA_NAO_E_INEXISTENTE", "Não constatada não implica inexistência.", "not_observed_as_nonexistent"),
        ("ORIGEM_REQUER_CAUSA", "Origem requer suporte causal.", "origin_without_causal_support"),
        ("QUESITO_NAO_CRIA_ANALISE", "Conclusão de quesito não cria análise nova.", "question_creates_analysis"),
        ("REDACAO_NAO_ALTERA_PAT", "Redação não altera PAT_FINAL.", "draft_changes_final_pat"),
        ("STALE_NAO_E_ATUAL", "Artefato STALE não pode ser usado como atual.", "stale_used_as_current"),
        ("OVERRIDE_PRESERVA_HISTORICO", "Override profissional preserva histórico.", "override_erases_history"),
    )
    return tuple(Invariant(code, message, lambda ctx, key=key: not ctx.get(key, False)) for code, message, key in rules)
