from dataclasses import replace
from types import SimpleNamespace

import pytest

from tests.test_report_foundation_v1 import upstreams
from scripts.backend_contract.vistoria import inspection_session_from_mapping, inspection_session_to_mapping


def visit_values():
    return dict(date="2026-09-20", start_time="09:10", end_time="10:20", weather="Ensolarado",
                temperature_c="27.5", relative_humidity_percent="62", attendants=[{"name": "Pessoa sintética", "role": "Proprietário", "presence_confirmed": True}])


def test_physical_visit_is_explicit_and_legacy_session_mapping_is_unchanged():
    from scripts.backend_contract.visit_context import VisitContext
    session = upstreams()[2]
    old = inspection_session_to_mapping(session)
    assert "visit_context" not in old
    context = VisitContext.from_values(visit_values(), confirmed_by="EXPERT-PROFILE-001", confirmed_at="2026-09-28T12:00:00+00:00")
    updated = replace(session, visit_context=context, participant_references=("Pessoa sintética",))
    assert updated.started_at == session.started_at and context.date != session.started_at[:10]
    assert inspection_session_from_mapping(inspection_session_to_mapping(updated)) == updated
    assert inspection_session_to_mapping(inspection_session_from_mapping(old)) == old


@pytest.mark.parametrize("change", [{"date": "2026-02-30"}, {"start_time": "24:00"}, {"start_time": "0٩:10"}, {"end_time": "1٠:20"}, {"date": "2026-09-2٠"}, {"end_time": "08:00"}, {"relative_humidity_percent": "101"}, {"temperature_c": "NaN"}, {"attendants": [{"name": "Parte", "role": "Autora", "presence_confirmed": False}]}])
def test_visit_rejects_invalid_values_and_unconfirmed_attendance(change):
    from scripts.backend_contract.visit_context import VisitContext
    with pytest.raises(ValueError):
        VisitContext.from_values({**visit_values(), **change}, confirmed_by="EXPERT-PROFILE-001", confirmed_at="2026-09-28T12:00:00+00:00")


def test_dedicated_confirmation_uses_profile_clock_and_revision():
    from scripts.backend_contract.application.vistoria import ConfirmInspectionVisit
    from scripts.backend_contract.application.ports import RepositoryConflict
    from datetime import datetime
    session = upstreams()[2]
    saved = []
    def persist(_workspace, snapshot, expected_revision, **flags):
        saved.append((snapshot, expected_revision, flags))
        return SimpleNamespace(revision=3)
    service = ConfirmInspectionVisit(SimpleNamespace(execute=lambda _w: (SimpleNamespace(revision=2), session)), SimpleNamespace(execute=persist), SimpleNamespace(execute=lambda _w: (None, SimpleNamespace(profile_id="EXPERT-PROFILE-001"))), SimpleNamespace(now=lambda: datetime.fromisoformat("2026-09-28T12:00:00+00:00")))
    _, updated = service.execute(session.workspace_id, values=visit_values(), expected_revision=2)
    assert updated.visit_context.confirmed_by == "EXPERT-PROFILE-001"
    assert updated.reviews == session.reviews
    assert saved[0][0].reviews == session.reviews
    assert saved[0][2] == {"allow_visit_confirmation": True}
    with pytest.raises(RepositoryConflict):
        service.execute(session.workspace_id, values=visit_values(), expected_revision=1)


def test_generic_inspection_save_cannot_forge_visit_confirmation():
    from contextlib import nullcontext
    from scripts.backend_contract.application.vistoria import SaveInspectionSession
    from scripts.backend_contract.visit_context import VisitContext
    from tests.test_vistoria_foundation_v1 import artifact
    session = upstreams()[2]
    predecessor = artifact(session)
    service = SaveInspectionSession(None, SimpleNamespace(execute=lambda *_args: predecessor), None, None, nullcontext, None, None)
    context = VisitContext.from_values(visit_values(), confirmed_by="EXPERT-PROFILE-001", confirmed_at="2026-09-28T12:00:00+00:00")
    with pytest.raises(ValueError, match="dedicated confirmation"):
        service.execute(session.workspace_id, replace(session, visit_context=context, participant_references=("Pessoa sintética",)), 1)


def test_offline_update_cannot_forge_physical_visit_confirmation():
    from scripts.backend_contract.application.field_mobile import UpdateOfflineInspection
    from scripts.backend_contract.field_mobile import offline_package_from_mapping
    from scripts.backend_contract.visit_context import VisitContext
    from tests.test_field_mobile_foundation_v1 import package_mapping
    package = offline_package_from_mapping(package_mapping())
    context = VisitContext.from_values(visit_values(), confirmed_by="EXPERT-PROFILE-001", confirmed_at="2026-09-28T12:00:00+00:00")
    forged = replace(package.inspection_snapshot, visit_context=context, participant_references=("Pessoa sintética",))
    service = UpdateOfflineInspection(None, lambda *_: SimpleNamespace(load=lambda _: package), None, None)
    with pytest.raises(ValueError, match="dedicated confirmation"):
        service.execute(package.workspace_id, device_id=package.device_id, package_id=package.package_id,
                        expected_package_revision=package.package_revision, snapshot=forged)


def test_inspection_save_validates_the_published_schema_before_writing(monkeypatch):
    """Revisao da PR #255 (P1, auditor, rodada 2): o dominio aceitava digito Unicode no
    horario (classe de digito Unicode) e o Save da sessao gravava sem validar o schema que a leitura valida --
    200 na gravacao, 400 em toda leitura seguinte, sessao perdida. Alem do dominio usar
    [0-9], o Save agora valida o payload: nada fora do schema chega ao repositorio."""
    from contextlib import nullcontext
    from datetime import UTC, datetime
    from uuid import UUID

    import scripts.backend_contract.application.vistoria as app
    from scripts.backend_contract.application.vistoria import inspection_planning_digest
    from scripts.backend_contract.application.models import PrivateContentId, PrivateContentMetadata, PrivateContentOrigin, WorkspaceId
    from tests.test_vistoria_foundation_v1 import payload, planning

    session = inspection_session_from_mapping(payload())
    upstream = planning()
    bound = replace(session, plan_snapshot=replace(session.plan_snapshot, planning_revision=2, planning_digest=inspection_planning_digest(upstream)))
    content = SimpleNamespace(metadata=PrivateContentMetadata(
        workspace_id=WorkspaceId.parse(session.workspace_id), content_id=PrivateContentId.parse(session.photos[0].private_content_id),
        original_filename="synthetic.jpg", byte_size=10, checksum_sha256=session.photos[0].original_sha256, media_type="image/jpeg",
        imported_at="2026-08-30T11:00:00+00:00", origin=PrivateContentOrigin.USER_IMPORT,
    ))
    calls = []
    service = app.SaveInspectionSession(
        SimpleNamespace(append_if_latest=lambda **kwargs: calls.append(kwargs) or SimpleNamespace(revision=1)),
        SimpleNamespace(execute=lambda *_args: None), SimpleNamespace(execute=lambda _w: (SimpleNamespace(revision=2), upstream)),
        SimpleNamespace(execute=lambda *_args: content), nullcontext,
        SimpleNamespace(now=lambda: datetime(2026, 8, 30, tzinfo=UTC)), SimpleNamespace(new_uuid=lambda: UUID("88888888-8888-4888-8888-888888888888")),
    )
    real = app.inspection_session_to_mapping
    monkeypatch.setattr(app, "inspection_session_to_mapping", lambda value: {**real(value), "schema_version": "9.9.9"})
    with pytest.raises(ValueError, match="violates its published schema"):
        service.execute(WorkspaceId.parse(session.workspace_id), bound, None, allow_initial_create=True)
    assert calls == []  # nada chegou ao repositorio
    monkeypatch.setattr(app, "inspection_session_to_mapping", real)
    assert service.execute(WorkspaceId.parse(session.workspace_id), bound, None, allow_initial_create=True).revision == 1
