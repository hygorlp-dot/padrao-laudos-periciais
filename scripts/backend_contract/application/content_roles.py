"""Papel semantico de um conteudo privado, separado da sua origem de armazenamento.

`PrivateContentOrigin.USER_IMPORT` diz apenas COMO os bytes entraram (o perito
enviou um arquivo). Nao diz PARA QUE servem. Um PDF de apoio a entrega e uma
peca dos autos chegam pelo mesmo caminho fisico, mas so a peca e fonte do caso:
tratar o anexo como fonte deixava a Analise do Caso com inventario novo nao
incorporado, e todo comando seguinte era recusado (#253, F8).

O papel e registrado como revisao propria, enderecada pelo content_id, no
momento em que o conteudo entra pela rota que conhece o seu proposito. Conteudo
sem registro de papel continua com a interpretacao historica (fonte do caso, se
for PDF importado pelo usuario): nenhum backup antigo ganha nem perde autoridade
por inferencia.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .models import PrivateContentMetadata, WorkspaceId, thaw_payload
from .ports import ArtifactRevisionRepository, RepositoryIntegrityError


PRIVATE_CONTENT_ROLE_KIND = "PRIVATE_CONTENT_ROLE_V1"
_PAYLOAD_FIELDS = frozenset({"schema_version", "workspace_id", "content_id", "checksum_sha256", "role"})
_HEX = frozenset("0123456789abcdef")


class PrivateContentRole(Enum):
    # So os papeis que algum caminho do produto atribui hoje. Fonte do caso e o
    # papel historico implicito e nao precisa de registro.
    DELIVERY_SUPPORT = "DELIVERY_SUPPORT"
    # Copia, dentro da pericia, de um ativo de identidade visual da instalacao
    # (#270). Nunca e fonte do caso, material ou documento analisado.
    BRANDING_ASSET = "BRANDING_ASSET"


def private_content_role_payload(metadata: PrivateContentMetadata, role: PrivateContentRole) -> dict[str, object]:
    if type(metadata) is not PrivateContentMetadata or type(role) is not PrivateContentRole:
        raise TypeError("papel de conteudo privado invalido")
    return {
        "schema_version": 1,
        "workspace_id": str(metadata.workspace_id),
        "content_id": str(metadata.content_id),
        "checksum_sha256": metadata.checksum_sha256,
        "role": role.value,
    }


def validate_private_content_role_payload(value: object) -> dict[str, object]:
    if type(value) is not dict or set(value) != _PAYLOAD_FIELDS or value["schema_version"] != 1:
        raise RepositoryIntegrityError("private content role is invalid")
    checksum = value["checksum_sha256"]
    if type(checksum) is not str or len(checksum) != 64 or not set(checksum) <= _HEX:
        raise RepositoryIntegrityError("private content role is invalid")
    if any(type(value[name]) is not str for name in ("workspace_id", "content_id", "role")):
        raise RepositoryIntegrityError("private content role is invalid")
    try:
        PrivateContentRole(value["role"])
        WorkspaceId.parse(value["workspace_id"])
    except ValueError as exc:
        raise RepositoryIntegrityError("private content role is invalid") from exc
    return value


@dataclass(frozen=True, slots=True)
class PrivateContentRoles:
    revisions: ArtifactRevisionRepository

    def role_of(self, metadata: PrivateContentMetadata) -> PrivateContentRole | None:
        record = self.revisions.latest(metadata.workspace_id, PRIVATE_CONTENT_ROLE_KIND, str(metadata.content_id))
        if record is None:
            return None
        payload = validate_private_content_role_payload(thaw_payload(record.payload))
        # O papel so vale para os bytes que o receberam. Se a identidade divergir,
        # nao ha interpretacao segura: falha fechada em vez de escolher um lado.
        if (
            payload["workspace_id"] != str(metadata.workspace_id)
            or payload["content_id"] != str(metadata.content_id)
            or payload["checksum_sha256"] != metadata.checksum_sha256
        ):
            raise RepositoryIntegrityError("private content role diverges from private source authority")
        return PrivateContentRole(payload["role"])
