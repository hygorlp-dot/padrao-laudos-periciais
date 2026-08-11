from copy import deepcopy

from .errors import DomainError


class MigrationRegistry:
    def __init__(self, current_version):
        if current_version < 1:
            raise ValueError("current_version inválida")
        self.current_version = current_version
        self.migration_version = 1
        self._steps = {}

    def register(self, source_version, target_version, operation):
        if target_version != source_version + 1:
            raise ValueError("Migrações devem ser sequenciais")
        self._steps[source_version] = (target_version, operation)

    def migrate(self, document):
        result = deepcopy(document)
        version = result.get("schema_version")
        if not isinstance(version, int) or version < 1 or version > self.current_version:
            raise DomainError("schema_version incompatível")
        while version < self.current_version:
            if version not in self._steps:
                raise DomainError(f"Migração ausente para schema_version {version}")
            target, operation = self._steps[version]
            result = operation(result)
            if result.get("schema_version") != target:
                raise DomainError("Migração não atualizou schema_version corretamente")
            version = target
        return result
