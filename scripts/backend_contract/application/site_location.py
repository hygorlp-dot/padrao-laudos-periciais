"""Pre-inspection site location: propose from pasted text, confirm by the expert."""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..report_foundation import EXPERT_PROFILE_ARTIFACT_ID, EXPERT_PROFILE_ARTIFACT_KIND, expert_profile_from_mapping
from ..site_location import (
    SITE_LOCATION_ARTIFACT_ID,
    SITE_LOCATION_ARTIFACT_KIND,
    SiteLocation,
    SiteLocationState,
    parse_location_input,
    site_location_from_mapping,
    site_location_to_mapping,
)
from .models import thaw_payload
from .ports import RepositoryConflict, RepositoryIntegrityError


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is not str:
        raise ValueError("site location text is invalid")
    return value.strip() or None


@dataclass(frozen=True, slots=True)
class GetSiteLocation:
    get_latest_revision: object

    def execute(self, workspace_id):
        record = self.get_latest_revision.execute(workspace_id, SITE_LOCATION_ARTIFACT_KIND, SITE_LOCATION_ARTIFACT_ID)
        return record, site_location_from_mapping(thaw_payload(record.payload))


@dataclass(frozen=True, slots=True)
class ProposeSiteLocation:
    """Read the coordinates locally and keep them as a proposal.

    The pasted text itself is not persisted.  A new proposal always replaces
    a confirmed location, so a changed place is never carried by a stale
    confirmation.
    """
    revisions: object
    get_latest_revision: object
    authority_guard: object
    clock: object
    ids: object

    def execute(self, workspace_id, *, location_input: object, address_label: object, note: object, expected_revision: int | None):
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 1):
            raise ValueError("site location expected revision is invalid")
        parsed = parse_location_input(location_input)
        location = SiteLocation(
            "1.0.0", str(workspace_id), parsed.latitude, parsed.longitude, "WGS84", parsed.input_format,
            _optional_text(address_label), _optional_text(note), SiteLocationState.PROPOSED, None, None,
        )
        return self._append(workspace_id, location, expected_revision), location

    def _append(self, workspace_id, location: SiteLocation, expected_revision: int | None):
        if not callable(self.authority_guard):
            raise RepositoryIntegrityError("site location authority guard is unavailable")
        with self.authority_guard():
            created_at = self.clock.now()
            if created_at.tzinfo is None or created_at.utcoffset() is None:
                raise ValueError("site location clock requires timezone")
            return self.revisions.append_if_latest(
                workspace_id=workspace_id, artifact_kind=SITE_LOCATION_ARTIFACT_KIND, artifact_id=SITE_LOCATION_ARTIFACT_ID,
                revision_id=str(self.ids.new_uuid()), created_at=created_at.isoformat(), payload=site_location_to_mapping(location),
                expected_revision=expected_revision,
            )


@dataclass(frozen=True, slots=True)
class ConfirmSiteLocation:
    """The expert confirms the proposed location under the master profile."""
    get_site_location: object
    get_latest_revision: object
    propose: ProposeSiteLocation

    def execute(self, workspace_id, *, expected_revision: int):
        record, location = self.get_site_location.execute(workspace_id)
        if record.revision != expected_revision:
            raise RepositoryConflict("expected site location revision is not latest")
        if location.state is not SiteLocationState.PROPOSED:
            raise ValueError("site location is already confirmed")
        profile_record = self.get_latest_revision.execute(workspace_id, EXPERT_PROFILE_ARTIFACT_KIND, EXPERT_PROFILE_ARTIFACT_ID)
        profile = expert_profile_from_mapping(thaw_payload(profile_record.payload))
        confirmed = replace(
            location, state=SiteLocationState.CONFIRMED, confirmed_by=profile.profile_id,
            confirmed_at=self.propose.clock.now().isoformat(),
        )
        return self.propose._append(workspace_id, confirmed, expected_revision), confirmed
