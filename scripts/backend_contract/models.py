from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class CaseId:
    value: UUID

    @classmethod
    def new(cls):
        return cls(uuid4())

    @classmethod
    def parse(cls, value: str):
        return cls(UUID(value))

    def __str__(self):
        return str(self.value)


class ArtifactStatus(StrEnum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True, slots=True)
class CaseRecord:
    case_id: CaseId
    cnj_number: str | None = None

    @classmethod
    def create(cls, cnj_number=None):
        return cls(CaseId.new(), cnj_number)
