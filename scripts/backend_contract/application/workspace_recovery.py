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


class BackupTooLarge(RepositoryError):
    """O pacote produzido excede o que ESTA instalação consegue reingerir.

    `SELF_PRODUCED_BACKUP MUST_BE REINGESTIBLE`. Entregar 200 num arquivo que a
    própria recuperação recusaria depois é vender segurança falsa: o usuário só
    descobriria no dia em que precisasse restaurar. O formato atual do pacote
    (JSON com conteúdo em base64) é materializado por inteiro para verificar, e
    é essa materialização que fixa o teto — levantar o número sem trocar o
    formato apenas move a falha para exaustão de memória.
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


#: Teto de ingestão da recuperação; ver `BackupTooLarge`.
MAX_BACKUP_PACKAGE_BYTES = 134_217_728

_QUARENTENA = "RECOVERY_NOT_PROMOTABLE"
_QUARENTENA_PAYLOAD = b"RECOVERY_STAGING_V1\n"


class RecoveryRetained(RepositoryError):
    """O descarte não removeu tudo; a quarentena foi mantida sobre o resíduo."""


_JOURNAL = "PROMOTION_TRANSACTION_V1"
_IDENTIDADE = "STAGING_IDENTITY_V1"


def _material_remanescente(raiz: Path) -> list[Path]:
    """Tudo o que não é marcador de quarentena nem journal da própria raiz.

    O journal é AUTORIDADE, não material: sai depois de provado que o conteúdo
    privado sumiu, na mesma ordem da quarentena. Apagá-lo junto com o material
    permitia perder a prova de retomada e preservar o sigiloso — exatamente a
    prioridade invertida.
    """
    restante = []
    for caminho in raiz.rglob("*"):
        if caminho.is_dir():
            continue
        if caminho.parent == raiz and caminho.name in (_QUARENTENA, _JOURNAL, _IDENTIDADE):
            continue
        restante.append(caminho)
    return restante


_JOURNAL_ILEGIVEL = object()


def _journal_bruto(raiz: Path):
    """Lê o journal SEM abrir o staging. `None` = não há; sentinela = ilegível."""
    try:
        bruto = (raiz / _JOURNAL).read_bytes()
    except FileNotFoundError:
        return None
    except OSError:
        return _JOURNAL_ILEGIVEL
    try:
        registro = json.loads(bruto.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _JOURNAL_ILEGIVEL
    return registro if type(registro) is dict else _JOURNAL_ILEGIVEL


def _tem_journal(staging: object) -> bool:
    """Há autoridade durável de promoção nesta raiz?

    FAIL-CLOSED: journal ilegível conta como PRESENTE. Tratar erro de leitura
    como ausência autorizaria justamente a destruição que este predicado existe
    para impedir.
    """
    try:
        return staging.ler_transacao() is not None
    except Exception:
        return True


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
    marcador = raiz / _QUARENTENA
    try:
        if marcador.read_bytes() != _QUARENTENA_PAYLOAD:
            return
    except OSError:
        return

    for caminho in _material_remanescente(raiz):
        try:
            caminho.unlink()
        except OSError:
            pass
    for diretorio in sorted(
        (p for p in raiz.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True
    ):
        try:
            diretorio.rmdir()
        except OSError:
            pass

    residuo = _material_remanescente(raiz)
    if residuo:
        # Quarentena PRESERVADA sobre o resíduo: nunca reportar sucesso com
        # material sigiloso ainda em disco.
        if exigir_remocao:
            raise RecoveryRetained("a recuperação preparada não pôde ser removida por completo")
        return
    try:
        (raiz / _JOURNAL).unlink(missing_ok=True)
        (raiz / _IDENTIDADE).unlink(missing_ok=True)
        marcador.unlink()
        raiz.rmdir()
    except OSError:
        # Não conseguiu fechar a raiz: restabelece a quarentena para que ela
        # jamais possa ser confundida com armazenamento ativo.
        try:
            if not marcador.exists():
                marcador.write_bytes(_QUARENTENA_PAYLOAD)
        except OSError:
            pass
        if exigir_remocao:
            raise RecoveryRetained("a recuperação preparada não pôde ser removida por completo")


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
        if len(payload) > MAX_BACKUP_PACKAGE_BYTES:
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

    def snapshot(self) -> tuple[tuple[str, dict], ...]:
        """Cópia rasa do registro, para varredura FORA do lock.

        Ler journal é I/O de disco e não pode acontecer sob o mutex que
        serializa `claim`.
        """
        with self._mutex:
            return tuple(self._sessions.items())

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
    workspaces: object = None
    new_recovery_id: object = uuid4

    def _promovibilidade(self, backup, staging) -> tuple[bool, str | None]:
        """Condições canônicas de promoção JÁ conhecidas no staging.

        `VERIFIED != PROMOTABLE`: dizer `promotable: True` e recusar segundos
        depois é mentira de contrato. Só afirma o que consegue sustentar.
        """
        workspace_id = WorkspaceId.parse(str(backup.workspace.workspace_id))
        if self.workspaces is not None and self.workspaces.get(workspace_id) is not None:
            transacao = None
            try:
                transacao = staging.ler_transacao()
            except Exception:
                transacao = None
            if type(transacao) is not dict:
                return False, "ja_existe_pericia_com_esta_identidade"
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
            if entry.get("state") not in (STAGED, FAILED_RECOVERABLE):
                continue
            staging = entry["staging"]
            if not self._journal_desta_promocao(staging, digest, workspace_id):
                continue
            self.sessions.settle(recovery_id, FAILED_RECOVERABLE)
            summary = _summary(backup, digest)
            entry["summary"] = summary
            promovivel, motivo = self._promovibilidade(backup, staging)
            return RecoverySession(recovery_id, summary, promovivel, motivo)

        if self.open_staging is None:
            return None
        base = Path(self.staging_root)
        try:
            candidatas = sorted(p for p in base.iterdir() if p.is_dir())
        except OSError:
            return None
        for raiz in candidatas:
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
            if registro is _JOURNAL_ILEGIVEL:
                raise RecoveryStageFailed(
                    "há uma promoção interrompida com journal ilegível nesta instalação"
                )
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
            self.sessions.register(recovery_id, staging, summary)
            self.sessions.settle(recovery_id, FAILED_RECOVERABLE)
            promovivel, motivo = self._promovibilidade(backup, staging)
            return RecoverySession(recovery_id, summary, promovivel, motivo)
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
        try:
            if (raiz / _QUARENTENA).read_bytes() != _QUARENTENA_PAYLOAD:
                continue
        except OSError:
            continue
        registro = _journal_bruto(raiz)
        if registro is _JOURNAL_ILEGIVEL:
            continue
        if registro is not None and registro.get("phase") != PROMOTED:
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


@dataclass(frozen=True, slots=True)
class DiscardWorkspaceRecovery:
    sessions: WorkspaceRecoverySessions

    def execute(self, recovery_id: str) -> str:
        # Reivindica DISCARDING antes de tocar em qualquer coisa: se houver uma
        # promoção em voo, quem perde a corrida recebe erro honesto em vez de
        # fechar o staging sob os pés dela.
        entry = self.sessions.claim(recovery_id, (STAGED, FAILED_RECOVERABLE), DISCARDING)
        # `FAILED_RECOVERABLE` COM journal NÃO é descartável: o journal é a única
        # prova durável que permite concluir uma promoção já iniciada no vivo.
        if _tem_journal(entry["staging"]):
            self.sessions.settle(recovery_id, FAILED_RECOVERABLE)
            raise RecoveryPromotionIncomplete(
                "esta promoção já começou a gravar e precisa ser retomada"
            )
        try:
            _encerrar_staging(entry["staging"], exigir_remocao=True)
        except BaseException:
            # A sessão CONTINUA existindo: o usuário precisa poder tentar de novo
            # depois de liberar o que segurava o arquivo (antivírus, indexador).
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
        except BaseException as exc:
            self.sessions.settle(recovery_id, FAILED_RECOVERABLE)
            # Journal presente = a primeira mutação viva JÁ aconteceu. Reportar
            # isso como "armazenamento indisponível" faria o produto dizer "nada
            # mudou" no exato instante em que gravou uma perícia parcial.
            if isinstance(exc, Exception) and _tem_journal(entry["staging"]):
                raise RecoveryPromotionIncomplete(
                    "a promoção foi interrompida depois de começar a gravar"
                ) from exc
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
