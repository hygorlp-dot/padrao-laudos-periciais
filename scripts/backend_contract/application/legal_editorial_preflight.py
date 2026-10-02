"""Pré-verificação jurídico-editorial do laudo da perícia (#272)."""

from __future__ import annotations

from dataclasses import dataclass

from ..installation_settings import DEFAULT_LEGAL_EDITORIAL
from .. import legal_editorial_preflight as _preflight

PROFILE_LABEL = "Sistema Pericial — CNJ/TRF5"
# Natureza de cada fonte: nada aqui é apresentado como formatação obrigatória.
REFERENCE_SOURCES = (
    {"name": "Recomendação CNJ nº 144/2023 (linguagem simples)", "nature": "RECOMMENDATORY"},
    {"name": "Lei nº 15.263/2025, art. 5º (linguagem simples na administração pública)", "nature": "MANDATORY"},
    {"name": "Manual Justiça Plural, capítulo 4", "nature": "INSTITUTIONAL"},
    {"name": "Orientações do TRF5 sobre linguagem simples", "nature": "INSTITUTIONAL"},
)


@dataclass(frozen=True, slots=True)
class GetReportPreflight:
    """Avisos sobre o laudo vigente, com o perfil capturado pela perícia; nada é gravado."""
    get_report: object
    get_workspace_settings: object | None = None

    def execute(self, workspace_id) -> dict:
        record, report = self.get_report.execute(workspace_id)
        profile = DEFAULT_LEGAL_EDITORIAL
        if self.get_workspace_settings is not None:
            _settings_record, settings = self.get_workspace_settings.current(workspace_id)
            if settings is not None:
                profile = settings.legal_editorial
        result = _preflight.legal_editorial_preflight(report, profile)
        findings = [
            {
                "code": item.code.value, "severity": item.severity.value, "section_id": item.section_id,
                "location_id": item.location_id, "excerpt": item.excerpt, "message": item.message, "suggestion": item.suggestion,
            }
            for item in result.findings
        ]
        return {
            "report_revision": record.revision if record is not None else None,
            "profile_id": result.profile_id,
            "profile_label": PROFILE_LABEL,
            "blocking": result.blocking,
            "findings": findings,
            "sources": [dict(item) for item in REFERENCE_SOURCES],
        }
