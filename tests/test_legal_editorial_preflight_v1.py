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
