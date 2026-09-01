from typing import Protocol

from .application.ai_gateway import AIProvider as AIProvider


class CaseRepository(Protocol):
    def get(self, case_id): ...
    def save(self, case): ...


class DocumentRepository(Protocol):
    def list_for_case(self, case_id): ...


class EvidenceRepository(Protocol):
    def get(self, evidence_id): ...


class NormRepository(Protocol):
    def get_verified(self, norm_id): ...


class CostRepository(Protocol):
    def find(self, source, code, competence, region): ...


class MediaStorage(Protocol):
    def store(self, case_id, content, metadata): ...


class ReportExporter(Protocol):
    def export(self, semantic_model, destination): ...


class SecretStore(Protocol):
    def get(self, key): ...
