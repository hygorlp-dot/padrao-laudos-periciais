"""Contratos first-party do monólito modular pericial."""

from .audit import AuditEvent, AuditLog
from .capabilities import CapabilityRegistry, CapabilityStatus, EvidenceLimitation
from .dependencies import DependencyGraph
from .errors import DomainError, ErrorCategory, ErrorContract, ErrorSeverity
from .invariants import InvariantRegistry, default_invariants
from .jobs import Job, JobStatus
from .migrations import MigrationRegistry
from .models import ArtifactStatus, CaseId, CaseRecord
from .ports import (
    AIProvider,
    CaseRepository,
    CostRepository,
    DocumentRepository,
    EvidenceRepository,
    MediaStorage,
    NormRepository,
    ReportExporter,
    SecretStore,
)
from .revisions import Authority, RevisionSource, RevisionStore, RevisionStoreSnapshot, ValueHistory
from .state_machine import CaseState, CaseStateMachine, TransitionRecord
from .unit_of_work import RollbackError, UnitOfWork

__all__ = [
    "AIProvider",
    "ArtifactStatus",
    "AuditEvent",
    "AuditLog",
    "Authority",
    "CapabilityRegistry",
    "CapabilityStatus",
    "CaseId",
    "CaseRecord",
    "CaseRepository",
    "CaseState",
    "CaseStateMachine",
    "CostRepository",
    "DependencyGraph",
    "DocumentRepository",
    "DomainError",
    "ErrorCategory",
    "ErrorContract",
    "ErrorSeverity",
    "EvidenceLimitation",
    "EvidenceRepository",
    "InvariantRegistry",
    "Job",
    "JobStatus",
    "MediaStorage",
    "MigrationRegistry",
    "NormRepository",
    "ReportExporter",
    "RevisionSource",
    "RevisionStore",
    "RevisionStoreSnapshot",
    "RollbackError",
    "SecretStore",
    "TransitionRecord",
    "UnitOfWork",
    "ValueHistory",
    "audit",
    "capabilities",
    "dependencies",
    "default_invariants",
    "errors",
    "invariants",
    "jobs",
    "migrations",
    "models",
    "ports",
    "revisions",
    "state_machine",
    "unit_of_work",
]
