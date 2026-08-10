"""APIs públicas da auditoria pericial desacoplada do motor."""
from .detector import executar_detector
from .grounding import auditar_claim, auditar_aspecto, extrair_claims
from .deep_audit import executar_deep_audit
from .trilha import registrar_trilha
from .orquestrar import executar_auditoria_integrada
from .proposition import auditar_proposicoes
__all__=["executar_detector","auditar_claim","auditar_aspecto","extrair_claims","executar_deep_audit","registrar_trilha","executar_auditoria_integrada","auditar_proposicoes"]
