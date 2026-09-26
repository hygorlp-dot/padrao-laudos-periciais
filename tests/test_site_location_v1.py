"""Pre-inspection site location, read locally and confirmed by the expert (#239, Phase D).

A maps link or coordinate text is interpreted on this machine: no map
provider, tile server or geocoder is contacted and the pasted text is not
kept.  A short link needs the network to name coordinates, so it is refused
with guidance.  Only a confirmed location enters the report, bound to its
revision and checksum so a later change makes the report stale.
"""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.backend_contract import delivery_renderer as dr
from scripts.backend_contract.application.report_foundation import (
    AmendReportDraft,
    _site_location_reasons,
    _with_site_location_staleness,
)
from scripts.backend_contract.application.site_location import ConfirmSiteLocation, GetSiteLocation, ProposeSiteLocation
from scripts.backend_contract.application.models import _freeze_payload, thaw_payload
from scripts.backend_contract.application.ports import ArtifactRevisionNotFound, RepositoryConflict
from scripts.backend_contract.report_foundation import (
    ReportSiteLocation,
    ReportState,
    report_snapshot_from_mapping,
    report_snapshot_to_mapping,
)
from scripts.backend_contract.site_location import (
    LocationInputError,
    LocationInputFormat,
    SiteLocation,
    SiteLocationState,
    parse_location_input,
    site_location_from_mapping,
    site_location_to_mapping,
)
from tests.test_report_authoring_v1 import _Record, _draft_bound_to, _upstream

FIXTURES = Path(__file__).parent / "fixtures"


# --- the parser -----------------------------------------------------------------


@pytest.mark.parametrize(("text", "expected", "kind"), [
    ("https://www.google.com/maps/place/Pra%C3%A7a+da+S%C3%A9/@-23.5503099,-46.6342009,17z/data=!3m1!4b1!4m6!3m5!1s0x94ce59!8m2!3d-23.5503099!4d-46.6342009!16s", (-23.55031, -46.634201), LocationInputFormat.GOOGLE_MAPS_PLACE),
    ("https://www.google.com/maps/place/X/@-23.0,-46.0,15z/data=!4m5!3m4!1s0x0!8m2!3d-23.5611!4d-46.6559", (-23.5611, -46.6559), LocationInputFormat.GOOGLE_MAPS_PLACE),
    ("https://maps.google.com/?q=-23.5505,-46.6333", (-23.5505, -46.6333), LocationInputFormat.GOOGLE_MAPS_QUERY),
    ("https://www.google.com/maps/search/?api=1&query=-22.9068%2C-43.1729", (-22.9068, -43.1729), LocationInputFormat.GOOGLE_MAPS_QUERY),
    ("https://www.google.com.br/maps/@-23.5505,-46.6333,15z", (-23.5505, -46.6333), LocationInputFormat.GOOGLE_MAPS_VIEWPORT),
    ("https://www.openstreetmap.org/?mlat=-23.5505&mlon=-46.6333#map=17/-23.5505/-46.6333", (-23.5505, -46.6333), LocationInputFormat.OPENSTREETMAP),
    ("https://www.openstreetmap.org/#map=17/-19.9167/-43.9345", (-19.9167, -43.9345), LocationInputFormat.OPENSTREETMAP),
    ("geo:-23.5505,-46.6333?z=17", (-23.5505, -46.6333), LocationInputFormat.GEO_URI),
    ("-23.550520, -46.633308", (-23.55052, -46.633308), LocationInputFormat.DECIMAL),
    ("-23,550520; -46,633308", (-23.55052, -46.633308), LocationInputFormat.DECIMAL),
    ("23°33'01.9\"S 46°38'00.0\"W", (-23.550528, -46.633333), LocationInputFormat.DEGREES_MINUTES_SECONDS),
    ("23°33'01,9\"S 46°38'00,0\"O", (-23.550528, -46.633333), LocationInputFormat.DEGREES_MINUTES_SECONDS),
])
def test_a_maps_link_or_coordinate_text_is_read_locally(text, expected, kind) -> None:
    parsed = parse_location_input(text)
    assert (parsed.latitude, parsed.longitude, parsed.input_format) == (*expected, kind)


@pytest.mark.parametrize(("text", "reason"), [
    ("https://maps.app.goo.gl/AbCdEf123", "SHORT_LINK_REQUIRES_NETWORK"),
    ("https://goo.gl/maps/xyz", "SHORT_LINK_REQUIRES_NETWORK"),
    ("Rua Augusta, 100, São Paulo", "NO_COORDINATES"),
    ("https://www.google.com/maps/place/Rua+Augusta", "NO_COORDINATES"),
    ("https://example.com/maps/@-23.5,-46.6,15z", "UNSUPPORTED_LINK"),
    ("-23,5505, -46,6333", "NO_COORDINATES"),
    ("0, 0", "NO_COORDINATES"),
    ("95.0, 10.0", "OUT_OF_RANGE"),
    ("", "NO_COORDINATES"),
])
def test_text_without_locally_readable_coordinates_is_refused_with_a_reason(text, reason) -> None:
    with pytest.raises(LocationInputError) as refused:
        parse_location_input(text)
    assert refused.value.reason == reason


def test_the_parser_never_reaches_the_network(monkeypatch) -> None:
    import socket

    def forbidden(*_args, **_kwargs):
        raise AssertionError("site location parsing must not open a connection")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    parse_location_input("https://www.google.com/maps/place/X/data=!3d-23.5611!4d-46.6559")
    with pytest.raises(LocationInputError):
        parse_location_input("https://maps.app.goo.gl/AbCdEf123")


# --- the domain -------------------------------------------------------------------


def _location(**changes) -> SiteLocation:
    values = dict(
        schema_version="1.0.0", workspace_id="11111111-1111-4111-8111-111111111111", latitude=-23.55052, longitude=-46.633308,
        datum="WGS84", input_format=LocationInputFormat.DECIMAL, address_label="Rua Sintética, 100 — Bloco B", note=None,
        state=SiteLocationState.PROPOSED, confirmed_by=None, confirmed_at=None,
    )
    return SiteLocation(**{**values, **changes})


def test_a_location_is_honest_about_its_confirmation_and_round_trips() -> None:
    location = _location()
    assert site_location_from_mapping(site_location_to_mapping(location)) == location
    assert location.coordinates_text == "23,550520° S, 46,633308° O"
    confirmed = _location(state=SiteLocationState.CONFIRMED, confirmed_by="EXPERT-PROFILE-001", confirmed_at="2026-09-26T10:00:00-03:00")
    assert site_location_from_mapping(site_location_to_mapping(confirmed)) == confirmed
    for dishonest in (
        dict(state=SiteLocationState.CONFIRMED),
        dict(confirmed_by="EXPERT-PROFILE-001"),
        dict(state=SiteLocationState.CONFIRMED, confirmed_by="X", confirmed_at="2026-09-26T10:00:00"),
        dict(datum="SIRGAS2000"), dict(latitude=-23.1234567), dict(address_label=" padded "),
    ):
        with pytest.raises(ValueError):
            _location(**dishonest)
    mapping = site_location_to_mapping(location)
    assert "input" not in mapping and set(mapping) == {"schema_version", "workspace_id", "latitude", "longitude", "datum", "input_format", "address_label", "note", "state", "confirmed_by", "confirmed_at"}


# --- the application --------------------------------------------------------------


class _Store:
    def __init__(self):
        self.records = []

    def append_if_latest(self, *, workspace_id, artifact_kind, artifact_id, revision_id, created_at, payload, expected_revision):
        latest = len(self.records) or None
        if expected_revision != latest:
            raise RepositoryConflict("stale")
        record = SimpleNamespace(revision=len(self.records) + 1, created_at=created_at, payload=_freeze_payload(payload), checksum_sha256=f"{len(self.records) + 1:064x}")
        self.records.append(record)
        return record

    def latest(self, _workspace_id, kind, _artifact_id):
        if kind == "EXPERT_MASTER_PROFILE_V1":
            profile = json.loads((FIXTURES / "report-snapshot-v1.json").read_text(encoding="utf-8"))["expert_profile"]
            return SimpleNamespace(revision=1, payload=_freeze_payload(profile))
        if not self.records:
            raise ArtifactRevisionNotFound("absent")
        return self.records[-1]


def _services(store: _Store):
    from datetime import UTC, datetime

    latest = SimpleNamespace(execute=store.latest)
    propose = ProposeSiteLocation(
        store, latest, lambda: __import__("contextlib").nullcontext(),
        SimpleNamespace(now=lambda: datetime(2026, 9, 26, 13, 0, tzinfo=UTC)),
        SimpleNamespace(new_uuid=lambda: "00000000-0000-4000-8000-000000000001"),
    )
    get = GetSiteLocation(latest)
    return get, propose, ConfirmSiteLocation(get, latest, propose)


def test_a_proposal_is_confirmed_by_the_expert_and_a_new_proposal_resets_it() -> None:
    store = _Store()
    get, propose, confirm = _services(store)
    _, proposed = propose.execute("w", location_input="https://maps.google.com/?q=-23.5505,-46.6333", address_label=" Rua Sintética, 100 ", note="", expected_revision=None)
    assert (proposed.state, proposed.address_label, proposed.note) == (SiteLocationState.PROPOSED, "Rua Sintética, 100", None)
    assert "maps.google" not in json.dumps(thaw_payload(store.records[-1].payload))
    with pytest.raises(RepositoryConflict):
        confirm.execute("w", expected_revision=9)
    _, confirmed = confirm.execute("w", expected_revision=1)
    assert (confirmed.state, confirmed.confirmed_by) == (SiteLocationState.CONFIRMED, "EXPERT-PROFILE-001")
    with pytest.raises(ValueError, match="already confirmed"):
        confirm.execute("w", expected_revision=2)
    _, moved = propose.execute("w", location_input="-23.6, -46.7", address_label=None, note=None, expected_revision=2)
    assert moved.state is SiteLocationState.PROPOSED and get.execute("w")[1] == moved
    with pytest.raises(LocationInputError):
        propose.execute("w", location_input="https://maps.app.goo.gl/x", address_label=None, note=None, expected_revision=3)


# --- the report -------------------------------------------------------------------


def _confirmed_store() -> tuple[_Store, object]:
    store = _Store()
    get, propose, confirm = _services(store)
    propose.execute("w", location_input="-23.550520, -46.633308", address_label="Rua Sintética, 100", note=None, expected_revision=None)
    confirm.execute("w", expected_revision=1)
    return store, get


def _amend(report, get_site_location):
    case, technical, _ = _upstream()
    return AmendReportDraft(
        get_snapshot=SimpleNamespace(execute=lambda _w: (_Record(revision=7), report)),
        save_snapshot=SimpleNamespace(execute=lambda _w, snapshot, expected: _Record(revision=8)),
        ids=SimpleNamespace(new_uuid=lambda: "00000000-0000-4000-8000-000000000123"),
        get_case_analysis=SimpleNamespace(execute=lambda _w: (_Record(revision=report.source_snapshot.case_analysis_revision), case)),
        get_technical_snapshot=SimpleNamespace(execute=lambda _w: (_Record(revision=report.source_snapshot.technical_snapshot_revision), technical)),
        get_site_location=get_site_location,
    )


def _draft():
    case, technical, _ = _upstream()
    return _draft_bound_to(case, technical)


def test_only_a_confirmed_location_enters_the_report_and_a_later_change_makes_it_stale() -> None:
    store, get = _confirmed_store()
    _, captured = _amend(_draft(), get).execute("w", expected_revision=7, action="SET_SITE_LOCATION", values={})
    site = captured.site_location
    assert (site.latitude, site.longitude, site.address_label, site.source_revision) == (-23.55052, -46.633308, "Rua Sintética, 100", 2)
    assert _site_location_reasons(captured, get) == ()
    mapping = report_snapshot_to_mapping(captured)
    assert report_snapshot_from_mapping(mapping) == captured
    assert "site_location" not in report_snapshot_to_mapping(_draft())

    # The expert pastes a new place: the captured one no longer matches.
    _get, propose, _confirm = _services(store)
    propose.execute("w", location_input="-23.6, -46.7", address_label=None, note=None, expected_revision=2)
    stale = _with_site_location_staleness(replace(captured, state=ReportState.DRAFT), get)
    assert stale.upstream_stale and "site location changed" in stale.upstream_stale_reasons

    unconfirmed_store = _Store()
    unconfirmed_get, unconfirmed_propose, _ = _services(unconfirmed_store)
    unconfirmed_propose.execute("w", location_input="-23.6, -46.7", address_label=None, note=None, expected_revision=None)
    with pytest.raises(ValueError, match="confirmed location"):
        _amend(_draft(), unconfirmed_get).execute("w", expected_revision=7, action="SET_SITE_LOCATION", values={})
    with pytest.raises(ValueError, match="confirmed location"):
        _amend(_draft(), GetSiteLocation(SimpleNamespace(execute=_Store().latest))).execute("w", expected_revision=7, action="SET_SITE_LOCATION", values={})
    _, removed = _amend(captured, get).execute("w", expected_revision=7, action="REMOVE_SITE_LOCATION", values={})
    assert removed.site_location is None


def test_the_report_presents_the_location_in_the_inspection_section() -> None:
    report = report_snapshot_from_mapping(json.loads((FIXTURES / "report-snapshot-v1.json").read_text(encoding="utf-8")))
    located = replace(report, site_location=ReportSiteLocation(-23.55052, -46.633308, "Rua Sintética, 100", 2, "a" * 64))
    blocks = dr.professional_report_blocks(located)
    index = next(position for position, block in enumerate(blocks) if block.kind == "HEADING_1" and block.text.endswith("VISTORIA"))
    assert blocks[index + 1].text == "Local vistoriado: Rua Sintética, 100; coordenadas geográficas 23,550520° S, 46,633308° O (WGS 84), conferidas pelo perito."
    assert any(line.startswith("LOCALIZAÇÃO | SITE_LOCATION_V1 | revisão 2") for line in dr.canonical_report_audit_lines(located))
    with pytest.raises(ValueError):
        ReportSiteLocation(-23.55052, -46.633308, None, 2, "not-a-digest")


# --- the local API ----------------------------------------------------------------


def test_the_site_location_routes_are_private_and_explain_a_short_link(tmp_path) -> None:
    from scripts.backend_contract.local_api.composition import build_local_api
    from tests.test_document_intake_v1 import provision_private_root
    from tests.test_local_api_v1 import TOKEN, http_request

    private = tmp_path / "private"
    provision_private_root(private)
    runtime = build_local_api(tmp_path / "case.sqlite3", private_root=private, token=TOKEN)
    runtime.start()
    try:
        def call(method, path, value=None, token=True):
            status, _headers, raw = http_request(runtime.server, method, path, value=value, headers={"X-Local-API-Token": TOKEN} if token else {})
            return status, json.loads(raw) if raw else None

        _status, workspace = call("POST", "/v1/workspaces", {"name": "Caso"})
        base = f"/v1/workspaces/{workspace['workspace_id']}/site-location"
        assert call("GET", base, token=False)[0] == 403
        assert call("GET", base)[0] == 404
        status, refused = call("PUT", base, {"expected_revision": None, "input": "https://maps.app.goo.gl/AbC", "address_label": None, "note": None})
        assert (status, refused["error"]["code"]) == (422, "LOCATION_SHORT_LINK_REQUIRES_NETWORK")
        status, proposed = call("PUT", base, {"expected_revision": None, "input": "-23.550520, -46.633308", "address_label": "Rua Sintética, 100", "note": None})
        assert status == 200 and proposed["location"]["state"] == "PROPOSED"
        profile = json.loads((FIXTURES / "report-snapshot-v1.json").read_text(encoding="utf-8"))["expert_profile"]
        assert call("PUT", f"/v1/workspaces/{workspace['workspace_id']}/expert-profile", {"expected_revision": None, "profile": {**profile, "revision": 1}})[0] == 200
        status, confirmed = call("POST", f"{base}/confirmation", {"expected_revision": 1})
        assert status == 200 and confirmed["location"]["state"] == "CONFIRMED"
        assert call("GET", base)[1]["revision"] == 2
    finally:
        runtime.close()


# --- backup and recovery ------------------------------------------------------------


def test_a_backup_restores_a_site_location_and_refuses_a_forged_one() -> None:
    import hashlib

    from scripts.backend_contract.application.models import canonical_payload_json
    from scripts.backend_contract.application.ports import RepositoryIntegrityError
    from scripts.backend_contract.infrastructure.productization import _revision_from_mapping

    workspace = "11111111-1111-4111-8111-111111111111"

    def envelope(payload, artifact_id="SITE-LOCATION"):
        return {
            "workspace_id": workspace, "artifact_kind": "SITE_LOCATION_V1", "artifact_id": artifact_id,
            "revision_id": "22222222-2222-4222-8222-222222222222", "revision": 1, "created_at": "2026-09-26T13:00:00+00:00",
            "checksum_sha256": hashlib.sha256(canonical_payload_json(payload).encode("utf-8")).hexdigest(), "payload": payload,
        }

    confirmed = site_location_to_mapping(_location(state=SiteLocationState.CONFIRMED, confirmed_by="EXPERT-PROFILE-001", confirmed_at="2026-09-26T10:00:00-03:00"))
    restored = _revision_from_mapping(envelope(confirmed), workspace)
    assert site_location_from_mapping(thaw_payload(restored.payload)).state is SiteLocationState.CONFIRMED
    for forged, artifact_id in (
        ({**confirmed, "confirmed_by": None}, "SITE-LOCATION"),
        ({**confirmed, "workspace_id": "33333333-3333-4333-8333-333333333333"}, "SITE-LOCATION"),
        (confirmed, "OTHER-LOCATION"),
    ):
        with pytest.raises((RepositoryIntegrityError, ValueError)):
            _revision_from_mapping(envelope(forged, artifact_id), workspace)
