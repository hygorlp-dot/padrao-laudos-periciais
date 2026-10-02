"""Ciclo de vida da ingestao de documentos do caso em duas fases (#266).

FASE 1 (aceite duravel) grava os bytes da fonte e responde. FASE 2 (derivacao:
extracao/OCR, inventario PJe, metadados) roda neste executor local, que pertence
ao runtime e nao a conexao do navegador. Um timeout de transporte deixa de poder
significar "a operacao falhou" depois que a fonte ja foi aceita.

A autoridade de "pronto" continua sendo a revisao PROCESS_METADATA_EXTRACTION,
gravada por ultimo pela derivacao. Este modulo so acrescenta o que o banco nao
tem como saber: se ha uma derivacao em curso agora e se a ultima tentativa nesta
execucao do produto falhou. Nada aqui e persistido; depois de um reinicio, bytes
sem metadados sao INTERRUPTED e voltam a PROCESSING somente por pedido explicito.

Um unico worker: OCR e CPU-bound e local, e serializar evita dois OCR do mesmo
documento disputando a mesma fonte. Nenhuma fila externa, nenhum egress.
"""
from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable

from .ports import PrivateContentNotFound

READY = "READY"
PROCESSING = "PROCESSING"
FAILED = "FAILED"
INTERRUPTED = "INTERRUPTED"
PROCESSING_STATES = (READY, PROCESSING, FAILED, INTERRUPTED)


class DerivationCancelled(Exception):
    """O runtime esta fechando: a derivacao para antes de qualquer escrita."""


def _key(record) -> tuple[str, str]:
    return str(record.workspace_id), str(record.content_id)


class _Job:
    __slots__ = ("record", "done")

    def __init__(self, record):
        self.record = record
        self.done = threading.Event()


class DocumentDerivationQueue:
    """Executor local, de um worker, das derivacoes de fontes ja aceitas."""

    def __init__(self, derive: Callable[[object, Callable[[], bool]], None], *, stop_wait_seconds: float = 5.0):
        if not callable(derive):
            raise TypeError("derivacao invalida")
        self._derive = derive
        self._stop_wait_seconds = stop_wait_seconds
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        self._pending: deque[_Job] = deque()
        self._jobs: dict[tuple[str, str], _Job] = {}
        self._failed: set[tuple[str, str]] = set()
        self._stopping = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        with self._lock:
            if self._stopping:
                raise RuntimeError("executor de derivacao fechado")
            if self._thread is not None:
                return
            self._thread = threading.Thread(target=self._run, name="document-derivation", daemon=True)
            self._thread.start()

    def close(self) -> None:
        with self._lock:
            self._stopping = True
            self._wake.notify_all()
            thread = self._thread
        if thread is not None:
            # Espera limitada: um OCR longo nao pode prender o encerramento. A
            # derivacao checa `_should_continue` antes de cada escrita, entao um
            # worker que sobreviva a esta espera nao grava nada; a fonte fica
            # INTERRUPTED (bytes sem metadados) e o reinicio oferece nova tentativa.
            thread.join(self._stop_wait_seconds)

    def _should_continue(self) -> bool:
        with self._lock:
            return not self._stopping

    def submit(self, record) -> threading.Event:
        """Agenda a derivacao; pedidos repetidos da mesma fonte compartilham o job."""
        key = _key(record)
        with self._lock:
            if self._stopping or self._thread is None:
                raise RuntimeError("executor de derivacao indisponivel")
            job = self._jobs.get(key)
            if job is not None:
                return job.done
            job = _Job(record)
            self._jobs[key] = job
            self._failed.discard(key)
            self._pending.append(job)
            self._wake.notify()
            return job.done

    def state_of(self, record) -> str | None:
        """PROCESSING, FAILED ou None (o banco decide entre READY e INTERRUPTED)."""
        key = _key(record)
        with self._lock:
            if key in self._jobs:
                return PROCESSING
            if key in self._failed:
                return FAILED
        return None

    def _run(self) -> None:
        while True:
            with self._lock:
                while not self._pending and not self._stopping:
                    self._wake.wait()
                if self._stopping:
                    # Jobs ainda nao iniciados nao rodam: sem metadados, a fonte
                    # sera INTERRUPTED no proximo inicio.
                    for job in self._pending:
                        self._jobs.pop(_key(job.record), None)
                        job.done.set()
                    self._pending.clear()
                    return
                job = self._pending.popleft()
            failed = False
            try:
                self._derive(job.record, self._should_continue)
            except DerivationCancelled:
                pass
            except BaseException:  # noqa: BLE001 -- vira FAILED; o worker nunca morre por um job
                # Nem um SystemExit vindo de uma dependencia pode matar o unico
                # worker: com ele morto, todo job seguinte ficaria PROCESSING
                # para sempre.
                failed = True
            finally:
                with self._lock:
                    self._jobs.pop(_key(job.record), None)
                    if failed:
                        self._failed.add(_key(job.record))
                job.done.set()


class CaseDocumentIngestion:
    """Aceite duravel + derivacao no executor local, com estado honesto por fonte.

    `grace_seconds` e o quanto a requisicao espera a derivacao antes de responder
    "aceito, processando": tem de ser menor que o timeout do transporte, para que
    a resposta sempre chegue antes dele e um documento pequeno continue saindo
    pronto na mesma resposta.
    """

    def __init__(self, importer, queue: DocumentDerivationQueue, documents, *, grace_seconds: float):
        if not all(callable(getattr(importer, name, None)) for name in ("accept", "is_derived", "needs_derivation")):
            raise TypeError("importador de documentos invalido")
        if type(queue) is not DocumentDerivationQueue:
            raise TypeError("executor de derivacao invalido")
        if isinstance(grace_seconds, bool) or not isinstance(grace_seconds, (int, float)) or not 0 <= grace_seconds <= 60:
            raise ValueError("janela de espera da derivacao invalida")
        self._importer = importer
        self._queue = queue
        self._documents = documents
        self._grace_seconds = float(grace_seconds)

    def state(self, record) -> str:
        running = self._queue.state_of(record)
        if running == PROCESSING:
            return PROCESSING
        # Autoridade persistida: so os metadados dizem "pronto". Uma falha em
        # memoria (por exemplo, no reparo de um inventario ausente) nunca
        # contradiz metadados ja gravados.
        if self._importer.is_derived(record):
            return READY
        return FAILED if running == FAILED else INTERRUPTED

    def _derive_within_grace(self, record) -> str:
        if not self._importer.needs_derivation(record):
            # Fonte pronta e completa: nada a agendar, nada a esperar atras de
            # outra derivacao longa no worker unico.
            return READY
        self._queue.submit(record).wait(self._grace_seconds)
        return self.state(record)

    def import_document(self, *, workspace_id, original_filename, content, media_type):
        """FASE 1 sincrona; FASE 2 agendada. Devolve (fonte, criada, estado)."""
        record, created = self._importer.accept(
            workspace_id=workspace_id, original_filename=original_filename,
            content=content, media_type=media_type,
        )
        return record, created, self._derive_within_grace(record)

    def states(self, workspace_id):
        return tuple((record, self.state(record)) for record in self._documents.execute(workspace_id))

    def retry(self, workspace_id, content_id):
        """Nova tentativa explicita sobre a MESMA fonte: nenhum byte e reenviado."""
        for record in self._documents.execute(workspace_id):
            if str(record.content_id) == str(content_id):
                return record, self._derive_within_grace(record)
        raise PrivateContentNotFound("documento do caso não encontrado")
