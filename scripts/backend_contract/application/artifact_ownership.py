"""Single inventory of persisted artifact authority owners."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ArtifactOwnership:
    artifact_kind: str
    mutation_owner: str
    portable: bool


APPLICATION_ARTIFACT_OWNERSHIP = {
    item.artifact_kind: item
    for item in (
        ArtifactOwnership("BUDGET_SNAPSHOT_V1", "Budget Application Service", True),
        ArtifactOwnership("CASE_ANALYSIS_SNAPSHOT_V1", "Case Analysis Application Service", True),
        ArtifactOwnership("DELIVERY_SNAPSHOT_V1", "Delivery Application Service", True),
        ArtifactOwnership("EXPERT_MASTER_PROFILE_V1", "Expert Profile Application Service", True),
        ArtifactOwnership("INSPECTION_SESSION_V1", "Inspection Application Service", True),
        ArtifactOwnership("PERICIAL_PLANNING_SNAPSHOT_V1", "Pericial Planning Application Service", True),
        ArtifactOwnership("PROCESS_CASE", "Process Case Application Service", True),
        ArtifactOwnership("REPORT_SNAPSHOT_V1", "Report Application Service", True),
        ArtifactOwnership("TECHNICAL_SNAPSHOT_V1", "Technical Findings Application Service", True),
        ArtifactOwnership("PROCESS_METADATA_EXTRACTION", "Process Metadata Application Service", False),
        ArtifactOwnership("PROCESS_METADATA_CONFIRMATION", "Process Metadata Application Service", False),
        ArtifactOwnership("PROCESS_METADATA_SOURCE_CONFIRMATION", "Process Metadata Application Service", False),
        ArtifactOwnership("OCR_PAGE_CACHE_V1", "OCR Cache Application Service", False),
    )
}

APPLICATION_OWNED_ARTIFACT_KINDS = frozenset(APPLICATION_ARTIFACT_OWNERSHIP)
PORTABLE_PRODUCT_ARTIFACT_KINDS = frozenset(
    kind for kind, ownership in APPLICATION_ARTIFACT_OWNERSHIP.items() if ownership.portable
)
INTERNAL_ARTIFACT_KINDS = APPLICATION_OWNED_ARTIFACT_KINDS - PORTABLE_PRODUCT_ARTIFACT_KINDS

# The pre-domain generic contract is retained only as one closed, explicitly
# noncanonical type.  It cannot collide with an application-owned kind.
USER_DEFINED_ARTIFACT_KINDS = frozenset({"LAUDO"})
