"""Entirely synthetic professional document family; no real PDF-derived bytes."""
from dataclasses import replace, FrozenInstanceError
import json

import pytest

from tests.test_report_foundation_v1 import bound_report, upstreams


def capture():
    from scripts.backend_contract.professional_report_presentation import capture_report_authorities
    report = bound_report()
    records, case, inspection, technical, _profile = upstreams()
    return capture_report_authorities(report, case=case, inspection=inspection, technical=technical, pathology=None)


def test_projection_is_immutable_captured_authority_not_latest_lookup():
    from scripts.backend_contract.professional_report_presentation import professional_report_projection
    report = replace(bound_report(), presentation=capture())
    projection = professional_report_projection(report)
    assert projection.report_id == report.report_id
    assert projection.questions[0].text == upstreams()[1].questions[0].text
    assert projection.questions[0].number is None  # position/page excerpt is not original number
    with pytest.raises(FrozenInstanceError):
        projection.report_id = "OTHER"


def test_capture_rejects_other_identity_and_revision_content():
    from scripts.backend_contract.professional_report_presentation import capture_report_authorities
    report = bound_report()
    _, case, inspection, technical, _ = upstreams()
    with pytest.raises(ValueError, match="captured"):
        capture_report_authorities(report, case=replace(case, snapshot_id="OTHER"), inspection=inspection, technical=technical, pathology=None)


@pytest.mark.parametrize("origin,label", [("USO_OPERACAO_MANUTENCAO", "Uso / Operação / Manutenção (agrupado)"), ("MISTA", "Mista")])
def test_aggregate_origins_are_presented_without_granular_inference(origin, label):
    from scripts.backend_contract.professional_report_presentation import origin_presentation
    assert origin_presentation(origin) == label


def test_not_observed_and_inconclusive_are_not_converted_or_assigned_criticality():
    from scripts.backend_contract.professional_report_presentation import classification_presentation, criticality_presentation
    assert classification_presentation("NAO_CONSTATADA") == "Não constatada"
    assert classification_presentation("INCONCLUSIVA") == "Inconclusivo"
    assert criticality_presentation("INCONCLUSIVA") == "Inconclusiva"
    assert criticality_presentation(None) == "Não informada"


def test_captured_projection_roundtrip_does_not_change_old_report_mapping():
    from scripts.backend_contract.report_foundation import report_snapshot_from_mapping, report_snapshot_to_mapping
    original = bound_report()
    before = report_snapshot_to_mapping(original)
    report = replace(original, presentation=capture())
    assert report_snapshot_from_mapping(report_snapshot_to_mapping(report)) == report
    assert report_snapshot_to_mapping(original) == before


def test_professional_details_command_cannot_replace_captured_authorities():
    from types import SimpleNamespace
    from scripts.backend_contract.application.report_foundation import AmendReportDraft
    from scripts.backend_contract.professional_report_presentation import capture_to_mapping
    from scripts.backend_contract.report_foundation import ReportState
    report = replace(bound_report(), presentation=capture(), state=ReportState.DRAFT, review_decisions=(), coverage=replace(bound_report().coverage, complete=False, reasons=("Draft",)))
    service = AmendReportDraft(SimpleNamespace(execute=lambda _: (SimpleNamespace(revision=4), report)), SimpleNamespace(execute=lambda *args: SimpleNamespace(revision=5)), None)
    values = {name: value for name, value in capture_to_mapping(report.presentation).items() if name != "sources"}
    values["details"]["objective"] = "Objetivo fornecido pelo profissional sintético."
    _, amended = service.execute(report.workspace_id, expected_revision=4, action="SET_PROFESSIONAL_PRESENTATION", values=values)
    assert amended.presentation.details.objective == values["details"]["objective"]
    assert amended.presentation.sources == report.presentation.sources
    with pytest.raises(ValueError):
        service.execute(report.workspace_id, expected_revision=4, action="SET_PROFESSIONAL_PRESENTATION", values={**values, "sources": []})


def test_captured_layout_orders_document_chapters_without_changing_semantic_sections():
    from scripts.backend_contract.delivery_renderer import professional_report_blocks
    from scripts.backend_contract.professional_report_presentation import ProfessionalReportDetails
    report = replace(bound_report(), presentation=replace(capture(), details=ProfessionalReportDetails(objective="Objetivo sintético.")))
    headings = tuple(b.text for b in professional_report_blocks(report) if b.kind == "HEADING_1")
    assert headings[0] == "1. CONSIDERAÇÕES GERAIS"
    assert headings.index("4. CONCLUSÃO GERAL") < headings.index("6. RESPOSTAS AOS QUESITOS")
    assert report.sections == bound_report().sections


def test_existing_word_writer_preserves_hierarchy_bookmarks_and_synthesis_grid():
    from xml.etree import ElementTree as ET
    from scripts.backend_contract.delivery_renderer import _canonical_content_markup, report_heading_texts
    report = replace(bound_report(), presentation=capture())
    content = _canonical_content_markup(report, b"w:", text_width=9000)
    root = ET.fromstring(b'<root xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">' + content + b'</root>')
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    headings = [p for p in root.findall("w:p", ns) if p.find("w:pPr/w:outlineLvl", ns) is not None]
    assert len(headings) == len(report_heading_texts(report))
    assert {p.find("w:pPr/w:outlineLvl", ns).get("{" + ns["w"] + "}val") for p in headings} >= {"0", "1"}
    assert all(p.find("w:bookmarkStart", ns) is not None for p in headings)


def pathology_report():
    from tests.test_report_foundation_v1 import pathology_upstream
    from scripts.backend_contract.construction_defect_analysis import construction_defect_analysis_from_mapping, construction_defect_analysis_to_mapping
    from scripts.backend_contract.application.report_foundation import report_upstream_digest
    from scripts.backend_contract.professional_report_presentation import capture_report_authorities
    report = bound_report()
    _, case, inspection, technical, _ = upstreams()
    record, pat = pathology_upstream()
    mapping = construction_defect_analysis_to_mapping(pat)
    identities = {"FIELD_OBSERVATION": inspection.observations[0].observation_id, "MEASUREMENT": inspection.measurements[0].measurement_id, "PHOTO_RECORD": inspection.photos[0].photo_id, "CASE_CLAIM": case.claims[0].item_id}
    for link in mapping["identity_links"]:
        if link["canonical_kind"] in identities:
            old = link["canonical_id"]
            link["canonical_id"] = identities[link["canonical_kind"]]
            for context in mapping["observation_contexts"]:
                for key, val in context.items():
                    if val == old:
                        context[key] = link["canonical_id"]
                    elif type(val) is list:
                        context[key] = [link["canonical_id"] if v == old else v for v in val]
    p = mapping["analysis_final"]["patologias"][0]
    p.update(sistema="Impermeabilização", ambiente="Sala sintética", alegacoes_relacionadas=["ALG-001"], constatacao={"situacao": "INCONCLUSIVA", "fotografias": ["FOT-001"]}, origem="USO_OPERACAO_MANUTENCAO", criticidade="INCONCLUSIVA")
    pat = construction_defect_analysis_from_mapping(mapping)
    report = replace(report, source_snapshot=replace(report.source_snapshot, construction_defect_analysis_snapshot_id=pat.snapshot_id, construction_defect_analysis_revision=record.revision, construction_defect_analysis_digest=report_upstream_digest(pat)))
    return replace(report, presentation=capture_report_authorities(report, case=case, inspection=inspection, technical=technical, pathology=pat))


def test_sheet_uses_effective_pat_raw_measurement_and_explicit_absences():
    from scripts.backend_contract.professional_report_presentation import professional_report_projection
    from scripts.backend_contract.delivery_renderer import professional_report_blocks, _canonical_content_markup
    report = pathology_report()
    item = professional_report_projection(report).items[0]
    assert item.measurements == ("1250 mm",)
    assert item.observation == (upstreams()[2].observations[0].raw_observation,)
    assert item.recommendation is None and item.photo_figure_id is None
    sheet = next(b for b in professional_report_blocks(report) if b.kind == "SHEET")
    assert "Fotografia não fornecida" in sheet.paragraph_texts
    assert "Mini-planta não fornecida" in sheet.paragraph_texts
    assert "Origem: Uso / Operação / Manutenção (agrupado)" in sheet.paragraph_texts
    assert "Criticidade: Inconclusiva" in sheet.paragraph_texts
    markup = _canonical_content_markup(report, b"w:", text_width=9000)
    assert b'gridSpan w:val="6"' in markup and b'cantSplit' in markup


def test_default_professional_document_has_first_page_slots_and_grey_chapter_style():
    from io import BytesIO
    from zipfile import ZipFile
    from scripts.backend_contract.report_default_template import default_report_template, default_template_manifest
    report = bound_report()
    content = default_report_template(report.editorial_profile, professional=True)
    with ZipFile(BytesIO(content)) as z:
        doc = z.read("word/document.xml")
        styles = z.read("word/styles.xml")
        assert b"[[PARTICIPANTS_ACTIVE]]" in doc and b"[[ACTION_TYPE]]" in doc
        assert b"[[PROTOCOL_OPENING]]" in doc and b"[[REPORT_CITY_DATE]]" in doc
        assert b'fill="D9D9D9"' in styles
        assert not any(name.startswith("word/media/") for name in z.namelist())
    assert "ACTION_TYPE" in {b.field for b in default_template_manifest(professional=True).bindings}
    from scripts.backend_contract.report_template import bind_report_template
    bound = bind_report_template(content, report, default_template_manifest(professional=True))
    assert bound.output_bytes


def test_repair_capture_refuses_arithmetic_divergence_and_ineligible_pat():
    from scripts.backend_contract.professional_report_presentation import ReportRepairLine, ReportRepairBudget
    line = ReportRepairLine("Grupo sintético", "1.1", "PAT-001", "Fonte sintética", "SYN-01", "Serviço sintético", "m²", "2", "2 × 1 m²", "100.00", "20", "120.00", "240.00")
    with pytest.raises(ValueError, match="arithmetic"):
        replace(line, total="200.00")
    with pytest.raises(ValueError, match="eligibility"):
        report = pathology_report()
        replace(report, presentation=replace(report.presentation, repair_budget=ReportRepairBudget("2026-10", "Sintético", "Não utilizar em caso real.", "BDI fornecido: 20%.", (line,))))


def test_structured_approved_recommendation_is_literal_presentation_not_new_decision():
    from scripts.backend_contract.professional_report_presentation import recommendation_presentation
    text = recommendation_presentation({"objetivo": "Objetivo registrado.", "etapas_gerais": ["Etapa registrada."], "investigacao_adicional": True})
    assert "Objetivo registrado." in text and "Etapa registrada." in text
    assert recommendation_presentation({}) is None


def golden_report():
    """Confirmed synthetic sources and assets; never derived from reference PDFs."""
    from io import BytesIO
    from hashlib import sha256
    from PIL import Image, ImageDraw
    from scripts.backend_contract.professional_report_presentation import capture_report_authorities, ProfessionalReportDetails, ReportRepairBudget, ReportRepairLine, ReportSheetFigures
    from scripts.backend_contract.construction_defect_analysis import construction_defect_analysis_from_mapping, construction_defect_analysis_to_mapping
    from scripts.backend_contract.application.report_foundation import report_upstream_digest
    from scripts.backend_contract.case_intake import QuestionSource
    from scripts.backend_contract.visit_context import VisitContext
    from scripts.backend_contract.report_foundation import ReportFigure, ReportReference, ReportProcess, ReportProperty
    from scripts.backend_contract.property_record import PropertyRecord, PropertyValue, property_record_to_mapping
    base = pathology_report()
    sources = {s.kind: s.read() for s in base.presentation.sources}
    case, inspection, technical, pat = (sources[k] for k in ("case", "inspection", "technical", "pathology"))
    q1 = replace(case.questions[0], provenance=(replace(case.questions[0].provenance[0], occurrence_id="OCC-GOLDEN-QUESTION-001", page_or_span="p. 1"),), source_question=QuestionSource("COURT", "7", 1, 1, "7. " + case.questions[0].text, "NUMBERED_NATIVE_TEXT_V1"))
    text = "Informe os limites da inspeção sintética e diferencie constatação, medição e hipótese, preservando as ressalvas documentadas. " * 5
    q2 = replace(q1, item_id="QUESTION-GOLDEN-002", text=text, provenance=(replace(q1.provenance[0], occurrence_id="OCC-GOLDEN-QUESTION-002", page_or_span="p. 2"),), source_question=QuestionSource("DEFENDANT", "23", 2, 2, "23. " + text, "NUMBERED_NATIVE_TEXT_V1"))
    case = replace(case, questions=(q1, q2))
    technical = replace(technical, question_links=(*technical.question_links, replace(technical.question_links[0], link_id="LINK-GOLDEN-002", question_id=q2.item_id)))
    images = []
    for plan in (False, True):
        image = Image.new("RGB", (800, 500), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((70, 70, 730, 430), outline="black", width=4)
        draw.line((400, 70, 400, 430), fill="gray", width=3)
        draw.text((85, 85), "SYNTHETIC PLAN" if plan else "SYNTHETIC PHOTO", fill="black")
        if not plan:
            draw.line((250, 80, 290, 420), fill="blue", width=7)
        out = BytesIO()
        image.save(out, format="JPEG")
        images.append(out.getvalue())
    inspection = replace(inspection, photos=(replace(inspection.photos[0], original_sha256=sha256(images[0]).hexdigest()),), visit_context=VisitContext("2026-09-01", "09:30", "11:15", "Céu claro confirmado no cenário sintético.", None, None, (), "PROFESSIONAL-001", "2026-09-01T12:00:00+00:00"), participant_references=())
    mapping = construction_defect_analysis_to_mapping(pat)
    first = mapping["analysis_final"]["patologias"][0]
    first.update(origem="ENDOGENA_CONSTRUTIVA", criticidade="MEDIA", elegibilidade_orcamento="ELEGIVEL_ORCAMENTO_VICIO", orcamento={"incluir": True, "revisao_profissional": {"status": "APROVADO"}}, recomendacao={"descricao": "Executar o reparo sintético no trecho medido, após projeto e conferência."}, redacao={"analise_alegacoes_causas": "A alegação foi confrontada com a observação e a medição sintéticas.", "consequencias": "Consequência registrada no cenário sintético.", "conclusao": "Conclusão construtiva sintética expressamente aprovada."})
    first["constatacao"]["situacao"] = "ANOMALIA"
    second = {**first, "id": "PAT-002", "sistema": "Vedações", "manifestacao": "Manifestação sintética inconclusiva.", "origem": "INCONCLUSIVA", "criticidade": "INCONCLUSIVA", "constatacao": {"situacao": "INCONCLUSIVA", "fotografias": []}, "orcamento": {"incluir": False}, "elegibilidade_orcamento": "NAO_ELEGIVEL", "recomendacao": {"descricao": None}, "redacao": {"conclusao": "Os elementos sintéticos não individualizam a causa."}}
    mapping["analysis_final"]["patologias"].append(second)
    mapping["identity_links"].append({"canonical_kind": "PATHOLOGY", "canonical_id": "PAT-002", "legacy_kind": "PATHOLOGY", "legacy_id": "PAT-002"})
    mapping["reviews"].append({**mapping["reviews"][0], "review_id": "PAT-REVIEW-002", "pat_id": "PAT-002"})
    pat = construction_defect_analysis_from_mapping(mapping)
    figures = tuple(ReportFigure(f"PHOTO-00000000-0000-4000-8000-{index:012d}", inspection.photos[0].private_content_id if index == 1 else "cccccccc-cccc-4ccc-8ccc-cccccccccccc", sha256(content).hexdigest(), "Fotografia sintética" if index == 1 else "Mini-planta sintética", "TECHNICAL_FINDINGS", 800, 500) for index, content in enumerate(images, 1))
    binding = replace(base.source_snapshot, case_analysis_digest=report_upstream_digest(case), inspection_session_digest=report_upstream_digest(inspection), technical_snapshot_digest=report_upstream_digest(technical), construction_defect_analysis_digest=report_upstream_digest(pat))
    answers = (replace(base.answers[0], question_text=q1.text), replace(base.answers[0], answer_id="ANSWER-GOLDEN-002", question_id=q2.item_id, question_text=q2.text, text="A resposta sintética conserva as limitações da inspeção e a decisão profissional registrada."))
    process_values = dict(numero_processo="0000000-00.2026.8.00.0000", ramo_justica="Estadual", tribunal="Tribunal sintético", vara="Vara sintética", municipio_sede="Município sintético", subsecao_judiciaria="", comarca_municipio="Comarca sintética", uf="BA", parte_requerente="Parte autora sintética", parte_requerida="Parte ré sintética")
    process = ReportProcess(base.workspace_id, 2, sha256(json.dumps(process_values, sort_keys=True).encode()).hexdigest(), **process_values)
    property_record = PropertyRecord("1.0.0", base.workspace_id, tuple(PropertyValue(field, value, None, "PROFESSIONAL-001", "2026-09-01T12:00:00+00:00") for field, value in (("street", "Rua sintética"), ("number", "10"), ("city", "Município sintético"), ("state", "BA"), ("private_area_m2", "80.00"))))
    property_capture = ReportProperty(property_record, 1, sha256(json.dumps(property_record_to_mapping(property_record), sort_keys=True).encode()).hexdigest())
    conclusion = next(c for c in base.claims if c.authority.value == "PROFESSIONALLY_CONCLUDED")
    conclusion = replace(conclusion, claim_id="CLAIM-GOLDEN-CONCLUSION", section_id=next(s.section_id for s in base.sections if s.kind == "CONCLUSIONS"))
    report = replace(base, presentation=None, source_snapshot=binding, figures=figures, answers=answers, process_record=process, property_record=property_capture, claims=(*base.claims, conclusion), coverage=replace(base.coverage, material_claims=base.coverage.material_claims + 1, traceable_claims=base.coverage.traceable_claims + 1, answers=2, traceable_answers=2), references=(ReportReference("REFERENCE-GOLDEN-001", "OTHER_REFERENCE", "Autor sintético", "Referência sintética exclusiva da prova", 2026, "SYNTHETIC-ONLY", "Não aplicar a casos reais."),))
    capture = capture_report_authorities(report, case=case, inspection=inspection, technical=technical, pathology=pat)
    details = ProfessionalReportDetails(action_type="Ação sintética", protocol_opening="O perito sintético apresenta o laudo solicitado no cenário de teste.", qualification="Identidade profissional sintética capturada no perfil.", preamble="Este documento constitui prova sintética de apresentação.", objective="Confrontar as fontes sintéticas e apresentar as decisões efetivas.", definitions="Definições fornecidas para este teste.", classification_framework="Classificações capturadas nas decisões profissionais sintéticas.", conditions="Acesso e limitações registrados na vistoria sintética.", city="Município sintético", report_date="2026-10-09", closing="Encerra-se o laudo sintético, sem dados de perícias reais.")
    budget = ReportRepairBudget("2026-10", "Fonte exclusivamente sintética", "Valores fictícios, sem aplicação real.", "BDI sintético explicitamente fornecido: 20%.", (ReportRepairLine("Impermeabilização", "1.1", "PAT-001", "SYNTHETIC", "SYN-001", "Reparo sintético do trecho", "m²", "2", "2 × 1 m²", "100.00", "20", "120.00", "240.00"),))
    capture = replace(capture, details=details, repair_budget=budget, sheet_figures=(ReportSheetFigures("PAT-001", figures[0].figure_id, figures[1].figure_id),))
    return replace(report, presentation=capture), dict(zip((f.figure_id for f in figures), images, strict=True))


def test_synthetic_golden_has_two_systems_literal_nonsequential_questions_and_one_eligible_repair():
    from scripts.backend_contract.professional_report_presentation import professional_report_projection
    report, images = golden_report()
    projection = professional_report_projection(report)
    assert len({i.system for i in projection.items}) == 2
    assert [(q.origin, q.number) for q in projection.questions] == [("COURT", "7"), ("DEFENDANT", "23")]
    assert projection.repair_budget.total == "240.00"
    assert [i.repair_eligible for i in projection.items] == [True, False]
    assert len(images) == 2


def test_professional_questions_render_original_number_then_literal_and_answer():
    from scripts.backend_contract.delivery_renderer import professional_report_blocks
    report, _ = golden_report()
    blocks = professional_report_blocks(report)
    questions = [b for b in blocks if b.kind == "QUESTION"]
    assert [b.lead for b in questions] == ["7)", "23)"]
    assert [b.text for b in questions] == [a.question_text for a in report.answers]
    assert all(b.lead == "R:" for b in blocks if b.kind == "ANSWER")


def test_wrapped_second_cell_paragraph_stays_bound_to_its_column():
    from scripts.backend_contract import delivery_renderer as dr
    def text(value, x, top):
        return dr._PositionedText(0, value, x, top - 10, 10, x + len(value) * 5, top - 10, top, strict_text=value)
    fragments = [text("Recomendação técnica capturada", 100, 650), text("sem mudança de autoridade.", 100, 635)]
    phrase = "Recomendação técnica capturada sem mudança de autoridade."
    assert dr._paragraph_sits_in_column(phrase, fragments, [], page=0, below=700, column_x=100, anchor_positions=[100, 350])
    elsewhere = [fragments[0], text("sem mudança de autoridade.", 350, 635)]
    assert not dr._paragraph_sits_in_column(phrase, elsewhere, [], page=0, below=700, column_x=100, anchor_positions=[100, 350])


@pytest.mark.skipif("not __import__('tests.test_default_report_template_v1', fromlist=['_native'])._native()", reason="Microsoft Word 16 unavailable")
@pytest.mark.parametrize("branding", ["NONE", "SYNTHETIC_CONFIGURED"])
def test_word16_professional_synthetic_golden_is_accepted_by_existing_fidelity_oracle(tmp_path, branding):
    from scripts.backend_contract.delivery_renderer import locate_heading_pages, report_heading_texts
    from scripts.backend_contract.report_default_template import default_report_template, default_template_manifest
    from scripts.backend_contract.infrastructure.office_pdf import LocalOfficePdfConverter
    from scripts.backend_contract.application.delivery_foundation import RenderDeliveryPackage
    report, images = golden_report()
    service = RenderDeliveryPackage(None, None, None, None, None, None, pdf_converter=LocalOfficePdfConverter())
    if branding == "NONE":
        template = default_report_template(report.editorial_profile, professional=True)
        manifest = default_template_manifest(professional=True)
    else:
        from scripts.backend_contract.report_default_template import branded_report_template, branded_template_manifest
        from tests.test_branded_report_template_v1 import _branding
        template = branded_report_template(report.editorial_profile, _branding(report), professional=True)
        manifest = branded_template_manifest(professional=True)
    word, pdf, renderer = service._paginated(template, report, manifest, images)
    assert pdf is not None and renderer is not None
    from io import BytesIO
    from zipfile import ZipFile
    from xml.etree import ElementTree as ET
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    root = ET.fromstring(ZipFile(BytesIO(word)).read("word/document.xml"))
    control = next(c for c in root.iter(w + "sdt") if any(t.attrib.get(w + "val") == "TOC_ENTRIES" for t in c.findall("./" + w + "sdtPr/" + w + "tag")))
    texts = ["".join(n.text or "" for n in p.iter(w + "t")) for p in control.iter(w + "p")][1:-1]
    assert tuple(int(v) for v in texts[1::2]) == locate_heading_pages(pdf, report_heading_texts(report))
    (tmp_path / "professional-golden.docx").write_bytes(word)
    (tmp_path / "professional-golden.pdf").write_bytes(pdf)



def test_professional_default_delivers_real_toc_with_dotted_leaders():
    from io import BytesIO
    from zipfile import ZipFile
    from xml.etree import ElementTree as ET
    from scripts.backend_contract.delivery_renderer import render_word_candidate, report_heading_texts
    from scripts.backend_contract.report_default_template import default_report_template, default_template_manifest
    report, images = golden_report()
    pages = tuple(3 for _ in report_heading_texts(report))
    word = render_word_candidate(template_bytes=default_report_template(report.editorial_profile, professional=True), report=report, manifest=default_template_manifest(professional=True), figure_images=images, toc_pages=pages).output_bytes
    root = ET.fromstring(ZipFile(BytesIO(word)).read("word/document.xml"))
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    assert any((n.text or "").strip().startswith("TOC ") for n in root.iter(w + "instrText"))
    assert any(n.attrib.get(w + "leader") == "dot" for n in root.iter(w + "tab"))
    assert sum((n.text or "").strip().startswith("PAGEREF ") for n in root.iter(w + "instrText")) == len(pages)


@pytest.mark.parametrize("quantity,cost,bdi,price", [
    ("2", "1E+999999", "20", "120"),
    ("2", "1E+999999", "1E+999999", "120"),
    ("1E+999999", "100", "20", "1E+999999"),
])
def test_extreme_repair_decimal_is_rejected_as_invalid_input_not_server_failure(quantity, cost, bdi, price):
    from scripts.backend_contract.professional_report_presentation import ReportRepairLine
    with pytest.raises(ValueError, match="repair budget"):
        ReportRepairLine("Grupo", "1", "PAT-001", "Sintética", "SYN", "Serviço sintético", "m²", quantity, "Memória sintética", cost, bdi, price, "240")


@pytest.mark.parametrize("count", [2, 500])
def test_repair_budget_total_preserves_cents_at_maximum_representable_line_amount(count):
    from scripts.backend_contract.professional_report_presentation import ReportRepairBudget, ReportRepairLine
    amount = "99999999999999999999999999.99"
    lines = tuple(ReportRepairLine("Grupo", str(i), "PAT-001", "Sintética", "SYN", "Serviço", "m²", "1", "Memória", amount, "0", amount, amount) for i in range(count))
    budget = ReportRepairBudget("2026-10", "Sintético", "Sintético", "Zero", lines)
    cents = int(amount.replace(".", "")) * count
    assert budget.total == f"{cents // 100}.{cents % 100:02d}"


def test_declared_toc_leaders_reject_missing_shifted_and_unrelated_dots():
    from dataclasses import replace
    from xml.etree import ElementTree as ET
    from scripts.backend_contract import delivery_renderer as d
    root = ET.fromstring('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:sdt><w:sdtPr><w:tag w:val="TOC_ENTRIES"/></w:sdtPr><w:sdtContent><w:p><w:pPr><w:tabs><w:tab w:val="right" w:leader="dot" w:pos="2000"/></w:tabs></w:pPr><w:r><w:t>Título</w:t></w:r><w:r><w:tab/></w:r></w:p></w:sdtContent></w:sdt></w:document>')
    heading = d._PositionedText(1, "título", 100, 700, 10, 130, 700, 710, strict_text="Título")
    dots = d._PositionedText(1, "." * 22, 133, 702, 10, 193, 702, 703, strict_text="." * 22)
    assert d._declared_toc_leader_dot_count(root, [heading, dots], []) == 22
    for wrong in ([], [replace(dots, page=2)], [replace(dots, x=153)], [replace(dots, right=165)], [replace(dots, font_size=20)]):
        with pytest.raises(ValueError, match="TOC dotted leader"):
            d._declared_toc_leader_dot_count(root, [heading, *wrong], [])
    unrelated = replace(dots, page=2)
    assert d._declared_toc_leader_dot_count(root, [heading, dots, unrelated], []) == 22


def test_projection_carries_captured_cover_synopsis_systems_references_and_closing():
    from scripts.backend_contract.professional_report_presentation import professional_report_projection
    report, _ = golden_report()
    projection = professional_report_projection(report)
    synopsis = dict(projection.synopsis)
    assert synopsis["Perito"] == report.expert_profile.full_name
    assert synopsis["Parte autora"] == "Parte autora sintética"
    assert synopsis["Parte ré"] == "Parte ré sintética"
    assert synopsis["Data da vistoria"] == "2026-09-01"
    assert projection.cover.process_number == report.process_record.numero_processo
    assert len(projection.systems) == 2
    assert projection.references == report.references
    assert projection.closing.report_date == "2026-10-09"
    assert not any("idade" in label.lower() for label, _ in projection.synopsis)


def test_repeated_expert_name_binds_header_before_same_literal_in_synopsis():
    from scripts.backend_contract import delivery_renderer as d
    body = d._WordTextExpectation("perito sintético", 10, (0, 0, 0), False, False, False, "left", True, "Arial")
    header = replace(body, font_size=9, in_table=False, expected_page=1, band="header")
    header_text = d._PositionedText(1, body.text, 85, 769, 9, 168, 769, 776, font_family="Arial", page_width=595.4, page_height=841.8)
    body_text = replace(header_text, y=600, bottom=600, top=608, font_size=10)
    # The header falls below the declared top margin because its logo pushes
    # Word's body down. Literal first-fit must not steal this occurrence.
    assert d._text_sizes_match([body, header], [header_text, body_text], [], top_margin=(56.7, 56.7), bottom_margin=(56.7, 56.7))
    assert not d._text_sizes_match([body, header], [header_text], [], top_margin=(56.7, 56.7), bottom_margin=(56.7, 56.7))
    assert not d._text_sizes_match([body, header], [body_text], [], top_margin=(56.7, 56.7), bottom_margin=(56.7, 56.7))


def test_professional_golden_ooxml_has_geometry_fields_roles_and_no_external_content():
    from io import BytesIO
    from zipfile import ZipFile
    from xml.etree import ElementTree as ET
    from scripts.backend_contract.delivery_renderer import render_word_candidate, report_heading_texts
    from scripts.backend_contract.report_default_template import default_report_template, default_template_manifest
    report, images = golden_report()
    word = render_word_candidate(template_bytes=default_report_template(report.editorial_profile, professional=True), report=report, manifest=default_template_manifest(professional=True), figure_images=images, toc_pages=tuple(3 for _ in report_heading_texts(report))).output_bytes
    with ZipFile(BytesIO(word)) as package:
        parts = {name: package.read(name) for name in package.namelist()}
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    root = ET.fromstring(parts["word/document.xml"])
    size = root.find(".//" + w + "pgSz")
    assert (size.get(w + "w"), size.get(w + "h")) == ("11906", "16838")
    assert root.find(".//" + w + "headerReference") is not None
    assert root.find(".//" + w + "footerReference") is not None
    styles = ET.fromstring(parts["word/styles.xml"])
    assert any(n.get(w + "ascii") == "Arial" for n in styles.iter(w + "rFonts"))
    headings = [p for p in root.iter(w + "p") if p.find("./" + w + "pPr/" + w + "outlineLvl") is not None]
    assert {p.find("./" + w + "pPr/" + w + "outlineLvl").get(w + "val") for p in headings} == {"0", "1", "2"}
    assert all(p.find(w + "bookmarkStart") is not None for p in headings)
    footer_fields = " ".join((n.text or "") for name, content in parts.items() if name.startswith("word/footer") and name.endswith(".xml") for n in ET.fromstring(content).iter(w + "instrText"))
    assert "PAGE" in footer_fields and "NUMPAGES" in footer_fields
    text = " ".join(n.text or "" for n in root.iter(w + "t"))
    for required in ("SÍNTESE DA PERÍCIA", "Perito", "Parte autora sintética", "Parte ré sintética", "7)", "23)", "240.00", "2 × 1 m²", "ENCERRAMENTO", "Encerra-se o laudo sintético"):
        assert required in text
    assert {n.get(w + "val") for n in root.iter(w + "gridSpan")} >= {"2", "3", "6"}
    assert len(list(root.iter(w + "cantSplit"))) >= 8
    assert len([name for name in parts if name.startswith("word/media/")]) == 2
    extents = list(root.iter("{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}extent"))
    assert len(extents) == 2
    assert all(abs(int(n.get("cx")) / int(n.get("cy")) - 800 / 500) < 0.001 for n in extents)
    assert not any("vba" in name.lower() for name in parts)
    for name, content in parts.items():
        if name.endswith(".rels"):
            assert not any(n.get("TargetMode") == "External" for n in ET.fromstring(content))


def test_manifestation_sheet_keeps_its_rows_together_without_pulling_following_narrative():
    from xml.etree import ElementTree as ET
    from scripts.backend_contract.delivery_renderer import _canonical_content_markup
    report, images = golden_report()
    content = _canonical_content_markup(report, b"w:", text_width=9000, figure_images=images)
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    root = ET.fromstring(b'<root xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">' + content + b'</root>')
    sheets = [table for table in root.iter(w + "tbl") if any("Classificação:" in (n.text or "") for n in table.iter(w + "t"))]
    assert len(sheets) == 2
    for table in sheets:
        rows = table.findall(w + "tr")
        assert all(row.find("./" + w + "trPr/" + w + "cantSplit") is not None for row in rows)
        assert all(len(list(row.iter(w + "keepNext"))) > 0 for row in rows[:-1])
        assert len(list(rows[-1].iter(w + "keepNext"))) == 0
        following = list(root)[list(root).index(table) + 1]
        assert following.tag == w + "p" and not list(following.iter(w + "t"))
        assert following.find("./" + w + "pPr/" + w + "keepNext").get(w + "val") == "0"
