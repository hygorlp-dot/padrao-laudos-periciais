"""Orquestração de produto para backup e recuperação de workspace.

Esta camada NÃO reimplementa formato de backup, motor de restauração nem
autoridade de armazenamento: ela apenas torna ALCANÇÁVEL, pelo caminho normal
do produto (UI → Local API → aplicação), a infraestrutura canônica que já
existe em `infrastructure.productization` (`CreateWorkspaceBackup`,
`VerifyWorkspaceBackup`, `RecoveryStaging`, `RestoreWorkspaceBackup`).

Modelo de restauração — `VERIFIED_STAGING_THEN_EXPLICIT_HUMAN_PROMOTION`:

    pacote → verificar → restaurar em staging isolado → reabrir e conferir
    → apresentar ao usuário → PROMOÇÃO EXPLÍCITA → workspace ativo

A quarentena `RECOVERY_NOT_PROMOTABLE` NUNCA é removida. A raiz de staging
permanece quarentenada por toda a sua vida e é descartada depois; `build_local_api`
continua recusando abrir qualquer base sob ancestralidade quarentenada. Promover
NÃO é "desquarentenar o staging": é **copiar o conteúdo já verificado do staging
para o armazenamento vivo**, e só quando não há colisão de identidade. Assim
`NO_SILENT_OVERWRITE` e `FAILED_RESTORE_PRESERVES_ORIGINAL` valem por
construção — o armazenamento vivo só é tocado no ato explícito de promoção, e
apenas para criar um workspace que ainda não existe.
"""

from __future__ import annotations

import json
import os
import stat
import threading

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

from ..streaming import MAX_DOCUMENT_BYTES
from .models import ArtifactRevision, PericiaWorkspace, WorkspaceId, thaw_payload
from .ports import (
    RepositoryConflict,
    RepositoryError,
    RepositoryIntegrityError,
    WorkspaceNotFound,
)

_AI_COST_LEDGER_KIND = "AI_COST_LEDGER_V1"


class BackupInvalid(ValueError):
    """O pacote não é um backup íntegro deste produto."""


class BackupIncompatible(ValueError):
    """O pacote é íntegro mas de uma versão não suportada."""


class RecoveryNotFound(RepositoryError):
    """A sessão de recuperação não existe neste processo."""


class RecoveryDiscarded(RepositoryError):
    """A sessão de recuperação foi descartada e não pode ser promovida."""


class RecoveryAlreadyPromoted(RepositoryError):
    """A sessão de recuperação já foi promovida."""


class RecoveryNotPromotable(RepositoryError):
    """O staging existe mas não satisfaz as condições de promoção."""


class BackupTooLarge(RepositoryError):
    """O pacote produzido excede o que ESTA instalação consegue reingerir.

    `SELF_PRODUCED_BACKUP MUST_BE REINGESTIBLE`. Entregar 200 num arquivo que a
    própria recuperação recusaria depois é vender segurança falsa: o usuário só
    descobriria no dia em que precisasse restaurar. O formato atual do pacote
    (JSON com conteúdo em base64) é materializado por inteiro para verificar, e
    é essa materialização que fixa o teto — levantar o número sem trocar o
    formato apenas move a falha para exaustão de memória.
    """


class RecoveryUnresumable(RepositoryError):
    """A promoção interrompida NÃO pode mais ser concluída — nunca.

    Estado que faltava na máquina. Sem ele, uma promoção impossível de retomar
    (prefixo vivo divergente porque o perito editou a perícia parcial, prova de
    identidade perdida, journal corrompido, versão desconhecida) ficava presa:
    promover recusava "retome", descartar recusava "não destrua a retomada", e
    não há remoção de workspace. Preso é melhor que destruído, mas continua
    sendo um beco.

    Aqui o journal deixou de ser autoridade de qualquer coisa alcançável, então
    descartar volta a ser legítimo — e é dito com o motivo verdadeiro.
    """


class RecoveryPromotionIncomplete(RepositoryError):
    """A promoção já mutou o armazenamento vivo e NÃO chegou ao fim.

    Estado distinto de `STAGED`: existe prefixo vivo E existe journal. A única
    saída honesta é RETOMAR. Descartar aqui apagaria a autoridade durável de
    retomada e travaria a perícia viva incompleta para sempre, num
    armazenamento append-only sem remoção de workspace.
    """


class RecoveryStageFailed(RepositoryError):
    """A restauração para staging isolado falhou; nada foi promovido."""


class WorkspaceRecoveryConflict(RepositoryError):
    """Promover sobrescreveria um workspace existente — recusado."""


@dataclass(frozen=True, slots=True)
class BackupSummary:
    """Resumo SANITIZADO de um pacote. Nunca carrega conteúdo privado."""

    workspace_id: str
    workspace_name: str
    workspace_created_at: str
    product_release: str
    storage_schema_version: int
    artifact_revisions: int
    private_contents: int
    backup_sha256: str


@dataclass(frozen=True, slots=True)
class RecoverySession:
    recovery_id: str
    summary: BackupSummary
    #: `VERIFIED != PROMOTABLE`. Verificar prova que o pacote é íntegro; promover
    #: depende de condições canônicas que já são conhecidas AGORA (identidade
    #: viva colidente, artefato não promovível). Afirmar `True` e negar segundos
    #: depois é mentira de contrato.
    promotable: bool = True
    not_promotable_reason: str | None = None
    #: Esta sessão RETOMA uma promoção que já gravou no armazenamento vivo.
    #: Sem isto a tela dizia "não substituiu nada" sobre uma promoção em curso.
    resuming: bool = False


@dataclass(frozen=True, slots=True)
class RecoverySessionStatus:
    """Estado sanitizado e alcançável de uma recuperação durável."""

    recovery_id: str
    state: str
    summary: BackupSummary | None
    reason: str | None
    allowed_actions: tuple[str, ...]


#: Versão do journal. Uma versão desconhecida (produto mais novo gravou, produto
#: mais velho leu) é IRRETOMÁVEL, não "ilegível que bloqueia tudo".
JOURNAL_VERSION = 1

UNRESUMABLE = "UNRESUMABLE"
RECOVERY_UNRESUMABLE = "RECOVERY_UNRESUMABLE"
RECOVERY_RETAINED = "RECOVERY_RETAINED"

_JOURNAL_AUSENTE = "ausente"
_JOURNAL_RETOMAVEL = "retomavel"
_JOURNAL_IRRETOMAVEL = "irretomavel"
_JOURNAL_INACESSIVEL = "inacessivel"

#: Teto de ingestão da recuperação; ver `BackupTooLarge`. Vem da MESMA constante
#: que o transporte usa como teto de corpo. Quando a instalação configura um
#: teto menor, a composição injeta o valor efetivo em `ExportWorkspaceBackup`:
#: dois literais iguais hoje viram dois limites divergentes na primeira
#: configuração menor, e aí o produto exporta o que não consegue reingerir.
MAX_BACKUP_PACKAGE_BYTES = MAX_DOCUMENT_BYTES

_QUARENTENA = "RECOVERY_NOT_PROMOTABLE"
_QUARENTENA_PAYLOAD = b"RECOVERY_STAGING_V1\n"
_SESSION = "RECOVERY_SESSION_V1"
_SESSION_VERSION = 1
_DISPOSITION = "RECOVERY_DISPOSITION_V1"
_DISPOSITION_VERSION = 1
_REPARSE_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class RecoveryRetained(RepositoryError):
    """O descarte não removeu tudo; a quarentena foi mantida sobre o resíduo."""


def _detalhes_sao_link_ou_reparse(details: os.stat_result) -> bool:
    return stat.S_ISLNK(details.st_mode) or bool(
        getattr(details, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE
    )


def _raiz_eh_link_ou_reparse(raiz: Path) -> bool:
    """Falha fechada antes de qualquer leitura/travessia de uma raiz candidata."""
    try:
        details = os.lstat(raiz)
    except OSError:
        return True
    return _detalhes_sao_link_ou_reparse(details)


_JOURNAL = "PROMOTION_TRANSACTION_V1"
_IDENTIDADE = "STAGING_IDENTITY_V1"


def _chave_identidade(details: os.stat_result) -> tuple[int, int, int]:
    return (details.st_dev, details.st_ino, stat.S_IFMT(details.st_mode))


@dataclass(slots=True)
class _CleanupNode:
    """Custódia transitória de um diretório da quarentena a remover."""

    path: Path
    name: str | None
    identity: tuple[int, int, int]
    descriptor: int | None
    anchor_path: Path | None
    files: list[str]
    children: list["_CleanupNode"]


def _fechar_anchor_windows(descriptor: int, anchor_path: Path) -> None:
    failure = None
    try:
        os.close(descriptor)
    except OSError as exc:
        failure = exc
    try:
        try:
            anchor_path.unlink()
        except FileNotFoundError:
            pass
    except OSError as exc:
        if failure is None:
            failure = exc
    if failure is not None:
        raise failure


def _fechar_custodia_cleanup_once(node: _CleanupNode) -> None:
    failure = None
    for child in node.children:
        try:
            _fechar_custodia_cleanup_once(child)
        except OSError as exc:
            if failure is None:
                failure = exc
    if node.descriptor is not None:
        descriptor = node.descriptor
        anchor_path = node.anchor_path
        try:
            os.close(descriptor)
        except OSError as exc:
            if failure is None:
                failure = exc
        else:
            node.descriptor = None
            if anchor_path is not None:
                try:
                    anchor_path.unlink()
                except FileNotFoundError:
                    node.anchor_path = None
                except OSError as exc:
                    if failure is None:
                        failure = exc
                else:
                    node.anchor_path = None
    elif node.anchor_path is not None:
        try:
            node.anchor_path.unlink()
            node.anchor_path = None
        except FileNotFoundError:
            node.anchor_path = None
        except OSError as exc:
            if failure is None:
                failure = exc
    if failure is not None:
        raise failure


def _fechar_custodia_cleanup(node: _CleanupNode) -> None:
    """Fecha toda a árvore e absorve uma falha transitória sem perder ownership."""

    try:
        _fechar_custodia_cleanup_once(node)
    except OSError as first_failure:
        try:
            _fechar_custodia_cleanup_once(node)
        except OSError:
            raise first_failure


def _adquirir_custodia_cleanup(
    path: Path,
    *,
    parent: _CleanupNode | None = None,
) -> _CleanupNode:
    """Ancora cada diretório antes de devolver nomes que serão removidos.

    No POSIX, todas as operações posteriores usam ``dir_fd`` + ``O_NOFOLLOW``.
    No Windows, um arquivo sem compartilhamento de remoção aberto em cada
    diretório impede que ele seja renomeado/substituído enquanto qualquer
    unlink de material ainda depende do caminho. ``O_TEMPORARY`` é
    deliberadamente proibido: sua semântica concede delete-sharing em versões
    do Windows que aceitam rename POSIX. Os anchors são removidos explicitamente
    ao fechar o handle e nunca são material do backup.
    """

    if parent is None:
        before = os.lstat(path)
    elif os.name == "posix":
        if parent.descriptor is None or path.name in {"", ".", ".."}:
            raise RecoveryRetained("custódia da recuperação indisponível")
        before = os.stat(
            path.name,
            dir_fd=parent.descriptor,
            follow_symlinks=False,
        )
    else:
        before = os.lstat(path)
    if _detalhes_sao_link_ou_reparse(before) or not stat.S_ISDIR(before.st_mode):
        raise RecoveryRetained("a recuperação contém link ou reparse point")

    descriptor = None
    anchor_path = None
    if os.name == "posix":
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptor = (
            os.open(path, flags)
            if parent is None
            else os.open(path.name, flags, dir_fd=parent.descriptor)
        )
        try:
            opened = os.fstat(descriptor)
        except Exception:
            os.close(descriptor)
            raise
        if _chave_identidade(before) != _chave_identidade(opened):
            os.close(descriptor)
            raise RecoveryRetained("a identidade da recuperação mudou")
    elif os.name == "nt":
        anchor_path = path / f".recovery-cleanup-custody.{uuid4().hex}.tmp"
        descriptor = os.open(
            anchor_path,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_BINARY,
            0o600,
        )
        try:
            opened = os.fstat(descriptor)
            after = os.lstat(path)
        except Exception:
            _fechar_anchor_windows(descriptor, anchor_path)
            raise
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or _chave_identidade(before) != _chave_identidade(after)
        ):
            _fechar_anchor_windows(descriptor, anchor_path)
            raise RecoveryRetained("a identidade da recuperação mudou")
    else:  # pragma: no cover - contrato de plataforma fechado
        raise RecoveryRetained("plataforma sem remoção de recuperação ancorada")

    node = _CleanupNode(
        path,
        path.name if parent is not None else None,
        _chave_identidade(before),
        descriptor,
        anchor_path,
        [],
        [],
    )
    try:
        scan_target = descriptor if os.name == "posix" else path
        with os.scandir(scan_target) as entries:
            for entry in entries:
                if anchor_path is not None and entry.name == anchor_path.name:
                    continue
                details = entry.stat(follow_symlinks=False)
                if _detalhes_sao_link_ou_reparse(details):
                    raise RecoveryRetained(
                        "a recuperação contém link ou reparse point"
                    )
                child_path = path / entry.name
                if stat.S_ISDIR(details.st_mode):
                    node.children.append(
                        _adquirir_custodia_cleanup(child_path, parent=node)
                    )
                elif stat.S_ISREG(details.st_mode):
                    node.files.append(entry.name)
                else:
                    raise RecoveryRetained(
                        "a recuperação contém objeto de filesystem inesperado"
                    )
        return node
    except Exception:
        _fechar_custodia_cleanup(node)
        raise


def _paths_da_custodia(node: _CleanupNode) -> list[Path]:
    paths = [node.path / name for name in node.files]
    for child in node.children:
        paths.extend(_paths_da_custodia(child))
    return paths


def _unlink_na_custodia(node: _CleanupNode, name: str) -> None:
    if os.name == "posix":
        if node.descriptor is None:
            raise OSError("custódia da recuperação foi encerrada")
        os.unlink(name, dir_fd=node.descriptor)
    else:
        (node.path / name).unlink()


def _remover_material_ancorado(
    node: _CleanupNode,
    material: set[Path],
) -> None:
    for name in node.files:
        if node.path / name not in material:
            continue
        try:
            _unlink_na_custodia(node, name)
        except OSError:
            pass
    for child in node.children:
        _remover_material_ancorado(child, material)
        if os.name == "nt":
            _fechar_custodia_cleanup(child)
        try:
            if os.name == "posix":
                if node.descriptor is None:
                    raise OSError("custódia da recuperação foi encerrada")
                os.rmdir(child.name, dir_fd=node.descriptor)
            else:
                child.path.rmdir()
        except OSError:
            pass
        if os.name == "posix":
            _fechar_custodia_cleanup(child)


def _residuo_na_raiz_ancorada(node: _CleanupNode) -> list[str]:
    scan_target = node.descriptor if os.name == "posix" else node.path
    if scan_target is None:
        raise OSError("custódia da recuperação foi encerrada")
    allowed = {_QUARENTENA, _JOURNAL, _IDENTIDADE, _SESSION, _DISPOSITION}
    if node.anchor_path is not None:
        allowed.add(node.anchor_path.name)
    with os.scandir(scan_target) as entries:
        return [entry.name for entry in entries if entry.name not in allowed]


def _ler_controle_ancorado(node: _CleanupNode, name: str) -> bytes:
    flags = os.O_RDONLY | (os.O_NOFOLLOW if os.name == "posix" else os.O_BINARY)
    if os.name == "posix":
        if node.descriptor is None:
            raise OSError("custódia da recuperação foi encerrada")
        descriptor = os.open(name, flags, dir_fd=node.descriptor)
    else:
        descriptor = os.open(node.path / name, flags)
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
            raise OSError("controle da recuperação não é arquivo regular exclusivo")
        chunks = []
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    finally:
        os.close(descriptor)


def _gravar_controle_ancorado(node: _CleanupNode, name: str, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= os.O_NOFOLLOW if os.name == "posix" else os.O_BINARY
    if os.name == "posix":
        if node.descriptor is None:
            raise OSError("custódia da recuperação foi encerrada")
        descriptor = os.open(name, flags, 0o600, dir_fd=node.descriptor)
    else:
        descriptor = os.open(node.path / name, flags, 0o600)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("escrita do controle não avançou")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _restaurar_controles_cleanup_windows(
    raiz: Path,
    expected_identity: tuple[int, int, int],
    controls: dict[str, bytes],
) -> None:
    """Reestabelece a decisão e a quarentena após falha terminal de cleanup."""

    try:
        restored = _adquirir_custodia_cleanup(raiz)
    except (OSError, RecoveryRetained):
        return
    try:
        if restored.identity != expected_identity:
            return
        ordered_controls = []
        disposition = controls.get(_DISPOSITION)
        if disposition is not None:
            ordered_controls.append((_DISPOSITION, disposition))
        ordered_controls.append((_QUARENTENA, _QUARENTENA_PAYLOAD))
        ordered_controls.extend(
            (name, payload)
            for name, payload in controls.items()
            if name != _DISPOSITION
        )

        pending = ordered_controls
        for _attempt in range(2):
            failed = []
            for name, payload in pending:
                try:
                    _gravar_controle_ancorado(restored, name, payload)
                except FileExistsError:
                    pass
                except OSError:
                    failed.append((name, payload))
            if not failed:
                break
            pending = failed
    finally:
        try:
            _fechar_custodia_cleanup(restored)
        except OSError:
            pass


def _inventario_seguro(raiz: Path) -> tuple[list[Path], list[Path]]:
    """Enumera sem seguir links; qualquer reparse aborta antes da primeira remoção."""
    arquivos: list[Path] = []
    diretorios: list[Path] = []

    def visitar(diretorio: Path) -> None:
        with os.scandir(diretorio) as entradas:
            for entrada in entradas:
                details = entrada.stat(follow_symlinks=False)
                if _detalhes_sao_link_ou_reparse(details):
                    raise RecoveryRetained(
                        "a recuperação contém link ou reparse point"
                    )
                caminho = Path(entrada.path)
                if stat.S_ISDIR(details.st_mode):
                    visitar(caminho)
                    diretorios.append(caminho)
                elif stat.S_ISREG(details.st_mode):
                    arquivos.append(caminho)
                else:
                    raise RecoveryRetained(
                        "a recuperação contém objeto de filesystem inesperado"
                    )

    visitar(raiz)
    return arquivos, diretorios


def _arvore_de_recuperacao_eh_segura(raiz: Path) -> bool:
    if _raiz_eh_link_ou_reparse(raiz):
        return False
    try:
        _inventario_seguro(raiz)
    except (OSError, RecoveryRetained):
        return False
    return True


def _material_remanescente(raiz: Path, arquivos: list[Path]) -> list[Path]:
    """Tudo o que não é marcador de quarentena nem journal da própria raiz.

    O journal é AUTORIDADE, não material: sai depois de provado que o conteúdo
    privado sumiu, na mesma ordem da quarentena. Apagá-lo junto com o material
    permitia perder a prova de retomada e preservar o sigiloso — exatamente a
    prioridade invertida.
    """
    restante = []
    for caminho in arquivos:
        if caminho.parent == raiz and caminho.name in (
            _QUARENTENA,
            _JOURNAL,
            _IDENTIDADE,
            _SESSION,
            _DISPOSITION,
        ):
            continue
        restante.append(caminho)
    return restante


_JOURNAL_CORROMPIDO = object()
_JOURNAL_TRAVADO = object()
_SIDECAR_CORROMPIDO = object()
_SIDECAR_TRAVADO = object()


def _json_canonico(registro: dict) -> bytes:
    return json.dumps(
        registro,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _gravar_sidecar_imutavel(raiz: Path, nome: str, registro: dict) -> None:
    """Publica um controle durável sem substituir uma autoridade já existente."""
    corpo = _json_canonico(registro)
    alvo = raiz / nome
    if alvo.exists():
        if alvo.read_bytes() != corpo:
            raise RepositoryIntegrityError(f"{nome} divergente")
        return
    temporario = raiz / f".{nome}.{uuid4().hex}"
    with temporario.open("xb") as stream:
        stream.write(corpo)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.link(temporario, alvo)
    except FileExistsError:
        if alvo.read_bytes() != corpo:
            raise RepositoryIntegrityError(f"{nome} divergente")
    finally:
        temporario.unlink(missing_ok=True)
    if os.name == "posix":
        descriptor = os.open(raiz, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _ler_sidecar(raiz: Path, nome: str):
    try:
        bruto = (raiz / nome).read_bytes()
    except FileNotFoundError:
        return None
    except OSError:
        return _SIDECAR_TRAVADO
    try:
        registro = json.loads(bruto.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _SIDECAR_CORROMPIDO
    return registro if type(registro) is dict else _SIDECAR_CORROMPIDO


def _summary_payload(summary: BackupSummary) -> dict:
    return {
        "workspace_id": summary.workspace_id,
        "workspace_name": summary.workspace_name,
        "workspace_created_at": summary.workspace_created_at,
        "product_release": summary.product_release,
        "storage_schema_version": summary.storage_schema_version,
        "artifact_revisions": summary.artifact_revisions,
        "private_contents": summary.private_contents,
        "backup_sha256": summary.backup_sha256,
    }


def _summary_from_payload(value: object) -> BackupSummary | None:
    if type(value) is not dict or set(value) != {
        "workspace_id",
        "workspace_name",
        "workspace_created_at",
        "product_release",
        "storage_schema_version",
        "artifact_revisions",
        "private_contents",
        "backup_sha256",
    }:
        return None
    if not all(type(value[key]) is str for key in (
        "workspace_id", "workspace_name", "workspace_created_at", "product_release", "backup_sha256"
    )):
        return None
    if not all(type(value[key]) is int and value[key] >= 0 for key in (
        "storage_schema_version", "artifact_revisions", "private_contents"
    )):
        return None
    try:
        WorkspaceId.parse(value["workspace_id"])
    except (TypeError, ValueError):
        return None
    digest = value["backup_sha256"]
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        return None
    return BackupSummary(**value)


def _recovery_id_da_raiz(raiz: Path) -> str | None:
    prefixo = "recovery-"
    if not raiz.name.startswith(prefixo):
        return None
    candidato = raiz.name[len(prefixo):]
    try:
        parsed = UUID(candidato)
    except (ValueError, AttributeError):
        return None
    return candidato if str(parsed) == candidato else None


def _plano_promocao_do_backup(backup: object) -> dict:
    """Deriva a identidade exata que um journal futuro deverá preservar."""
    return {
        "workspace_id": backup.workspace.workspace_id,
        "workspace_name": backup.workspace.name,
        "workspace_created_at": backup.workspace.created_at,
        "revisions": [
            [
                item["revision_id"],
                item["artifact_kind"],
                item["artifact_id"],
                item["checksum_sha256"],
            ]
            for item in backup.artifact_revisions
        ],
        "private_contents": sorted(
            [item["content_id"], item["checksum_sha256"]]
            for item in backup.private_contents
        ),
    }


def _hash_plano_promocao(plano: dict) -> str:
    return sha256(_json_canonico(plano)).hexdigest()


def _gravar_session_descriptor(
    staging: object,
    recovery_id: str,
    summary: BackupSummary,
    promotion_plan_sha256: str,
) -> None:
    _gravar_sidecar_imutavel(
        Path(staging.root),
        _SESSION,
        {
            "version": _SESSION_VERSION,
            "recovery_id": recovery_id,
            "staging_identity": staging.identidade,
            "promotion_plan_sha256": promotion_plan_sha256,
            "summary": _summary_payload(summary),
        },
    )


def _descriptor_da_raiz(raiz: Path):
    registro = _ler_sidecar(raiz, _SESSION)
    if registro in (None, _SIDECAR_TRAVADO, _SIDECAR_CORROMPIDO):
        return registro
    if set(registro) != {
        "version",
        "recovery_id",
        "staging_identity",
        "promotion_plan_sha256",
        "summary",
    }:
        return _SIDECAR_CORROMPIDO
    if (
        type(registro["version"]) is not int
        or registro["version"] != _SESSION_VERSION
    ):
        return _SIDECAR_CORROMPIDO
    recovery_id = _recovery_id_da_raiz(raiz)
    if recovery_id is None or registro["recovery_id"] != recovery_id:
        return _SIDECAR_CORROMPIDO
    if type(registro["staging_identity"]) is not str or not registro["staging_identity"]:
        return _SIDECAR_CORROMPIDO
    plan_digest = registro["promotion_plan_sha256"]
    if (
        type(plan_digest) is not str
        or len(plan_digest) != 64
        or any(char not in "0123456789abcdef" for char in plan_digest)
    ):
        return _SIDECAR_CORROMPIDO
    summary = _summary_from_payload(registro["summary"])
    if summary is None:
        return _SIDECAR_CORROMPIDO
    return registro, summary


_JOURNAL_FIELDS = {
    "recovery_id",
    "backup_sha256",
    "workspace_id",
    "staging_identity",
    "workspace_name",
    "workspace_created_at",
    "revisions",
    "private_contents",
    "phase",
    "version",
}


def _journal_compativel_com_descriptor(journal: object, descriptor: object) -> bool:
    """Valida a prova terminal inteira; o nome da fase nunca basta."""
    if type(journal) is not dict or not isinstance(descriptor, tuple):
        return False
    session, summary = descriptor
    if set(journal) != _JOURNAL_FIELDS:
        return False
    if type(journal["version"]) is not int or journal["version"] != JOURNAL_VERSION:
        return False
    if (
        type(journal["phase"]) is not str
        or journal["phase"] not in {PROMOTING, PROMOTED, UNRESUMABLE}
    ):
        return False
    expected_strings = {
        "recovery_id": session["recovery_id"],
        "backup_sha256": summary.backup_sha256,
        "workspace_id": summary.workspace_id,
        "staging_identity": session["staging_identity"],
        "workspace_name": summary.workspace_name,
        "workspace_created_at": summary.workspace_created_at,
    }
    if any(
        type(journal[key]) is not str or journal[key] != expected
        for key, expected in expected_strings.items()
    ):
        return False
    revisions = journal["revisions"]
    private_contents = journal["private_contents"]
    if type(revisions) is not list or len(revisions) != summary.artifact_revisions:
        return False
    if type(private_contents) is not list or len(private_contents) != summary.private_contents:
        return False
    if any(
        type(item) is not list
        or len(item) != 4
        or any(type(field) is not str or not field for field in item)
        or len(item[3]) != 64
        or any(char not in "0123456789abcdef" for char in item[3])
        for item in revisions
    ):
        return False
    if any(
        type(item) is not list
        or len(item) != 2
        or any(type(field) is not str or not field for field in item)
        or len(item[1]) != 64
        or any(char not in "0123456789abcdef" for char in item[1])
        for item in private_contents
    ):
        return False
    plano = {
        "workspace_id": journal["workspace_id"],
        "workspace_name": journal["workspace_name"],
        "workspace_created_at": journal["workspace_created_at"],
        "revisions": revisions,
        "private_contents": private_contents,
    }
    return _hash_plano_promocao(plano) == session["promotion_plan_sha256"]


def _journal_bruto(raiz: Path):
    """Lê o journal SEM abrir o staging.

    `None` = não há. `_JOURNAL_CORROMPIDO` = existe e nunca vai ser entendido.
    `_JOURNAL_TRAVADO` = não deu para ler AGORA (transitório).
    """
    try:
        bruto = (raiz / _JOURNAL).read_bytes()
    except FileNotFoundError:
        return None
    except OSError:
        return _JOURNAL_TRAVADO
    try:
        registro = json.loads(bruto.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _JOURNAL_CORROMPIDO
    if (
        type(registro) is not dict
        or type(registro.get("version")) is not int
        or registro.get("version") != JOURNAL_VERSION
    ):
        return _JOURNAL_CORROMPIDO
    return registro


def _classificar_journal(staging: object) -> str:
    """AUTORIDADE ÚNICA sobre "o que há nesta raiz?".

    O mesmo fato era decidido em cinco lugares com polaridades diferentes, e o
    único que falhava ABERTO era justamente o que apagava. Aqui há quatro
    respostas, e cada chamador reage a elas — ninguém mais inlina a pergunta.

    - `ausente`      não há promoção iniciada; nada a preservar.
    - `retomavel`    journal íntegro, versão conhecida, identidade conferida.
    - `irretomavel`  corrompido, versão desconhecida, prova de identidade
                     ausente ou fase já marcada — nunca vai convergir.
    - `inacessivel`  não deu para LER agora (arquivo travado, placeholder do
                     OneDrive não hidratado). Transitório: preserva, não decide.
    """
    caminho = None
    try:
        caminho = Path(staging.root) / _JOURNAL
    except Exception:
        return _JOURNAL_INACESSIVEL
    try:
        bruto = caminho.read_bytes()
    except FileNotFoundError:
        return _JOURNAL_AUSENTE
    except OSError:
        return _JOURNAL_INACESSIVEL
    try:
        registro = json.loads(bruto.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _JOURNAL_IRRETOMAVEL
    if (
        type(registro) is not dict
        or type(registro.get("version")) is not int
        or registro.get("version") != JOURNAL_VERSION
    ):
        return _JOURNAL_IRRETOMAVEL
    phase = registro.get("phase")
    if phase == UNRESUMABLE:
        return _JOURNAL_IRRETOMAVEL
    if type(phase) is not str or phase not in {PROMOTING, PROMOTED}:
        return _JOURNAL_IRRETOMAVEL
    try:
        registrada = staging.identidade_registrada
    except Exception:
        return _JOURNAL_INACESSIVEL
    if registrada is None or registro.get("staging_identity") != registrada:
        return _JOURNAL_IRRETOMAVEL
    return _JOURNAL_RETOMAVEL


def _marcar_irretomavel(staging: object) -> None:
    """Persiste a classificação antes de afirmá-la ao usuário."""
    registro = staging.ler_transacao()
    if type(registro) is not dict:
        raise RepositoryIntegrityError(
            "não foi possível persistir a classificação irretomável"
        )
    staging.gravar_transacao({**registro, "phase": UNRESUMABLE})


def _encerrar_staging(staging: object, *, exigir_remocao: bool = False) -> None:
    """Fecha os handles E REMOVE a raiz, com a QUARENTENA SAINDO POR ÚLTIMO.

    `QUARANTINE_OUTLIVES_PRIVATE_MATERIAL`. `RecoveryStaging.discard()` só fecha
    handles; a raiz permanece. E um `rmtree(ignore_errors=True)` cego apagava o
    marcador de quarentena ANTES do conteúdo privado e ainda reportava sucesso —
    invertendo exatamente a prioridade que a quarentena existe para garantir.

    Ordem: fecha handles -> remove o material -> VERIFICA que sumiu -> só então
    remove o marcador -> remove a raiz. Se sobrar material, a quarentena é
    mantida (ou restabelecida) e, com `exigir_remocao`, o chamador recebe
    `RecoveryRetained` para poder dizer a verdade ao usuário e permitir
    retentativa.

    A remoção só ocorre sobre diretório que se PROVA ser raiz de recuperação
    nossa: precisa do marcador com o conteúdo canônico.
    """
    try:
        raiz = Path(staging.root)
    except Exception:
        staging.discard()
        return
    staging.discard()
    _remover_raiz_quarentenada(raiz, exigir_remocao=exigir_remocao)


def _remover_raiz_quarentenada(raiz: Path, *, exigir_remocao: bool = False) -> None:
    """Remoção da raiz em si, sem exigir posse de handle.

    Um staging órfão de queda muitas vezes NÃO reabre (o namespace privado ficou
    a meio caminho), e era exatamente ele que precisava ser recolhido. Exigir o
    objeto de staging para remover deixava esse caso sem saída. O que protege
    aqui é o marcador canônico, não a posse do handle.
    """
    custody = None
    try:
        custody = _adquirir_custodia_cleanup(raiz)
        marker_valid = False
        try:
            marker_valid = (
                _ler_controle_ancorado(custody, _QUARENTENA)
                == _QUARENTENA_PAYLOAD
            )
        except OSError:
            pass
        if not marker_valid:
            # Um comando humano explícito pode remover a raiz dedicada mesmo
            # com controles ilegíveis. A coleta automática continua exigindo
            # o marcador canônico; a custódia impede rebind durante a decisão.
            explicitly_authorized = (
                exigir_remocao and _recovery_id_da_raiz(raiz) is not None
            )
            if not explicitly_authorized:
                raise RecoveryRetained(
                    "a quarentena da recuperação não pôde ser validada"
                )

        paths = _paths_da_custodia(custody)
        material = set(_material_remanescente(raiz, paths))
        _remover_material_ancorado(custody, material)
        if _residuo_na_raiz_ancorada(custody):
            raise RecoveryRetained(
                "a recuperação preparada não pôde ser removida por completo"
            )

        controls = {}
        for name in (_JOURNAL, _IDENTIDADE, _SESSION, _DISPOSITION):
            try:
                controls[name] = _ler_controle_ancorado(custody, name)
            except FileNotFoundError:
                continue

        for name in controls:
            try:
                _unlink_na_custodia(custody, name)
            except FileNotFoundError:
                pass
        try:
            _unlink_na_custodia(custody, _QUARENTENA)
        except FileNotFoundError:
            pass

        if os.name == "nt":
            expected_identity = custody.identity
            try:
                try:
                    _fechar_custodia_cleanup(custody)
                finally:
                    custody = None
                raiz.rmdir()
                return
            except OSError:
                _restaurar_controles_cleanup_windows(
                    raiz,
                    expected_identity,
                    controls,
                )
                raise RecoveryRetained(
                    "a recuperação preparada não pôde ser removida por completo"
                )

        try:
            raiz.rmdir()
            return
        except OSError:
            # O dir_fd ainda nomeia a raiz originalmente validada, mesmo que
            # seu pathname tenha sido trocado. Restaura a autoridade ali.
            for name, payload in controls.items():
                try:
                    _gravar_controle_ancorado(custody, name, payload)
                except FileExistsError:
                    pass
            try:
                _gravar_controle_ancorado(
                    custody,
                    _QUARENTENA,
                    _QUARENTENA_PAYLOAD,
                )
            except FileExistsError:
                pass
            raise RecoveryRetained(
                "a recuperação preparada não pôde ser removida por completo"
            )
    except (OSError, RecoveryRetained) as exc:
        if exigir_remocao:
            if isinstance(exc, RecoveryRetained):
                raise
            raise RecoveryRetained(
                "a árvore da recuperação não pôde ser validada com segurança"
            ) from exc
    finally:
        if custody is not None:
            _fechar_custodia_cleanup(custody)


def _summary(backup: object, digest: str) -> BackupSummary:
    workspace = backup.workspace
    return BackupSummary(
        workspace_id=str(workspace.workspace_id),
        workspace_name=workspace.name,
        workspace_created_at=workspace.created_at,
        product_release=backup.product_release,
        storage_schema_version=backup.storage_schema_version,
        artifact_revisions=len(backup.artifact_revisions),
        private_contents=len(backup.private_contents),
        backup_sha256=digest,
    )


@dataclass(frozen=True, slots=True)
class ExportWorkspaceBackup:
    """UI → Local API → aplicação → `CreateWorkspaceBackup`."""

    create_backup: object
    workspaces: object
    max_package_bytes: int = MAX_BACKUP_PACKAGE_BYTES

    def execute(self, workspace_id: WorkspaceId) -> bytes:
        if type(workspace_id) is not WorkspaceId:
            raise TypeError("workspace_id inválido")
        if self.workspaces.get(workspace_id) is None:
            raise WorkspaceNotFound("workspace não encontrado")
        payload = self.create_backup.execute(workspace_id)
        if type(payload) is not bytes or not payload:
            raise RepositoryIntegrityError("pacote de backup inválido")
        if len(payload) > self.max_package_bytes:
            raise BackupTooLarge(
                "o pacote desta perícia excede o que a recuperação consegue reingerir"
            )
        return payload


@dataclass(frozen=True, slots=True)
class InspectWorkspaceBackup:
    """Verificação sem efeito colateral: nada é escrito, nada sai da máquina."""

    verify_backup: object
    hash_payload: object

    def execute(self, payload: bytes) -> BackupSummary:
        if type(payload) is not bytes or not payload:
            raise BackupInvalid("pacote de backup ausente")
        try:
            backup = self.verify_backup.execute(payload)
        except RepositoryIntegrityError as exc:
            raise BackupInvalid("pacote de backup inválido") from exc
        except (TypeError, ValueError) as exc:
            raise BackupInvalid("pacote de backup inválido") from exc
        return _summary(backup, self.hash_payload(payload))


#: Transições legais da sessão. `PROMOTING` e `DISCARDING` são MUTUAMENTE
#: EXCLUSIVAS: enquanto uma promoção está em voo, o descarte não pode fechar o
#: staging por baixo dela — era assim que dois cliques na UI produziam perícia
#: fantasma (workspace vivo criado, staging apagado, promoção morta em 503).
STAGED = "STAGED"
PROMOTING = "PROMOTING"
PROMOTED = "PROMOTED"
DISCARDING = "DISCARDING"
DISCARDED = "DISCARDED"
FAILED_RECOVERABLE = "FAILED_RECOVERABLE"


class WorkspaceRecoverySessions:
    """Registro em processo das sessões de recuperação, com transição atômica.

    A autoridade de `RecoveryStaging` vive num `WeakKeyDictionary` na
    infraestrutura: o objeto precisa de referência FORTE para sobreviver entre
    requisições HTTP distintas. Este registro é essa referência.

    O servidor é `ThreadingHTTPServer`, então duas requisições sobre o MESMO
    `recovery_id` correm de verdade. `claim` é o ponto de serialização: um
    compare-and-set sob lock por sessão. Não é framework de lock distribuído — é
    a fronteira estreita de estado que a autoridade exige.
    """

    __slots__ = ("_sessions", "_mutex", "_staging_mutex")

    def __init__(self) -> None:
        self._sessions: dict[str, dict] = {}
        self._mutex = threading.Lock()
        # Evita a janela `scan -> create -> register` duplicada para uploads
        # simultâneos do mesmo pacote. Staging é uma operação rara e local;
        # serializá-la aqui é preferível a publicar duas cópias privadas.
        self._staging_mutex = threading.Lock()

    @property
    def staging_lock(self):
        return self._staging_mutex

    def register(
        self,
        recovery_id: str,
        staging: object | None,
        summary: BackupSummary | None,
        *,
        state: str = STAGED,
        root: Path | None = None,
        reason: str | None = None,
        disposition: str | None = None,
    ) -> dict:
        with self._mutex:
            entry = {
                "staging": staging,
                "summary": summary,
                "state": state,
                "root": Path(staging.root) if staging is not None else root,
                "reason": reason,
                "disposition": disposition,
            }
            self._sessions[recovery_id] = entry
            return entry

    def get(self, recovery_id: str) -> dict:
        with self._mutex:
            entry = self._sessions.get(recovery_id)
        if entry is None:
            raise RecoveryNotFound("sessão de recuperação não encontrada")
        return entry

    def claim(self, recovery_id: str, permitidos: tuple[str, ...], destino: str) -> dict:
        """Transição ATÔMICA de estado. Quem perde a corrida recebe erro honesto."""
        with self._mutex:
            entry = self._sessions.get(recovery_id)
            if entry is None:
                raise RecoveryNotFound("sessão de recuperação não encontrada")
            atual = entry["state"]
            if atual not in permitidos:
                if atual == PROMOTED:
                    raise RecoveryAlreadyPromoted("esta recuperação já foi promovida")
                if atual == DISCARDED:
                    raise RecoveryDiscarded("esta recuperação foi descartada")
                if atual == RECOVERY_UNRESUMABLE:
                    raise RecoveryUnresumable(
                        "esta promoção interrompida não pode mais ser concluída"
                    )
                if atual == DISCARDING:
                    # EM ANDAMENTO != DESCARTADA. Responder "não encontrada" a
                    # quem cai nesta janela afirma um fim que ainda não houve.
                    raise WorkspaceRecoveryConflict(
                        "esta recuperação já tem uma operação em andamento"
                    )
                raise WorkspaceRecoveryConflict(
                    "esta recuperação já tem uma operação em andamento"
                )
            entry["claimed_from"] = atual
            entry["state"] = destino
            return entry

    def settle(self, recovery_id: str, destino: str) -> None:
        with self._mutex:
            entry = self._sessions.get(recovery_id)
            if entry is not None:
                entry["state"] = destino

    def snapshot(self) -> tuple[tuple[str, dict], ...]:
        """Cópia rasa do registro, para varredura FORA do lock.

        Ler journal é I/O de disco e não pode acontecer sob o mutex que
        serializa `claim`.
        """
        with self._mutex:
            return tuple(self._sessions.items())

    def is_current(
        self, recovery_id: str, entry: dict, states: tuple[str, ...]
    ) -> bool:
        """Confirma o ponto de linearização depois de I/O fora do mutex."""
        with self._mutex:
            current = self._sessions.get(recovery_id)
            return current is entry and current.get("state") in states

    def drop(self, recovery_id: str) -> None:
        with self._mutex:
            self._sessions.pop(recovery_id, None)

    def close_all(self) -> None:
        for entry in tuple(self._sessions.values()):
            staging = entry["staging"]
            # RUNTIME_CLOSE != DISCARD_RECOVERY. STAGED também é trabalho já
            # verificado do usuário; o descriptor durável permite reconstruí-lo
            # no próximo processo. O fechamento só libera handles.
            if staging is None:
                continue
            try:
                staging.close()
            except Exception:
                pass
        self._sessions.clear()


@dataclass(frozen=True, slots=True)
class StageWorkspaceRecovery:
    """Verifica o pacote e o restaura numa raiz de staging ISOLADA.

    O staging nasce e morre quarentenado (`RECOVERY_NOT_PROMOTABLE`). Nada no
    armazenamento vivo é tocado aqui — nem em caso de sucesso.
    """

    verify_backup: object
    create_staging: object
    restore_backup: object
    sessions: WorkspaceRecoverySessions
    staging_root: Path
    hash_payload: object
    open_staging: object = None
    workspaces: object = None
    new_recovery_id: object = uuid4

    def _promovibilidade(self, backup, staging) -> tuple[bool, str | None]:
        """Condições canônicas de promoção JÁ conhecidas no staging.

        `VERIFIED != PROMOTABLE`: dizer `promotable: True` e recusar segundos
        depois é mentira de contrato. Só afirma o que consegue sustentar.
        """
        workspace_id = WorkspaceId.parse(str(backup.workspace.workspace_id))
        if self.workspaces is not None and self.workspaces.get(workspace_id) is not None:
            # Perícia viva com esta identidade só é tocável se ELA veio desta
            # promoção. Cada motivo abaixo é o motivo REAL — dizer "já existe
            # perícia" quando o que houve foi journal ilegível é mentira.
            estado = _classificar_journal(staging)
            if estado == _JOURNAL_AUSENTE:
                return False, "ja_existe_pericia_com_esta_identidade"
            if estado == _JOURNAL_IRRETOMAVEL:
                return False, "promocao_interrompida_irretomavel"
            if estado == _JOURNAL_INACESSIVEL:
                return False, "estado_da_promocao_ilegivel"
        if any(
            item.get("artifact_kind") == _AI_COST_LEDGER_KIND
            for item in backup.artifact_revisions
            if isinstance(item, dict)
        ):
            return False, "autoridade_de_custo_de_ia_nao_promovivel"
        return True, None

    def execute(self, payload: bytes) -> RecoverySession:
        if type(payload) is not bytes or not payload:
            raise BackupInvalid("pacote de backup ausente")
        try:
            backup = self.verify_backup.execute(payload)
        except RepositoryIntegrityError as exc:
            raise BackupInvalid("pacote de backup inválido") from exc
        except (TypeError, ValueError) as exc:
            raise BackupInvalid("pacote de backup inválido") from exc
        digest = self.hash_payload(payload)
        with self.sessions.staging_lock:
            return self._stage_verified(payload, backup, digest)

    def _stage_verified(self, payload: bytes, backup: object, digest: str) -> RecoverySession:
        retomada = self._promocao_interrompida(backup, digest)
        if retomada is not None:
            return retomada
        recovery_id = str(self.new_recovery_id())
        root = Path(self.staging_root) / f"recovery-{recovery_id}"
        try:
            staging = self.create_staging(root)
        except (RepositoryError, OSError) as exc:
            raise RecoveryStageFailed("não foi possível isolar a recuperação") from exc
        try:
            self.restore_backup(staging).execute(payload)
        except BaseException as exc:
            try:
                _encerrar_staging(staging)
            except Exception:
                pass
            raise RecoveryStageFailed("a restauração isolada falhou") from exc
        if not (root / "RECOVERY_NOT_PROMOTABLE").exists():
            _encerrar_staging(staging)
            raise RepositoryIntegrityError("a quarentena de recuperação desapareceu")
        summary = _summary(backup, digest)
        try:
            # A sessão existe antes do journal de promoção. Sem esta identidade
            # durável, fechar o app apagava STAGED e journal corrompido virava
            # uma raiz sem recovery_id/resumo/ação normal de usuário.
            _gravar_session_descriptor(
                staging,
                recovery_id,
                summary,
                _hash_plano_promocao(_plano_promocao_do_backup(backup)),
            )
        except BaseException as exc:
            try:
                _encerrar_staging(staging)
            except Exception:
                pass
            raise RecoveryStageFailed(
                "não foi possível tornar a recuperação preparada durável"
            ) from exc
        self.sessions.register(recovery_id, staging, summary)
        promovivel, motivo = self._promovibilidade(backup, staging)
        return RecoverySession(recovery_id, summary, promovivel, motivo)

    def _promocao_interrompida(self, backup, digest: str) -> RecoverySession | None:
        """Descobre no disco uma promoção DESTE pacote interrompida por crash.

        Autoridade durável = raiz quarentenada + journal de promoção. A sessão em
        memória é só cache: some no crash, e é justamente aí que a recuperação
        precisa continuar existindo. Reabrir a raiz interrompida é o que evita a
        perícia meio-restaurada permanente, sem exigir terminal.

        NUNCA promove sozinha: apenas volta a expor a recuperação como retomável;
        a promoção segue sendo ato humano explícito.
        """
        workspace_id = str(backup.workspace.workspace_id)

        # 1) SESSÃO VIVA PRIMEIRO. Reabrir do disco uma raiz que este mesmo
        # processo ainda mantém aberta falha na aquisição do namespace privado.
        # Engolir esse erro e seguir fabricava um SEGUNDO staging — outra cópia
        # integral e em claro do material sigiloso — para então responder um
        # motivo falso ("já existe perícia com esta identidade"). Quem recarrega
        # a tela e reenvia o mesmo pacote precisa cair na RETOMADA.
        for recovery_id, entry in self.sessions.snapshot():
            state = entry.get("state")
            existing_summary = entry.get("summary")
            mesmo_pacote = (
                type(existing_summary) is BackupSummary
                and existing_summary.backup_sha256 == digest
                and existing_summary.workspace_id == workspace_id
            )
            if mesmo_pacote and state == RECOVERY_UNRESUMABLE:
                result = RecoverySession(
                    recovery_id,
                    existing_summary,
                    False,
                    entry.get("reason") or "promocao_interrompida_irretomavel",
                    True,
                )
                if self.sessions.is_current(
                    recovery_id, entry, (RECOVERY_UNRESUMABLE,)
                ):
                    return result
                continue
            if mesmo_pacote and state == RECOVERY_RETAINED:
                result = RecoverySession(
                    recovery_id,
                    existing_summary,
                    False,
                    "limpeza_de_recuperacao_pendente",
                    bool(entry.get("disposition") == "ABANDON"),
                )
                if self.sessions.is_current(recovery_id, entry, (RECOVERY_RETAINED,)):
                    return result
                continue
            if state not in (STAGED, FAILED_RECOVERABLE):
                continue
            staging = entry["staging"]
            if mesmo_pacote and state == STAGED:
                promovivel, motivo = self._promovibilidade(backup, staging)
                result = RecoverySession(
                    recovery_id, existing_summary, promovivel, motivo
                )
                if self.sessions.is_current(recovery_id, entry, (STAGED,)):
                    return result
                continue
            if mesmo_pacote and _classificar_journal(staging) == _JOURNAL_IRRETOMAVEL:
                self.sessions.settle(recovery_id, RECOVERY_UNRESUMABLE)
                entry["reason"] = "promotion_journal_unreadable_or_unsupported"
                result = RecoverySession(
                    recovery_id,
                    existing_summary,
                    False,
                    entry["reason"],
                    True,
                )
                if self.sessions.is_current(
                    recovery_id, entry, (RECOVERY_UNRESUMABLE,)
                ):
                    return result
                continue
            if not self._journal_desta_promocao(staging, digest, workspace_id):
                continue
            self.sessions.settle(recovery_id, FAILED_RECOVERABLE)
            summary = _summary(backup, digest)
            entry["summary"] = summary
            promovivel, motivo = self._promovibilidade(backup, staging)
            result = RecoverySession(
                recovery_id, summary, promovivel, motivo, True
            )
            if self.sessions.is_current(
                recovery_id, entry, (FAILED_RECOVERABLE,)
            ):
                return result

        if self.open_staging is None:
            return None
        base = Path(self.staging_root)
        try:
            candidatas = sorted(p for p in base.iterdir() if p.is_dir())
        except OSError:
            return None
        for raiz in candidatas:
            if not _arvore_de_recuperacao_eh_segura(raiz):
                continue
            marcador = raiz / _QUARENTENA
            try:
                if marcador.read_bytes() != _QUARENTENA_PAYLOAD:
                    continue
            except OSError:
                continue
            # 2) O journal é lido do disco ANTES de abrir a raiz: só assim dá
            # para saber se esta raiz nos interessa, e só o que interessa pode
            # falhar fechado.
            registro = _journal_bruto(raiz)
            if registro is None:
                continue
            if registro is _JOURNAL_TRAVADO:
                # TRANSITÓRIO, e por isso mesmo não pode ser ignorado: pular a
                # raiz faz o produto seguir em frente e FABRICAR outra cópia
                # integral e em claro do material sigiloso, para então mentir o
                # motivo. Falhar fechado aqui é honesto e se cura sozinho na
                # próxima tentativa, quando o arquivo voltar a ser legível.
                raise RecoveryStageFailed(
                    "o estado de uma promoção interrompida não pôde ser lido agora"
                )
            if registro is _JOURNAL_CORROMPIDO:
                # Corrompido não pode ser ligado a pacote nenhum, então também
                # não pode BLOQUEAR pacote nenhum. Bloquear aqui matava toda
                # restauração da instalação por causa de uma raiz alheia — e a
                # restauração é o último recurso do produto.
                continue
            if (
                registro.get("backup_sha256") != digest
                or registro.get("workspace_id") != workspace_id
            ):
                continue
            try:
                staging = self.open_staging(raiz)
            except (RepositoryError, RepositoryIntegrityError, OSError) as exc:
                # É a raiz CERTA e não abre. Fabricar um staging novo aqui
                # levaria ao beco sem saída; falha fechada com motivo honesto.
                raise RecoveryStageFailed(
                    "uma promoção interrompida deste backup não pôde ser reaberta"
                ) from exc
            try:
                transacao = staging.ler_transacao()
                if (
                    type(transacao) is not dict
                    or transacao.get("staging_identity") != staging.identidade
                ):
                    staging.close()
                    continue
            except Exception:
                try:
                    staging.close()
                except Exception:
                    pass
                continue
            recovery_id = str(transacao.get("recovery_id") or self.new_recovery_id())
            summary = _summary(backup, digest)
            entry = self.sessions.register(recovery_id, staging, summary)
            self.sessions.settle(recovery_id, FAILED_RECOVERABLE)
            promovivel, motivo = self._promovibilidade(backup, staging)
            result = RecoverySession(recovery_id, summary, promovivel, motivo, True)
            if self.sessions.is_current(
                recovery_id, entry, (FAILED_RECOVERABLE,)
            ):
                return result
        return None

    @staticmethod
    def _journal_desta_promocao(staging, digest: str, workspace_id: str) -> bool:
        try:
            transacao = staging.ler_transacao()
        except Exception:
            return False
        return (
            type(transacao) is dict
            and transacao.get("backup_sha256") == digest
            and transacao.get("workspace_id") == workspace_id
        )

def recolher_stagings_orfaos(base) -> tuple[str, ...]:
    """Recolhe, na REABERTURA do produto, raízes de staging sem retomada pendente.

    Uma queda durante a preparação — ou uma remoção que falhou no sucesso da
    promoção — deixava uma cópia integral e em claro do material sigiloso em
    disco, quarentenada e SEM nenhuma rota de produto para removê-la. Cada queda
    somava outra. Reter material sigiloso indefinidamente sem saída é o defeito;
    a cópia em si é reconstruível a partir do arquivo de backup do usuário.

    FAIL-CLOSED quanto à retomada: só recolhe o que PROVA não ter promoção
    pendente — sem journal, ou journal já em `PROMOTED`. Journal ilegível ou em
    `PROMOTING` é preservado, porque é (ou pode ser) a única autoridade que
    permite concluir uma perícia meio-gravada.

    Roda antes de existir qualquer sessão, então não há corrida com o usuário.
    """
    raiz_base = Path(base)
    try:
        candidatas = sorted(p for p in raiz_base.iterdir() if p.is_dir())
    except OSError:
        return ()
    recolhidas = []
    for raiz in candidatas:
        if not _arvore_de_recuperacao_eh_segura(raiz):
            continue
        try:
            if (raiz / _QUARENTENA).read_bytes() != _QUARENTENA_PAYLOAD:
                continue
        except OSError:
            continue
        registro = _journal_bruto(raiz)
        if registro is _JOURNAL_TRAVADO:
            # Transitório: não decide nada agora, tenta na próxima reabertura.
            continue
        descriptor = _descriptor_da_raiz(raiz)
        if descriptor is _SIDECAR_TRAVADO:
            continue
        if descriptor is not None:
            # Descriptor válido OU inválido prova que uma sessão chegou a ser
            # publicada. A coleta nunca decide abandoná-la pelo usuário. A
            # única exceção é uma promoção comprovadamente concluída, cuja
            # raiz é apenas resíduo terminal.
            if not _journal_compativel_com_descriptor(registro, descriptor):
                continue
            if registro["phase"] != PROMOTED:
                continue
        elif registro is not None:
            # Journal legado sem descriptor publicado não prova terminalidade.
            # Só a dupla ausência comprova queda anterior à publicação.
            continue
        # NÃO reabre o staging para recolhê-lo: reabrir reprovisiona o
        # armazenamento privado e o SQLite da raiz, e os handles recém-criados
        # impedem a própria remoção. A autoridade que autoriza remover é o
        # marcador canônico de quarentena, não a posse de um handle.
        try:
            _remover_raiz_quarentenada(raiz)
        except Exception:
            continue
        if not raiz.exists():
            recolhidas.append(raiz.name)
    return tuple(recolhidas)


def _disposition_da_raiz(raiz: Path):
    registro = _ler_sidecar(raiz, _DISPOSITION)
    if registro in (None, _SIDECAR_TRAVADO, _SIDECAR_CORROMPIDO):
        return registro
    if set(registro) != {"version", "recovery_id", "mode"}:
        return _SIDECAR_CORROMPIDO
    if (
        type(registro["version"]) is not int
        or registro["version"] != _DISPOSITION_VERSION
    ):
        return _SIDECAR_CORROMPIDO
    if registro["recovery_id"] != _recovery_id_da_raiz(raiz):
        return _SIDECAR_CORROMPIDO
    if type(registro["mode"]) is not str or registro["mode"] not in {
        "DISCARD",
        "ABANDON",
    }:
        return _SIDECAR_CORROMPIDO
    return registro


def reconstruir_sessoes_recuperacao(base, sessions, open_staging) -> tuple[str, ...]:
    """Reconstrói sessões sem promover nem tocar no armazenamento vivo."""
    raiz_base = Path(base)
    try:
        candidatas = sorted(p for p in raiz_base.iterdir() if p.is_dir())
    except OSError:
        return ()
    reconstruidas = []
    for raiz in candidatas:
        recovery_id = _recovery_id_da_raiz(raiz)
        if recovery_id is None:
            continue
        if not _arvore_de_recuperacao_eh_segura(raiz):
            # Preservar a árvore sem publicá-la cria uma recuperação invisível
            # e sem saída pelo produto. O nome canônico basta para expor o
            # estado sanitizado; nenhum membro inseguro é lido ou percorrido.
            sessions.register(
                recovery_id,
                None,
                None,
                state=RECOVERY_UNRESUMABLE,
                root=raiz,
                reason="unsafe_recovery_tree",
            )
            reconstruidas.append(recovery_id)
            continue
        marcador_valido = False
        try:
            marcador_valido = (raiz / _QUARENTENA).read_bytes() == _QUARENTENA_PAYLOAD
        except OSError:
            pass
        descriptor = _descriptor_da_raiz(raiz)
        journal = _journal_bruto(raiz)
        disposition = _disposition_da_raiz(raiz)
        summary = descriptor[1] if isinstance(descriptor, tuple) else None
        reason = None
        staging = None

        if disposition not in (None, _SIDECAR_TRAVADO, _SIDECAR_CORROMPIDO):
            state = RECOVERY_RETAINED
            reason = "cleanup_incomplete"
            mode = disposition["mode"]
        elif disposition in (_SIDECAR_TRAVADO, _SIDECAR_CORROMPIDO):
            state = RECOVERY_RETAINED
            reason = "disposition_unreadable"
            mode = None
        elif not marcador_valido:
            state = RECOVERY_UNRESUMABLE
            reason = "quarantine_marker_unreadable"
            mode = None
        elif descriptor in (_SIDECAR_TRAVADO, _SIDECAR_CORROMPIDO, None):
            state = RECOVERY_UNRESUMABLE
            reason = "session_descriptor_unreadable"
            mode = None
        elif journal is _JOURNAL_TRAVADO:
            state = FAILED_RECOVERABLE
            reason = "promotion_journal_temporarily_unreadable"
            mode = None
        elif journal is _JOURNAL_CORROMPIDO:
            state = RECOVERY_UNRESUMABLE
            reason = "promotion_journal_unreadable_or_unsupported"
            mode = None
        elif journal is None:
            state = STAGED
            mode = None
        elif not _journal_compativel_com_descriptor(journal, descriptor):
            state = RECOVERY_UNRESUMABLE
            reason = "promotion_journal_unreadable_or_unsupported"
            mode = None
        else:
            phase = journal.get("phase")
            identity = descriptor[0]["staging_identity"]
            if journal.get("staging_identity") != identity:
                state = RECOVERY_UNRESUMABLE
                reason = "staging_identity_mismatch"
            elif phase == PROMOTING:
                state = FAILED_RECOVERABLE
            elif phase == UNRESUMABLE:
                state = RECOVERY_UNRESUMABLE
                reason = "promotion_cannot_converge"
            elif phase == PROMOTED:
                # Estado terminal positivamente provado: a coleta é segura.
                try:
                    _remover_raiz_quarentenada(raiz)
                except Exception:
                    pass
                continue
            else:
                state = RECOVERY_UNRESUMABLE
                reason = "promotion_journal_unreadable_or_unsupported"
            mode = None

        if state in (STAGED, FAILED_RECOVERABLE) and reason is None:
            try:
                staging = open_staging(raiz)
                if staging.identidade_registrada != descriptor[0]["staging_identity"]:
                    staging.close()
                    staging = None
                    state = RECOVERY_UNRESUMABLE
                    reason = "staging_identity_mismatch"
            except Exception:
                staging = None
                state = RECOVERY_UNRESUMABLE
                reason = "staging_cannot_be_reopened"

        sessions.register(
            recovery_id,
            staging,
            summary,
            state=state,
            root=raiz,
            reason=reason,
            disposition=mode,
        )
        reconstruidas.append(recovery_id)
    return tuple(reconstruidas)


def _allowed_actions(entry: dict) -> tuple[str, ...]:
    state = entry["state"]
    if state == STAGED:
        return ("PROMOTE", "DISCARD")
    if state == FAILED_RECOVERABLE:
        if entry.get("staging") is not None and entry.get("reason") is None:
            return ("PROMOTE", "ABANDON")
        return ("ABANDON",)
    if state == RECOVERY_UNRESUMABLE:
        return ("ABANDON",)
    if state == RECOVERY_RETAINED:
        mode = entry.get("disposition")
        return (("RETRY_DISCARD",) if mode == "DISCARD" else ("RETRY_ABANDON",))
    return ()


@dataclass(frozen=True, slots=True)
class ListWorkspaceRecoveries:
    sessions: WorkspaceRecoverySessions

    def execute(self) -> tuple[RecoverySessionStatus, ...]:
        result = []
        for recovery_id, entry in self.sessions.snapshot():
            state = entry["state"]
            if state in (PROMOTED, DISCARDED):
                continue
            result.append(
                RecoverySessionStatus(
                    recovery_id=recovery_id,
                    state=state,
                    summary=entry.get("summary"),
                    reason=entry.get("reason"),
                    allowed_actions=_allowed_actions(entry),
                )
            )
        return tuple(sorted(result, key=lambda item: item.recovery_id))


def _gravar_disposition(entry: dict, recovery_id: str, mode: str) -> None:
    raiz = entry.get("root")
    if raiz is None and entry.get("staging") is not None:
        raiz = Path(entry["staging"].root)
    if raiz is None:
        raise RepositoryIntegrityError("raiz da recuperação indisponível")
    custody = _adquirir_custodia_cleanup(Path(raiz))
    try:
        record = {
            "version": _DISPOSITION_VERSION,
            "recovery_id": recovery_id,
            "mode": mode,
        }
        body = _json_canonico(record)
        try:
            current = _ler_controle_ancorado(custody, _DISPOSITION)
        except FileNotFoundError:
            current = None
        if current is not None:
            if current != body:
                raise RepositoryIntegrityError(f"{_DISPOSITION} divergente")
        else:
            temporary = f".{_DISPOSITION}.{uuid4().hex}"
            _gravar_controle_ancorado(custody, temporary, body)
            try:
                if os.name == "posix":
                    if custody.descriptor is None:
                        raise OSError("custódia da recuperação foi encerrada")
                    os.link(
                        temporary,
                        _DISPOSITION,
                        src_dir_fd=custody.descriptor,
                        dst_dir_fd=custody.descriptor,
                        follow_symlinks=False,
                    )
                    os.fsync(custody.descriptor)
                else:
                    os.link(
                        custody.path / temporary,
                        custody.path / _DISPOSITION,
                        follow_symlinks=False,
                    )
            except FileExistsError:
                if _ler_controle_ancorado(custody, _DISPOSITION) != body:
                    raise RepositoryIntegrityError(f"{_DISPOSITION} divergente")
            finally:
                try:
                    _unlink_na_custodia(custody, temporary)
                except FileNotFoundError:
                    pass
        entry["disposition"] = mode
    finally:
        _fechar_custodia_cleanup(custody)


def _remover_entry(entry: dict) -> None:
    staging = entry.get("staging")
    if staging is not None:
        _encerrar_staging(staging, exigir_remocao=True)
        return
    raiz = entry.get("root")
    if raiz is None:
        raise RepositoryIntegrityError("raiz da recuperação indisponível")
    _remover_raiz_quarentenada(Path(raiz), exigir_remocao=True)


def _mutacao_viva_ocorreu(workspaces: object | None, staging: object) -> bool:
    """A promoção chegou a tocar o armazenamento vivo?

    O journal prova INTENÇÃO, não gravação — ele é escrito antes da primeira
    mutação exatamente para sobreviver à queda no meio dela. Quem sabe se algo
    foi gravado é o armazenamento vivo. FAIL-CLOSED: sem como conferir, assume
    que gravou, porque o erro caro é destruir a retomada de uma perícia parcial.
    """
    if workspaces is None:
        return True
    try:
        registro = staging.ler_transacao()
    except Exception:
        return True
    if type(registro) is not dict:
        return True
    try:
        return workspaces.get(WorkspaceId.parse(str(registro.get("workspace_id")))) is not None
    except Exception:
        return True


@dataclass(frozen=True, slots=True)
class DiscardWorkspaceRecovery:
    sessions: WorkspaceRecoverySessions
    #: Autoridade REAL sobre "algo já foi gravado no vivo?". O journal é escrito
    #: ANTES da primeira mutação, de propósito; usá-lo como prova de gravação
    #: faz o produto afirmar perícia parcial onde não há nenhuma.
    workspaces: object | None = None

    def execute(
        self, recovery_id: str, *, aceitar_incompleta: bool = False
    ) -> str:
        """`aceitar_incompleta` é a saída CONSCIENTE, nunca o caminho normal.

        Existe para o caso em que a retomada é possível em tese mas impossível
        na prática (disco cheio — e é a própria cópia preparada que ocupa o
        espaço). O usuário declara que aceita a perícia ficar incompleta; o
        produto não decide isso por ele nem faz em silêncio.
        """
        # Reivindica DISCARDING antes de tocar em qualquer coisa: se houver uma
        # promoção em voo, quem perde a corrida recebe erro honesto em vez de
        # fechar o staging sob os pés dela.
        permitidos = (
            (FAILED_RECOVERABLE, RECOVERY_UNRESUMABLE, RECOVERY_RETAINED)
            if aceitar_incompleta
            else (STAGED, FAILED_RECOVERABLE, RECOVERY_RETAINED)
        )
        entry = self.sessions.claim(recovery_id, permitidos, DISCARDING)
        anterior = entry.get("claimed_from")
        disposition = entry.get("disposition")
        disposition_irrecuperavel = anterior == RECOVERY_RETAINED and disposition is None
        if anterior == RECOVERY_RETAINED:
            esperado = "ABANDON" if aceitar_incompleta else "DISCARD"
            if disposition not in (None, esperado):
                self.sessions.settle(recovery_id, RECOVERY_RETAINED)
                raise WorkspaceRecoveryConflict(
                    "a limpeza retida pertence a outra decisão do usuário"
                )
            if disposition_irrecuperavel and not aceitar_incompleta:
                # Sem uma disposition legível não podemos inferir que o usuário
                # havia escolhido DISCARD. A única saída anunciada é um novo
                # ABANDON confirmado explicitamente pelo transporte.
                self.sessions.settle(recovery_id, RECOVERY_RETAINED)
                raise WorkspaceRecoveryConflict(
                    "a decisão anterior está ilegível; confirme o abandono"
                )
        staging = entry.get("staging")
        estado = (
            _classificar_journal(staging)
            if staging is not None
            else _JOURNAL_IRRETOMAVEL
        )
        # Só o RETOMÁVEL é protegido: aí o journal é a única prova durável que
        # permite concluir uma promoção já iniciada no vivo. Irretomável não é
        # autoridade de nada alcançável, e inacessível pode voltar a ser lido —
        # nenhum dos dois justifica prender o usuário para sempre.
        if (
            estado == _JOURNAL_RETOMAVEL
            and not aceitar_incompleta
            and _mutacao_viva_ocorreu(self.workspaces, staging)
        ):
            self.sessions.settle(recovery_id, FAILED_RECOVERABLE)
            raise RecoveryPromotionIncomplete(
                "esta promoção já começou a gravar e precisa ser retomada"
            )
        if estado == _JOURNAL_INACESSIVEL and not aceitar_incompleta:
            self.sessions.settle(recovery_id, FAILED_RECOVERABLE)
            raise RecoveryPromotionIncomplete(
                "não foi possível ler o estado desta promoção agora"
            )
        mode = "ABANDON" if aceitar_incompleta else "DISCARD"
        try:
            if not disposition_irrecuperavel:
                _gravar_disposition(entry, recovery_id, mode)
            _remover_entry(entry)
        except BaseException:
            # A sessão CONTINUA existindo: o usuário precisa poder tentar de novo
            # depois de liberar o que segurava o arquivo (antivírus, indexador).
            self.sessions.settle(recovery_id, RECOVERY_RETAINED)
            raise
        self.sessions.settle(recovery_id, DISCARDED)
        self.sessions.drop(recovery_id)
        return recovery_id


@dataclass(frozen=True, slots=True)
class AbandonWorkspaceRecovery:
    discard: DiscardWorkspaceRecovery

    def execute(self, recovery_id: str) -> str:
        return self.discard.execute(recovery_id, aceitar_incompleta=True)


@dataclass(frozen=True, slots=True)
class PromoteWorkspaceRecovery:
    """PROMOÇÃO EXPLÍCITA: única operação que toca o armazenamento vivo.

    A raiz de staging NÃO é desquarentenada nem adotada como armazenamento — o
    conteúdo já verificado é copiado para o armazenamento vivo, e apenas quando
    o workspace ainda não existe lá. Sem isso, recusa com conflito: um backup
    nunca sobrescreve trabalho vivo em silêncio.
    """

    sessions: WorkspaceRecoverySessions
    workspaces: object
    revisions: object
    private_contents: object | None

    def execute(self, recovery_id: str) -> BackupSummary:
        # Reivindica PROMOTING: enquanto durar, nenhum descarte fecha o staging e
        # nenhuma segunda promoção entra. `FAILED_RECOVERABLE` é reivindicável
        # porque uma promoção interrompida TEM de ser retomável.
        entry = self.sessions.claim(recovery_id, (STAGED, FAILED_RECOVERABLE), PROMOTING)
        if _classificar_journal(entry["staging"]) == _JOURNAL_IRRETOMAVEL:
            self.sessions.settle(recovery_id, RECOVERY_UNRESUMABLE)
            entry["reason"] = "promotion_journal_unreadable_or_unsupported"
            raise RecoveryUnresumable(
                "esta promoção interrompida não pode mais ser concluída"
            )
        try:
            return self._promover(recovery_id, entry)
        except BaseException as exc:
            self.sessions.settle(recovery_id, FAILED_RECOVERABLE)
            if not isinstance(exc, Exception):
                raise
            estado = _classificar_journal(entry["staging"])
            if estado == _JOURNAL_AUSENTE:
                raise
            # Conflito de prefixo/identidade NÃO é transitório: a perícia viva
            # divergiu do pacote e nenhuma retomada converge. Chamar isso de
            # "retome" mandaria o usuário repetir para sempre uma operação
            # impossível, com o descarte recusado do outro lado.
            if isinstance(exc, (WorkspaceRecoveryConflict, RecoveryNotPromotable)):
                try:
                    _marcar_irretomavel(entry["staging"])
                except Exception as persist_error:
                    raise RecoveryPromotionIncomplete(
                        "a promoção divergiu, mas a classificação não pôde ser persistida"
                    ) from persist_error
                self.sessions.settle(recovery_id, RECOVERY_UNRESUMABLE)
                raise RecoveryUnresumable(
                    "a perícia viva divergiu deste pacote; a promoção não converge mais"
                ) from exc
            if estado == _JOURNAL_IRRETOMAVEL:
                raise RecoveryUnresumable(
                    "esta promoção interrompida não pode mais ser concluída"
                ) from exc
            # Journal presente = a primeira mutação viva JÁ aconteceu. Reportar
            # isso como "armazenamento indisponível" faria o produto dizer "nada
            # mudou" no exato instante em que gravou uma perícia parcial.
            if not _mutacao_viva_ocorreu(self.workspaces, entry["staging"]):
                # Journal presente sem nada gravado: a falha é o que ela é, não
                # uma promoção meio-feita. Afirmar o contrário empurraria o
                # usuário para o descarte consciente de uma perícia inexistente.
                raise
            raise RecoveryPromotionIncomplete(
                "a promoção foi interrompida depois de começar a gravar"
            ) from exc

    @staticmethod
    def _transacao_autoriza(transacao, staging, summary: BackupSummary) -> bool:
        """A perícia viva só pode ser tocada se ELA veio desta mesma promoção.

        Prova durável e exata: mesmo pacote, mesma identidade de workspace e
        mesma raiz de staging. Sem isso, uma perícia viva alheia poderia ser
        mutada por um backup de linhagem parecida — `NO_SILENT_OVERWRITE`.
        """
        if type(transacao) is not dict:
            return False
        return (
            transacao.get("backup_sha256") == summary.backup_sha256
            and transacao.get("workspace_id") == summary.workspace_id
            and transacao.get("staging_identity") == staging.identidade
        )

    def _promover(self, recovery_id: str, entry: dict) -> BackupSummary:
        staging = entry["staging"]
        if staging.discarded:
            raise RecoveryDiscarded("esta recuperação foi descartada")
        summary: BackupSummary = entry["summary"]
        workspace_id = WorkspaceId.parse(summary.workspace_id)

        staged_workspace = staging.workspaces.get(workspace_id)
        if staged_workspace is None:
            raise RecoveryNotPromotable("o staging não contém o workspace verificado")
        staged_revisions = tuple(staging.revisions.list_workspace(workspace_id))
        if len(staged_revisions) != summary.artifact_revisions:
            raise RecoveryNotPromotable("o staging divergiu da verificação")
        if any(item.artifact_kind == _AI_COST_LEDGER_KIND for item in staged_revisions):
            raise RecoveryNotPromotable(
                "a autoridade de custo de IA não pode ser promovida neste armazenamento"
            )

        # RETOMADA de promoção interrompida.
        #
        # Não há transação entre o SQLite e o sistema de arquivos, e o
        # armazenamento é append-only por design (a FK é `ON DELETE RESTRICT`, não
        # existe remoção de workspace). Uma falha depois das primeiras escrituras
        # vivas deixava, portanto, uma perícia parcialmente restaurada que
        # recusava toda retentativa com 409 — sem saída pelo produto.
        #
        # A retomada é deliberadamente ESTREITA: só continua quando ESTA MESMA
        # sessão já havia começado a promover e o que está vivo é comprovadamente
        # um PREFIXO EXATO do que foi verificado (mesma identidade, mesmo nome,
        # mesma data, revisões idênticas em ordem e checksum). Qualquer outra
        # coisa continua sendo conflito: `NO_SILENT_OVERWRITE` segue valendo, e
        # uma perícia viva alheia nunca é tocada.
        # A autoridade da retomada é DURÁVEL: mora no journal de promoção, dentro
        # da raiz de staging quarentenada. Um booleano em memória não sobrevive ao
        # crash — que é justamente quando a promoção precisa ser retomável.
        transacao = staging.ler_transacao()
        live_workspace = self.workspaces.get(workspace_id)
        live_revisions: tuple = ()
        if live_workspace is not None:
            if not self._transacao_autoriza(transacao, staging, summary):
                raise WorkspaceRecoveryConflict("já existe uma perícia com esta identidade")
            live_revisions = tuple(self.revisions.list_workspace(workspace_id))
            prefixo_valido = (
                live_workspace.name == staged_workspace.name
                and live_workspace.created_at == staged_workspace.created_at
                and len(live_revisions) <= len(staged_revisions)
                and all(
                    vivo.revision_id == staged.revision_id
                    and vivo.artifact_kind == staged.artifact_kind
                    and vivo.artifact_id == staged.artifact_id
                    and vivo.checksum_sha256 == staged.checksum_sha256
                    for vivo, staged in zip(live_revisions, staged_revisions)
                )
            )
            if not prefixo_valido:
                raise WorkspaceRecoveryConflict("já existe uma perícia com esta identidade")

        staged_private = ()
        if self.private_contents is not None:
            staged_private = tuple(staging.private_contents.list_all(workspace_id))
        elif staging.private_contents.list_all(workspace_id):
            raise RecoveryNotPromotable("o armazenamento vivo não aceita conteúdo privado")
        if len(staged_private) != summary.private_contents:
            raise RecoveryNotPromotable("o staging divergiu da verificação")

        # ORDEM DE ESCRITA — o conteúdo privado vem POR ÚLTIMO, de propósito.
        #
        # Tentou-se o inverso (privado primeiro, para que a falha de I/O mais
        # provável ocorresse antes de qualquer linha viva). Foi PIOR: uma promoção
        # que falha depois de gravar parte do conteúdo privado deixa cópia INTEGRAL
        # e em claro do material sigiloso no armazenamento VIVO — onde nada a
        # referencia, nenhuma rota a enxerga e nenhuma coleta a remove (a coleta de
        # staging só alcança a raiz de recuperação). E a retentativa não recupera:
        # um `store()` abortado já registrou o prefixo em `_known_prefixes`, então
        # a segunda tentativa levanta `RepositoryConflict` enquanto `open_content`
        # devolve `None` — aquele conteúdo fica permanentemente ingravável.
        #
        # Com o privado por último, uma falha nas fases anteriores não deposita
        # nada no armazenamento permanente. Permanece a janela em que a falha
        # ocorre DEPOIS das linhas vivas; ela é tratada como restauração
        # incompleta e reportada, nunca silenciada.
        # Journal ANTES da primeira mutação viva: se o processo morrer daqui em
        # diante, a reabertura reconhece a promoção interrompida e a retoma.
        staging.gravar_transacao(
            {
                "recovery_id": recovery_id,
                "backup_sha256": summary.backup_sha256,
                "workspace_id": summary.workspace_id,
                "staging_identity": staging.identidade,
                "workspace_name": staged_workspace.name,
                "workspace_created_at": staged_workspace.created_at,
                "revisions": [
                    [r.revision_id, r.artifact_kind, r.artifact_id, r.checksum_sha256]
                    for r in staged_revisions
                ],
                "private_contents": sorted(
                    [str(m.content_id), m.checksum_sha256] for m in staged_private
                ),
                "phase": PROMOTING,
                "version": JOURNAL_VERSION,
            }
        )
        if live_workspace is None:
            self.workspaces.create(
                PericiaWorkspace(workspace_id, staged_workspace.name, staged_workspace.created_at)
            )
        for record in staged_revisions[len(live_revisions):]:
            if type(record) is not ArtifactRevision:
                raise RepositoryIntegrityError("revisão restaurada inválida")
            self.revisions.append(
                workspace_id=workspace_id,
                artifact_kind=record.artifact_kind,
                artifact_id=record.artifact_id,
                revision_id=record.revision_id,
                created_at=record.created_at,
                payload=thaw_payload(record.payload),
            )
        ja_gravados = {
            item.content_id for item in self.private_contents.list_all(workspace_id)
        } if self.private_contents is not None else set()
        for metadata in staged_private:
            if metadata.content_id in ja_gravados:
                continue
            with staging.private_contents.open_content(workspace_id, metadata.content_id) as opened:
                content = opened.stream.read()
            try:
                self.private_contents.store(metadata, content)
            except RepositoryConflict:
                # A identidade tem uma importação abortada desta mesma
                # recuperação: `store()` a recusa para sempre, mas a continuação
                # exata converge. O digest esperado é o do pacote VERIFICADO —
                # essa é a autoridade que impede reuso de identidade com
                # conteúdo diferente.
                self.private_contents.continue_exact_recovery_write(
                    metadata, content, expected_sha256=metadata.checksum_sha256
                )

        promoted = tuple(self.revisions.list_workspace(workspace_id))
        if len(promoted) != len(staged_revisions):
            raise RepositoryIntegrityError("a reabertura do workspace promovido divergiu")
        for live, staged in zip(promoted, staged_revisions, strict=True):
            if (
                live.artifact_kind != staged.artifact_kind
                or live.artifact_id != staged.artifact_id
                or live.revision_id != staged.revision_id
                or live.created_at != staged.created_at
                or live.checksum_sha256 != staged.checksum_sha256
            ):
                raise RepositoryIntegrityError("a reabertura do workspace promovido divergiu")

        entry["promoted"] = True
        # Marca a fase antes de recolher: se a remoção falhar, a varredura de
        # reabertura precisa saber que aqui não há mais nada a retomar.
        try:
            transacao = staging.ler_transacao()
            if type(transacao) is dict:
                staging.gravar_transacao({**transacao, "phase": PROMOTED})
        except Exception:
            pass
        _encerrar_staging(staging)
        self.sessions.drop(recovery_id)
        return summary
