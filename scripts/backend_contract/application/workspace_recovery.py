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

import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

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


def _encerrar_staging(staging: object) -> None:
    """Fecha os handles E REMOVE a raiz do disco.

    `RecoveryStaging.discard()` só fecha handles — a raiz permanece. Sem esta
    coleta, cada tentativa de recuperação deixaria no disco uma cópia INTEGRAL e
    em claro do conteúdo privado da perícia, para sempre, enquanto a UI afirma ao
    usuário que a descartou.

    A remoção só acontece sobre um diretório que se PROVA ser uma raiz de
    recuperação nossa: precisa conter o marcador de quarentena com o conteúdo
    canônico. Sem essa prova, nada é apagado.
    """
    try:
        raiz = Path(staging.root)
    except Exception:
        staging.discard()
        return
    staging.discard()
    marcador = raiz / "RECOVERY_NOT_PROMOTABLE"
    try:
        if marcador.read_bytes() != b"RECOVERY_STAGING_V1\n":
            return
    except OSError:
        return
    shutil.rmtree(raiz, ignore_errors=True)


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

    def execute(self, workspace_id: WorkspaceId) -> bytes:
        if type(workspace_id) is not WorkspaceId:
            raise TypeError("workspace_id inválido")
        if self.workspaces.get(workspace_id) is None:
            raise WorkspaceNotFound("workspace não encontrado")
        payload = self.create_backup.execute(workspace_id)
        if type(payload) is not bytes or not payload:
            raise RepositoryIntegrityError("pacote de backup inválido")
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

    __slots__ = ("_sessions", "_mutex")

    def __init__(self) -> None:
        self._sessions: dict[str, dict] = {}
        self._mutex = threading.Lock()

    def register(self, recovery_id: str, staging: object, summary: BackupSummary) -> None:
        with self._mutex:
            self._sessions[recovery_id] = {
                "staging": staging,
                "summary": summary,
                "state": STAGED,
            }

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
                if atual in (DISCARDING, DISCARDED):
                    raise RecoveryDiscarded("esta recuperação foi descartada")
                raise WorkspaceRecoveryConflict(
                    "esta recuperação já tem uma operação em andamento"
                )
            entry["state"] = destino
            return entry

    def settle(self, recovery_id: str, destino: str) -> None:
        with self._mutex:
            entry = self._sessions.get(recovery_id)
            if entry is not None:
                entry["state"] = destino

    def drop(self, recovery_id: str) -> None:
        with self._mutex:
            self._sessions.pop(recovery_id, None)

    def close_all(self) -> None:
        for entry in tuple(self._sessions.values()):
            staging = entry["staging"]
            try:
                # Uma promoção INTERROMPIDA não pode ser recolhida no
                # encerramento: a raiz quarentenada mais o journal SÃO a
                # autoridade durável que permite retomá-la depois. Recolher aqui
                # destruiria a evidência do crash e deixaria a perícia
                # meio-restaurada sem saída. Só fecha os handles.
                if staging.ler_transacao() is not None:
                    staging.close()
                    continue
            except Exception:
                pass
            try:
                _encerrar_staging(staging)
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
    new_recovery_id: object = uuid4

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
        self.sessions.register(recovery_id, staging, summary)
        return RecoverySession(recovery_id, summary)

    def _promocao_interrompida(self, backup, digest: str) -> RecoverySession | None:
        """Descobre no disco uma promoção DESTE pacote interrompida por crash.

        Autoridade durável = raiz quarentenada + journal de promoção. A sessão em
        memória é só cache: some no crash, e é justamente aí que a recuperação
        precisa continuar existindo. Reabrir a raiz interrompida é o que evita a
        perícia meio-restaurada permanente, sem exigir terminal.

        NUNCA promove sozinha: apenas volta a expor a recuperação como retomável;
        a promoção segue sendo ato humano explícito.
        """
        if self.open_staging is None:
            return None
        base = Path(self.staging_root)
        workspace_id = str(backup.workspace.workspace_id)
        try:
            candidatas = sorted(p for p in base.iterdir() if p.is_dir())
        except OSError:
            return None
        for raiz in candidatas:
            marcador = raiz / "RECOVERY_NOT_PROMOTABLE"
            try:
                if marcador.read_bytes() != b"RECOVERY_STAGING_V1\n":
                    continue
            except OSError:
                continue
            try:
                staging = self.open_staging(raiz)
            except (RepositoryError, RepositoryIntegrityError, OSError):
                continue
            try:
                transacao = staging.ler_transacao()
                if (
                    type(transacao) is not dict
                    or transacao.get("backup_sha256") != digest
                    or transacao.get("workspace_id") != workspace_id
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
            self.sessions.register(recovery_id, staging, summary)
            self.sessions.settle(recovery_id, FAILED_RECOVERABLE)
            return RecoverySession(recovery_id, summary)
        return None


@dataclass(frozen=True, slots=True)
class DiscardWorkspaceRecovery:
    sessions: WorkspaceRecoverySessions

    def execute(self, recovery_id: str) -> str:
        # Reivindica DISCARDING antes de tocar em qualquer coisa: se houver uma
        # promoção em voo, quem perde a corrida recebe erro honesto em vez de
        # fechar o staging sob os pés dela.
        entry = self.sessions.claim(recovery_id, (STAGED, FAILED_RECOVERABLE), DISCARDING)
        try:
            _encerrar_staging(entry["staging"])
        except BaseException:
            self.sessions.settle(recovery_id, FAILED_RECOVERABLE)
            raise
        self.sessions.settle(recovery_id, DISCARDED)
        self.sessions.drop(recovery_id)
        return recovery_id


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
        try:
            return self._promover(recovery_id, entry)
        except BaseException:
            self.sessions.settle(recovery_id, FAILED_RECOVERABLE)
            raise

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
        _encerrar_staging(staging)
        self.sessions.drop(recovery_id)
        return summary
