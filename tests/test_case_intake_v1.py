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
