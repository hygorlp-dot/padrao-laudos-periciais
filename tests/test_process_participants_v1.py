"""#268 — participantes processuais como colecao estruturada e auditavel.

Tudo sintetico. A capa PJe de teste so traz a tabela de partes que o produto
le; nenhum nome, numero ou documento real.
"""

from __future__ import annotations

from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from scripts.backend_contract.application.pje_party_table import (
    PjeParticipantPole,
    parse_pje_participant_rows,
    parse_pje_party_table,
)
from scripts.backend_contract.judicial_domain import EntityKind, NormalizedProceduralRole
from scripts.backend_contract.process_participants import (
    CaseParticipant,
    ParticipantOrigin,
    ParticipantPole,
    ParticipantReviewState,
    ParticipantSource,
    ProcessParticipantsRegister,
    legacy_participants,
    participants_register_from_mapping,
    participants_register_to_mapping,
    participants_summary,
    source_participant_id,
)
from tests.test_property_record_v1 import _text_pdf


_HEADER = "PARTES PROCURADOR TERCEIRO VINCULADO"


def _rows(text):
    return [(row.pole.value, row.role, row.name, [(item.name, item.role) for item in row.representatives]) for row in parse_pje_participant_rows(text).rows]


@pytest.mark.parametrize(
    "lines, expected",
    [
        (["ALFA UM (AUTOR) ADV UM (ADVOGADO)", "BETA DOIS (REU) PROC DOIS (PROCURADOR)"], [("ACTIVE", 1), ("PASSIVE", 1)]),
        (["ALFA UM (AUTOR) ADV UM (ADVOGADO)", "ALFA DOIS (AUTORA) ADV UM (ADVOGADO)", "BETA (REU)"], [("ACTIVE", 2), ("PASSIVE", 1)]),
        (["ALFA (REQUERENTE)", "BETA UM (REQUERIDO)", "BETA DOIS (REQUERIDA)", "BETA TRES (EXECUTADO)"], [("ACTIVE", 1), ("PASSIVE", 3)]),
    ],
)
def test_grammar_keeps_every_party_of_each_pole(lines, expected):
    rows = _rows("\n".join([_HEADER, *lines]))
    for pole, count in expected:
        assert sum(1 for row in rows if row[0] == pole) == count
    assert len(rows) == len(lines)


def test_grammar_reads_other_participants_and_links_every_representative():
    text = "\n".join([
        "Cabeçalho qualquer",
        "POLO ATIVO",
        "ALFA SINTÉTICA (AUTORA) ADVOGADA UM (ADVOGADA)",
        "ADVOGADO DOIS (ADVOGADO)",
        "",
        "POLO PASSIVO",
        "EMPRESA SINTÉTICA S.A. (RÉU) PROCURADOR TRÊS (PROCURADOR)",
        "OUTROS PARTICIPANTES",
        "ÓRGÃO SINTÉTICO (FISCAL DA LEI)",
        "TERCEIRA SINTÉTICA (TERCEIRO INTERESSADO) DEFENSORA QUATRO (DEFENSORA PÚBLICA)",
    ])
    assert _rows(text) == [
        ("ACTIVE", "AUTORA", "ALFA SINTÉTICA", [("ADVOGADA UM", "ADVOGADA"), ("ADVOGADO DOIS", "ADVOGADO")]),
        ("PASSIVE", "REU", "EMPRESA SINTÉTICA S.A.", [("PROCURADOR TRÊS", "PROCURADOR")]),
        ("OTHER", "FISCAL DA LEI", "ÓRGÃO SINTÉTICO", []),
        ("OTHER", "TERCEIRO INTERESSADO", "TERCEIRA SINTÉTICA", [("DEFENSORA QUATRO", "DEFENSORA PUBLICA")]),
    ]


def test_grammar_spans_point_at_the_exact_source_name():
    text = _HEADER + "\nJOSÉ SINTÉTICO (AUTOR) ADV (ADVOGADO)\n"
    row = parse_pje_participant_rows(text).rows[0]
    assert text[row.source_start:row.source_end] == "JOSÉ SINTÉTICO"
    representative = row.representatives[0]
    assert text[representative.source_start:representative.source_end] == "ADV"


def test_grammar_fails_closed_and_never_infers_pole_from_the_name():
    rows = parse_pje_participant_rows("\n".join([
        "POLO ATIVO",
        "ALFA (REU)",
        "BETA (AUTOR)",
    ]))
    # O papel contradiz a secao: a leitura para, nada e reclassificado.
    assert rows.rows == () and rows.terminated
    narrative = parse_pje_participant_rows("Na petição, FULANO (AUTOR) alega...\n")
    assert narrative.rows == ()
    unknown = parse_pje_participant_rows(_HEADER + "\nALFA (AUTOR)\nTEXTO (QUALQUER COISA)\nBETA (REU)")
    assert [row.name for row in unknown.rows] == ["ALFA"] and unknown.terminated


def test_legacy_grammar_is_untouched_by_the_participant_grammar():
    text = _HEADER + "\nALFA (AUTOR) ADV (ADVOGADO)\nBETA (REU)\n"
    legacy = parse_pje_party_table(text)
    assert [row.name for row in legacy.rows] == ["ALFA"]
    assert [row.pole for row in parse_pje_participant_rows(text).rows] == [PjeParticipantPole.ACTIVE, PjeParticipantPole.PASSIVE]


def test_grammar_is_linear_on_adversarial_lines():
    from time import perf_counter
    line = "A" * 5000 + " (AUTOR) " + "(" * 3000 + " B (ADVOGADO)"
    started = perf_counter()
    parse_pje_participant_rows(_HEADER + "\n" + line * 3)
    assert perf_counter() - started < 2.0


_CONTENT = "11111111-1111-4111-8111-111111111111"


def _source(page=1, start=0, end=4):
    return ParticipantSource(_CONTENT, "a" * 64, "capa.pdf", page, start, end, "ALFA (AUTOR)", "NATIVE_TEXT", None)


def _participant(**changes):
    value = CaseParticipant(
        source_participant_id(workspace_id="w", content_id=_CONTENT, logical_document_id=None, page=1, source_start=0, source_end=4, pole=ParticipantPole.ACTIVE, role_label="AUTOR"),
        "ALFA", ParticipantPole.ACTIVE, NormalizedProceduralRole.CLAIMANT, "AUTOR", EntityKind.UNKNOWN, (), (_source(),),
        ParticipantOrigin.SOURCE, ParticipantReviewState.CONFIRMED, "2026-10-02T12:00:00+00:00",
    )
    return replace(value, **changes)


def test_source_identity_ignores_the_name_and_separates_same_names():
    first = source_participant_id(workspace_id="w", content_id=_CONTENT, logical_document_id=None, page=1, source_start=0, source_end=4, pole=ParticipantPole.ACTIVE, role_label="AUTOR")
    same_name_elsewhere = source_participant_id(workspace_id="w", content_id=_CONTENT, logical_document_id=None, page=1, source_start=40, source_end=44, pole=ParticipantPole.ACTIVE, role_label="AUTOR")
    other_workspace = source_participant_id(workspace_id="x", content_id=_CONTENT, logical_document_id=None, page=1, source_start=0, source_end=4, pole=ParticipantPole.ACTIVE, role_label="AUTOR")
    assert len({first, same_name_elsewhere, other_workspace}) == 3


def test_register_rejects_proposal_promotion_and_missing_provenance():
    with pytest.raises(ValueError):
        ProcessParticipantsRegister("1.0.0", "w", (_participant(review_state=ParticipantReviewState.PROPOSED, decided_at=None),))
    with pytest.raises(ValueError):
        _participant(provenance=())
    with pytest.raises(ValueError):
        _participant(decided_at=None)
    with pytest.raises(ValueError):
        ProcessParticipantsRegister("1.0.0", "w", (_participant(), _participant()))
    register = ProcessParticipantsRegister("1.0.0", "w", (_participant(),))
    assert participants_register_from_mapping(participants_register_to_mapping(register)) == register


def test_legacy_projection_keeps_the_exact_strings_without_splitting():
    projected = legacy_participants("w", "ALFA UM E ALFA DOIS", "BETA", "2026-10-02T12:00:00+00:00")
    assert [(item.pole, item.name, item.origin) for item in projected.participants] == [
        (ParticipantPole.ACTIVE, "ALFA UM E ALFA DOIS", ParticipantOrigin.LEGACY_PROCESS_CASE),
        (ParticipantPole.PASSIVE, "BETA", ParticipantOrigin.LEGACY_PROCESS_CASE),
    ]
    assert legacy_participants("w", "", " ", "2026-10-02T12:00:00+00:00").participants == ()


def test_cover_summary_never_hides_how_many_were_left_out():
    participants = tuple(
        _participant(participant_id=f"PARTICIPANT-MAN-{index:032X}", origin=ParticipantOrigin.MANUAL, provenance=(), name=f"PARTE {index}")
        for index in range(20)
    )
    summary = participants_summary(participants, ParticipantPole.ACTIVE)
    assert summary.startswith("PARTE 0; PARTE 1; PARTE 2 e outros 17")
    assert participants_summary(participants, ParticipantPole.PASSIVE) == ""


# --- Fluxo de produto: HTTP real, reinicio, backup, laudo ------------------


def _cover(lines):
    return _text_pdf(["PODER JUDICIARIO", "Processo Judicial Eletronico", *lines])


def _runtime(tmp_path):
    from scripts.backend_contract.local_api.composition import build_local_api
    from tests.test_product_integration_oracle_v1 import TOKEN
    runtime = build_local_api(tmp_path / "participants.db", token=TOKEN, private_root=tmp_path / "private")
    runtime.start()
    return runtime


def _save_process(runtime, root):
    from tests.test_product_integration_oracle_v1 import _http
    status, process = _http(runtime, "GET", root + "/process-case")
    assert status == 200
    data = {**process["data"], "numero_processo": "0000000-00.2026.4.05.0000"}
    assert _http(runtime, "POST", root + "/process-case", {"expected_revision": process["revision"], "data": data})[0] in (200, 201)


def _import(runtime, root, pdf, filename):
    from tests.test_product_integration_oracle_v1 import _http
    status, _ = _http(runtime, "POST", root + "/materials", raw_body=pdf, headers={"Content-Type": "application/pdf", "X-Document-Filename": filename})
    assert status == 201


def test_product_flow_confirms_rejects_adds_and_survives_restart_and_backup(tmp_path):
    from scripts.backend_contract.infrastructure.productization import VerifyWorkspaceBackup
    from tests.test_product_integration_oracle_v1 import TOKEN, _http, http_request
    runtime = _runtime(tmp_path)
    try:
        status, workspace = _http(runtime, "POST", "/v1/workspaces", {"name": "Partes sintéticas"})
        assert status == 201
        root = f"/v1/workspaces/{workspace['workspace_id']}"
        status, empty = _http(runtime, "GET", root + "/process-participants")
        assert status == 200 and empty["participants"] == [] and empty["proposals"] == [] and empty["revision"] is None
        assert empty["process_record_saved"] is False
        _save_process(runtime, root)
        _import(runtime, root, _cover([
            _HEADER,
            "ALFA SINTETICA (AUTORA) ADVOGADA UM (ADVOGADA)",
            "ADVOGADO DOIS (ADVOGADO)",
            "ALFA SINTETICA (AUTORA) ADVOGADA UM (ADVOGADA)",
            "BETA SINTETICA S.A. (REU) PROCURADOR TRES (PROCURADOR)",
            "GAMA SINTETICA (REU)",
            "DELTA SINTETICA (TERCEIRO INTERESSADO)",
        ]), "capa-sintetica.pdf")
        status, view = _http(runtime, "GET", root + "/process-participants")
        assert status == 200
        proposals = view["proposals"]
        # Mesmo nome duas vezes na fonte: duas propostas, nunca fundidas pelo nome.
        assert [(p["pole"], p["name"]) for p in proposals] == [
            ("ACTIVE", "ALFA SINTETICA"), ("ACTIVE", "ALFA SINTETICA"), ("PASSIVE", "BETA SINTETICA S.A."),
            ("PASSIVE", "GAMA SINTETICA"), ("OTHER", "DELTA SINTETICA"),
        ]
        assert all(p["review_state"] == "PROPOSED" for p in proposals) and view["participants"] == []
        alfa = proposals[0]
        assert [r["name"] for r in alfa["representatives"]] == ["ADVOGADA UM", "ADVOGADO DOIS"]
        assert alfa["provenance"][0]["page"] == 1 and alfa["provenance"][0]["filename"] == "capa-sintetica.pdf"
        assert len(alfa["provenance"][0]["source_sha256"]) == 64

        def decide(action, expected, **payload):
            return _http(runtime, "POST", root + "/process-participants/decisions", {"action": action, "expected_revision": expected, "payload": payload})

        status, saved = decide("CONFIRM", None, proposal_id=alfa["participant_id"])
        assert status == 200 and saved["revision"] == 1
        assert decide("CONFIRM", None, proposal_id=proposals[2]["participant_id"])[0] == 409
        assert decide("CONFIRM", 1, proposal_id="PARTICIPANT-SRC-FFFFFFFFFFFFFFFFFFFFFFFF")[0] == 400
        assert decide("REJECT", 1, proposal_id=proposals[1]["participant_id"])[0] == 200
        assert decide("CONFIRM", 2, proposal_id=proposals[2]["participant_id"])[0] == 200
        assert decide("CONFIRM", 3, proposal_id=proposals[3]["participant_id"])[0] == 200
        assert decide("CONFIRM", 4, proposal_id=proposals[4]["participant_id"])[0] == 200
        manual = {
            "name": "EPSILON MANUAL", "pole": "OTHER", "procedural_role": "ASSISTANT", "source_role_label": "Assistente técnico",
            "person_type": "NATURAL_PERSON", "representatives": [],
        }
        status, saved = decide("ADD_MANUAL", 5, participant=manual)
        assert status == 200 and saved["participants"][-1]["origin"] == "MANUAL"
        beta = next(p for p in saved["participants"] if p["name"] == "BETA SINTETICA S.A.")
        edited = {**{key: beta[key] for key in ("pole", "procedural_role", "source_role_label", "person_type")}, "name": "BETA SINTÉTICA S.A.",
                  "representatives": [{"name": r["name"], "role_label": r["role_label"], "registration": r["registration"]} for r in beta["representatives"]] + [{"name": "ADVOGADA NOVA", "role_label": "Advogada", "registration": None}]}
        edited["person_type"] = "LEGAL_ENTITY"
        status, saved = decide("EDIT", 6, participant_id=beta["participant_id"], participant=edited)
        assert status == 200
        beta = next(p for p in saved["participants"] if p["participant_id"] == beta["participant_id"])
        assert beta["edited"] is True and beta["provenance"][0]["excerpt"].startswith("BETA SINTETICA S.A.")
        # O procurador lido da fonte mantem a proveniencia; o novo nao inventa uma.
        assert beta["representatives"][0]["provenance"] and beta["representatives"][1]["provenance"] == []
        order = [p["participant_id"] for p in saved["participants"]]
        status, reordered = decide("REORDER", 7, participant_ids=list(reversed(order)))
        assert status == 200 and [p["participant_id"] for p in reordered["participants"]] == list(reversed(order))
        assert decide("REORDER", 8, participant_ids=order[:-1])[0] == 400
        gama = next(p for p in reordered["participants"] if p["name"] == "GAMA SINTETICA")
        status, removed = decide("REMOVE", 8, participant_id=gama["participant_id"])
        assert status == 200 and next(p for p in removed["participants"] if p["participant_id"] == gama["participant_id"])["review_state"] == "REJECTED"
        status, final = _http(runtime, "GET", root + "/process-participants")
        assert status == 200 and final["revision"] == 9 and final["proposals"] == []
        confirmed = [p for p in final["participants"] if p["review_state"] == "CONFIRMED"]
        assert {p["pole"] for p in confirmed} == {"ACTIVE", "PASSIVE", "OTHER"} and len(confirmed) == 4
        status, _, backup = http_request(runtime.server, "POST", root + "/backup", value={}, headers={"X-Local-API-Token": TOKEN})
        assert status == 200
        restored = VerifyWorkspaceBackup().execute(backup)
        assert sum(r["artifact_kind"] == "PROCESS_PARTICIPANTS_V1" for r in restored.artifact_revisions) == 9
    finally:
        runtime.close()
    reopened = _runtime(tmp_path)
    try:
        status, after = _http(reopened, "GET", root + "/process-participants")
        assert status == 200 and after["participants"] == final["participants"] and after["revision"] == 9
    finally:
        reopened.close()


def test_backup_refuses_a_forged_participant_source(tmp_path):
    from scripts.backend_contract.application.ports import RepositoryIntegrityError
    from scripts.backend_contract.infrastructure.productization import VerifyWorkspaceBackup
    from tests.test_product_integration_oracle_v1 import TOKEN, _http, _reseal, http_request
    runtime = _runtime(tmp_path)
    try:
        _, workspace = _http(runtime, "POST", "/v1/workspaces", {"name": "Fonte forjada"})
        root = f"/v1/workspaces/{workspace['workspace_id']}"
        _import(runtime, root, _cover([_HEADER, "ALFA SINTETICA (AUTOR)"]), "capa.pdf")
        _save_process(runtime, root)
        proposal = _http(runtime, "GET", root + "/process-participants")[1]["proposals"][0]
        assert _http(runtime, "POST", root + "/process-participants/decisions", {"action": "CONFIRM", "expected_revision": None, "payload": {"proposal_id": proposal["participant_id"]}})[0] == 200
        status, _, backup = http_request(runtime.server, "POST", root + "/backup", value={}, headers={"X-Local-API-Token": TOKEN})
        assert status == 200
        for tamper in ("sha", "content"):
            altered = json.loads(backup)
            revision = next(r for r in altered["artifact_revisions"] if r["artifact_kind"] == "PROCESS_PARTICIPANTS_V1")
            source = revision["payload"]["participants"][0]["provenance"][0]
            if tamper == "sha":
                source["source_sha256"] = "f" * 64
            else:
                source["content_id"] = "22222222-2222-4222-8222-222222222222"
            with pytest.raises(RepositoryIntegrityError, match="participant source"):
                VerifyWorkspaceBackup().execute(_reseal(altered))
    finally:
        runtime.close()


def test_legacy_scalar_parties_become_a_projection_and_are_materialized_on_first_decision(tmp_path):
    from tests.test_product_integration_oracle_v1 import _http
    runtime = _runtime(tmp_path)
    try:
        _, workspace = _http(runtime, "POST", "/v1/workspaces", {"name": "Legado"})
        root = f"/v1/workspaces/{workspace['workspace_id']}"
        status, process = _http(runtime, "GET", root + "/process-case")
        assert status == 200
        data = {**process["data"], "parte_requerente": "ALFA E BETA", "parte_requerida": "GAMA"}
        assert _http(runtime, "POST", root + "/process-case", {"expected_revision": None, "data": data})[0] in (200, 201)
        status, view = _http(runtime, "GET", root + "/process-participants")
        assert status == 200 and view["legacy_projection"] is True and view["revision"] is None
        assert [(p["pole"], p["name"], p["origin"]) for p in view["participants"]] == [
            ("ACTIVE", "ALFA E BETA", "LEGACY_PROCESS_CASE"), ("PASSIVE", "GAMA", "LEGACY_PROCESS_CASE"),
        ]
        manual = {"name": "DELTA", "pole": "PASSIVE", "procedural_role": "DEFENDANT", "source_role_label": "Réu", "person_type": "UNKNOWN", "representatives": []}
        status, saved = _http(runtime, "POST", root + "/process-participants/decisions", {"action": "ADD_MANUAL", "expected_revision": None, "payload": {"participant": manual}})
        assert status == 200 and [p["name"] for p in saved["participants"]] == ["ALFA E BETA", "GAMA", "DELTA"]
        status, view = _http(runtime, "GET", root + "/process-participants")
        assert view["legacy_projection"] is False and view["revision"] == 1
    finally:
        runtime.close()


def test_excluded_source_stops_proposals_and_marks_confirmed_participant_stale():
    from scripts.backend_contract.application.case_document_texts import CaseDocumentText, LogicalDocumentSpan
    from scripts.backend_contract.application.process_participants import GetProcessParticipants, ParticipantProposals
    page = SimpleNamespace(number=2, text=_HEADER + "\nALFA (AUTOR)\nBETA (REU)\n", extraction_mode=SimpleNamespace(value="NATIVE_TEXT"))
    available = LogicalDocumentSpan("DOC-1", "Petição", "PETICAO_INICIAL", 1, 3, True)
    document = CaseDocumentText(_CONTENT, "a" * 64, "autos.pdf", (page,), (available,), False)
    texts = SimpleNamespace(execute=lambda _w: (document,))
    proposals = ParticipantProposals(texts).execute("w")
    assert [p.name for p in proposals.proposals] == ["ALFA", "BETA"]
    assert all(p.provenance[0].logical_document_id == "DOC-1" for p in proposals.proposals)
    confirmed = replace(proposals.proposals[0], review_state=ParticipantReviewState.CONFIRMED, decided_at="2026-10-02T12:00:00+00:00")
    register = ProcessParticipantsRegister("1.0.0", "w", (confirmed,))
    from scripts.backend_contract.application.models import _freeze_payload
    record = SimpleNamespace(revision=1, created_at="2026-10-02T12:00:00+00:00", payload=_freeze_payload(participants_register_to_mapping(register)))
    excluded_document = replace(document, logical_documents=(replace(available, available=False),))
    excluded_texts = SimpleNamespace(execute=lambda _w: (excluded_document,))
    process_case = SimpleNamespace(execute=lambda _w: SimpleNamespace(revision=1, updated_at=None, data=None))
    service = GetProcessParticipants(SimpleNamespace(execute=lambda *_a: record), process_case, excluded_texts, ParticipantProposals(excluded_texts))
    view = service.execute("w")
    assert view.proposals == () and view.stale_participant_ids == (confirmed.participant_id,)
    assert view.register.confirmed == (confirmed,)
    pending = replace(document, pages=(), reading_pending=True)
    waiting = ParticipantProposals(SimpleNamespace(execute=lambda _w: (pending,))).execute("w")
    assert waiting.proposals == () and waiting.pending_documents == ("autos.pdf",)


def test_report_captures_participants_only_after_the_register_exists():
    from scripts.backend_contract.application.models import ProcessCaseData
    from scripts.backend_contract.delivery_renderer import professional_report_blocks
    from scripts.backend_contract.report_foundation import ReportProcess, report_snapshot_from_mapping, report_snapshot_to_mapping
    from scripts.backend_contract.report_template import _FIELD_VALUES
    from tests.test_report_foundation_v1 import bound_report
    report = bound_report()
    data = ProcessCaseData.empty().as_dict()
    data.update(numero_processo="0000000-00.2026.4.05.0000", vara="1ª Vara Federal", tribunal="Tribunal Sintético")
    legacy_capture = ReportProcess(workspace_id=report.workspace_id, source_revision=1, source_checksum="c" * 64, **data)
    assert "participants" not in report_snapshot_to_mapping(replace(report, process_record=legacy_capture))["process_record"]
    many = tuple(
        _participant(participant_id=f"PARTICIPANT-MAN-{index:032X}", origin=ParticipantOrigin.MANUAL, provenance=(), name=f"AUTORA {index:02d}")
        for index in range(20)
    ) + (_participant(participant_id="PARTICIPANT-MAN-" + "F" * 32, origin=ParticipantOrigin.MANUAL, provenance=(), name="RÉ ÚNICA", pole=ParticipantPole.PASSIVE),
         _participant(participant_id="PARTICIPANT-MAN-" + "E" * 32, origin=ParticipantOrigin.MANUAL, provenance=(), name="MINISTÉRIO SINTÉTICO", pole=ParticipantPole.OTHER, source_role_label="Fiscal da lei"),
         _participant(participant_id="PARTICIPANT-MAN-" + "D" * 32, origin=ParticipantOrigin.MANUAL, provenance=(), name="DESCARTADA", review_state=ParticipantReviewState.REJECTED))
    capture = replace(legacy_capture, participants=many, participants_revision=3, participants_checksum="d" * 64)
    current = replace(report, process_record=capture)
    mapping = report_snapshot_to_mapping(current)
    assert report_snapshot_from_mapping(mapping) == current
    assert len(mapping["process_record"]["participants"]) == 23
    texts = [block.paragraph_texts for block in professional_report_blocks(current)]
    flat = [text for group in texts for text in group]
    # Nenhuma parte confirmada some do documento; a descartada nao aparece.
    lines = "\n".join(flat)
    # Entrada manual usa o papel que o perito escreveu.
    assert all(f"AUTORA {index:02d} (AUTOR)" in flat for index in range(20))
    assert "RÉ ÚNICA (AUTOR)" in flat and "MINISTÉRIO SINTÉTICO (Fiscal da lei)" in flat and "DESCARTADA" not in lines
    headings = [text for text in flat if text in ("Polo ativo:", "Polo passivo:", "Outros participantes:")]
    assert headings == ["Polo ativo:", "Polo passivo:", "Outros participantes:"]
    assert flat.index("Polo ativo:") < flat.index("AUTORA 00 (AUTOR)") < flat.index("Polo passivo:") < flat.index("RÉ ÚNICA (AUTOR)")
    assert _FIELD_VALUES["PARTICIPANTS_ACTIVE"](current).endswith("e outros 17 (relação completa no item 1)")
    assert _FIELD_VALUES["PARTICIPANTS_PASSIVE"](current) == "RÉ ÚNICA"
    assert _FIELD_VALUES["PARTICIPANTS_OTHER"](current) == "MINISTÉRIO SINTÉTICO"


def test_participants_are_isolated_between_workspaces(tmp_path):
    from tests.test_product_integration_oracle_v1 import _http
    runtime = _runtime(tmp_path)
    try:
        _, first = _http(runtime, "POST", "/v1/workspaces", {"name": "Perícia A"})
        _, second = _http(runtime, "POST", "/v1/workspaces", {"name": "Perícia B"})
        root_a, root_b = (f"/v1/workspaces/{item['workspace_id']}" for item in (first, second))
        _import(runtime, root_a, _cover([_HEADER, "ALFA SINTETICA (AUTOR)"]), "capa-a.pdf")
        proposal = _http(runtime, "GET", root_a + "/process-participants")[1]["proposals"][0]
        status, other = _http(runtime, "GET", root_b + "/process-participants")
        assert status == 200 and other["proposals"] == [] and other["participants"] == []
        _save_process(runtime, root_b)
        status, _ = _http(runtime, "POST", root_b + "/process-participants/decisions", {"action": "CONFIRM", "expected_revision": None, "payload": {"proposal_id": proposal["participant_id"]}})
        assert status == 400
        # O mesmo PDF na outra pericia e outra fonte: outra identidade.
        _import(runtime, root_b, _cover([_HEADER, "ALFA SINTETICA (AUTOR)"]), "capa-a.pdf")
        mirrored = _http(runtime, "GET", root_b + "/process-participants")[1]["proposals"][0]
        assert mirrored["participant_id"] != proposal["participant_id"]
    finally:
        runtime.close()


# --- Revisao independente da PR #274.


def _document(*pages, logical=()):
    from scripts.backend_contract.application.case_document_texts import CaseDocumentText
    return CaseDocumentText(_CONTENT, "a" * 64, "autos.pdf", tuple(pages), tuple(logical), False)


def _text_page(text, number=1):
    return SimpleNamespace(number=number, text=text, extraction_mode=SimpleNamespace(value="NATIVE_TEXT"))


def _proposal_set(*pages):
    from scripts.backend_contract.application.process_participants import ParticipantProposals
    document = _document(*pages)
    return ParticipantProposals(SimpleNamespace(execute=lambda _w: (document,))).execute("w")


def test_legacy_text_longer_than_a_name_is_projected_whole_never_cut():
    from scripts.backend_contract.process_participants import legacy_projection
    many = ", ".join(f"AUTOR SINTETICO NUMERO {index:02d}" for index in range(15))
    assert len(many) > 300
    register, blocked = legacy_projection("w", many, "RÉ SINTÉTICA", "2026-10-02T12:00:00+00:00")
    assert register.participants[0].name == many and blocked == ()
    register, blocked = legacy_projection("w", "ALFA\x00BETA", "GAMA\x02", "2026-10-02T12:00:00+00:00")
    assert register.participants == () and blocked == (ParticipantPole.ACTIVE, ParticipantPole.PASSIVE)


def test_a_representative_never_crosses_a_section_or_table_header():
    for separator in ("POLO PASSIVO", _HEADER):
        parsed = parse_pje_participant_rows("\n".join([
            _HEADER, "POLO ATIVO", "JOAO SINTETICO (AUTOR) MARIA ADV (ADVOGADO)", separator,
            "PEDRO ADV CEF (ADVOGADO)", "CAIXA SINTETICA (REU)",
        ]))
        assert [(row.name, [item.name for item in row.representatives]) for row in parsed.rows] == [("JOAO SINTETICO", ["MARIA ADV"])]
        assert parsed.terminated is True


def test_inline_other_interested_prefix_does_not_leak_into_the_name():
    rows = _rows(_HEADER + "\nOUTROS INTERESSADOS: UNIAO SINTETICA (TERCEIRO INTERESSADO)\n")
    assert rows == [("OTHER", "TERCEIRO INTERESSADO", "UNIAO SINTETICA", [])]


def test_an_odd_line_is_skipped_and_said_without_dropping_the_rest():
    odd = "FULANO " * 50 + "(AUTOR)"
    result = _proposal_set(_text_page("\n".join([_HEADER, "ALFA (AUTOR)", odd, "JO\x02AO (AUTOR)"])), _text_page(_HEADER + "\nBETA (REU)\n", 2))
    assert [item.name for item in result.proposals] == ["ALFA", "BETA"]
    assert result.interrupted_pages == (("autos.pdf", 1),)


def test_table_continued_on_the_next_page_or_stopped_at_zero_rows_is_flagged():
    continued = _proposal_set(
        _text_page(_HEADER + "\nPOLO ATIVO\nAUTOR UM (AUTOR)\n"),
        _text_page("AUTOR DOIS (AUTOR)\nPOLO PASSIVO\nCAIXA SINTETICA (REU)\n", 2),
    )
    assert ("autos.pdf", 2) in continued.interrupted_pages
    stopped = _proposal_set(_text_page(_HEADER + "\nJOAO (LITISCONSORTE)\n"))
    assert stopped.proposals == () and stopped.interrupted_pages == (("autos.pdf", 1),)


def test_control_characters_never_reach_a_participant():
    with pytest.raises(ValueError):
        _participant(name="JO\x02AO")
    with pytest.raises(ValueError):
        _participant(origin=ParticipantOrigin.MANUAL, provenance=(), participant_id="PARTICIPANT-MAN-" + "A" * 32, name="LINHA\nDUPLA")


def test_source_roles_keep_their_accents_in_the_report_line():
    from scripts.backend_contract.process_participants import participant_line
    result = _proposal_set(_text_page(_HEADER + "\nDEFENSORIA SINTETICA (ASSISTENTE TECNICO) FULANA (DEFENSOR PUBLICO)\n"))
    line = participant_line(replace(result.proposals[0], review_state=ParticipantReviewState.CONFIRMED, decided_at="2026-10-02T12:00:00+00:00"))
    assert "(assistente técnico)" in line and "(defensor público)" in line


def test_same_name_in_the_same_pole_is_flagged_never_merged():
    from scripts.backend_contract.application.process_participants import GetProcessParticipants, ParticipantProposals
    document = _document(_text_page(_HEADER + "\nCAIXA ECONOMICA SINTETICA (REU)\nCAIXA ECONÔMICA SINTÉTICA (REU)\n"))
    texts = SimpleNamespace(execute=lambda _w: (document,))
    from scripts.backend_contract.application.models import ProcessCaseData
    data = replace(ProcessCaseData.empty(), parte_requerida="Caixa Econômica Sintética")
    process_case = SimpleNamespace(execute=lambda _w: SimpleNamespace(revision=1, updated_at="2026-10-02T12:00:00+00:00", data=data))
    from scripts.backend_contract.application.ports import ArtifactRevisionNotFound

    def missing(*_args):
        raise ArtifactRevisionNotFound("none")

    view = GetProcessParticipants(SimpleNamespace(execute=missing), process_case, texts, ParticipantProposals(texts)).execute("w")
    assert len(view.proposals) == 2 and view.legacy_projection is True
    assert [item.matches_id for item in view.duplicates] == ["PARTICIPANT-LEGACY-PASSIVE", "PARTICIPANT-LEGACY-PASSIVE"]


def test_decisions_require_the_saved_process_and_restore_checks_the_source(tmp_path):
    from tests.test_product_integration_oracle_v1 import _http
    runtime = _runtime(tmp_path)
    try:
        _, workspace = _http(runtime, "POST", "/v1/workspaces", {"name": "Sem processo"})
        root = f"/v1/workspaces/{workspace['workspace_id']}"
        manual = {"name": "ALFA", "pole": "ACTIVE", "procedural_role": "CLAIMANT", "source_role_label": "Autora", "person_type": "UNKNOWN", "representatives": []}
        status, body = _http(runtime, "POST", root + "/process-participants/decisions", {"action": "ADD_MANUAL", "expected_revision": None, "payload": {"participant": manual}})
        assert status == 409 and body["error"]["code"] == "PROCESS_RECORD_REQUIRED"
        assert _http(runtime, "GET", root + "/process-participants")[1]["revision"] is None
    finally:
        runtime.close()


def test_restore_of_a_rejected_source_whose_piece_was_excluded_is_refused():
    from scripts.backend_contract.application.case_document_texts import LogicalDocumentSpan
    from scripts.backend_contract.application.models import _freeze_payload
    from scripts.backend_contract.application.process_participants import DecideProcessParticipants, GetProcessParticipants, ParticipantProposals
    from contextlib import nullcontext
    from datetime import datetime, timezone
    from uuid import uuid4
    available = LogicalDocumentSpan("DOC-1", "Capa", "CAPA", 1, 1, True)
    page = _text_page(_HEADER + "\nALFA (AUTOR)\n")
    proposal = _proposal_set(page).proposals[0]
    rejected = replace(proposal, provenance=(replace(proposal.provenance[0], logical_document_id="DOC-1"),), review_state=ParticipantReviewState.REJECTED, decided_at="2026-10-02T12:00:00+00:00")
    register = ProcessParticipantsRegister("1.0.0", "w", (rejected,))
    record = SimpleNamespace(revision=1, created_at="2026-10-02T12:00:00+00:00", payload=_freeze_payload(participants_register_to_mapping(register)))
    excluded = _document(page, logical=(replace(available, available=False),))
    texts = SimpleNamespace(execute=lambda _w: (excluded,))
    process_case = SimpleNamespace(execute=lambda _w: SimpleNamespace(revision=1, updated_at=None, data=None))
    reader = GetProcessParticipants(SimpleNamespace(execute=lambda *_a: record), process_case, texts, ParticipantProposals(texts))
    decide = DecideProcessParticipants(
        reader, SimpleNamespace(append_if_latest=lambda **_k: pytest.fail("must not write")), nullcontext,
        SimpleNamespace(now=lambda: datetime(2026, 10, 2, tzinfo=timezone.utc)), SimpleNamespace(new_uuid=uuid4),
    )
    with pytest.raises(ValueError, match="source changed or was excluded"):
        decide.execute("w", action="RESTORE", expected_revision=1, payload={"participant_id": rejected.participant_id})


def test_report_participants_without_process_record_fail_closed_and_later_confirmations_make_it_stale():
    from scripts.backend_contract.application.ports import ArtifactRevisionNotFound
    from scripts.backend_contract.application.report_foundation import GetReportProcess, _process_reasons

    def only_participants(_workspace, kind, _artifact):
        if kind == "PROCESS_CASE":
            raise ArtifactRevisionNotFound("none")
        return SimpleNamespace()

    with pytest.raises(ValueError, match="without the process record"):
        GetReportProcess(SimpleNamespace(execute=only_participants)).execute("w")
    confirmed = SimpleNamespace(workspace_id="w", confirmed_participants=(object(),))
    getter = SimpleNamespace(execute=lambda _w: confirmed)
    assert _process_reasons(SimpleNamespace(process_record=None), getter, "w") == ("process participants changed",)
    empty = SimpleNamespace(execute=lambda _w: SimpleNamespace(workspace_id="w", confirmed_participants=()))
    assert _process_reasons(SimpleNamespace(process_record=None), empty, "w") == ()


def test_cover_fields_fall_back_to_the_exact_legacy_text():
    from scripts.backend_contract.application.models import ProcessCaseData
    from scripts.backend_contract.report_foundation import ReportProcess
    from scripts.backend_contract.report_template import _FIELD_VALUES
    from tests.test_report_foundation_v1 import bound_report
    report = bound_report()
    data = ProcessCaseData.empty().as_dict()
    data.update(numero_processo="0000000-00.2026.4.05.0000", vara="1ª Vara Federal", parte_requerente="ALFA E BETA SINTETICAS", parte_requerida="")
    legacy = replace(report, process_record=ReportProcess(workspace_id=report.workspace_id, source_revision=1, source_checksum="c" * 64, **data))
    assert _FIELD_VALUES["PARTICIPANTS_ACTIVE"](legacy) == "ALFA E BETA SINTETICAS"
    assert _FIELD_VALUES["PARTICIPANTS_PASSIVE"](legacy) == "—" and _FIELD_VALUES["PARTICIPANTS_OTHER"](legacy) == "—"
    assert _FIELD_VALUES["PARTICIPANTS_ACTIVE"](replace(report, process_record=None)) == "—"


@pytest.mark.parametrize("tamper", ["name", "excerpt", "span", "representative_page"])
def test_backup_rederives_participant_name_excerpt_and_span_from_the_bytes(tmp_path, tamper):
    from scripts.backend_contract.application.ports import RepositoryIntegrityError
    from scripts.backend_contract.infrastructure.productization import VerifyWorkspaceBackup
    from tests.test_product_integration_oracle_v1 import TOKEN, _http, _reseal, http_request
    runtime = _runtime(tmp_path)
    try:
        _, workspace = _http(runtime, "POST", "/v1/workspaces", {"name": "Fonte forjada"})
        root = f"/v1/workspaces/{workspace['workspace_id']}"
        _import(runtime, root, _cover([_HEADER, "ALFA SINTETICA (AUTOR) ADVOGADA SINTETICA (ADVOGADA)", "BETA SINTETICA (REU)"]), "capa.pdf")
        _save_process(runtime, root)
        proposal = _http(runtime, "GET", root + "/process-participants")[1]["proposals"][0]
        assert _http(runtime, "POST", root + "/process-participants/decisions", {"action": "CONFIRM", "expected_revision": None, "payload": {"proposal_id": proposal["participant_id"]}})[0] == 200
        status, _, backup = http_request(runtime.server, "POST", root + "/backup", value={}, headers={"X-Local-API-Token": TOKEN})
        assert status == 200
        VerifyWorkspaceBackup().execute(backup)
        altered = json.loads(backup)
        revision = next(r for r in altered["artifact_revisions"] if r["artifact_kind"] == "PROCESS_PARTICIPANTS_V1")
        participant = revision["payload"]["participants"][0]
        source = participant["provenance"][0]
        if tamper == "name":
            participant["name"] = "NOME FORJADO"
        elif tamper == "excerpt":
            source["excerpt"] = "NOME FORJADO (AUTOR)"
        elif tamper == "span":
            source["source_start"] += 1
        else:
            participant["representatives"][0]["provenance"][0]["page"] += 1
        with pytest.raises(RepositoryIntegrityError, match="participant source"):
            VerifyWorkspaceBackup().execute(_reseal(altered))
    finally:
        runtime.close()


def test_natural_table_end_is_not_an_interruption_but_a_refused_role_line_is():
    complete = _proposal_set(_text_page("\n".join([
        "Processo Judicial Eletrônico", _HEADER, "POLO ATIVO", "JOAO SINTETICO (AUTOR) MARIA ADV (ADVOGADO)",
        "POLO PASSIVO", "CAIXA SINTETICA (REU)", "", "Documentos", "Id. Data da Assinatura Documento Tipo",
    ])))
    assert [item.name for item in complete.proposals] == ["JOAO SINTETICO", "CAIXA SINTETICA"] and complete.interrupted_pages == ()
    petition = _proposal_set(_text_page("DOS FATOS\nPOLO PASSIVO\nA ré é instituição financeira.\n"))
    assert petition.interrupted_pages == ()
    refused = _proposal_set(_text_page(_HEADER + "\nJOAO (AUTOR)\nMARIA (LITISCONSORTE)\n"))
    assert refused.interrupted_pages == (("autos.pdf", 1),)
    representative_next_page = _proposal_set(_text_page(_HEADER + "\nJOAO (AUTOR)\n"), _text_page("FULANO (ADVOGADO)\nOutro texto\n", 2))
    assert representative_next_page.interrupted_pages == (("autos.pdf", 2),)


def test_a_broken_name_line_never_hides_the_rest_of_a_pole():
    # Razao social quebrada em duas linhas: a leitura para, e isso e dito.
    broken = _proposal_set(_text_page("\n".join([
        _HEADER, "POLO ATIVO", "JOAO SINTETICO (AUTOR)", "POLO PASSIVO",
        "CAIXA ECONOMICA FEDERAL - CEF E OUTRA EMPRESA", "CONSTRUTORA SINTETICA LTDA (REU)",
    ])))
    assert [item.name for item in broken.proposals] == ["JOAO SINTETICO"] and broken.interrupted_pages == (("autos.pdf", 1),)
    middle = _proposal_set(_text_page("\n".join([_HEADER, "ALFA (AUTOR)", "BETA SINTETICA DE NOME", "MUITO LONGO (AUTORA)", "GAMA (AUTOR)"])))
    assert middle.interrupted_pages == (("autos.pdf", 1),)
