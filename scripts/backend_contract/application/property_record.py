"""Explicit professional confirmation of property facts, isolated by workspace."""

from dataclasses import dataclass

from ..property_record import (
    PROPERTY_FIELDS, PROPERTY_RECORD_ID, PROPERTY_RECORD_KIND, PropertyRecord, PropertyValue,
    property_record_from_mapping, property_record_to_mapping, property_proposals,
)
from .models import thaw_payload
from .ports import ArtifactRevisionNotFound, RepositoryConflict, RepositoryIntegrityError

__all__ = ["GetPropertyRecord", "SavePropertyRecord", "GetPropertyProposals", "PROPERTY_FIELDS", "property_record_to_mapping"]


@dataclass(frozen=True, slots=True)
class GetPropertyRecord:
    get_latest_revision: object

    def execute(self, workspace_id):
        record = self.get_latest_revision.execute(workspace_id, PROPERTY_RECORD_KIND, PROPERTY_RECORD_ID)
        property_record = property_record_from_mapping(thaw_payload(record.payload))
        if property_record.workspace_id != str(workspace_id):
            raise ValueError("property workspace mismatch")
        return record, property_record


@dataclass(frozen=True, slots=True)
class GetPropertyProposals:
    list_documents: object
    open_document: object
    extractor: object

    def execute(self, workspace_id):
        proposals = []
        for document in self.list_documents.execute(workspace_id):
            if document.workspace_id != workspace_id:
                raise RepositoryIntegrityError("property source workspace mismatch")
            with self.open_document.execute(workspace_id, document.content_id) as opened:
                if opened.metadata != document:
                    raise RepositoryIntegrityError("property source identity mismatch")
                extracted = self.extractor.extract(opened.stream, document_sha256=document.checksum_sha256)
                if extracted.document_sha256 != document.checksum_sha256:
                    raise RepositoryIntegrityError("property extraction source mismatch")
                proposals.extend(property_proposals(workspace_id, document.content_id, document.checksum_sha256, document.original_filename, extracted.pages))
        return tuple(proposals)


@dataclass(frozen=True, slots=True)
class SavePropertyRecord:
    get_record: GetPropertyRecord
    revisions: object
    get_expert_profile: object
    get_proposals: object | None
    authority_guard: object
    clock: object
    ids: object

    def execute(self, workspace_id, *, changes, expected_revision):
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 1):
            raise ValueError("property expected revision is invalid")
        if type(changes) is not list or not changes or any(type(change) is not dict or set(change) != {"field", "value", "proposal_id"} for change in changes):
            raise ValueError("property changes are invalid")
        if any(type(change["field"]) is not str for change in changes) or len({change["field"] for change in changes}) != len(changes):
            raise ValueError("property changes must be unique")
        if not callable(self.authority_guard):
            raise RepositoryIntegrityError("property authority guard is unavailable")
        with self.authority_guard():
            try:
                previous, current = self.get_record.execute(workspace_id)
            except ArtifactRevisionNotFound:
                previous, current = None, PropertyRecord("1.0.0", str(workspace_id), ())
            if (previous.revision if previous else None) != expected_revision:
                raise RepositoryConflict("expected property revision is not latest")
            _, profile = self.get_expert_profile.execute(workspace_id)
            captured_at = self.clock.now().isoformat()
            proposals = {}
            if any(change["proposal_id"] is not None for change in changes):
                if self.get_proposals is None:
                    raise ValueError("property source proposals unavailable")
                proposals = {p.proposal_id: p for p in self.get_proposals.execute(workspace_id)}
            values = {item.field: item for item in current.values}
            for change in changes:
                field, value, proposal_id = change["field"], change["value"], change["proposal_id"]
                if field not in {item[0] for item in PROPERTY_FIELDS}:
                    raise ValueError("property field is invalid")
                evidence = None
                if proposal_id is not None:
                    if type(proposal_id) is not str:
                        raise ValueError("property proposal is invalid")
                    proposal = proposals.get(proposal_id)
                    if proposal is None or (proposal.workspace_id, proposal.field, proposal.value) != (str(workspace_id), field, value):
                        raise ValueError("property proposal is stale or belongs to another workspace")
                    evidence = proposal.evidence
                if value is None and proposal_id is None:
                    values.pop(field, None)
                else:
                    values[field] = PropertyValue(field, value, evidence, profile.profile_id, captured_at)
            updated = PropertyRecord("1.0.0", str(workspace_id), tuple(values[field] for field, *_ in PROPERTY_FIELDS if field in values))
            record = self.revisions.append_if_latest(
                workspace_id=workspace_id, artifact_kind=PROPERTY_RECORD_KIND, artifact_id=PROPERTY_RECORD_ID,
                revision_id=str(self.ids.new_uuid()), created_at=captured_at, payload=property_record_to_mapping(updated), expected_revision=expected_revision,
            )
            return record, updated
