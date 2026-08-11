from copy import deepcopy

from .errors import DomainError
from .models import ArtifactStatus


class DependencyGraph:
    def __init__(self):
        self._status = {}
        self._downstream = {}

    def add_artifact(self, artifact_id):
        if not artifact_id:
            raise ValueError("artifact_id obrigatório")
        self._status.setdefault(artifact_id, ArtifactStatus.CURRENT)
        self._downstream.setdefault(artifact_id, set())

    def add_dependency(self, upstream_id, downstream_id):
        missing = [item for item in (upstream_id, downstream_id) if item not in self._status]
        if missing:
            raise DomainError(f"Dependência órfã: {', '.join(missing)}")
        if upstream_id == downstream_id:
            raise DomainError("Autodependência não permitida")
        if upstream_id in self._descendants(downstream_id):
            raise DomainError("Ciclo de dependência não permitido")
        self._downstream[upstream_id].add(downstream_id)

    def _descendants(self, artifact_id):
        found, pending = set(), list(self._downstream[artifact_id])
        while pending:
            item = pending.pop()
            if item not in found:
                found.add(item)
                pending.extend(self._downstream[item])
        return found

    def invalidate_dependents(self, upstream_id):
        if upstream_id not in self._status:
            raise DomainError(f"Artefato inexistente: {upstream_id}")
        stale, pending = set(), list(self._downstream[upstream_id])
        while pending:
            item = pending.pop()
            if item in stale:
                continue
            stale.add(item)
            self._status[item] = ArtifactStatus.STALE
            pending.extend(self._downstream[item])
        return stale

    def mark_stale(self, artifact_id):
        if artifact_id not in self._status:
            raise DomainError(f"Artefato inexistente: {artifact_id}")
        self._status[artifact_id] = ArtifactStatus.STALE

    def status(self, artifact_id):
        if artifact_id not in self._status:
            raise DomainError(f"Artefato inexistente: {artifact_id}")
        return self._status[artifact_id]

    def require_current(self, artifact_id):
        if self.status(artifact_id) is not ArtifactStatus.CURRENT:
            raise DomainError(f"Artefato não atual: {artifact_id}")

    def snapshot(self):
        return deepcopy((self._status, self._downstream))

    def restore(self, snapshot):
        self._status, self._downstream = snapshot
