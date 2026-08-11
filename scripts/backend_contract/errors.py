from dataclasses import dataclass
from enum import StrEnum
from uuid import uuid4


class DomainError(RuntimeError):
    pass


class ErrorCategory(StrEnum):
    DOMAIN = "DOMAIN"
    VALIDATION = "VALIDATION"
    EVIDENCE = "EVIDENCE"
    AI = "AI"
    NETWORK = "NETWORK"
    STORAGE = "STORAGE"
    INTEGRATION = "INTEGRATION"
    PRIVACY = "PRIVACY"


class ErrorSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True, slots=True)
class ErrorContract:
    error_code: str
    severity: ErrorSeverity
    category: ErrorCategory
    correlation_id: str
    message: str
    recoverable: bool
    suggested_action: str
    case_id: str | None = None
    artifact_id: str | None = None

    def __post_init__(self):
        if not self.error_code or not self.message or not self.suggested_action:
            raise ValueError("Contrato de erro incompleto")

    @classmethod
    def create(cls, **values):
        if "severity" in values:
            values["severity"] = ErrorSeverity(values["severity"])
        if "category" in values:
            values["category"] = ErrorCategory(values["category"])
        return cls(correlation_id=str(uuid4()), **values)
