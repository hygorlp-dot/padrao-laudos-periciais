from dataclasses import replace
import json
from pathlib import Path

import pytest

from scripts.backend_contract.application.process_metadata import PdfTextPage
from tests.test_report_foundation_v1 import upstreams


def test_questions_keep_original_number_origin_unicode_and_physical_pages():
    from scripts.backend_contract.case_intake import extract_questions
    doc = replace(upstreams()[1].documents[0], page_count_or_span="p. 2-3 | PJe sintético")
    pages = (PdfTextPage(1, "QUESITOS DO JUÍZO\n99. Fora do documento?"), PdfTextPage(2, "QUESITOS DA PARTE AUTORA\n01) A parede apresenta\numidade?\n\n2. Qual a extensão?\n"), PdfTextPage(3, "QUESITOS DA PARTE RÉ\n7 - Há fissuras?\n\nNestes termos,"))
    values = extract_questions(doc, pages)
    assert [(p.source.origin, p.source.original_number, p.text) for p in values] == [("CLAIMANT", "01)", "A parede apresenta\numidade?"), ("CLAIMANT", "2.", "Qual a extensão?"), ("DEFENDANT", "7 -", "Há fissuras?")]
    assert [p.source.page_start for p in values] == [2, 2, 3]
    assert values[0].text in values[0].source.excerpt


def test_question_intake_does_not_guess_origin_or_treat_narrative_mentions_as_questions():
    from scripts.backend_contract.case_intake import extract_questions
    doc = replace(upstreams()[1].documents[0], page_count_or_span="Documento completo")
    assert extract_questions(doc, (PdfTextPage(1, "A parte autora mencionou os quesitos.\n1. Qual seria a área?"),)) == ()


def test_inventory_document_heading_is_a_proposal_but_body_mention_is_not_presence():
    from scripts.backend_contract.case_intake import inventory_proposals
    doc = replace(upstreams()[1].documents[0], raw_type="peticao.pdf", page_count_or_span="Documento completo")
    values = inventory_proposals((doc,), {doc.document_id: (PdfTextPage(1, "PETIÇÃO\n\nRequer a juntada do habite-se."),)})
    row = next(p for p in values if p["category"] == "HABITE_SE")
    assert row["state"] == "NOT_FOUND_IN_CURRENT_INGESTED_MATERIAL" and not row["matches"]
    values = inventory_proposals((doc,), {doc.document_id: (PdfTextPage(1, "HABITE-SE\nCertificado sintético"),)})
    row = next(p for p in values if p["category"] == "HABITE_SE")
    assert row["state"] == "PROPOSED_PRESENT" and row["matches"][0]["page"] == 1


def test_real_intake_accepts_literal_questions_once_and_backup_rejects_forged_excerpt(tmp_path):
    # `pymupdf` nao e dependencia declarada: o CI instala so requirements-dev.txt.
    # `_text_pdf` usa `pypdf`, e o extrator do produto le deste PDF exatamente o
    # mesmo texto que lia do gerado por pymupdf (acentos e quebras incluidos).
    from tests.test_property_record_v1 import _text_pdf
    from scripts.backend_contract.local_api.composition import build_local_api
    from scripts.backend_contract.infrastructure.productization import VerifyWorkspaceBackup
    from scripts.backend_contract.application.ports import RepositoryIntegrityError
    from tests.test_product_integration_oracle_v1 import _http, http_request, _reseal, TOKEN
    runtime = build_local_api(tmp_path / "intake.db", token=TOKEN, private_root=tmp_path / "private")
    runtime.start()
    try:
        status, workspace = _http(runtime, "POST", "/v1/workspaces", {"name": "Quesitos sintéticos"})
        assert status == 201
        root = f"/v1/workspaces/{workspace['workspace_id']}"
        profile = json.loads((Path(__file__).parent / "fixtures/report-snapshot-v1.json").read_text(encoding="utf-8"))["expert_profile"]
        assert _http(runtime, "PUT", root + "/expert-profile", {"expected_revision": None, "profile": profile})[0] == 200
        data = _text_pdf(["QUESITOS DA PARTE AUTORA", "01) A parede apresenta umidade?", "", "2. Qual a extensão?"])
        assert _http(runtime, "POST", root + "/materials", raw_body=data, headers={"Content-Type": "application/pdf", "X-Document-Filename": "quesitos-sinteticos.pdf"})[0] == 201
        assert _http(runtime, "POST", root + "/case-analysis", {})[0] == 201
        status, proposed = _http(runtime, "GET", root + "/case-analysis/intake")
        assert status == 200 and len(proposed["questions"]) == 2
        chosen = proposed["questions"][0]
        body = {"proposal_ids": [chosen["proposal_id"]], "expected_revision": proposed["revision"]}
        status, accepted = _http(runtime, "POST", root + "/case-analysis/questions", body)
        assert status == 200 and len(accepted["snapshot"]["questions"]) == 1
        question = accepted["snapshot"]["questions"][0]
        assert question["text"] == chosen["text"] and question["source_question"]["original_number"] == "01)"
        body["expected_revision"] = accepted["revision"]
        status, repeated = _http(runtime, "POST", root + "/case-analysis/questions", body)
        assert status == 200 and repeated["revision"] == accepted["revision"]
        status, confirmed = _http(runtime, "POST", root + "/case-analysis/document-inventory", {"expected_revision": accepted["revision"], "values": {"category": "HABITE_SE", "status": "PROFESSIONALLY_CONFIRMED_ABSENT_FROM_CASE", "source_document_ids": [], "reason": "Conferência sintética integral feita pelo perito."}})
        assert status == 200 and confirmed["snapshot"]["document_inventory"][0]["confirmed_by"] == profile["profile_id"]
        status, case = _http(runtime, "POST", root + "/case-analysis/items", {"expected_revision": confirmed["revision"], "item_kind": "PERICIAL_OBJECT", "text": "Verificar condição superficial sintética.", "source_document_id": question["provenance"][0]["source_document_id"], "page_or_span": "p. 1", "technical_subjects": ["Superfície"], "values": {}})
        assert status == 200
        for item in [*case["snapshot"]["questions"], *case["snapshot"]["pericial_objects"]]:
            status, case = _http(runtime, "POST", root + "/case-analysis/reviews", {"expected_revision": case["revision"], "target_item_id": item["item_id"], "action": "CONFIRM", "corrected_value": None, "reviewer": profile["profile_id"], "reason": "Fonte sintética conferida."})
            assert status == 200
        status, planning = _http(runtime, "POST", root + "/pericial-planning", {"title": "Vistoria sintética"})
        assert status == 201
        planned = planning["snapshot"]["inspection_requirements"][0]
        status, planning = _http(runtime, "POST", root + "/pericial-planning/decisions", {"expected_revision": planning["revision"], "target_item_id": planned["item_id"], "action": "APPROVE", "reviewer": profile["profile_id"], "reason": "Planejamento sintético confirmado.", "decided_value": None})
        assert status == 200
        status, inspection = _http(runtime, "POST", root + "/inspection-session", {"responsible_professional": profile["profile_id"], "location_context": "Imóvel sintético", "participant_references": []})
        assert status == 201 and "visit_context" not in inspection["snapshot"]
        from tests.test_inspection_visit_context_v1 import visit_values
        status, inspection = _http(runtime, "POST", root + "/inspection-session/visit-context", {"expected_revision": inspection["revision"], "values": visit_values()})
        assert status == 200 and inspection["snapshot"]["visit_context"]["date"] == "2026-09-20"
        assert inspection["snapshot"]["participant_references"] == ["Pessoa sintética"]
        forged_visit = json.loads(json.dumps(inspection["snapshot"]))
        forged_visit["visit_context"]["weather"] = "Clima adulterado"
        assert _http(runtime, "PUT", root + "/inspection-session", {"expected_revision": inspection["revision"], "snapshot": forged_visit})[0] == 400
        assert _http(runtime, "POST", root + "/inspection-session/visit-context", {"expected_revision": 1, "values": visit_values()})[0] == 409
        assert _http(runtime, "GET", root + "/case-analysis/intake", headers={"X-Local-API-Token": "invalid"})[0] == 403
        status, _, backup = http_request(runtime.server, "POST", root + "/backup", value={}, headers={"X-Local-API-Token": TOKEN})
        assert status == 200
        VerifyWorkspaceBackup().execute(backup)
        forged = json.loads(backup)
        for revision in forged["artifact_revisions"]:
            if revision["artifact_kind"] == "CASE_ANALYSIS_SNAPSHOT_V1" and revision["revision"] == accepted["revision"]:
                q = revision["payload"]["questions"][0]
                q["text"] = "Pergunta inventada?"
                q["source_question"]["excerpt"] = "01) Pergunta inventada?"
                for review in revision["payload"]["human_reviews"]:
                    if review["target_item_id"] == q["item_id"]:
                        review["original_extraction"] = review["corrected_value"] = q["text"]
        with pytest.raises(RepositoryIntegrityError, match="question source evidence"):
            VerifyWorkspaceBackup().execute(_reseal(forged))
    finally:
        runtime.close()


def test_intake_commands_write_over_the_persisted_base_after_a_professional_exclusion(tmp_path):
    """Integracao com a #251: a Analise do Caso lida pelo GET e uma PROJECAO (peca excluida
    pelo perito aparece sem conteudo). Os comandos de intake gravavam essa projecao, que
    diverge do predecessor persistido -- toda confirmacao de inventario e todo aceite de
    quesito passavam a falhar depois de qualquer exclusao. Quem escreve parte do persistido."""
    from tests.test_pje_effective_availability_v1 import _distinct_pje_pdf, _effective, _find, _request, _runtime, _set_available, _setup

    runtime = _runtime(tmp_path)
    try:
        workspace_id, material = _setup(runtime, _distinct_pje_pdf(tmp_path / "autos.pdf", "intake-apos-exclusao"))
        root = f"/v1/workspaces/{workspace_id}"
        profile = json.loads((Path(__file__).parent / "fixtures/report-snapshot-v1.json").read_text(encoding="utf-8"))["expert_profile"]
        assert _request(runtime, "PUT", root + "/expert-profile", value={"expected_revision": None, "profile": profile})[0] == 200
        _effective(runtime, workspace_id)
        _set_available(runtime, workspace_id, material["content_id"], "DOC-PJE-002", False)
        excluded = _find(_effective(runtime, workspace_id), "DOC-PJE-002")
        available = _find(_effective(runtime, workspace_id), "DOC-PJE-001")
        assert excluded["content_available"] is False

        status, intake = _request(runtime, "GET", root + "/case-analysis/intake")
        assert status == 200, intake
        status, refused = _request(runtime, "POST", root + "/case-analysis/document-inventory", value={"expected_revision": intake["revision"], "values": {
            "category": "HABITE_SE", "status": "PROFESSIONALLY_CONFIRMED_PRESENT", "source_document_ids": [excluded["document_id"]], "reason": "Conferencia sintetica."}})
        assert status == 400, refused  # presenca nao pode se apoiar na peca excluida
        status, confirmed = _request(runtime, "POST", root + "/case-analysis/document-inventory", value={"expected_revision": intake["revision"], "values": {
            "category": "HABITE_SE", "status": "PROFESSIONALLY_CONFIRMED_PRESENT", "source_document_ids": [available["document_id"]], "reason": "Conferencia sintetica."}})
        assert status == 200, confirmed
        # a resposta e o read-model: a exclusao continua visivel, nada foi gravado como projecao
        assert _find(confirmed["snapshot"], "DOC-PJE-002")["content_available"] is False
        _set_available(runtime, workspace_id, material["content_id"], "DOC-PJE-002", True)
        assert _find(_effective(runtime, workspace_id), "DOC-PJE-002")["content_available"] is True
    finally:
        runtime.close()


def test_accepting_questions_after_a_professional_exclusion_keeps_the_exclusion(tmp_path):
    """Mesmo contrato para o aceite de quesitos: proposta vinda de fonte disponivel, gravada
    sobre a base persistida; a exclusao da outra peca segue visivel e reversivel."""
    from tests.test_pje_effective_availability_v1 import _distinct_pje_pdf, _effective, _find, _request, _runtime, _set_available, _setup
    from tests.test_property_record_v1 import _text_pdf

    runtime = _runtime(tmp_path)
    try:
        workspace_id, material = _setup(runtime, _distinct_pje_pdf(tmp_path / "autos.pdf", "quesitos-apos-exclusao"))
        root = f"/v1/workspaces/{workspace_id}"
        status, _ = _request(runtime, "POST", root + "/materials", body=_text_pdf(["QUESITOS DA PARTE AUTORA", "01) A parede apresenta umidade?"]),
                             headers={"Content-Type": "application/pdf", "X-Document-Filename": "quesitos-sinteticos.pdf"})
        assert status == 201
        _effective(runtime, workspace_id)
        _set_available(runtime, workspace_id, material["content_id"], "DOC-PJE-002", False)

        status, intake = _request(runtime, "GET", root + "/case-analysis/intake")
        assert status == 200 and len(intake["questions"]) == 1, intake
        status, accepted = _request(runtime, "POST", root + "/case-analysis/questions", value={
            "proposal_ids": [intake["questions"][0]["proposal_id"]], "expected_revision": intake["revision"]})
        assert status == 200, accepted
        assert [item["text"] for item in accepted["snapshot"]["questions"]] == ["A parede apresenta umidade?"]
        assert _find(accepted["snapshot"], "DOC-PJE-002")["content_available"] is False
        _set_available(runtime, workspace_id, material["content_id"], "DOC-PJE-002", True)
        assert _find(_effective(runtime, workspace_id), "DOC-PJE-002")["content_available"] is True
    finally:
        runtime.close()


def test_intake_never_opens_a_document_excluded_by_the_professional():
    """As propostas saem da projecao: peca excluida pelo perito nao e aberta nem lida,
    mesmo com a escrita partindo da base persistida."""
    from types import SimpleNamespace

    from scripts.backend_contract.application.case_intake import GetCaseIntake

    case = upstreams()[1]
    available = [d.document_id for d in case.documents if d.content_available]
    assert available
    excluded = {document_id: False for document_id in available}

    def refuse_open(*_args):
        raise AssertionError("opened a document excluded by the professional")

    intake = GetCaseIntake(
        SimpleNamespace(execute_for_command=lambda _w: (SimpleNamespace(revision=3), case, excluded)),
        SimpleNamespace(execute=refuse_open), SimpleNamespace(),
    )
    record, projected, questions, _inventory = intake.execute(case.workspace_id)
    assert record.revision == 3 and questions == ()
    assert not any(d.content_available for d in projected.documents)
    _record, base, availability, _proposals = intake.execute_for_command(case.workspace_id)
    assert base is case and availability == excluded  # a escrita parte do persistido
