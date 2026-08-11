"""Camada determinística de redação pericial a partir do PAT_FINAL."""

from .auditar_estilo import auditar_estilo, auditar_redundancia_estrutural
from .auditar_fidelidade import auditar_fidelidade, auditar_grounding_redacao
from .autocorrigir_redacao import autocorrigir
from .pipeline import executar_pipeline_redacao
from .planejar_redacao import planejar
from .redigir import redigir

__all__ = [
    "auditar_estilo",
    "auditar_redundancia_estrutural",
    "auditar_fidelidade",
    "auditar_grounding_redacao",
    "autocorrigir",
    "executar_pipeline_redacao",
    "planejar",
    "redigir",
]
