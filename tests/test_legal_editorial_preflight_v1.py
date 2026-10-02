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
    report_pending_markers,
)
from tests.test_default_report_template_v1 import _report


def _with_text(*texts):
    # A pré-verificação lê seções, afirmações e respostas; um rascunho basta.
    report = _report()
    claims = tuple(SimpleNamespace(section_id=report.claims[0].section_id, claim_id=f"CLAIM-{index:03d}", text=text) for index, text in enumerate(texts, 1))
    from dataclasses import fields
    return SimpleNamespace(**{**{item.name: getattr(report, item.name) for item in fields(report)}, "claims": claims, "answers": ()})


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
    assert report_pending_markers(marked) == ("[INFORMAÇÃO NECESSÁRIA: área privativa]",)
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
    result = GetReportPreflight(SimpleNamespace(execute=lambda _w: (SimpleNamespace(revision=4), report)), SimpleNamespace(current=lambda _w: (None, settings))).execute("w")
    codes = [item["code"] for item in result["findings"]]
    assert result["blocking"] is True and result["report_revision"] == 4
    assert "LATINISM" not in codes and "ACRONYM_NOT_DEFINED" in codes and "PENDING_MARKER" in codes
    assert result["profile_label"] == "Sistema Pericial — CNJ/TRF5"
    assert {item["nature"] for item in result["sources"]} == {"RECOMMENDATORY", "MANDATORY", "INSTITUTIONAL"}
    assert "obrigatória" not in str(result).lower()


def _with_process(report, **changes):
    from scripts.backend_contract.application.models import ProcessCaseData
    from scripts.backend_contract.report_foundation import ReportProcess
    data = ProcessCaseData.empty().as_dict()
    data.update({"numero_processo": "0000000-00.2026.4.05.0000", "vara": "1ª Vara Sintética", "tribunal": "Tribunal Sintético", **changes})
    return replace(report, process_record=ReportProcess(workspace_id=report.workspace_id, source_revision=1, source_checksum="c" * 64, **data))


@pytest.mark.parametrize(("changes", "location"), [
    ({"process": {"vara": "[INFORMAÇÃO NECESSÁRIA: vara]"}}, "FIELD:COURT"),
    ({"process": {"parte_requerente": "[VALIDAÇÃO DO PERITO: confirmar autor]"}}, "FIELD:PARTICIPANTS_ACTIVE"),
    ({"process": {"parte_requerida": "[INFORMAÇÃO NECESSÁRIA: réu]"}}, "FIELD:PARTICIPANTS_PASSIVE"),
    ({"profile": {"professional_title": "[INFORMAÇÃO NECESSÁRIA: título]"}}, "FIELD:EXPERT_TITLE"),
    ({"profile": {"signature_name": "[VALIDAÇÃO DO PERITO: nome na assinatura]"}}, "PROFILE:signature_name"),
])
def test_pending_marker_on_the_cover_or_header_blocks_and_says_where(changes, location):
    # Revisão do 2º conjunto, P1-2: só o corpo era varrido; a capa saía com a
    # pendência e o painel dizia "Nenhuma pendência aberta".
    report = _report()
    report = _with_process(report, **changes.get("process", {}))
    if "profile" in changes:
        report = replace(report, expert_profile=replace(report.expert_profile, **changes["profile"]))
    result = legal_editorial_preflight(report)
    assert result.blocking
    pending = [item for item in result.findings if item.code.value == "PENDING_MARKER"]
    assert [item.location_id for item in pending] == [location]
    assert pending[0].excerpt.startswith("[") and pending[0].excerpt.endswith("]")
    assert len(report_pending_markers(report)) == 1


def test_bound_word_is_scanned_as_the_last_barrier_including_split_runs_and_headers():
    from io import BytesIO
    from zipfile import ZipFile
    from scripts.backend_contract.legal_editorial_preflight import word_pending_markers
    from scripts.backend_contract.report_default_template import default_report_template
    clean = default_report_template(_report().editorial_profile)
    assert word_pending_markers(clean) == ()
    with ZipFile(BytesIO(clean)) as source:
        entries = {name: source.read(name) for name in source.namelist()}
    header = next(name for name in entries if name.startswith("word/header"))
    entries[header] = entries[header].replace(b"</w:hdr>", '<w:p><w:r><w:t>[INFORMAÇÃO </w:t></w:r><w:r><w:t xml:space="preserve">NECESSÁRIA: logotipo]</w:t></w:r></w:p></w:hdr>'.encode())
    output = BytesIO()
    with ZipFile(output, "w") as target:
        for name, data in entries.items():
            target.writestr(name, data)
    assert word_pending_markers(output.getvalue()) == ("[INFORMAÇÃO NECESSÁRIA: logotipo]",)


def test_delivery_render_refuses_a_bound_word_whose_template_text_carries_a_pending_marker():
    from hashlib import sha256
    from io import BytesIO
    import json
    from zipfile import ZipFile
    from scripts.backend_contract.application.delivery_foundation import RenderDeliveryPackage
    from scripts.backend_contract.delivery_foundation import DeliveryState
    from scripts.backend_contract.delivery_renderer import DELIVERY_RENDERING_VERSION
    from scripts.backend_contract.report_default_template import default_report_template, default_template_manifest
    from scripts.backend_contract.report_foundation import report_snapshot_to_mapping

    report = _report()
    assert report_pending_markers(report) == ()
    with ZipFile(BytesIO(default_report_template(report.editorial_profile))) as source:
        entries = {name: source.read(name) for name in source.namelist()}
    header = next(name for name in entries if name.startswith("word/header"))
    entries[header] = entries[header].replace(b"</w:hdr>", "<w:p><w:r><w:t>[VALIDAÇÃO DO PERITO: logotipo do escritório]</w:t></w:r></w:p></w:hdr>".encode())
    output = BytesIO()
    with ZipFile(output, "w") as target:
        for name, data in entries.items():
            target.writestr(name, data)
    template = output.getvalue()
    digest = sha256(json.dumps(report_snapshot_to_mapping(report), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    snapshot = SimpleNamespace(
        state=DeliveryState.DRAFT, rendering_version=DELIVERY_RENDERING_VERSION, template_id=default_template_manifest().template_id,
        template_content_id="11111111-1111-4111-8111-111111111111", template_digest=sha256(template).hexdigest(),
        binding=SimpleNamespace(report_digest=digest),
    )
    service = RenderDeliveryPackage(
        SimpleNamespace(execute=lambda _w: (SimpleNamespace(revision=1), snapshot)),
        SimpleNamespace(execute=lambda _w: (None, report)),
        SimpleNamespace(execute=lambda _w, _c: SimpleNamespace(content=template, metadata=SimpleNamespace(checksum_sha256=sha256(template).hexdigest()))),
        SimpleNamespace(execute=lambda **_k: pytest.fail("nothing may be stored")), None, None,
    )
    with pytest.raises(ValueError, match="bound Word carries open pending markers"):
        service.execute("w", manifest=default_template_manifest(), expected_revision=1)


def test_acronym_and_sentence_heuristics_handle_uf_hyphen_neighbours_and_abbreviations():
    # Revisão do 2º conjunto, P2-3.
    acronyms = lambda *texts: [item.excerpt for item in legal_editorial_preflight(_with_text(*texts)).findings if item.code is PreflightCode.ACRONYM_NOT_DEFINED]  # noqa: E731
    assert acronyms("O imóvel fica em Recife/PE e foi vistoriado.") == []
    assert len(acronyms("A norma ABNT NBR 15575 trata de desempenho.")) == 2
    assert len(acronyms("O perito é inscrito no CREA-PE.")) == 1
    assert acronyms("LAUDO PERICIAL DE ENGENHARIA") == []
    long = "O perito verificou, conforme o art. 473 do Código de Processo Civil, " + " ".join(["a fissura"] * 22) + " na parede."
    sentences = [item for item in legal_editorial_preflight(_with_text(long)).findings if item.code is PreflightCode.LONG_SENTENCE]
    assert len(sentences) == 1 and sentences[0].excerpt.startswith("O perito verificou")
