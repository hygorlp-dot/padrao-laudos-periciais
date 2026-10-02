"""#272 — perfil jurídico-editorial de referência e pré-verificação do laudo.

Avisos nunca reescrevem o texto do perito. Marcador de pendência bloqueia a
emissão sempre, com ou sem perfil. Textos sintéticos.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from scripts.backend_contract.installation_settings import DEFAULT_LEGAL_EDITORIAL
from scripts.backend_contract.legal_editorial_preflight import (
    PreflightCode,
    PreflightSeverity,
    legal_editorial_preflight,
)
from tests.test_default_report_template_v1 import _report


def _with_text(*texts):
    # A pré-verificação lê seções, afirmações e respostas; um rascunho basta.
    report = _report()
    claims = tuple(SimpleNamespace(section_id=report.claims[0].section_id, claim_id=f"CLAIM-{index:03d}", text=text) for index, text in enumerate(texts, 1))
    return SimpleNamespace(sections=report.sections, claims=claims, answers=())


def _codes(report, profile=None):
    return [(item.code, item.severity) for item in legal_editorial_preflight(report, profile).findings]


def test_pending_markers_always_block():
    report = _with_text("O pavimento apresenta [INFORMAÇÃO NECESSÁRIA: data da vistoria].", "Medida sujeita a [VALIDAÇÃO DO PERITO].")
    result = legal_editorial_preflight(report)
    assert result.blocking
    markers = [item for item in result.findings if item.code is PreflightCode.PENDING_MARKER]
    assert [item.excerpt for item in markers] == ["[INFORMAÇÃO NECESSÁRIA: data da vistoria]", "[VALIDAÇÃO DO PERITO]"]
    # Perfil com todos os avisos desligados continua bloqueando.
    quiet = replace(DEFAULT_LEGAL_EDITORIAL, check_acronyms=False, check_latinisms=False, check_foreign_terms=False, check_jargon=False, check_long_sentences=False, check_long_paragraphs=False)
    assert legal_editorial_preflight(report, quiet).blocking


def test_acronym_needs_the_full_name_at_first_occurrence_only():
    report = _with_text(
        "O contrato da CEF foi examinado.",
        "Conforme a Associação Brasileira de Normas Técnicas (ABNT), a NBR 15575 (Norma de Desempenho) se aplica. A ABNT também prevê ensaios.",
        "A parte CAIXA ECONOMICA FEDERAL apresentou documentos.",
    )
    flagged = [item for item in legal_editorial_preflight(report).findings if item.code is PreflightCode.ACRONYM_NOT_DEFINED]
    # NBR sem o nome por extenso também é sinalizada; ABNT foi definida e o nome em caixa-alta não é sigla.
    assert [item.message.split("“")[1].split("”")[0] for item in flagged] == ["CEF", "NBR"]


def test_latinisms_foreign_terms_and_jargon_are_warnings_with_a_suggestion():
    report = _with_text("Data venia, a vistoria in loco usou um checklist. Outrossim, a exordial não informa a área.")
    findings = legal_editorial_preflight(report).findings
    by_code = {item.code: item for item in findings}
    assert {PreflightCode.LATINISM, PreflightCode.FOREIGN_TERM, PreflightCode.JARGON} <= set(by_code)
    assert all(item.severity is PreflightSeverity.WARNING for item in findings)
    assert "no local" in [item.suggestion for item in findings if "in loco" in item.message][0]
    assert not legal_editorial_preflight(report).blocking


def test_long_sentence_and_paragraph_use_profile_thresholds():
    sentence = " ".join(["palavra"] * 50) + "."
    report = _with_text(sentence)
    assert (PreflightCode.LONG_SENTENCE, PreflightSeverity.WARNING) in _codes(report)
    relaxed = replace(DEFAULT_LEGAL_EDITORIAL, long_sentence_words=60)
    assert (PreflightCode.LONG_SENTENCE, PreflightSeverity.WARNING) not in _codes(report, relaxed)
    paragraph = " ".join(["Frase curta aqui."] * 70)
    assert (PreflightCode.LONG_PARAGRAPH, PreflightSeverity.WARNING) in _codes(_with_text(paragraph))


def test_clean_text_has_no_findings_and_disabled_checks_stay_silent():
    assert legal_editorial_preflight(_with_text("A fissura tem abertura de 0,3 mm e extensão de 1,2 m.")).findings == ()
    noisy = _with_text("Ab initio, o layout da CEF.")
    silent = replace(DEFAULT_LEGAL_EDITORIAL, check_acronyms=False, check_latinisms=False, check_foreign_terms=False)
    assert legal_editorial_preflight(noisy, silent).findings == ()


def test_unknown_profile_type_is_refused():
    with pytest.raises(TypeError):
        legal_editorial_preflight(_report(), object())


def test_delivery_render_refuses_a_report_with_open_pending_markers():
    from hashlib import sha256
    import json
    from scripts.backend_contract.application.delivery_foundation import RenderDeliveryPackage
    from scripts.backend_contract.delivery_foundation import DeliveryState
    from scripts.backend_contract.delivery_renderer import DELIVERY_RENDERING_VERSION
    from scripts.backend_contract.legal_editorial_preflight import report_pending_markers
    from scripts.backend_contract.report_default_template import default_report_template, default_template_manifest
    from scripts.backend_contract.report_foundation import report_snapshot_to_mapping

    report = _report()
    assert report_pending_markers(report) == ()
    marked = replace(report, claims=(replace(report.claims[0], text="Área a confirmar [INFORMAÇÃO NECESSÁRIA: área privativa]."), *report.claims[1:]))
    assert report_pending_markers(marked) == ("[INFORMAÇÃO NECESSÁRIA",)
    template = default_report_template(report.editorial_profile)
    digest = sha256(json.dumps(report_snapshot_to_mapping(marked), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    snapshot = SimpleNamespace(
        state=DeliveryState.DRAFT, rendering_version=DELIVERY_RENDERING_VERSION, template_id=default_template_manifest().template_id,
        template_content_id="11111111-1111-4111-8111-111111111111", template_digest=sha256(template).hexdigest(),
        binding=SimpleNamespace(report_digest=digest),
    )
    service = RenderDeliveryPackage(
        SimpleNamespace(execute=lambda _w: (SimpleNamespace(revision=1), snapshot)),
        SimpleNamespace(execute=lambda _w: (None, marked)),
        SimpleNamespace(execute=lambda _w, _c: SimpleNamespace(content=template, metadata=SimpleNamespace(checksum_sha256=sha256(template).hexdigest()))),
        SimpleNamespace(execute=lambda **_k: pytest.fail("nothing may be stored")), None, None,
    )
    with pytest.raises(ValueError, match="pending markers"):
        service.execute("w", manifest=default_template_manifest(), expected_revision=1)


def test_preflight_service_uses_the_case_profile_and_states_source_nature():
    from scripts.backend_contract.application.legal_editorial_preflight import GetReportPreflight
    report = _with_text("Ab initio, a CEF entregou o imóvel.", "Falta [VALIDAÇÃO DO PERITO: cota].")
    report = SimpleNamespace(**vars(report))
    settings = SimpleNamespace(legal_editorial=replace(DEFAULT_LEGAL_EDITORIAL, check_latinisms=False))
    import scripts.backend_contract.legal_editorial_preflight as module
    original = module.report_pending_markers
    module.report_pending_markers = lambda _report: ("[VALIDAÇÃO DO PERITO",)
    try:
        result = GetReportPreflight(SimpleNamespace(execute=lambda _w: (SimpleNamespace(revision=4), report)), SimpleNamespace(current=lambda _w: (None, settings))).execute("w")
    finally:
        module.report_pending_markers = original
    codes = [item["code"] for item in result["findings"]]
    assert result["blocking"] is True and result["report_revision"] == 4
    assert "LATINISM" not in codes and "ACRONYM_NOT_DEFINED" in codes and "PENDING_MARKER" in codes
    assert result["profile_label"] == "Sistema Pericial — CNJ/TRF5"
    assert {item["nature"] for item in result["sources"]} == {"RECOMMENDATORY", "MANDATORY", "INSTITUTIONAL"}
    assert "obrigatória" not in str(result).lower()
