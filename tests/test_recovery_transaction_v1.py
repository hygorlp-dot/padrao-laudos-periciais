"""#183 — transação de recuperação durável, serializável e idempotente.

REDs escritos APÓS a nota de arquitetura (`docs/arquitetura/recuperacao-transacional-v1.md`)
e ANTES do reparo, com `AUTONOMOUS_CAUSAL_REPAIR_LOOP_V1` acionado: a classe causal
`PARTIAL_PROMOTION_NOT_RECOVERABLE` sobreviveu a três reparos locais de ordem de
escrita e de retomada em memória.

O que estes testes travam:

    PROCESS MEMORY         != DURABLE PROMOTION AUTHORITY
    SQLITE PREFIX COMPLETE != PRIVATE STORE COMMIT COMPLETE
    PRIVATE list_all()     != PRIVATE _known_prefixes

Invariante governante: toda transição autoritativa interrompida é ATÔMICA ou
DURAVELMENTE RETOMÁVEL. Uma promoção falha nunca pode deixar workspace visível +
revisões/privado parciais + nenhuma sessão válida + nenhuma rota de continuação.
"""

from __future__ import annotations

import json
import hashlib
import os
import stat
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_backup_recovery_reachability_v1 import (
    _api,
    _json as _local_json,
    _pdf_grande,
    _runtime,
    _slow_request,
    _workspace_with_material,
)


pytestmark = pytest.mark.skipif(
    os.name != "nt",
    reason="the positive mutable Recovery V1 matrix is Windows-only",
)

RECOVERY_OPERATION_TIMEOUT_SECONDS = 30.0


def _json(runtime, method, path, *, value=None, body=None, headers=None, timeout=RECOVERY_OPERATION_TIMEOUT_SECONDS):
    """Use a bounded operation deadline for fsync-heavy Recovery commands."""

    return _local_json(
        runtime,
        method,
        path,
        value=value,
        body=body,
        headers=headers,
        timeout=timeout,
    )


def _pacote(runtime, workspace_id):
    status, _headers, package = _api(runtime, "POST", f"/v1/workspaces/{workspace_id}/backup")
    assert status == 200
    return package


def _directory_reparse(link, target):
    if os.name != "nt":
        link.symlink_to(target, target_is_directory=True)
        return
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert created.returncode == 0, (created.stdout, created.stderr)


def _remove_directory_reparse(link: Path) -> None:
    """Remove somente o link/junction sintético, nunca percorre seu target."""

    if not os.path.lexists(link):
        return
    if link.is_symlink():
        link.unlink()
    elif getattr(link, "is_junction", lambda: False)():
        os.rmdir(link)


class _EmptyScandir:
    """Context manager minimo para REDs POSIX sem depender do host Windows."""

    def __enter__(self):
        return iter(())

    def __exit__(self, _exc_type, _exc_value, _traceback):
        return False


def _external_tree_sha256(root: Path) -> str:
    """Oracle independente: nomes, tipos e bytes do alvo externo."""

    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        details = os.lstat(path)
        digest.update(details.st_mode.to_bytes(8, "big", signed=False))
        if path.is_file():
            payload = path.read_bytes()
            digest.update(len(payload).to_bytes(8, "big"))
            digest.update(payload)
    return digest.hexdigest()


@pytest.mark.parametrize(
    ("state", "disposition", "discoverable", "allowed"),
    (
        ("STAGED", None, True, ("PROMOTE", "DISCARD")),
        ("PROMOTING", None, True, ()),
        ("FAILED_RECOVERABLE", None, True, ("ABANDON",)),
        ("RECOVERY_UNRESUMABLE", None, True, ("ABANDON",)),
        ("PROMOTED", None, False, ()),
        ("DISCARDING", None, True, ()),
        ("DISCARDED", None, False, ()),
        ("RECOVERY_RETAINED", "DISCARD", True, ("RETRY_DISCARD",)),
        ("RECOVERY_RETAINED", "ABANDON", True, ("RETRY_ABANDON",)),
        ("RECOVERY_RETAINED", "COLLECT", True, ("RETRY_ABANDON",)),
    ),
)
def test_matriz_estado_comando_expoe_somente_acoes_seguras(tmp_path, state, disposition, discoverable, allowed):
    """Cada estado tem saída explícita ou é terminal/em-voo sem comando concorrente."""
    from scripts.backend_contract.application.workspace_recovery import (
        ListWorkspaceRecoveries,
        WorkspaceRecoverySessions,
    )

    recovery_id = "00000000-0000-4000-8000-000000000001"
    sessions = WorkspaceRecoverySessions()
    sessions.register(
        recovery_id,
        None,
        None,
        state=state,
        root=tmp_path / f"recovery-{recovery_id}",
        disposition=disposition,
    )
    listed = ListWorkspaceRecoveries(sessions).execute()
    assert bool(listed) is discoverable
    if discoverable:
        assert listed[0].state == state
        assert listed[0].allowed_actions == allowed


def _origem_com_dois_privados(tmp_path, nome="origem"):
    """Perícia com DOIS conteúdos privados — é preciso que a falha caia no 2º."""
    runtime = _runtime(tmp_path, nome)
    try:
        workspace_id, primeiro = _workspace_with_material(runtime, tmp_path, name="Caso duplo")
        # PRECISA ser um conteúdo DISTINTO: o intake deduplica por checksum e
        # devolveria 200 (já existe) em vez de 201, deixando um só privado.
        segundo_pdf = _pdf_grande(tmp_path / f"segundo-{workspace_id}.pdf", 40_000)
        status, segundo = _json(
            runtime,
            "POST",
            f"/v1/workspaces/{workspace_id}/materials",
            body=segundo_pdf.read_bytes(),
            headers={"Content-Type": "application/pdf", "X-Document-Filename": "segundo.pdf"},
        )
        assert status == 201, segundo
        return workspace_id, (primeiro, segundo), _pacote(runtime, workspace_id)
    finally:
        runtime.close()


class _FalhaAposIntent:
    """Injeta falha DEPOIS do registro do intent, durante a gravação do conteúdo.

    É a janela exata do defeito: `store()` já pôs o prefixo em `_known_prefixes`
    (que é o universo que ele consulta para recusar) mas o conteúdo nunca entra em
    `_committed` (que é o universo que `list_all`/`open_content` enxergam).
    """

    def __init__(self, falhar_na_chamada=1):
        self._alvo = falhar_na_chamada
        self._n = 0
        self.disparou = False

    def __enter__(self):
        from scripts.backend_contract.infrastructure import private_filesystem

        self._modulo = private_filesystem
        self._original = private_filesystem._write_fsynced

        def _write(destino, dados, **kwargs):
            if destino.name.endswith(".content"):
                self._n += 1
                if self._n == self._alvo:
                    self.disparou = True
                    raise OSError(5, "falha de I/O transitória")
            return self._original(destino, dados, **kwargs)

        private_filesystem._write_fsynced = _write
        return self

    def __exit__(self, *exc):
        self._modulo._write_fsynced = self._original
        return False


def _stage(runtime, package):
    status, staged = _json(
        runtime,
        "POST",
        "/v1/recovery/staging",
        body=package,
        headers={"Content-Type": "application/octet-stream"},
    )
    return status, staged


def _promote(runtime, recovery_id):
    return _json(runtime, "POST", f"/v1/recovery/{recovery_id}/promote", value={"confirm": True})


def _materiais(runtime, workspace_id):
    status, docs = _json(runtime, "GET", f"/v1/workspaces/{workspace_id}/materials")
    if status != 200:
        return None
    return docs["items"]


# ------------------------------------------------------------------ A + B


def test_promocao_interrompida_na_perna_privada_retoma_na_mesma_sessao(tmp_path):
    """RED A — falha do store privado APÓS registro de intent deve ser retomável.

    Hoje a retomada mede progresso por `list_all()` (=`_committed`) enquanto o
    `store()` recusa por `_known_prefixes`. São universos distintos: o conteúdo
    abortado é invisível para a retomada e impossível de regravar, então aquele
    `content_id` fica permanentemente ingravável.
    """
    workspace_id, (primeiro, segundo), package = _origem_com_dois_privados(tmp_path)

    alvo = _runtime(tmp_path, "alvo")
    try:
        status, staged = _stage(alvo, package)
        assert status == 201, staged
        recovery_id = staged["recovery_id"]

        with _FalhaAposIntent(falhar_na_chamada=2) as falha:
            status, _erro = _promote(alvo, recovery_id)
        assert falha.disparou, "a injeção não alcançou a gravação de conteúdo privado"
        assert status >= 400, "a promoção deveria ter falhado"

        # A retomada — com o armazenamento já são — TEM de convergir.
        status, resultado = _promote(alvo, recovery_id)
        assert status == 200, f"promoção interrompida não converge na mesma sessão: {resultado}"

        itens = _materiais(alvo, workspace_id)
        assert itens is not None, "workspace promovido não é legível"
        assert len(itens) == 2, f"conteúdo privado incompleto após retomada: {len(itens)}/2"
        assert {i["content_id"] for i in itens} == {primeiro["content_id"], segundo["content_id"]}
        assert {i["checksum_sha256"] for i in itens} == {primeiro["checksum_sha256"], segundo["checksum_sha256"]}
    finally:
        alvo.close()


def test_promocao_interrompida_retoma_apos_reinicio_do_produto(tmp_path):
    """RED B — a autoridade de retomada precisa ser DURÁVEL.

    `promotion_started` vive num dict em memória: após reinício do processo a
    perícia parcial vira `409 WORKSPACE_CONFLICT` permanente, sem rota de remoção.
    Crash durante a promoção é exatamente quando o processo morre.
    """
    workspace_id, (primeiro, segundo), package = _origem_com_dois_privados(tmp_path, "origem-b")

    alvo = _runtime(tmp_path, "alvo-b")
    try:
        status, staged = _stage(alvo, package)
        assert status == 201, staged
        with _FalhaAposIntent(falhar_na_chamada=2) as falha:
            status, _erro = _promote(alvo, staged["recovery_id"])
        assert falha.disparou
        assert status >= 400
    finally:
        alvo.close()

    # === reinício do produto ===
    alvo2 = _runtime(tmp_path, "alvo-b")
    try:
        status, staged2 = _stage(alvo2, package)
        assert status == 201, staged2
        status, resultado = _promote(alvo2, staged2["recovery_id"])
        assert status == 200, f"promoção interrompida não é retomável após reinício: {resultado}"
        itens = _materiais(alvo2, workspace_id)
        assert itens is not None and len(itens) == 2, f"conteúdo privado incompleto após reinício: {itens and len(itens)}/2"
        assert {i["checksum_sha256"] for i in itens} == {primeiro["checksum_sha256"], segundo["checksum_sha256"]}
    finally:
        alvo2.close()


# ------------------------------------------------------------------ C + D


def _corrida(runtime, recovery_id, atraso_ms):
    """Dispara PROMOTE e, `atraso_ms` depois, DISCARD — a sequência que a UI permite."""
    resultados = {}
    pronto = threading.Barrier(2)

    def promover():
        pronto.wait()
        resultados["promote"] = _promote(runtime, recovery_id)[0]

    def descartar():
        pronto.wait()
        threading.Event().wait(atraso_ms / 1000)
        resultados["discard"] = _json(runtime, "POST", f"/v1/recovery/{recovery_id}/discard")[0]

    fios = [threading.Thread(target=promover), threading.Thread(target=descartar)]
    for f in fios:
        f.start()
    for f in fios:
        f.join(timeout=60)
    return resultados


def test_corrida_promote_discard_nunca_deixa_workspace_fantasma(tmp_path):
    """RED C — `STAGED → PROMOTING` e `STAGED → DISCARDING` são mutuamente exclusivas.

    Hoje o PROMOTE cria o workspace vivo, o DISCARD fecha o staging por baixo dele,
    o PROMOTE morre e sobra perícia fantasma com 0 materiais, permanentemente
    não-completável e sem rota de remoção. Sem nenhuma injeção de falha.
    """
    workspace_id, _materials, package = _origem_com_dois_privados(tmp_path, "origem-c")

    for atraso in (3, 12, 30, 70):
        alvo = _runtime(tmp_path, f"alvo-c{atraso}")
        try:
            status, staged = _stage(alvo, package)
            assert status == 201, staged
            resultados = _corrida(alvo, staged["recovery_id"], atraso)

            venceu_promote = resultados.get("promote") == 200
            venceu_discard = resultados.get("discard") == 200
            assert not (venceu_promote and venceu_discard), f"[{atraso}ms] PROMOTE e DISCARD venceram juntos: {resultados}"

            itens = _materiais(alvo, workspace_id)
            if venceu_promote:
                assert itens is not None and len(itens) == 2, f"[{atraso}ms] promoção venceu mas ficou parcial: {itens and len(itens)}/2"
            else:
                assert itens is None, f"[{atraso}ms] workspace FANTASMA: promote={resultados.get('promote')} discard={resultados.get('discard')} materiais={len(itens)}"
        finally:
            alvo.close()


def test_duas_promocoes_simultaneas_nao_mutam_concorrentemente(tmp_path):
    """RED D — no máximo uma promoção autoritativa; nunca dois 200."""
    workspace_id, _m, package = _origem_com_dois_privados(tmp_path, "origem-d")

    alvo = _runtime(tmp_path, "alvo-d")
    try:
        status, staged = _stage(alvo, package)
        assert status == 201, staged
        recovery_id = staged["recovery_id"]

        resultados = []
        pronto = threading.Barrier(2)

        def promover():
            pronto.wait()
            resultados.append(_promote(alvo, recovery_id)[0])

        fios = [threading.Thread(target=promover) for _ in range(2)]
        for f in fios:
            f.start()
        for f in fios:
            f.join(timeout=60)

        assert resultados.count(200) == 1, f"promoções concorrentes: {resultados}"
        itens = _materiais(alvo, workspace_id)
        assert itens is not None and len(itens) == 2, f"estado final inconsistente: {itens and len(itens)}/2"
    finally:
        alvo.close()


def test_mesmo_backup_em_staging_concorrente_publica_uma_unica_sessao(tmp_path):
    """RED A7 — idempotência também vale na janela anterior ao register."""
    _workspace_id, _m, package = _origem_com_dois_privados(tmp_path, "origem-d2")
    alvo = _runtime(tmp_path, "alvo-d2")
    try:
        pronto = threading.Barrier(2)
        resultados = []

        def preparar():
            pronto.wait()
            resultados.append(_stage(alvo, package))

        fios = [threading.Thread(target=preparar) for _ in range(2)]
        for fio in fios:
            fio.start()
        for fio in fios:
            fio.join(timeout=60)
        assert all(not fio.is_alive() for fio in fios)
        assert [status for status, _body in resultados] == [201, 201]
        assert len({body["recovery_id"] for _status, body in resultados}) == 1
        assert len(_raizes(tmp_path, "alvo-d2")) == 1
    finally:
        alvo.close()


def test_restage_concorrente_com_descarte_nunca_retorna_sessao_removida(tmp_path, monkeypatch):
    """RED A8 — `201` precisa nomear uma sessão viva ao linearizar a resposta."""
    from scripts.backend_contract.application.workspace_recovery import (
        StageWorkspaceRecovery,
    )

    _workspace_id, _m, package = _origem_com_dois_privados(tmp_path, "origem-stage-discard")
    alvo = _runtime(tmp_path, "alvo-stage-discard")
    release = threading.Event()
    try:
        status, primeiro = _stage(alvo, package)
        assert status == 201, primeiro
        recovery_id = primeiro["recovery_id"]
        entered = threading.Event()
        original = StageWorkspaceRecovery._promovibilidade

        def gated(self, backup, staging):
            entered.set()
            assert release.wait(timeout=20)
            return original(self, backup, staging)

        monkeypatch.setattr(StageWorkspaceRecovery, "_promovibilidade", gated)
        resultados = []
        fio = threading.Thread(target=lambda: resultados.append(_stage(alvo, package)))
        fio.start()
        assert entered.wait(timeout=20)

        discard_status, discard_body = _json(alvo, "POST", f"/v1/recovery/{recovery_id}/discard")
        assert discard_status == 200, discard_body
        release.set()
        fio.join(timeout=60)
        assert not fio.is_alive()

        stage_status, stage_body = resultados[0]
        assert stage_status == 201, stage_body
        list_status, listing = _json(alvo, "GET", "/v1/recovery")
        assert list_status == 200, listing
        assert stage_body["recovery_id"] in {item["recovery_id"] for item in listing["recoveries"]}
        assert stage_body["recovery_id"] != recovery_id
    finally:
        release.set()
        alvo.close()


def test_segundo_cleanup_concorrente_nao_inicia_dupla_remocao(tmp_path, monkeypatch):
    """Somente o primeiro claim alcança custódia e mutação destrutiva."""
    from scripts.backend_contract.application import workspace_recovery as wr

    _workspace_id, _materials, package = _origem_com_dois_privados(tmp_path, "concurrent-cleanup-source")
    target = _runtime(tmp_path, "concurrent-cleanup-target")
    status, staged = _stage(target, package)
    assert status == 201, staged
    recovery_id = staged["recovery_id"]
    root = tmp_path / ".concurrent-cleanup-target.sqlite3.recovery" / f"recovery-{recovery_id}"
    entered = threading.Event()
    release = threading.Event()
    original_custody = wr._adquirir_custodia_cleanup

    def gated_custody(path, *args, **kwargs):
        if Path(path) == root and not entered.is_set():
            entered.set()
            assert release.wait(timeout=20)
        return original_custody(path, *args, **kwargs)

    monkeypatch.setattr(wr, "_adquirir_custodia_cleanup", gated_custody)
    results = []
    worker = threading.Thread(target=lambda: results.append(_json(target, "POST", f"/v1/recovery/{recovery_id}/discard")))
    try:
        worker.start()
        assert entered.wait(timeout=20)
        second_status, second_body = _json(target, "POST", f"/v1/recovery/{recovery_id}/discard")
        assert second_status == 409, second_body
        assert second_body["error"]["code"] == "WORKSPACE_CONFLICT"

        release.set()
        worker.join(timeout=60)
        assert not worker.is_alive()
        assert results[0][0] == 200, results[0]
        assert not root.exists()
    finally:
        release.set()
        worker.join(timeout=60)
        target.close()


# ------------------------------------------------------------------ E


def test_descarte_com_handle_preso_nao_mente_e_permite_retentativa(tmp_path):
    """RED E — `QUARANTINE_OUTLIVES_PRIVATE_MATERIAL`.

    Hoje `rmtree(ignore_errors=True)` remove o marcador de quarentena ANTES do
    conteúdo privado e a API responde 200 mesmo retendo PDF em claro — invertendo
    exatamente a prioridade que a quarentena existe para garantir.
    """
    _workspace_id, _m, package = _origem_com_dois_privados(tmp_path, "origem-e")

    alvo = _runtime(tmp_path, "alvo-e")
    preso = None
    try:
        status, staged = _stage(alvo, package)
        assert status == 201, staged
        recovery_id = staged["recovery_id"]

        # ESCOPO: só a raiz de recuperação. O armazenamento privado VIVO da perícia
        # de origem tem seus próprios `.content` legítimos e não é resíduo.
        raizes = [p for p in tmp_path.rglob("*.recovery") if p.is_dir()]
        assert len(raizes) == 1, f"esperava uma raiz de recuperação, achei {raizes}"
        raiz = raizes[0]

        def _sigilo_no_staging():
            return [p for p in raiz.rglob("*.content") if p.exists()]

        conteudos = sorted(_sigilo_no_staging())
        assert conteudos, "staging não materializou conteúdo privado"
        preso = open(conteudos[0], "rb")  # antivírus/indexador segurando o arquivo

        status, corpo = _json(alvo, "POST", f"/v1/recovery/{recovery_id}/discard")
        residuo = _sigilo_no_staging()
        marcadores = list(raiz.rglob("RECOVERY_NOT_PROMOTABLE"))

        if status == 200:
            assert not residuo, f"DISCARD respondeu 200 retendo conteúdo privado em claro: {[p.name for p in residuo]}"
        else:
            # falhou honestamente: a quarentena TEM de sobreviver ao material
            assert marcadores, "descarte falhou mas removeu a quarentena antes do material privado"
            assert isinstance(corpo, dict)

        preso.close()
        preso = None

        # com o obstáculo removido, a retentativa TEM de concluir
        status, _ = _json(alvo, "POST", f"/v1/recovery/{recovery_id}/discard")
        assert status == 200, "retentativa de descarte não converge após liberar o handle"
        assert not _sigilo_no_staging(), "conteúdo privado sobreviveu ao descarte bem-sucedido"
    finally:
        if preso is not None:
            preso.close()
        alvo.close()


def test_descarte_retido_sobrevive_ao_reinicio_e_repete_a_mesma_decisao(tmp_path, monkeypatch):
    """Falha após disposition não perde a ação nem muda DISCARD para ABANDON."""
    from scripts.backend_contract.application import workspace_recovery as wr

    _workspace_id, _m, package = _origem_com_dois_privados(tmp_path, "origem-e2")
    alvo = _runtime(tmp_path, "alvo-e2")
    status, staged = _stage(alvo, package)
    assert status == 201, staged
    recovery_id = staged["recovery_id"]

    original = wr._remover_raiz_quarentenada

    def _retida(*_args, **_kwargs):
        raise wr.RecoveryRetained("falha injetada depois da decisão")

    monkeypatch.setattr(wr, "_remover_raiz_quarentenada", _retida)
    status, corpo = _json(alvo, "POST", f"/v1/recovery/{recovery_id}/discard")
    assert status == 409, corpo
    assert corpo["error"]["code"] == "RECOVERY_RETAINED"
    alvo.close()
    monkeypatch.setattr(wr, "_remover_raiz_quarentenada", original)

    reaberto = _runtime(tmp_path, "alvo-e2")
    try:
        status, corpo = _json(reaberto, "GET", "/v1/recovery")
        assert status == 200, corpo
        assert corpo["recoveries"][0]["state"] == "RECOVERY_RETAINED"
        assert corpo["recoveries"][0]["allowed_actions"] == ["RETRY_DISCARD"]
        status, corpo = _json(reaberto, "POST", f"/v1/recovery/{recovery_id}/discard")
        assert status == 200, corpo
        assert _raizes(tmp_path, "alvo-e2") == []
    finally:
        reaberto.close()


# ------------------------------------------------------------------ F + G


def test_upload_grande_tem_autoridade_unica_de_limite_e_spool(tmp_path):
    """RED F — teto ampliado e spool precisam vir da MESMA autoridade.

    O defeito era a divergência: `request_body_limit` dizia "binário grande" para
    `/v1/recovery/*`, enquanto `is_document_upload` decidia o spool e excluía
    essas rotas. A recuperação ganhou 128 MiB sem ganhar o spool.

    Sobre memória, o que este teste afirma é o que a medição sustenta: o
    TRANSPORTE não pode acrescentar mais de uma materialização do pacote. A
    amplificação restante (~4x medidos) é do parse do JSON canônico dentro de
    `VerifyWorkspaceBackup`, que recebe `bytes` por contrato — é propriedade do
    FORMATO de backup, não do transporte, e não seria honesto cobrá-la aqui.
    """
    import tracemalloc

    from scripts.backend_contract.infrastructure.productization import VerifyWorkspaceBackup

    origem = _runtime(tmp_path, "origem-f")
    try:
        status, workspace = _json(origem, "POST", "/v1/workspaces", value={"name": "Grande"})
        assert status == 201
        workspace_id = workspace["workspace_id"]
        pdf = _pdf_grande(tmp_path / "grande.pdf", 3_000_000)
        status, material = _slow_request(
            origem,
            "POST",
            f"/v1/workspaces/{workspace_id}/materials",
            body=pdf.read_bytes(),
            headers={"Content-Type": "application/pdf", "X-Document-Filename": "grande.pdf"},
        )
        assert status == 201, material
        status, package = _slow_request(origem, "POST", f"/v1/workspaces/{workspace_id}/backup", raw=True)
        assert status == 200
    finally:
        origem.close()

    tamanho = len(package)
    assert tamanho > 1_048_576, "o pacote precisa ultrapassar o teto JSON legado"

    alvo = _runtime(tmp_path, "alvo-f")
    try:
        from scripts.backend_contract.local_api.transport import LocalApi

        assert hasattr(LocalApi, "is_large_binary_upload"), "não existe autoridade única de upload binário grande"
        sonda = LocalApi.__new__(LocalApi)
        sonda._max_body_bytes = 1_048_576
        sonda._max_document_body_bytes = 134_217_728
        for rota in (
            "/v1/recovery/verify",
            "/v1/recovery/staging",
            f"/v1/workspaces/{workspace_id}/materials",
        ):
            grande = sonda.is_large_binary_upload("POST", rota)
            teto = sonda.request_body_limit("POST", rota)
            assert grande is True, f"{rota} deveria ser upload binário grande"
            assert teto == 134_217_728, f"{rota} não recebeu o teto ampliado"
        # rota JSON legada continua estreita e sem spool
        assert sonda.is_large_binary_upload("POST", "/v1/workspaces") is False
        assert sonda.request_body_limit("POST", "/v1/workspaces") == 1_048_576

        # custo do TRANSPORTE = uma materialização, não mais
        tracemalloc.start()
        b0 = tracemalloc.get_traced_memory()[1]
        VerifyWorkspaceBackup().execute(package)
        pico_direto = tracemalloc.get_traced_memory()[1] - b0
        tracemalloc.stop()

        tracemalloc.start()
        b1 = tracemalloc.get_traced_memory()[1]
        status, _resumo = _slow_request(
            alvo,
            "POST",
            "/v1/recovery/verify",
            body=package,
            headers={"Content-Type": "application/octet-stream"},
        )
        pico_http = tracemalloc.get_traced_memory()[1] - b1
        tracemalloc.stop()
        assert status == 200

        transporte = (pico_http - pico_direto) / tamanho
        assert transporte <= 1.5, f"o transporte acrescentou {transporte:.2f}x o pacote — mais de uma materialização (http {pico_http} B vs direto {pico_direto} B)"
    finally:
        alvo.close()


def test_backup_produzido_pelo_produto_e_sempre_reingerivel(tmp_path):
    """RED G — `SELF_PRODUCED_BACKUP MUST_BE REINGESTIBLE_BY_RECOVERY`.

    Não produzir em silêncio um backup que o próprio produto não restaura.
    """
    origem = _runtime(tmp_path, "origem-g")
    try:
        status, workspace = _json(origem, "POST", "/v1/workspaces", value={"name": "Reingestao"})
        assert status == 201
        workspace_id = workspace["workspace_id"]
        pdf = _pdf_grande(tmp_path / "g.pdf", 3_000_000)
        status, material = _slow_request(
            origem,
            "POST",
            f"/v1/workspaces/{workspace_id}/materials",
            body=pdf.read_bytes(),
            headers={"Content-Type": "application/pdf", "X-Document-Filename": "g.pdf"},
        )
        assert status == 201, material
        status, package = _slow_request(origem, "POST", f"/v1/workspaces/{workspace_id}/backup", raw=True)
        assert status == 200, "o produto recusou exportar"
    finally:
        origem.close()

    alvo = _runtime(tmp_path, "alvo-g")
    try:
        status, resumo = _slow_request(
            alvo,
            "POST",
            "/v1/recovery/verify",
            body=package,
            headers={"Content-Type": "application/octet-stream"},
        )
        assert status == 200, f"o produto não reingere o backup que ele mesmo produziu: {resumo}"
        status, staged = _slow_request(
            alvo,
            "POST",
            "/v1/recovery/staging",
            body=package,
            headers={"Content-Type": "application/octet-stream"},
        )
        assert status == 201, staged
        status, promovido = _slow_request(
            alvo,
            "POST",
            f"/v1/recovery/{staged['recovery_id']}/promote",
            value={"confirm": True},
        )
        assert status == 200, promovido
        assert _materiais(alvo, workspace_id), "perícia restaurada sem material"
    finally:
        alvo.close()


# ------------------------------------------------------------------ H


def test_staging_nunca_declara_promotable_quando_a_promocao_e_impossivel(tmp_path):
    """RED H — `VERIFIED != PROMOTABLE`.

    `promotable` é literal `True` em transport; restaurar na mesma máquina uma
    perícia que ainda existe (o caso mais comum) responde `promotable: True` e
    depois `409 WORKSPACE_CONFLICT`.
    """
    runtime = _runtime(tmp_path, "mesma-maquina")
    try:
        workspace_id, _ = _workspace_with_material(runtime, tmp_path, name="Ainda viva")
        package = _pacote(runtime, workspace_id)

        status, staged = _stage(runtime, package)
        assert status == 201, staged
        assert staged["promotable"] is False, "staging declarou promotable=True para identidade que já existe viva"

        status, _erro = _promote(runtime, staged["recovery_id"])
        assert status == 409, "a promoção deveria conflitar"
    finally:
        runtime.close()


# ------------------------------------------------------------------ J


def test_falha_em_qualquer_fase_nunca_deixa_estado_fantasma_permanente(tmp_path):
    """RED J — `FAILED_PROMOTION_MUST_NOT_LEAVE_UNRECOVERABLE_LIVE_PREFIX`.

    Para CADA fase material da promoção: falhar, reabrir o produto e exigir que o
    resultado seja retomada bem-sucedida OU aborto limpo. Nunca workspace visível
    + parcial + sem rota de continuação.
    """
    from scripts.backend_contract.infrastructure.sqlite import (
        SQLiteArtifactRevisionRepository,
        SQLiteWorkspaceRepository,
    )

    fases = ("workspace", "revisao", "privado")
    for fase in fases:
        workspace_id, (primeiro, segundo), package = _origem_com_dois_privados(tmp_path, f"origem-j-{fase}")
        alvo = _runtime(tmp_path, f"alvo-j-{fase}")
        criar = SQLiteWorkspaceRepository.create
        anexar = SQLiteArtifactRevisionRepository.append
        injecao = None
        try:
            status, staged = _stage(alvo, package)
            assert status == 201, staged

            if fase == "workspace":
                SQLiteWorkspaceRepository.create = lambda self, *a, **k: (_ for _ in ()).throw(OSError(5, "falha de I/O"))
            elif fase == "revisao":
                estado = {"n": 0}

                def _append(self, *a, **k):
                    estado["n"] += 1
                    if estado["n"] == 2:
                        raise OSError(5, "falha de I/O")
                    return anexar(self, *a, **k)

                SQLiteArtifactRevisionRepository.append = _append
            else:
                injecao = _FalhaAposIntent(falhar_na_chamada=2)
                injecao.__enter__()

            status, _erro = _promote(alvo, staged["recovery_id"])
            assert status >= 400, f"[{fase}] a promoção deveria ter falhado"
        finally:
            SQLiteWorkspaceRepository.create = criar
            SQLiteArtifactRevisionRepository.append = anexar
            if injecao is not None:
                injecao.__exit__(None, None, None)
            alvo.close()

        # === reabertura do produto ===
        alvo2 = _runtime(tmp_path, f"alvo-j-{fase}")
        try:
            itens = _materiais(alvo2, workspace_id)
            if itens is None:
                continue  # aborto limpo: nada vivo, retentativa trivialmente possível

            status, staged2 = _stage(alvo2, package)
            assert status == 201, staged2
            status, resultado = _promote(alvo2, staged2["recovery_id"])
            assert status == 200, f"[{fase}] estado fantasma permanente após reabertura: {len(itens)} materiais vivos, promoção {status} {resultado}"
            finais = _materiais(alvo2, workspace_id)
            assert finais is not None and len(finais) == 2, f"[{fase}] retomada não completou: {finais and len(finais)}/2"
            assert {i["checksum_sha256"] for i in finais} == {primeiro["checksum_sha256"], segundo["checksum_sha256"]}
        finally:
            alvo2.close()


# ------------------------------------------------------------------ K + L + M
# Achados da revisão terminal A4 sobre a classe causal reaberta pelo caminho que
# a INTERFACE oferece: a promoção parcial era retomável, mas a única saída que o
# produto expunha era a que destruía a autoridade de retomada.


def test_descarte_recusa_apagar_a_autoridade_de_retomada(tmp_path):
    """RED K — `FAILED_RECOVERABLE` COM journal NÃO é descartável.

    Uma promoção que já mutou o armazenamento vivo deixa journal na raiz
    quarentenada; esse journal é a ÚNICA prova durável que permite retomá-la.
    Descartar apaga a raiz inteira e trava a perícia viva incompleta para sempre
    — o armazenamento é append-only e não há remoção de workspace.
    """
    _origem, _ids, package = _origem_com_dois_privados(tmp_path, "k-origem")
    destino = _runtime(tmp_path, "k-destino")
    try:
        status, staged = _stage(destino, package)
        assert status == 201, staged
        recovery_id = staged["recovery_id"]

        with _FalhaAposIntent(falhar_na_chamada=2) as falha:
            status, corpo = _promote(destino, recovery_id)
        assert falha.disparou
        assert status >= 400, corpo

        # O produto DEVE recusar o descarte e dizer que a promoção está
        # incompleta, em vez de destruir a única rota de conclusão.
        status, corpo = _json(destino, "POST", f"/v1/recovery/{recovery_id}/discard")
        assert status == 409, corpo
        assert corpo["error"]["code"] == "RECOVERY_PROMOTION_INCOMPLETE"

        # E a retomada precisa continuar funcionando depois da recusa.
        status, corpo = _promote(destino, recovery_id)
        assert status == 200, corpo
        assert len(_materiais(destino, _origem)) == 2
    finally:
        destino.close()


def test_promocao_interrompida_apos_mutacao_viva_nao_se_diz_indisponivel(tmp_path):
    """RED L — falha DEPOIS da primeira mutação viva tem código próprio.

    Mapeá-la para `503 REPOSITORY_UNAVAILABLE` faz o produto dizer "armazenamento
    local indisponível, nada mudou" no exato instante em que uma perícia parcial
    foi gravada. Mentira de contrato é defeito, não texto.
    """
    _origem, _ids, package = _origem_com_dois_privados(tmp_path, "l-origem")
    destino = _runtime(tmp_path, "l-destino")
    try:
        status, staged = _stage(destino, package)
        assert status == 201, staged

        with _FalhaAposIntent(falhar_na_chamada=2) as falha:
            status, corpo = _promote(destino, staged["recovery_id"])
        assert falha.disparou
        assert status == 409, corpo
        assert corpo["error"]["code"] == "RECOVERY_PROMOTION_INCOMPLETE"
    finally:
        destino.close()


def test_reenviar_o_mesmo_pacote_reencontra_a_promocao_interrompida(tmp_path):
    """RED M — recarregar a tela e reenviar o pacote NÃO cria segundo staging.

    A redescoberta lia a raiz do disco com `open_or_provision`, que falha
    enquanto a sessão viva ainda mantém o store aberto; a exceção era engolida e
    o produto fabricava uma SEGUNDA cópia integral do material privado em claro,
    para então dizer "não promovível".
    """
    _origem, _ids, package = _origem_com_dois_privados(tmp_path, "m-origem")
    destino = _runtime(tmp_path, "m-destino")
    try:
        status, staged = _stage(destino, package)
        assert status == 201, staged
        primeiro = staged["recovery_id"]

        with _FalhaAposIntent(falhar_na_chamada=2) as falha:
            _promote(destino, primeiro)
        assert falha.disparou

        status, retomada = _stage(destino, package)
        assert status == 201, retomada
        assert retomada["recovery_id"] == primeiro
        assert retomada["promotable"] is True

        status, corpo = _promote(destino, retomada["recovery_id"])
        assert status == 200, corpo
        assert len(_materiais(destino, _origem)) == 2
    finally:
        destino.close()


# ------------------------------------------------------------------ N + O
# Raiz de staging órfã: material sigiloso em claro, quarentenado, e SEM nenhuma
# rota de produto para removê-lo. A quarentena deve sobreviver ao material —
# não o material sobreviver ao produto.


def _raizes(tmp_path, nome):
    base = tmp_path / f".{nome}.sqlite3.recovery"
    if not base.exists():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir())


def _cleanup_intent_path(tmp_path, nome, recovery_id):
    return tmp_path / f".{nome}.sqlite3.recovery" / f".recovery-cleanup-intent-{recovery_id}"


def _filesystem_identity_for(root):
    from scripts.backend_contract.application import workspace_recovery as wr

    custody = wr.RecoveryFilesystemCustody.acquire(root)
    assert custody is not None
    try:
        return custody.identity
    finally:
        custody.close()


def _cleanup_intent_payload(recovery_id, mode, *, root=None, identity=None):
    if identity is None:
        identity = _filesystem_identity_for(root) if root is not None else ((0, 0) if os.name == "nt" else (0, 0, stat.S_IFDIR))
    return json.dumps(
        {
            "filesystem_identity": {
                "parts": list(identity),
                "platform": os.name,
            },
            "mode": mode,
            "recovery_id": recovery_id,
            "root_name": f"recovery-{recovery_id}",
            "version": 2,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _assinatura_viva(runtime, workspace_id):
    """Estado autoritativo vivo que abandono de staging nunca pode tocar."""
    from scripts.backend_contract.application.models import WorkspaceId

    parsed = WorkspaceId.parse(str(workspace_id))
    workspace = runtime._store.workspaces.get(parsed)
    revisions = tuple(runtime._store.revisions.list_workspace(parsed))
    private = tuple(runtime._private_store.list_all(parsed))
    return workspace, revisions, private


def test_startup_nunca_percorre_link_disfarcado_de_raiz_de_recuperacao(tmp_path):
    """RED B8 — coleta órfã não pode apagar bytes fora do namespace."""
    externo = tmp_path / "b8-reparse-externo"
    externo.mkdir()
    (externo / "RECOVERY_NOT_PROMOTABLE").write_bytes(b"RECOVERY_STAGING_V1\n")
    sentinel = externo / "sentinel.bin"
    sentinel.write_bytes(b"PRESERVE")
    base = tmp_path / ".b8-reparse.sqlite3.recovery"
    base.mkdir()
    raiz = base / "recovery-00000000-0000-4000-8000-000000000001"
    try:
        raiz.symlink_to(externo, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink de diretório indisponível neste host: {exc}")

    runtime = _runtime(tmp_path, "b8-reparse")
    try:
        assert raiz.is_symlink()
        assert sentinel.read_bytes() == b"PRESERVE"
        assert (externo / "RECOVERY_NOT_PROMOTABLE").read_bytes() == (b"RECOVERY_STAGING_V1\n")
    finally:
        runtime.close()


def test_startup_nunca_percorre_link_aninhado_na_raiz_de_recuperacao(tmp_path):
    """Sibling B8 — o preflight cobre a árvore inteira antes de qualquer unlink."""
    externo = tmp_path / "b8-reparse-aninhado-externo"
    externo.mkdir()
    sentinel_externo = externo / "sentinel-externo.bin"
    sentinel_externo.write_bytes(b"PRESERVE-EXTERNO")
    base = tmp_path / ".b8-reparse-aninhado.sqlite3.recovery"
    raiz = base / "recovery-00000000-0000-4000-8000-000000000002"
    raiz.mkdir(parents=True)
    (raiz / "RECOVERY_NOT_PROMOTABLE").write_bytes(b"RECOVERY_STAGING_V1\n")
    sentinel_local = raiz / "sentinel-local.bin"
    sentinel_local.write_bytes(b"PRESERVE-LOCAL")
    try:
        (raiz / "subdir-reparse").symlink_to(externo, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink de diretório indisponível neste host: {exc}")

    runtime = _runtime(tmp_path, "b8-reparse-aninhado")
    try:
        assert sentinel_externo.read_bytes() == b"PRESERVE-EXTERNO"
        assert sentinel_local.read_bytes() == b"PRESERVE-LOCAL"
        assert raiz.exists()
    finally:
        runtime.close()


def test_atributo_windows_reparse_e_reconhecido_sem_percorrer_o_alvo():
    """O detector não depende de `Path.is_symlink()` para junctions Windows."""
    import stat as stat_module
    from types import SimpleNamespace

    from scripts.backend_contract.application import workspace_recovery as wr

    details = SimpleNamespace(
        st_mode=stat_module.S_IFDIR,
        st_file_attributes=wr._REPARSE_ATTRIBUTE,
    )
    assert wr._detalhes_sao_link_ou_reparse(details)


@pytest.mark.parametrize("swap_target", ["root", "nested"])
def test_cleanup_mantem_custodia_ate_o_ultimo_unlink(tmp_path, monkeypatch, swap_target):
    """RED A9/B9 — preflight não autoriza paths que possam ser religados."""
    from scripts.backend_contract.application import workspace_recovery as wr

    root = tmp_path / "recovery-00000000-0000-4000-8000-000000000099"
    local = root if swap_target == "root" else root / "subdir"
    local.mkdir(parents=True)
    (root / "RECOVERY_NOT_PROMOTABLE").write_bytes(b"RECOVERY_STAGING_V1\n")
    (local / "payload.bin").write_bytes(b"LOCAL")

    outside = tmp_path / f"outside-{swap_target}-swap"
    outside.mkdir()
    sentinel = outside / "payload.bin"
    sentinel.write_bytes(b"EXTERNAL-MUST-SURVIVE")
    saved = tmp_path / f"saved-{swap_target}-root"

    original = wr._material_remanescente
    attempted = False
    swap_blocked = False

    def swap_after_inventory(root_arg, files):
        nonlocal attempted, swap_blocked
        if not attempted:
            attempted = True
            try:
                (root if swap_target == "root" else local).rename(saved)
                _directory_reparse(root if swap_target == "root" else local, outside)
            except OSError:
                swap_blocked = True
        return original(root_arg, files)

    monkeypatch.setattr(wr, "_material_remanescente", swap_after_inventory)
    try:
        wr._remover_raiz_quarentenada(root, exigir_remocao=True)
    except wr.RecoveryRetained:
        pass

    assert attempted is True
    if os.name == "nt":
        assert swap_blocked is True
    assert sentinel.read_bytes() == b"EXTERNAL-MUST-SURVIVE"


def test_recuperacao_publicada_com_reparse_permanece_visivel_apos_restart(tmp_path):
    """RED B9 — preservar no disco não pode ocultar a recuperação do produto."""
    _workspace_id, _materials, package = _origem_com_dois_privados(tmp_path, "b9-visible-source")
    target = _runtime(tmp_path, "b9-visible-target")
    status, staged = _stage(target, package)
    assert status == 201, staged
    recovery_id = staged["recovery_id"]
    root = tmp_path / ".b9-visible-target.sqlite3.recovery" / f"recovery-{recovery_id}"
    target.close()

    outside = tmp_path / "b9-visible-outside"
    outside.mkdir()
    sentinel = outside / "sentinel.bin"
    sentinel.write_bytes(b"EXTERNAL-MUST-SURVIVE")
    _directory_reparse(root / "nested-reparse", outside)

    reopened = _runtime(tmp_path, "b9-visible-target")
    try:
        status, listing = _json(reopened, "GET", "/v1/recovery")
        assert status == 200, listing
        item = next(recovery for recovery in listing["recoveries"] if recovery["recovery_id"] == recovery_id)
        assert item["state"] == "RECOVERY_UNRESUMABLE"
        assert item["allowed_actions"] == ["ABANDON"]
        assert sentinel.read_bytes() == b"EXTERNAL-MUST-SURVIVE"
        assert root.exists()
    finally:
        reopened.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows cleanup custody handle")
def test_custodia_cleanup_fecha_anchor_quando_validacao_pos_abertura_falha(tmp_path, monkeypatch):
    """Sibling A9 — handle no-follow é fechado se a identidade pós-open falha."""
    from scripts.backend_contract.application import workspace_recovery as wr

    root = tmp_path / "recovery-00000000-0000-4000-8000-000000000098"
    root.mkdir()
    real_lstat = wr.os.lstat
    base_custody = wr.RecoveryFilesystemCustody.acquire(root.parent)
    assert base_custody is not None
    real_open_directory = wr._abrir_diretorio_windows_relativo
    real_close_handle = wr._fechar_handle_windows_unica_vez
    root_calls = 0
    opened = []
    closed = []

    def record_open(parent_handle, name, **kwargs):
        result = real_open_directory(parent_handle, name, **kwargs)
        opened.append(result[0])
        return result

    def record_close(handle):
        closed.append(handle)
        return real_close_handle(handle)

    def fail_second_root_lstat(path):
        nonlocal root_calls
        if path == root:
            root_calls += 1
            if root_calls == 2:
                raise OSError("synthetic identity read failure")
        return real_lstat(path)

    monkeypatch.setattr(wr.os, "lstat", fail_second_root_lstat)
    monkeypatch.setattr(wr, "_abrir_diretorio_windows_relativo", record_open)
    monkeypatch.setattr(wr, "_fechar_handle_windows_unica_vez", record_close)
    with pytest.raises(OSError, match="synthetic identity"):
        wr._adquirir_custodia_cleanup(
            root,
            parent_windows_handle=base_custody.directory_handle,
        )

    assert len(opened) == 1
    assert closed == opened
    assert list(root.iterdir()) == []
    base_custody.close()
    root.rmdir()


def test_falha_ao_soltar_anchor_raiz_preserva_disposition_para_restart(tmp_path, monkeypatch):
    """RED B10 — falha terminal de anchor não pode apagar a decisão durável."""
    _workspace_id, _materials, package = _origem_com_dois_privados(tmp_path, "b10-anchor-source")
    target = _runtime(tmp_path, "b10-anchor-target")
    status, staged = _stage(target, package)
    assert status == 201, staged
    recovery_id = staged["recovery_id"]
    root = tmp_path / ".b10-anchor-target.sqlite3.recovery" / f"recovery-{recovery_id}"

    from scripts.backend_contract.application import workspace_recovery as wr

    original_remove_directory = wr._remover_diretorio_windows_ancorado
    injected = False

    def fail_after_controls_were_removed(node):
        nonlocal injected
        if node.path == root and not injected and not (root / "RECOVERY_NOT_PROMOTABLE").exists():
            injected = True
            raise PermissionError(13, "synthetic root custody release failure")
        return original_remove_directory(node)

    monkeypatch.setattr(
        wr,
        "_remover_diretorio_windows_ancorado",
        fail_after_controls_were_removed,
    )
    status, body = _json(target, "POST", f"/v1/recovery/{recovery_id}/discard")
    assert status == 409, body
    assert body["error"]["code"] == "RECOVERY_RETAINED"
    assert injected is True
    monkeypatch.setattr(
        wr,
        "_remover_diretorio_windows_ancorado",
        original_remove_directory,
    )

    intent = _cleanup_intent_path(tmp_path, "b10-anchor-target", recovery_id)
    assert intent.read_bytes() == _cleanup_intent_payload(
        recovery_id,
        "DISCARD",
        root=root,
    )
    target.close()

    reopened = _runtime(tmp_path, "b10-anchor-target")
    try:
        status, listing = _json(reopened, "GET", "/v1/recovery")
        assert status == 200, listing
        item = next(recovery for recovery in listing["recoveries"] if recovery["recovery_id"] == recovery_id)
        assert item["state"] == "RECOVERY_RETAINED"
        assert item["allowed_actions"] == ["RETRY_DISCARD"]
    finally:
        reopened.close()


def test_intent_externo_sobrevive_falha_persistente_de_cleanup(tmp_path, monkeypatch):
    """RED A12/B12 — a autoridade não pode morar na raiz destruída."""
    from scripts.backend_contract.application import workspace_recovery as wr

    _workspace_id, _materials, package = _origem_com_dois_privados(tmp_path, "protocol-discard-source")
    target = _runtime(tmp_path, "protocol-discard-target")
    status, staged = _stage(target, package)
    assert status == 201, staged
    recovery_id = staged["recovery_id"]
    root = tmp_path / ".protocol-discard-target.sqlite3.recovery" / f"recovery-{recovery_id}"
    intent = _cleanup_intent_path(tmp_path, "protocol-discard-target", recovery_id)

    original_remove_directory = wr._remover_diretorio_windows_ancorado

    def fail_root_removal(node):
        if node.path == root:
            raise PermissionError(13, "synthetic persistent root rmdir failure")
        return original_remove_directory(node)

    monkeypatch.setattr(wr, "_remover_diretorio_windows_ancorado", fail_root_removal)
    status, body = _json(target, "POST", f"/v1/recovery/{recovery_id}/discard")
    assert status == 409, body
    assert body["error"]["code"] == "RECOVERY_RETAINED"
    monkeypatch.setattr(
        wr,
        "_remover_diretorio_windows_ancorado",
        original_remove_directory,
    )

    assert root.exists()
    assert intent.read_bytes() == _cleanup_intent_payload(
        recovery_id,
        "DISCARD",
        root=root,
    )
    target.close()

    reopened = _runtime(tmp_path, "protocol-discard-target")
    try:
        status, listing = _json(reopened, "GET", "/v1/recovery")
        assert status == 200, listing
        item = next(recovery for recovery in listing["recoveries"] if recovery["recovery_id"] == recovery_id)
        assert item["state"] == "RECOVERY_RETAINED"
        assert item["allowed_actions"] == ["RETRY_DISCARD"]
    finally:
        reopened.close()


def test_intent_externo_preserva_abandono_apos_restart(tmp_path, monkeypatch):
    """RED protocolo — ABANDON persiste fora da raiz antes do primeiro unlink."""
    _workspace_id, _materials, package = _origem_com_dois_privados(tmp_path, "protocol-abandon-source")
    target = _runtime(tmp_path, "protocol-abandon-target")
    status, staged = _stage(target, package)
    assert status == 201, staged
    recovery_id = staged["recovery_id"]
    root = tmp_path / ".protocol-abandon-target.sqlite3.recovery" / f"recovery-{recovery_id}"
    target.close()
    (root / "RECOVERY_NOT_PROMOTABLE").write_bytes(b"CORRUPTED")

    reopened = _runtime(tmp_path, "protocol-abandon-target")
    from scripts.backend_contract.application import workspace_recovery as wr

    original_remove_directory = wr._remover_diretorio_windows_ancorado

    def fail_root_removal(node):
        if node.path == root:
            raise PermissionError(13, "synthetic persistent root rmdir failure")
        return original_remove_directory(node)

    monkeypatch.setattr(wr, "_remover_diretorio_windows_ancorado", fail_root_removal)
    status, body = _json(
        reopened,
        "POST",
        f"/v1/recovery/{recovery_id}/abandon",
        value={"confirm_abandon": True},
    )
    assert status == 409, body
    assert body["error"]["code"] == "RECOVERY_RETAINED"
    monkeypatch.setattr(
        wr,
        "_remover_diretorio_windows_ancorado",
        original_remove_directory,
    )
    intent = _cleanup_intent_path(tmp_path, "protocol-abandon-target", recovery_id)
    assert intent.read_bytes() == _cleanup_intent_payload(
        recovery_id,
        "ABANDON",
        root=root,
    )
    reopened.close()

    restarted = _runtime(tmp_path, "protocol-abandon-target")
    try:
        status, listing = _json(restarted, "GET", "/v1/recovery")
        assert status == 200, listing
        item = next(recovery for recovery in listing["recoveries"] if recovery["recovery_id"] == recovery_id)
        assert item["state"] == "RECOVERY_RETAINED"
        assert item["allowed_actions"] == ["RETRY_ABANDON"]
    finally:
        restarted.close()


@pytest.mark.parametrize("existing", ["exact", "divergent", "hardlink"])
def test_intent_externo_file_exists_exige_controle_regular_exato(tmp_path, existing):
    """RED protocolo — FileExists só equivale a bytes canônicos exclusivos."""
    _workspace_id, _materials, package = _origem_com_dois_privados(tmp_path, f"intent-{existing}-source")
    target_name = f"intent-{existing}-target"
    target = _runtime(tmp_path, target_name)
    status, staged = _stage(target, package)
    assert status == 201, staged
    recovery_id = staged["recovery_id"]
    root = tmp_path / f".{target_name}.sqlite3.recovery" / f"recovery-{recovery_id}"
    intent = _cleanup_intent_path(tmp_path, target_name, recovery_id)
    expected = _cleanup_intent_payload(recovery_id, "DISCARD", root=root)
    if existing == "exact":
        intent.write_bytes(expected)
    elif existing == "divergent":
        intent.write_bytes(b"{")
    else:
        outside = tmp_path / "foreign-intent.bin"
        outside.write_bytes(expected)
        os.link(outside, intent)

    status, body = _json(target, "POST", f"/v1/recovery/{recovery_id}/discard")
    if existing == "exact":
        assert status == 200, body
        assert not root.exists()
        assert not intent.exists()
    else:
        assert status != 200, body
        assert root.exists()
        assert intent.read_bytes() == (b"{" if existing == "divergent" else expected)
    target.close()


def test_falha_na_publicacao_do_intent_nao_inicia_cleanup(tmp_path, monkeypatch):
    """RED protocolo — sem commit do WAL externo, nenhum byte é removido."""
    from scripts.backend_contract.application import workspace_recovery as wr

    _workspace_id, _materials, package = _origem_com_dois_privados(tmp_path, "intent-create-source")
    target = _runtime(tmp_path, "intent-create-target")
    status, staged = _stage(target, package)
    assert status == 201, staged
    recovery_id = staged["recovery_id"]
    root = tmp_path / ".intent-create-target.sqlite3.recovery" / f"recovery-{recovery_id}"
    before = sorted(path.relative_to(root) for path in root.rglob("*"))
    original_publish = wr._gravar_sidecar_imutavel
    injected = False

    def fail_cleanup_intent(base, name, record, custody=None):
        nonlocal injected
        if name.startswith(".recovery-cleanup-intent-"):
            injected = True
            raise OSError("synthetic intent create failure")
        return original_publish(base, name, record, custody)

    monkeypatch.setattr(wr, "_gravar_sidecar_imutavel", fail_cleanup_intent)
    status, body = _json(target, "POST", f"/v1/recovery/{recovery_id}/discard")
    assert status != 200, body
    assert injected is True
    assert sorted(path.relative_to(root) for path in root.rglob("*")) == before
    target.close()


def test_escrita_parcial_do_intent_falha_antes_do_cleanup(tmp_path, monkeypatch):
    """RED protocolo — intent parcial não vira autoridade nem libera unlink."""
    from scripts.backend_contract.application import workspace_recovery as wr

    _workspace_id, _materials, package = _origem_com_dois_privados(tmp_path, "intent-partial-source")
    target = _runtime(tmp_path, "intent-partial-target")
    status, staged = _stage(target, package)
    assert status == 201, staged
    recovery_id = staged["recovery_id"]
    root = tmp_path / ".intent-partial-target.sqlite3.recovery" / f"recovery-{recovery_id}"
    intent = _cleanup_intent_path(tmp_path, "intent-partial-target", recovery_id)
    before = sorted(path.relative_to(root) for path in root.rglob("*"))
    original_publish = wr._gravar_sidecar_imutavel
    injected = False

    def leave_partial_cleanup_intent(base, name, record, custody=None):
        nonlocal injected
        if name.startswith(".recovery-cleanup-intent-"):
            injected = True
            (Path(base) / name).write_bytes(b"{")
            raise OSError("synthetic partial intent write")
        return original_publish(base, name, record, custody)

    monkeypatch.setattr(wr, "_gravar_sidecar_imutavel", leave_partial_cleanup_intent)
    status, body = _json(target, "POST", f"/v1/recovery/{recovery_id}/discard")
    assert status != 200, body
    assert injected is True
    assert intent.read_bytes() == b"{"
    assert sorted(path.relative_to(root) for path in root.rglob("*")) == before
    target.close()

    reopened = _runtime(tmp_path, "intent-partial-target")
    try:
        status, listing = _json(reopened, "GET", "/v1/recovery")
        assert status == 200, listing
        item = next(recovery for recovery in listing["recoveries"] if recovery["recovery_id"] == recovery_id)
        assert item["state"] == "RECOVERY_RETAINED"
        assert item["allowed_actions"] == ["RETRY_ABANDON"]
    finally:
        reopened.close()


@pytest.mark.parametrize(
    "failed_control",
    ["STAGING_IDENTITY_V1", "RECOVERY_SESSION_V1", "RECOVERY_NOT_PROMOTABLE"],
)
def test_intent_externo_sobrevive_falha_removendo_controle_interno(tmp_path, monkeypatch, failed_control):
    """RED matriz — falha em controle interno não perde a decisão humana."""
    from scripts.backend_contract.application import workspace_recovery as wr

    _workspace_id, _materials, package = _origem_com_dois_privados(tmp_path, f"control-{failed_control}-source")
    target_name = f"control-{failed_control}-target"
    target = _runtime(tmp_path, target_name)
    status, staged = _stage(target, package)
    assert status == 201, staged
    recovery_id = staged["recovery_id"]
    root = tmp_path / f".{target_name}.sqlite3.recovery" / f"recovery-{recovery_id}"
    original_unlink = wr._unlink_na_custodia

    def fail_selected_control(node, name):
        if name == failed_control:
            raise PermissionError(13, "synthetic control unlink failure")
        return original_unlink(node, name)

    monkeypatch.setattr(wr, "_unlink_na_custodia", fail_selected_control)
    status, body = _json(target, "POST", f"/v1/recovery/{recovery_id}/discard")
    assert status == 409, body
    assert body["error"]["code"] == "RECOVERY_RETAINED"
    monkeypatch.setattr(wr, "_unlink_na_custodia", original_unlink)
    intent = _cleanup_intent_path(tmp_path, target_name, recovery_id)
    assert intent.read_bytes() == _cleanup_intent_payload(
        recovery_id,
        "DISCARD",
        root=root,
    )
    assert root.exists()
    target.close()

    reopened = _runtime(tmp_path, target_name)
    try:
        status, listing = _json(reopened, "GET", "/v1/recovery")
        assert status == 200, listing
        item = next(recovery for recovery in listing["recoveries"] if recovery["recovery_id"] == recovery_id)
        assert item["state"] == "RECOVERY_RETAINED"
        assert item["allowed_actions"] == ["RETRY_DISCARD"]
    finally:
        reopened.close()


def test_intent_externo_sobrevive_falha_removendo_journal(tmp_path, monkeypatch):
    """O journal pode falhar por último sem apagar a decisão de descarte."""
    from scripts.backend_contract.application import workspace_recovery as wr

    _workspace_id, _materials, package = _origem_com_dois_privados(tmp_path, "control-journal-source")
    target = _runtime(tmp_path, "control-journal-target")
    status, staged = _stage(target, package)
    assert status == 201, staged
    recovery_id = staged["recovery_id"]
    root = tmp_path / ".control-journal-target.sqlite3.recovery" / f"recovery-{recovery_id}"
    (root / "PROMOTION_TRANSACTION_V1").write_bytes(b"SYNTHETIC-JOURNAL")
    original_unlink = wr._unlink_na_custodia

    def fail_journal(node, name):
        if name == "PROMOTION_TRANSACTION_V1":
            raise PermissionError(13, "synthetic journal unlink failure")
        return original_unlink(node, name)

    monkeypatch.setattr(wr, "_unlink_na_custodia", fail_journal)
    status, body = _json(target, "POST", f"/v1/recovery/{recovery_id}/discard")
    assert status == 409, body
    assert body["error"]["code"] == "RECOVERY_RETAINED"
    monkeypatch.setattr(wr, "_unlink_na_custodia", original_unlink)
    intent = _cleanup_intent_path(tmp_path, "control-journal-target", recovery_id)
    assert intent.read_bytes() == _cleanup_intent_payload(
        recovery_id,
        "DISCARD",
        root=root,
    )
    assert root.exists()
    target.close()

    reopened = _runtime(tmp_path, "control-journal-target")
    try:
        status, listing = _json(reopened, "GET", "/v1/recovery")
        assert status == 200, listing
        item = next(recovery for recovery in listing["recoveries"] if recovery["recovery_id"] == recovery_id)
        assert item["state"] == "RECOVERY_RETAINED"
        assert item["allowed_actions"] == ["RETRY_DISCARD"]
    finally:
        reopened.close()


def test_root_ausente_sem_prova_de_handle_retem_intent_apos_restart(tmp_path, monkeypatch):
    """Path ausente não recria prova de identidade depois de process death."""
    _workspace_id, _materials, package = _origem_com_dois_privados(tmp_path, "intent-gc-source")
    target = _runtime(tmp_path, "intent-gc-target")
    status, staged = _stage(target, package)
    assert status == 201, staged
    recovery_id = staged["recovery_id"]
    root = tmp_path / ".intent-gc-target.sqlite3.recovery" / f"recovery-{recovery_id}"
    intent = _cleanup_intent_path(tmp_path, "intent-gc-target", recovery_id)
    original_unlink = Path.unlink
    injected = False

    def fail_intent_gc_once(path, *args, **kwargs):
        nonlocal injected
        if path == intent and not injected:
            injected = True
            raise PermissionError(13, "synthetic cleanup intent gc failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_intent_gc_once)
    status, body = _json(target, "POST", f"/v1/recovery/{recovery_id}/discard")
    assert status == 200, body
    assert injected is True
    assert not root.exists()
    assert intent.exists()
    monkeypatch.setattr(Path, "unlink", original_unlink)
    target.close()

    reopened = _runtime(tmp_path, "intent-gc-target")
    try:
        status, listing = _json(reopened, "GET", "/v1/recovery")
        assert status == 200, listing
        assert all(item["recovery_id"] != recovery_id for item in listing["recoveries"])
        assert intent.exists()
    finally:
        reopened.close()


def test_rmdir_transitorio_retem_e_retry_converge(tmp_path, monkeypatch):
    """A raiz existente conserva a decisão; novo retry conclui sem redecidir."""
    _workspace_id, _materials, package = _origem_com_dois_privados(tmp_path, "rmdir-transient-source")
    target = _runtime(tmp_path, "rmdir-transient-target")
    status, staged = _stage(target, package)
    assert status == 201, staged
    recovery_id = staged["recovery_id"]
    root = tmp_path / ".rmdir-transient-target.sqlite3.recovery" / f"recovery-{recovery_id}"
    intent = _cleanup_intent_path(tmp_path, "rmdir-transient-target", recovery_id)
    from scripts.backend_contract.application import workspace_recovery as wr

    original_remove_directory = wr._remover_diretorio_windows_ancorado
    original_rmdir = os.rmdir
    injected = False

    def fail_root_once(node):
        nonlocal injected
        if node.path == root and not injected:
            injected = True
            raise PermissionError(13, "synthetic transient rmdir failure")
        return original_remove_directory(node)

    def fail_posix_root_once(path, *args, **kwargs):
        nonlocal injected
        if Path(path).name == root.name and not injected:
            injected = True
            raise PermissionError(13, "synthetic transient rmdir failure")
        return original_rmdir(path, *args, **kwargs)

    if os.name == "nt":
        monkeypatch.setattr(
            wr,
            "_remover_diretorio_windows_ancorado",
            fail_root_once,
        )
    else:
        monkeypatch.setattr(os, "rmdir", fail_posix_root_once)
    status, body = _json(target, "POST", f"/v1/recovery/{recovery_id}/discard")
    assert status == 409, body
    assert body["error"]["code"] == "RECOVERY_RETAINED"
    assert root.exists()
    assert intent.read_bytes() == _cleanup_intent_payload(recovery_id, "DISCARD", root=root)

    monkeypatch.setattr(
        wr,
        "_remover_diretorio_windows_ancorado",
        original_remove_directory,
    )
    monkeypatch.setattr(os, "rmdir", original_rmdir)
    status, body = _json(target, "POST", f"/v1/recovery/{recovery_id}/discard")
    assert status == 200, body
    assert not root.exists()
    assert not intent.exists()
    target.close()


@pytest.mark.parametrize(
    ("phase", "return_code"),
    [
        ("before_custody", 71),
        ("after_material", 72),
        ("before_rmdir", 73),
        ("after_root_absent", 74),
    ],
)
def test_process_death_em_cada_fase_de_cleanup_reconstroi_intent(tmp_path, phase, return_code):
    """A intenção externa fecha todas as janelas de crash do cleanup."""
    _workspace_id, _materials, package = _origem_com_dois_privados(tmp_path, f"death-{phase}-source")
    target_name = f"death-{phase}-target"
    target = _runtime(tmp_path, target_name)
    status, staged = _stage(target, package)
    assert status == 201, staged
    recovery_id = staged["recovery_id"]
    root = tmp_path / f".{target_name}.sqlite3.recovery" / f"recovery-{recovery_id}"
    intent = _cleanup_intent_path(tmp_path, target_name, recovery_id)
    target.close()

    script = r"""
import os
import sys
from pathlib import Path

from scripts.backend_contract.application import workspace_recovery as wr
from tests.test_backup_recovery_reachability_v1 import _json, _runtime

base = Path(sys.argv[1])
target_name = sys.argv[2]
recovery_id = sys.argv[3]
phase = sys.argv[4]
root = base / f".{target_name}.sqlite3.recovery" / f"recovery-{recovery_id}"

if phase == "before_custody":
    original = wr._adquirir_custodia_cleanup
    def patched(path, *args, **kwargs):
        if Path(path) == root:
            os._exit(71)
        return original(path, *args, **kwargs)
    wr._adquirir_custodia_cleanup = patched
elif phase == "after_material":
    original = wr._remover_material_ancorado
    def patched(node, material):
        result = original(node, material)
        if node.path == root:
            os._exit(72)
        return result
    wr._remover_material_ancorado = patched
elif phase == "before_rmdir":
    if os.name == "nt":
        original = wr._remover_diretorio_windows_ancorado
        def patched(node):
            if node.path == root:
                os._exit(73)
            return original(node)
        wr._remover_diretorio_windows_ancorado = patched
    else:
        original = os.rmdir
        def patched(path, *args, **kwargs):
            if Path(path).name == root.name:
                os._exit(73)
            return original(path, *args, **kwargs)
        os.rmdir = patched
elif phase == "after_root_absent":
    original = wr._coletar_cleanup_intent_apos_raiz_ausente
    def patched(path, candidate_recovery_id, *args, **kwargs):
        if Path(path) == root:
            os._exit(74)
        return original(path, candidate_recovery_id, *args, **kwargs)
    wr._coletar_cleanup_intent_apos_raiz_ausente = patched

runtime = _runtime(base, target_name)
_json(runtime, "POST", f"/v1/recovery/{recovery_id}/discard")
raise AssertionError("fault injection did not terminate the process")
"""
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(tmp_path),
            target_name,
            recovery_id,
            phase,
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        timeout=30,
    )
    assert completed.returncode == return_code

    if phase == "after_root_absent":
        assert not root.exists()
        assert intent.exists()
    else:
        assert root.exists()
        assert intent.read_bytes() == _cleanup_intent_payload(
            recovery_id,
            "DISCARD",
            root=root,
        )

    reopened = _runtime(tmp_path, target_name)
    try:
        status, listing = _json(reopened, "GET", "/v1/recovery")
        assert status == 200, listing
        matching = [item for item in listing["recoveries"] if item["recovery_id"] == recovery_id]
        if phase == "after_root_absent":
            assert matching == []
            assert intent.exists()
        else:
            assert len(matching) == 1
            assert matching[0]["state"] == "RECOVERY_RETAINED"
            assert matching[0]["allowed_actions"] == ["RETRY_DISCARD"]
    finally:
        reopened.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows cleanup custody handles")
def test_falha_ao_criar_anchor_nao_muta_a_raiz(tmp_path, monkeypatch):
    """Falha ao abrir o diretório não inicia qualquer remoção privada."""
    from scripts.backend_contract.application import workspace_recovery as wr

    root = tmp_path / "recovery-00000000-0000-4000-8000-000000000097"
    root.mkdir()
    sentinel = root / "private.bin"
    sentinel.write_bytes(b"PRIVATE-SENTINEL")
    base_custody = wr.RecoveryFilesystemCustody.acquire(root.parent)
    assert base_custody is not None
    original_open = wr._abrir_diretorio_windows_relativo

    def fail_directory_open(parent_handle, name, **kwargs):
        if name == root.name:
            raise PermissionError(13, "synthetic directory custody failure")
        return original_open(parent_handle, name, **kwargs)

    monkeypatch.setattr(wr, "_abrir_diretorio_windows_relativo", fail_directory_open)
    with pytest.raises(PermissionError, match="synthetic directory custody"):
        wr._adquirir_custodia_cleanup(
            root,
            parent_windows_handle=base_custody.directory_handle,
        )

    assert sentinel.read_bytes() == b"PRIVATE-SENTINEL"
    assert not list(root.glob(".recovery-cleanup-custody.*"))
    base_custody.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows cleanup custody handles")
def test_falha_ao_remover_anchor_filho_nao_vaza_handle_pai(tmp_path, monkeypatch):
    """RED A10 — erro num handle filho não interrompe o fechamento da árvore."""
    from scripts.backend_contract.application import workspace_recovery as wr

    root = tmp_path / "recovery-00000000-0000-4000-8000-000000000096"
    child = root / "child"
    child.mkdir(parents=True)
    base_custody = wr.RecoveryFilesystemCustody.acquire(root.parent)
    assert base_custody is not None
    custody = wr._adquirir_custodia_cleanup(
        root,
        parent_windows_handle=base_custody.directory_handle,
    )
    descriptors = [custody.descriptor, custody.children[0].descriptor]
    assert all(descriptor is not None for descriptor in descriptors)

    original_close = wr._fechar_handle_windows_unica_vez
    calls = []

    def fail_child_handle(handle):
        calls.append(handle)
        original_close(handle)
        if handle == descriptors[1]:
            raise PermissionError(13, "synthetic child handle release failure")

    monkeypatch.setattr(wr, "_fechar_handle_windows_unica_vez", fail_child_handle)
    with pytest.raises(PermissionError, match="synthetic child handle"):
        wr._fechar_custodia_cleanup(custody)

    assert calls == [descriptors[1], descriptors[0]]
    assert custody.descriptor is None
    assert custody.children[0].descriptor is None
    base_custody.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows cleanup custody handles")
def test_close_ambiguo_nunca_fecha_descriptor_reutilizado(tmp_path, monkeypatch):
    """RED A12 — erro depois do close consome o fd e nunca o fecha de novo."""
    from scripts.backend_contract.application import workspace_recovery as wr

    root = tmp_path / "recovery-00000000-0000-4000-8000-000000000095"
    (root / "child").mkdir(parents=True)
    base_custody = wr.RecoveryFilesystemCustody.acquire(root.parent)
    assert base_custody is not None
    custody = wr._adquirir_custodia_cleanup(
        root,
        parent_windows_handle=base_custody.directory_handle,
    )
    child = custody.children[0]
    child_descriptor = child.descriptor
    assert child_descriptor is not None
    original_close = wr._fechar_handle_windows_unica_vez
    calls = []
    injected = False

    def close_then_fail(descriptor):
        nonlocal injected
        calls.append(descriptor)
        if descriptor == child_descriptor and not injected:
            injected = True
            original_close(descriptor)
            raise OSError("synthetic ambiguous close failure")
        return original_close(descriptor)

    monkeypatch.setattr(wr, "_fechar_handle_windows_unica_vez", close_then_fail)
    with pytest.raises(OSError, match="synthetic ambiguous close failure"):
        wr._fechar_custodia_cleanup(custody)
    assert injected is True
    assert calls.count(child_descriptor) == 1
    assert child.descriptor is None
    base_custody.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows cleanup custody handles")
def test_close_ambiguo_antes_da_liberacao_nunca_repete_o_fd(tmp_path, monkeypatch):
    """RED protocolo — HANDLE desconhecido não é ownership reutilizável."""
    from scripts.backend_contract.application import workspace_recovery as wr

    root = tmp_path / "recovery-00000000-0000-4000-8000-000000000093"
    root.mkdir()
    base_custody = wr.RecoveryFilesystemCustody.acquire(root.parent)
    assert base_custody is not None
    custody = wr._adquirir_custodia_cleanup(
        root,
        parent_windows_handle=base_custody.directory_handle,
    )
    descriptor = custody.descriptor
    assert descriptor is not None and custody.anchor_path is None
    original_close = wr._fechar_handle_windows_unica_vez
    calls = 0

    def fail_before_release(candidate):
        nonlocal calls
        if candidate == descriptor:
            calls += 1
            raise OSError("synthetic close failure before release")
        return original_close(candidate)

    monkeypatch.setattr(wr, "_fechar_handle_windows_unica_vez", fail_before_release)
    with pytest.raises(OSError, match="synthetic close failure"):
        wr._fechar_custodia_cleanup(custody)
    assert calls == 1
    assert custody.descriptor is None
    monkeypatch.setattr(wr, "_fechar_handle_windows_unica_vez", original_close)
    original_close(descriptor)
    base_custody.close()


@pytest.mark.parametrize("reparse_location", ["root", "nested"])
def test_abandono_de_raiz_reparse_nao_escreve_no_alvo_externo(tmp_path, reparse_location):
    """RED B10 — decisão local não pode atravessar uma raiz reparse."""
    recovery_id = "00000000-0000-4000-8000-000000000097"
    external = tmp_path / "b10-unsafe-external"
    external.mkdir()
    (external / "sentinel.bin").write_bytes(b"EXTERNAL-MUST-NOT-CHANGE")

    base = tmp_path / ".b10-unsafe.sqlite3.recovery"
    base.mkdir()
    root = base / f"recovery-{recovery_id}"
    if reparse_location == "root":
        (external / "RECOVERY_NOT_PROMOTABLE").write_bytes(b"RECOVERY_STAGING_V1\n")
        _directory_reparse(root, external)
    else:
        root.mkdir()
        (root / "RECOVERY_NOT_PROMOTABLE").write_bytes(b"RECOVERY_STAGING_V1\n")
        _directory_reparse(root / "nested-reparse", external)
    before = {path.name: path.read_bytes() for path in external.iterdir()}

    runtime = _runtime(tmp_path, "b10-unsafe")
    try:
        status, listing = _json(runtime, "GET", "/v1/recovery")
        assert status == 200, listing
        assert listing["recoveries"][0]["allowed_actions"] == ["ABANDON"]

        status, body = _json(
            runtime,
            "POST",
            f"/v1/recovery/{recovery_id}/abandon",
            value={"confirm_abandon": True},
        )
        assert status == 409, body
        assert body["error"]["code"] == "RECOVERY_RETAINED"
        assert {path.name: path.read_bytes() for path in external.iterdir()} == before
    finally:
        runtime.close()


def test_staging_orfao_sem_journal_e_recolhido_na_reabertura(tmp_path):
    """RED N — queda durante a preparação não pode acumular cópias eternas.

    Sem journal, nada há para retomar: a cópia é reconstruível a partir do
    arquivo de backup que o usuário guardou. Mantê-la é reter material sigiloso
    sem saída pelo produto.
    """
    _origem, _ids, package = _origem_com_dois_privados(tmp_path, "n-origem")
    destino = _runtime(tmp_path, "n-destino")
    try:
        status, staged = _stage(destino, package)
        assert status == 201, staged
        # Simula a QUEDA ANTES de publicar RECOVERY_SESSION_V1. Depois desse
        # descriptor, a raiz não é órfã: é trabalho preparado do usuário.
        for entrada in destino._recovery_sessions._sessions.values():
            (entrada["staging"].root / "RECOVERY_SESSION_V1").unlink()
            entrada["staging"].close()
        destino._recovery_sessions._sessions.clear()
    finally:
        destino.close()
    assert _raizes(tmp_path, "n-destino"), "a raiz órfã precisa existir para o teste valer"

    reaberto = _runtime(tmp_path, "n-destino")
    try:
        assert _raizes(tmp_path, "n-destino") == []
    finally:
        reaberto.close()


def test_residuo_de_promocao_concluida_e_recolhido_na_reabertura(tmp_path):
    """RED O — journal de promoção CONCLUÍDA não é autoridade de retomada.

    Se a remoção do staging falhou no sucesso da promoção, o resíduo ficava sem
    sessão e sem rota. Só `PROMOTING` merece ser preservado.
    """
    origem, _ids, package = _origem_com_dois_privados(tmp_path, "o-origem")
    destino = _runtime(tmp_path, "o-destino")
    try:
        status, staged = _stage(destino, package)
        assert status == 201, staged
        status, corpo = _promote(destino, staged["recovery_id"])
        assert status == 200, corpo
        assert len(_materiais(destino, origem)) == 2
    finally:
        destino.close()

    reaberto = _runtime(tmp_path, "o-destino")
    try:
        assert _raizes(tmp_path, "o-destino") == []
        assert len(_materiais(reaberto, origem)) == 2
    finally:
        reaberto.close()


def test_promocao_interrompida_sobrevive_a_varredura_de_orfaos(tmp_path):
    """RED O' — a varredura NUNCA pode recolher o que ainda é retomável."""
    origem, _ids, package = _origem_com_dois_privados(tmp_path, "p-origem")
    destino = _runtime(tmp_path, "p-destino")
    try:
        status, staged = _stage(destino, package)
        assert status == 201, staged
        with _FalhaAposIntent(falhar_na_chamada=2) as falha:
            _promote(destino, staged["recovery_id"])
        assert falha.disparou
    finally:
        destino.close()

    reaberto = _runtime(tmp_path, "p-destino")
    try:
        assert _raizes(tmp_path, "p-destino"), "a promoção interrompida foi destruída"
        status, retomadas = _json(reaberto, "GET", "/v1/recovery")
        assert status == 200, retomadas
        assert len(retomadas["recoveries"]) == 1
        retomada = retomadas["recoveries"][0]
        assert retomada["state"] == "FAILED_RECOVERABLE"
        assert retomada["allowed_actions"] == ["PROMOTE", "ABANDON"]
        status, corpo = _promote(reaberto, retomada["recovery_id"])
        assert status == 200, corpo
        assert len(_materiais(reaberto, origem)) == 2
    finally:
        reaberto.close()


def test_recuperacao_preparada_sobrevive_ao_fechamento_e_reinicio(tmp_path):
    """RED O'' — fechar o aplicativo não é descartar um staging válido.

    Uma recuperação já verificada e preparada é trabalho recuperável do usuário.
    `runtime.close()` deve apenas fechar handles; a inicialização seguinte deve
    preservar a raiz para que a ação normal possa ser reconstruída.
    """
    _origem, _ids, package = _origem_com_dois_privados(tmp_path, "o2-origem")
    destino = _runtime(tmp_path, "o2-destino")
    status, staged = _stage(destino, package)
    assert status == 201, staged
    assert _raizes(tmp_path, "o2-destino")

    destino.close()
    assert _raizes(tmp_path, "o2-destino"), "close descartou a recuperação preparada"

    reaberto = _runtime(tmp_path, "o2-destino")
    try:
        assert _raizes(tmp_path, "o2-destino"), "restart recolheu um staging válido"
        status, corpo = _json(reaberto, "GET", "/v1/recovery")
        assert status == 200, corpo
        assert corpo == {
            "recoveries": [
                {
                    "recovery_id": staged["recovery_id"],
                    "state": "STAGED",
                    "summary": staged["summary"],
                    "reason": None,
                    "allowed_actions": ["PROMOTE", "DISCARD"],
                }
            ]
        }
        status, corpo = _promote(reaberto, staged["recovery_id"])
        assert status == 200, corpo
    finally:
        reaberto.close()


# ------------------------------------------------------------------ Q
# SELF_PRODUCED_BACKUP MUST_BE REINGESTIBLE


def test_backup_grande_demais_e_recusado_em_vez_de_prometer_seguranca_falsa(tmp_path):
    """RED Q — o produto não pode entregar 200 num pacote que ele não restaura.

    E o teto tem de ser UM só: a instalação que configura um corpo menor não
    pode continuar exportando pacotes que a própria ingestão recusaria. Aqui o
    teto efetivo vem da configuração, não de um literal paralelo.
    """
    from scripts.backend_contract.local_api.server import LocalServerConfig
    from scripts.planejamento_pericial.app_composition import build_pericial_local_api
    from tests.test_backup_recovery_reachability_v1 import TOKEN
    from tests.test_document_intake_v1 import provision_private_root

    private = tmp_path / "q-private"
    provision_private_root(private)
    runtime = build_pericial_local_api(
        tmp_path / "q.sqlite3",
        private_root=private,
        token=TOKEN,
        config=LocalServerConfig(max_document_body_bytes=4_096),
    )
    runtime.start()
    try:
        workspace_id, _material = _workspace_with_material(runtime, tmp_path, name="Caso enorme")
        status, corpo = _json(runtime, "POST", f"/v1/workspaces/{workspace_id}/backup")
        assert status == 413, corpo
        assert corpo["error"]["code"] == "BACKUP_TOO_LARGE"
    finally:
        runtime.close()


def _journal_da_unica_raiz(tmp_path, nome):
    base = tmp_path / f".{nome}.sqlite3.recovery"
    raizes = [p for p in base.iterdir() if p.is_dir()]
    assert len(raizes) == 1, raizes
    return raizes[0] / "PROMOTION_TRANSACTION_V1"


def _interromper_promocao(tmp_path, nome):
    origem, _ids, package = _origem_com_dois_privados(tmp_path, f"{nome}-origem")
    destino = _runtime(tmp_path, nome)
    status, staged = _stage(destino, package)
    assert status == 201, staged
    with _FalhaAposIntent(falhar_na_chamada=2) as falha:
        status, corpo = _promote(destino, staged["recovery_id"])
    assert falha.disparou
    assert status == 409, corpo
    return origem, package, destino, staged["recovery_id"]


def test_fechar_o_app_nunca_apaga_journal_ilegivel(tmp_path):
    """RED R1 — `close_all` falhava ABERTA: erro de leitura virava "não há".

    É a mesma classe do P0 anterior, movida do descarte para o fechamento
    normal do produto. Qualquer OSError no shutdown (antivírus, indexador,
    placeholder do OneDrive) apagava a autoridade de retomada.
    """
    _origem, _pkg, destino, _rid = _interromper_promocao(tmp_path, "r1")
    journal = _journal_da_unica_raiz(tmp_path, "r1")
    try:
        journal.write_bytes(b"{trunc")
    finally:
        destino.close()
    base = tmp_path / ".r1.sqlite3.recovery"
    assert [p.name for p in base.iterdir() if p.is_dir()], "o journal ilegível foi destruído"


def test_journal_ilegivel_de_outra_raiz_nao_mata_toda_restauracao(tmp_path):
    """RED R2 — uma raiz corrompida bricava a restauração de QUALQUER backup."""
    _origem, _pkg, destino, _rid = _interromper_promocao(tmp_path, "r2")
    journal = _journal_da_unica_raiz(tmp_path, "r2")
    journal.write_bytes(b"{trunc")
    destino.close()

    outra, _ids2, outro_pacote = _origem_com_dois_privados(tmp_path, "r2-outra")
    reaberto = _runtime(tmp_path, "r2")
    try:
        status, corpo = _stage(reaberto, outro_pacote)
        assert status == 201, corpo
        status, corpo = _promote(reaberto, corpo["recovery_id"])
        assert status == 200, corpo
        assert len(_materiais(reaberto, outra)) == 2
    finally:
        reaberto.close()


def test_restart_nunca_recolhe_journal_corrompido_sem_decisao_humana(tmp_path):
    """RED R2b — não compreender autoridade nunca prova que ela não existiu."""
    workspace_id, package, destino, recovery_id = _interromper_promocao(tmp_path, "r2b")
    journal = _journal_da_unica_raiz(tmp_path, "r2b")
    journal.write_bytes(b"{trunc")
    destino.close()
    assert _raizes(tmp_path, "r2b")

    reaberto = _runtime(tmp_path, "r2b")
    try:
        assert _raizes(tmp_path, "r2b"), "restart abandonou journal corrompido"
        status, corpo = _json(reaberto, "GET", "/v1/recovery")
        assert status == 200, corpo
        assert corpo["recoveries"][0]["recovery_id"] == recovery_id
        assert corpo["recoveries"][0]["state"] == "RECOVERY_UNRESUMABLE"
        assert corpo["recoveries"][0]["allowed_actions"] == ["ABANDON"]

        status, restaged = _stage(reaberto, package)
        assert status == 201, restaged
        assert restaged["recovery_id"] == recovery_id
        assert restaged["promotable"] is False
        assert len(_raizes(tmp_path, "r2b")) == 1, "reenvio fabricou segunda cópia privada"

        antes = _assinatura_viva(reaberto, workspace_id)
        status, corpo = _json(
            reaberto,
            "POST",
            f"/v1/recovery/{recovery_id}/abandon",
            value={"confirm_abandon": 1},
        )
        assert status == 400, corpo
        assert _assinatura_viva(reaberto, workspace_id) == antes
        assert _raizes(tmp_path, "r2b")

        status, corpo = _json(
            reaberto,
            "POST",
            f"/v1/recovery/{recovery_id}/abandon",
            value={"confirm_abandon": True},
        )
        assert status == 200, corpo
        assert _assinatura_viva(reaberto, workspace_id) == antes
        assert _raizes(tmp_path, "r2b") == []
    finally:
        reaberto.close()


@pytest.mark.parametrize(
    "adulteracao",
    [
        "phase_nao_escalar",
        "phase_desconhecida",
        "version_booleana",
        "revision_id_divergente",
        "private_id_divergente",
    ],
)
def test_restart_preserva_journal_sem_prova_terminal_exata(tmp_path, adulteracao):
    """RED B8 — journal parseável não basta para autorizar coleta terminal."""
    _workspace_id, _package, destino, recovery_id = _interromper_promocao(tmp_path, f"b8-{adulteracao}")
    journal = _journal_da_unica_raiz(tmp_path, f"b8-{adulteracao}")
    registro = json.loads(journal.read_text(encoding="utf-8"))
    if adulteracao == "phase_nao_escalar":
        registro["phase"] = []
    elif adulteracao == "phase_desconhecida":
        registro["phase"] = "FUTURE"
    elif adulteracao == "version_booleana":
        registro["version"] = True
    elif adulteracao == "revision_id_divergente":
        original = registro["revisions"][0][0]
        registro["revisions"][0][0] = ("0" if original[0] != "0" else "1") + original[1:]
        registro["phase"] = "PROMOTED"
    else:
        original = registro["private_contents"][0][0]
        registro["private_contents"][0][0] = ("0" if original[0] != "0" else "1") + original[1:]
        registro["phase"] = "PROMOTED"
    journal.write_text(json.dumps(registro), encoding="utf-8")
    raiz = journal.parent
    destino.close()

    reaberto = _runtime(tmp_path, f"b8-{adulteracao}")
    try:
        assert raiz.exists(), "journal sem vínculo exato autorizou coleta"
        status, corpo = _json(reaberto, "GET", "/v1/recovery")
        assert status == 200, corpo
        assert corpo["recoveries"][0]["recovery_id"] == recovery_id
        assert corpo["recoveries"][0]["state"] == "RECOVERY_UNRESUMABLE"
        assert corpo["recoveries"][0]["reason"] == ("promotion_journal_unreadable_or_unsupported")
        assert corpo["recoveries"][0]["allowed_actions"] == ["ABANDON"]
    finally:
        reaberto.close()


def test_restart_nunca_recolhe_versao_desconhecida_sem_decisao_humana(tmp_path):
    """RED R2c — versão futura é quarentena irretomável, não órfão descartável."""
    _origem, _pkg, destino, recovery_id = _interromper_promocao(tmp_path, "r2c")
    journal = _journal_da_unica_raiz(tmp_path, "r2c")
    journal.write_text('{"version":999,"phase":"PROMOTING"}', encoding="utf-8")
    destino.close()
    assert _raizes(tmp_path, "r2c")

    reaberto = _runtime(tmp_path, "r2c")
    try:
        assert _raizes(tmp_path, "r2c"), "restart abandonou versão desconhecida"
        status, corpo = _json(reaberto, "GET", "/v1/recovery")
        assert status == 200, corpo
        assert corpo["recoveries"][0]["recovery_id"] == recovery_id
        assert corpo["recoveries"][0]["state"] == "RECOVERY_UNRESUMABLE"
        assert corpo["recoveries"][0]["allowed_actions"] == ["ABANDON"]
    finally:
        reaberto.close()


def test_promoted_sem_identidade_nao_autoriza_coleta_automatica(tmp_path):
    """RED B7 — nome da fase sozinho não prova uma promoção terminal.

    `PROMOTED` só autoriza apagar a raiz quando o journal completo está ligado
    ao descriptor publicado. Um dict de versão/fase é autoridade corrompida,
    não prova positiva de conclusão.
    """
    _origem, _ids, package = _origem_com_dois_privados(tmp_path, "b7-origem")
    destino = _runtime(tmp_path, "b7-destino")
    status, staged = _stage(destino, package)
    assert status == 201, staged
    raiz = tmp_path / ".b7-destino.sqlite3.recovery" / f"recovery-{staged['recovery_id']}"
    (raiz / "PROMOTION_TRANSACTION_V1").write_text('{"version":1,"phase":"PROMOTED"}', encoding="utf-8")
    destino.close()

    reaberto = _runtime(tmp_path, "b7-destino")
    try:
        assert raiz.exists(), "fase sem identidade apagou uma sessão publicada"
        status, corpo = _json(reaberto, "GET", "/v1/recovery")
        assert status == 200, corpo
        assert corpo["recoveries"] == [
            {
                "recovery_id": staged["recovery_id"],
                "state": "RECOVERY_UNRESUMABLE",
                "summary": staged["summary"],
                "reason": "promotion_journal_unreadable_or_unsupported",
                "allowed_actions": ["ABANDON"],
            }
        ]
    finally:
        reaberto.close()


def test_descriptor_com_version_booleana_falha_fechado(tmp_path):
    """Sibling B8 — `True == 1` não transforma tipo inválido em versão válida."""
    _origem, _ids, package = _origem_com_dois_privados(tmp_path, "b8s-origem")
    destino = _runtime(tmp_path, "b8s-destino")
    status, staged = _stage(destino, package)
    assert status == 201, staged
    raiz = tmp_path / ".b8s-destino.sqlite3.recovery" / f"recovery-{staged['recovery_id']}"
    descriptor = raiz / "RECOVERY_SESSION_V1"
    registro = json.loads(descriptor.read_text(encoding="utf-8"))
    descriptor.write_text(json.dumps({**registro, "version": True}), encoding="utf-8")
    destino.close()

    reaberto = _runtime(tmp_path, "b8s-destino")
    try:
        status, corpo = _json(reaberto, "GET", "/v1/recovery")
        assert status == 200, corpo
        assert corpo["recoveries"][0]["state"] == "RECOVERY_UNRESUMABLE"
        assert corpo["recoveries"][0]["reason"] == "session_descriptor_unreadable"
        assert corpo["recoveries"][0]["allowed_actions"] == ["ABANDON"]
    finally:
        reaberto.close()


def test_marcador_corrompido_nunca_produz_descarte_falso_positivo(tmp_path):
    """RED B7 — `200` de descarte implica raiz realmente ausente."""
    _origem, _ids, package = _origem_com_dois_privados(tmp_path, "b7m-origem")
    destino = _runtime(tmp_path, "b7m-destino")
    try:
        status, staged = _stage(destino, package)
        assert status == 201, staged
        raiz = tmp_path / ".b7m-destino.sqlite3.recovery" / f"recovery-{staged['recovery_id']}"
        (raiz / "RECOVERY_NOT_PROMOTABLE").write_bytes(b"CORRUPTED\n")

        status, corpo = _json(destino, "POST", f"/v1/recovery/{staged['recovery_id']}/discard")
        assert status == 200, corpo
        assert not raiz.exists(), "descarte afirmou sucesso mas reteve a raiz"
    finally:
        destino.close()


def test_marcador_corrompido_reaparece_e_permite_abandono_explicito(tmp_path):
    """Sibling B7 — corrupção da quarentena não cria raiz invisível."""
    _origem, _ids, package = _origem_com_dois_privados(tmp_path, "b7r-origem")
    destino = _runtime(tmp_path, "b7r-destino")
    status, staged = _stage(destino, package)
    assert status == 201, staged
    raiz = tmp_path / ".b7r-destino.sqlite3.recovery" / f"recovery-{staged['recovery_id']}"
    (raiz / "RECOVERY_NOT_PROMOTABLE").write_bytes(b"CORRUPTED\n")
    destino.close()

    reaberto = _runtime(tmp_path, "b7r-destino")
    try:
        status, corpo = _json(reaberto, "GET", "/v1/recovery")
        assert status == 200, corpo
        assert corpo["recoveries"] == [
            {
                "recovery_id": staged["recovery_id"],
                "state": "RECOVERY_UNRESUMABLE",
                "summary": staged["summary"],
                "reason": "quarantine_marker_unreadable",
                "allowed_actions": ["ABANDON"],
            }
        ]
        status, corpo = _json(
            reaberto,
            "POST",
            f"/v1/recovery/{staged['recovery_id']}/abandon",
            value={"confirm_abandon": True},
        )
        assert status == 200, corpo
        assert not raiz.exists()
    finally:
        reaberto.close()


@pytest.mark.parametrize("corromper_marcador", [False, True])
@pytest.mark.parametrize(
    "adulteracao_disposition",
    ["json_invalido", "mode_nao_escalar", "version_booleana"],
)
def test_disposition_corrompida_permite_novo_abandono_explicito(tmp_path, corromper_marcador, adulteracao_disposition):
    """RED A7 — `RETRY_ABANDON` precisa executar a ação que anuncia."""
    _origem, _ids, package = _origem_com_dois_privados(tmp_path, "a7d-origem")
    destino = _runtime(tmp_path, "a7d-destino")
    status, staged = _stage(destino, package)
    assert status == 201, staged
    raiz = tmp_path / ".a7d-destino.sqlite3.recovery" / f"recovery-{staged['recovery_id']}"
    disposition = _cleanup_intent_path(tmp_path, "a7d-destino", staged["recovery_id"])
    if adulteracao_disposition != "json_invalido":
        disposition.write_text(
            json.dumps(
                {
                    "version": (True if adulteracao_disposition == "version_booleana" else 1),
                    "recovery_id": staged["recovery_id"],
                    "root_name": f"recovery-{staged['recovery_id']}",
                    "mode": ([] if adulteracao_disposition == "mode_nao_escalar" else "ABANDON"),
                }
            ),
            encoding="utf-8",
        )
    else:
        disposition.write_bytes(b"CORRUPTED\n")
    if corromper_marcador:
        (raiz / "RECOVERY_NOT_PROMOTABLE").write_bytes(b"CORRUPTED\n")
    destino.close()

    reaberto = _runtime(tmp_path, "a7d-destino")
    try:
        status, corpo = _json(reaberto, "GET", "/v1/recovery")
        assert status == 200, corpo
        assert corpo["recoveries"] == [
            {
                "recovery_id": staged["recovery_id"],
                "state": "RECOVERY_RETAINED",
                "summary": staged["summary"],
                "reason": "disposition_unreadable",
                "allowed_actions": ["RETRY_ABANDON"],
            }
        ]
        status, corpo = _json(
            reaberto,
            "POST",
            f"/v1/recovery/{staged['recovery_id']}/discard",
        )
        assert status == 409, corpo
        status, corpo = _json(
            reaberto,
            "POST",
            f"/v1/recovery/{staged['recovery_id']}/abandon",
            value={"confirm_abandon": True},
        )
        assert status == 200, corpo
        assert not raiz.exists()
    finally:
        reaberto.close()


def test_restart_preserva_irretomavel_mesmo_sem_arquivo_privado(tmp_path):
    """A autoridade publicada exige abandono explícito mesmo sem `.content`.

    A raiz também contém o banco staged e a trilha da operação. Inferir
    abandono pela ausência de um tipo de arquivo apagaria histórico sem a
    decisão do usuário.
    """
    _origem, _pkg, destino, recovery_id = _interromper_promocao(tmp_path, "r2d")
    journal = _journal_da_unica_raiz(tmp_path, "r2d")
    registro = json.loads(journal.read_text(encoding="utf-8"))
    journal.write_text(json.dumps({**registro, "phase": "UNRESUMABLE"}), encoding="utf-8")
    for material in journal.parent.rglob("*.content"):
        material.unlink()
    destino.close()

    reaberto = _runtime(tmp_path, "r2d")
    try:
        assert _raizes(tmp_path, "r2d"), "restart inferiu abandono sem autoridade"
        status, corpo = _json(reaberto, "GET", "/v1/recovery")
        assert status == 200, corpo
        assert corpo["recoveries"][0]["recovery_id"] == recovery_id
        assert corpo["recoveries"][0]["state"] == "RECOVERY_UNRESUMABLE"
        assert corpo["recoveries"][0]["allowed_actions"] == ["ABANDON"]
    finally:
        reaberto.close()


def test_pericia_parcial_editada_torna_a_recuperacao_irretomavel_e_descartavel(tmp_path):
    """RED R3 — retomar virou impossível, então prender o usuário é indefensável.

    A perícia meio-restaurada aparece na lista e é editável. Uma revisão nova
    quebra o prefixo, e nenhuma retomada futura pode convergir. O produto
    precisa DIZER isso e devolver a saída.
    """
    origem, _pkg, destino, recovery_id = _interromper_promocao(tmp_path, "r3")
    try:
        status, corpo = _json(
            destino,
            "POST",
            f"/v1/workspaces/{origem}/artifacts/LAUDO/laudo/revisions",
            value={"payload": {"texto": "trabalho novo do perito"}},
        )
        assert status == 201, corpo

        status, corpo = _promote(destino, recovery_id)
        assert status == 409, corpo
        assert corpo["error"]["code"] == "RECOVERY_UNRESUMABLE"

        status, corpo = _json(
            destino,
            "POST",
            f"/v1/recovery/{recovery_id}/abandon",
            value={"confirm_abandon": True},
        )
        assert status == 200, corpo
    finally:
        destino.close()


def test_identidade_perdida_com_journal_torna_irretomavel_sem_segunda_copia(tmp_path):
    """RED R4 — sem a identidade não dá para provar retomada; nem fabricar cópia."""
    _origem, package, destino, recovery_id = _interromper_promocao(tmp_path, "r4")
    try:
        journal = _journal_da_unica_raiz(tmp_path, "r4")
        (journal.parent / "STAGING_IDENTITY_V1").unlink()

        status, corpo = _promote(destino, recovery_id)
        assert status == 409, corpo
        assert corpo["error"]["code"] == "RECOVERY_UNRESUMABLE"

        # E não pode nascer uma SEGUNDA raiz com o material privado em claro.
        base = tmp_path / ".r4.sqlite3.recovery"
        status, corpo = _json(
            destino,
            "POST",
            f"/v1/recovery/{recovery_id}/abandon",
            value={"confirm_abandon": True},
        )
        assert status == 200, corpo
        assert [p for p in base.iterdir() if p.is_dir()] == []
    finally:
        destino.close()


# ------------------------------------------------------------------ S
# Terceira rodada terminal (A6/B6). A mesma classe causal reaparece sempre que
# uma condição TRANSITÓRIA é lida como veredito PERMANENTE.


def test_identidade_travada_nao_autoriza_destruir_a_retomada(tmp_path, monkeypatch):
    """RED S1 — prova ilegível AGORA não é prova ausente PARA SEMPRE.

    O código nomeia a mesma condição como transitória para o journal (antivírus,
    indexador, placeholder do OneDrive) e a tratava como permanente para a
    identidade: `except OSError: return None`. Como `None` classifica a raiz
    como IRRETOMÁVEL, o descarte passava a ser autorizado e apagava a autoridade
    de retomada — sem sequer exigir a declaração consciente.
    """
    import scripts.backend_contract.application.workspace_recovery as wr
    from scripts.backend_contract.infrastructure.productization import (
        abrir_staging_quarentenado,
    )

    _origem, _pkg, destino, _rid = _interromper_promocao(tmp_path, "s1")
    destino.close()
    journal = _journal_da_unica_raiz(tmp_path, "s1")
    assert (journal.parent / "STAGING_IDENTITY_V1").exists()

    staging = abrir_staging_quarentenado(journal.parent)
    original = wr.RecoveryFilesystemCustody.read_file
    try:

        def _travado(self, name):
            if self.path == journal.parent and name == "STAGING_IDENTITY_V1":
                raise PermissionError(13, "arquivo em uso")
            return original(self, name)

        monkeypatch.setattr(wr.RecoveryFilesystemCustody, "read_file", _travado)
        estado = wr._classificar_journal(staging)
        assert estado == wr._JOURNAL_INACESSIVEL, estado
    finally:
        staging.close()


def test_journal_travado_nao_fabrica_segunda_copia_do_material(tmp_path):
    """RED S2 — pular a raiz certa por leitura travada duplicava o sigiloso.

    Era a regressão exata do RED M, redisparada pelo estado "travado". Falhar
    fechado com motivo transitório é honesto; fabricar outra cópia integral em
    claro do material privado, não.
    """
    import scripts.backend_contract.application.workspace_recovery as wr

    _origem, package, destino, _rid = _interromper_promocao(tmp_path, "s2")
    try:
        base = tmp_path / ".s2.sqlite3.recovery"
        antes = [p for p in base.iterdir() if p.is_dir()]
        assert len(antes) == 1

        original = wr._journal_bruto
        wr._journal_bruto = lambda raiz: wr._JOURNAL_TRAVADO
        try:
            # Sem sessão viva na frente, a redescoberta cai na varredura do disco.
            destino._recovery_sessions._sessions.clear()
            status, corpo = _stage(destino, package)
        finally:
            wr._journal_bruto = original

        assert status >= 400, corpo
        depois = [p for p in base.iterdir() if p.is_dir()]
        assert depois == antes, "uma segunda cópia do material privado foi criada"
    finally:
        destino.close()


def test_journal_corrompido_sobrevive_a_reabertura_como_sobrevive_ao_fechamento(tmp_path):
    """RED S3 — `close_all` preservava e a varredura apagava a MESMA raiz.

    Duas polaridades para o mesmo fato. Inclui o caso de um build anterior
    encontrar journal de versão futura: apagar ali destrói o que o build novo
    saberia retomar.
    """
    _origem, _pkg, destino, _rid = _interromper_promocao(tmp_path, "s3")
    journal = _journal_da_unica_raiz(tmp_path, "s3")
    journal.write_bytes(b'{"version": 999, "phase": "PROMOTING"}')
    destino.close()

    base = tmp_path / ".s3.sqlite3.recovery"
    assert [p for p in base.iterdir() if p.is_dir()], "fechamento já destruiu"

    reaberto = _runtime(tmp_path, "s3")
    try:
        assert [p for p in base.iterdir() if p.is_dir()], "a reabertura destruiu"
    finally:
        reaberto.close()


def test_falha_antes_da_primeira_gravacao_viva_nao_afirma_pericia_parcial(tmp_path):
    """RED S4 — journal gravado != armazenamento vivo mutado.

    O journal é escrito ANTES da primeira mutação viva, de propósito. Tratar sua
    existência como prova de que algo já foi gravado faz o produto dizer "parte
    da perícia já foi gravada — NÃO descarte" quando nada foi, e força o usuário
    a declarar que aceita uma perícia incompleta que não existe.
    """
    origem, _ids, package = _origem_com_dois_privados(tmp_path, "s4-origem")
    destino = _runtime(tmp_path, "s4")
    try:
        status, staged = _stage(destino, package)
        assert status == 201, staged
        recovery_id = staged["recovery_id"]

        repositorio = destino._store.workspaces
        original = type(repositorio).create

        def _falha(self, *args, **kwargs):
            raise OSError(5, "falha de I/O antes de qualquer gravação viva")

        type(repositorio).create = _falha
        try:
            status, corpo = _promote(destino, recovery_id)
        finally:
            type(repositorio).create = original
        assert status >= 400, corpo

        # Nada vivo foi criado...
        status_lista, lista = _json(destino, "GET", "/v1/workspaces")
        assert status_lista == 200
        assert all(w["workspace_id"] != origem for w in lista["items"]), lista

        # ...logo o descarte comum precisa funcionar, sem declaração consciente.
        status, corpo = _json(destino, "POST", f"/v1/recovery/{recovery_id}/discard")
        assert status == 200, corpo
    finally:
        destino.close()


# --------------------------------------------------------------- A13 / B13
# A base de recovery também é autoridade. Custodiar apenas o filho já atravessou
# um namespace potencialmente externo e, portanto, chegou tarde demais.


@pytest.mark.parametrize(
    "external_layout",
    ("empty", "sentinel", "quarantine", "session", "journal", "cleanup-intent"),
)
def test_recovery_base_reparse_falha_antes_de_enumerar_ou_mutar_alvo_externo(tmp_path, monkeypatch, request, external_layout):
    """RED A13/B13 — ancestry não confiável implica zero traversal e zero mutação."""

    from scripts.backend_contract.application.ports import RepositoryIntegrityError

    name = f"trust-anchor-{external_layout}"
    recovery_id = "00000000-0000-4000-8000-000000000183"
    external = tmp_path / f"external-{external_layout}"
    external.mkdir()
    if external_layout != "empty":
        (external / "sentinel.bin").write_bytes(b"EXTERNAL-BYTES-MUST-NOT-CHANGE")
    if external_layout in {"quarantine", "session", "journal"}:
        child = external / f"recovery-{recovery_id}"
        child.mkdir()
        (child / "RECOVERY_NOT_PROMOTABLE").write_bytes(b"RECOVERY_STAGING_V1\n")
        if external_layout == "session":
            (child / "RECOVERY_SESSION_V1").write_text(json.dumps({"synthetic": "descriptor"}), encoding="utf-8")
        if external_layout == "journal":
            (child / "PROMOTION_TRANSACTION_V1").write_text(json.dumps({"version": 1, "phase": "PROMOTING"}), encoding="utf-8")
    if external_layout == "cleanup-intent":
        (external / f".recovery-cleanup-intent-{recovery_id}").write_bytes(_cleanup_intent_payload(recovery_id, "COLLECT"))

    base = tmp_path / f".{name}.sqlite3.recovery"
    _directory_reparse(base, external)
    request.addfinalizer(lambda: _remove_directory_reparse(base))
    before_hash = _external_tree_sha256(external)
    before_sentinel = (external / "sentinel.bin").read_bytes() if (external / "sentinel.bin").exists() else None
    original_iterdir = Path.iterdir
    enumerations = []

    def reject_path_enumeration(candidate):
        if candidate == base:
            enumerations.append(candidate)
            raise AssertionError("recovery base reparse was enumerated")
        return original_iterdir(candidate)

    monkeypatch.setattr(Path, "iterdir", reject_path_enumeration)
    runtime = None
    try:
        with pytest.raises(RepositoryIntegrityError):
            runtime = _runtime(tmp_path, name)
    finally:
        if runtime is not None:
            runtime.close()

    assert enumerations == []
    assert _external_tree_sha256(external) == before_hash
    if before_sentinel is not None:
        assert (external / "sentinel.bin").read_bytes() == before_sentinel


def test_parent_da_base_reparse_falha_antes_de_abrir_storage_ou_recovery(tmp_path, request):
    """A cadeia começa na raiz do volume, não no pai aparente do banco."""

    from scripts.backend_contract.application.ports import RepositoryIntegrityError

    external = tmp_path / "external-parent"
    external.mkdir()
    sentinel = external / "sentinel.bin"
    sentinel.write_bytes(b"PARENT-SENTINEL")
    parent = tmp_path / "redirected-parent"
    _directory_reparse(parent, external)
    request.addfinalizer(lambda: _remove_directory_reparse(parent))
    before = _external_tree_sha256(external)
    runtime = None
    try:
        with pytest.raises(RepositoryIntegrityError):
            runtime = _runtime(parent, "parent-reparse")
    finally:
        if runtime is not None:
            runtime.close()
    assert sentinel.read_bytes() == b"PARENT-SENTINEL"
    assert _external_tree_sha256(external) == before


@pytest.mark.parametrize("mode", ("COLLECT", "DISCARD", "ABANDON"))
@pytest.mark.parametrize("attempt", (1, 2), ids=("first-attempt", "retry"))
def test_cleanup_e_retentativa_sob_base_reparse_nao_publicam_intent_nem_removem(tmp_path, request, mode, attempt):
    """Startup/discard/abandon/retries compartilham o mesmo trust anchor."""

    from scripts.backend_contract.application import workspace_recovery as wr

    recovery_id = "00000000-0000-4000-8000-000000000184"
    external = tmp_path / f"external-cleanup-{mode}-{attempt}"
    child = external / f"recovery-{recovery_id}"
    child.mkdir(parents=True)
    (child / "RECOVERY_NOT_PROMOTABLE").write_bytes(b"RECOVERY_STAGING_V1\n")
    sentinel = child / "sentinel.bin"
    sentinel.write_bytes(b"CLEANUP-MUST-NOT-CROSS-NAMESPACE")
    base = tmp_path / f".cleanup-{mode}-{attempt}.sqlite3.recovery"
    _directory_reparse(base, external)
    request.addfinalizer(lambda: _remove_directory_reparse(base))
    root = base / child.name
    before = _external_tree_sha256(external)

    for _ in range(attempt):
        with pytest.raises(wr.RecoveryRetained):
            wr._remover_raiz_quarentenada(
                root,
                exigir_remocao=True,
                cleanup_mode=mode,
            )
        assert _external_tree_sha256(external) == before
        assert not (external / f".recovery-cleanup-intent-{recovery_id}").exists()
        assert sentinel.read_bytes() == b"CLEANUP-MUST-NOT-CROSS-NAMESPACE"


def test_cleanup_intent_gc_sob_base_reparse_nao_remove_sidecar_externo(tmp_path, request):
    """Root ausente só autoriza GC dentro de uma base continuamente custodiada."""

    from scripts.backend_contract.application import workspace_recovery as wr

    recovery_id = "00000000-0000-4000-8000-000000000185"
    external = tmp_path / "external-intent-gc"
    external.mkdir()
    intent = external / f".recovery-cleanup-intent-{recovery_id}"
    intent.write_bytes(_cleanup_intent_payload(recovery_id, "COLLECT"))
    sentinel = external / "sentinel.bin"
    sentinel.write_bytes(b"GC-MUST-NOT-CROSS-NAMESPACE")
    base = tmp_path / ".intent-gc.sqlite3.recovery"
    _directory_reparse(base, external)
    request.addfinalizer(lambda: _remove_directory_reparse(base))
    before = _external_tree_sha256(external)

    wr._coletar_cleanup_intent_apos_raiz_ausente(
        base / f"recovery-{recovery_id}",
        recovery_id,
    )

    assert intent.exists()
    assert sentinel.read_bytes() == b"GC-MUST-NOT-CROSS-NAMESPACE"
    assert _external_tree_sha256(external) == before


@pytest.mark.skipif(os.name != "nt", reason="Windows junction/rename custody")
@pytest.mark.parametrize("swap", ("late-junction", "base-rename"))
def test_staging_rejeita_troca_da_base_entre_validacao_e_criacao(tmp_path, monkeypatch, request, swap):
    """RED TOCTOU — validation e use precisam compartilhar os mesmos handles."""

    from scripts.backend_contract.application import workspace_recovery as wr
    from scripts.backend_contract.infrastructure.productization import RecoveryStaging

    base = tmp_path / f".{swap}.sqlite3.recovery"
    base.mkdir()
    parked = tmp_path / f"parked-{swap}"
    external = tmp_path / f"external-{swap}"
    external.mkdir()
    sentinel = external / "sentinel.bin"
    sentinel.write_bytes(b"TOCTOU-SENTINEL")
    root = base / "recovery-00000000-0000-4000-8000-000000000186"
    before = _external_tree_sha256(external)
    original_relative_open = wr._abrir_diretorio_windows_relativo
    injected = False
    swap_blocked = False

    def cleanup_swap():
        _remove_directory_reparse(base)
        if parked.exists() and not base.exists():
            parked.rename(base)

    request.addfinalizer(cleanup_swap)

    def swap_before_child_create(parent_handle, name, **kwargs):
        nonlocal injected, swap_blocked
        if not injected and kwargs.get("create") and name == root.name:
            injected = True
            try:
                base.rename(parked)
                _directory_reparse(base, external)
            except OSError:
                swap_blocked = True
        return original_relative_open(parent_handle, name, **kwargs)

    monkeypatch.setattr(
        wr,
        "_abrir_diretorio_windows_relativo",
        swap_before_child_create,
    )
    staging = None
    try:
        staging = RecoveryStaging.create(root)
    finally:
        monkeypatch.setattr(
            wr,
            "_abrir_diretorio_windows_relativo",
            original_relative_open,
        )
        if staging is not None:
            staging.close()
    assert injected
    assert swap_blocked
    assert not parked.exists()
    assert sentinel.read_bytes() == b"TOCTOU-SENTINEL"
    assert _external_tree_sha256(external) == before


def test_namespace_recovery_normal_continua_criando_listando_e_descartando(tmp_path):
    """Controle positivo: a defesa não torna o recovery local legítimo inutilizável."""

    origem, _ids, package = _origem_com_dois_privados(tmp_path, "anchor-normal-source")
    destino = _runtime(tmp_path, "anchor-normal-target")
    try:
        status, staged = _stage(destino, package)
        assert status == 201, staged
        status, listing = _json(destino, "GET", "/v1/recovery")
        assert status == 200, listing
        assert [item["recovery_id"] for item in listing["recoveries"]] == [staged["recovery_id"]]
        status, body = _json(destino, "POST", f"/v1/recovery/{staged['recovery_id']}/discard")
        assert status == 200, body
    finally:
        destino.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows late root rebind custody")
def test_reconstrucao_nao_le_alvo_externo_se_raiz_troca_apos_preflight(tmp_path, monkeypatch, request):
    """Sibling TOCTOU — o guard da raiz deve sobreviver ao preflight."""

    from scripts.backend_contract.application import workspace_recovery as wr

    recovery_id = "00000000-0000-4000-8000-000000000187"
    base = tmp_path / ".late-root.sqlite3.recovery"
    root = base / f"recovery-{recovery_id}"
    root.mkdir(parents=True)
    (root / "RECOVERY_NOT_PROMOTABLE").write_bytes(b"RECOVERY_STAGING_V1\n")
    parked = base / f"parked-{recovery_id}"
    external = tmp_path / "late-root-external"
    external.mkdir()
    (external / "RECOVERY_NOT_PROMOTABLE").write_bytes(b"RECOVERY_STAGING_V1\n")
    sentinel = external / "sentinel.bin"
    sentinel.write_bytes(b"LATE-ROOT-SENTINEL")
    before = _external_tree_sha256(external)
    original_preflight = wr._arvore_de_recuperacao_eh_segura
    original_read_bytes = Path.read_bytes
    external_reads = []
    swapped = False

    def cleanup_swap():
        _remove_directory_reparse(root)
        if parked.exists() and not root.exists():
            parked.rename(root)

    request.addfinalizer(cleanup_swap)

    def swap_after_preflight(candidate, custody=None):
        nonlocal swapped
        result = original_preflight(candidate, custody)
        if candidate == root and result and not swapped:
            swapped = True
            root.rename(parked)
            _directory_reparse(root, external)
        return result

    def record_external_read(path):
        if path.parent == root and swapped:
            external_reads.append(path.name)
        return original_read_bytes(path)

    monkeypatch.setattr(wr, "_arvore_de_recuperacao_eh_segura", swap_after_preflight)
    monkeypatch.setattr(Path, "read_bytes", record_external_read)
    sessions = wr.WorkspaceRecoverySessions()
    try:
        wr.reconstruir_sessoes_recuperacao(base, sessions, lambda _root: None)
    except (OSError, wr.RecoveryRetained, wr.RepositoryIntegrityError):
        pass

    assert external_reads == []
    assert sentinel.read_bytes() == b"LATE-ROOT-SENTINEL"
    assert _external_tree_sha256(external) == before


# --------------------------------------------------------------- A15 / B15 RED
# A14/B14 provaram que ancestry valida nao basta se a identidade nasce depois do
# create ou morre antes do delete. Estes REDs coordenam exatamente as duas
# janelas. Cada arvore e sintetica; o hash independente inclui nomes, tipos e
# bytes, e nenhum caso usa material de processo real.


@pytest.mark.skipif(os.name != "nt", reason="Windows atomic directory handle")
@pytest.mark.parametrize(
    ("created_level", "external_layout"),
    (
        ("base", "sentinel"),
        ("base", "canonical-quarantine"),
        ("child", "sentinel"),
        ("child", "canonical-quarantine"),
    ),
)
def test_identity_continuity_creation_binds_new_child_before_first_write(tmp_path, monkeypatch, created_level, external_layout):
    """RED 1-9,20-23: create+handle e uma operacao, nao duas por pathname.

    Cobre swap entre create/primeiro handle, swap imediatamente apos create,
    rename/parking do objeto novo, replacement externo (inclusive arvore
    logicamente valida) e a corrida anterior ao primeiro write. O oracle exige
    zero quarantine, SQLite, private material ou intent no substituto.
    """

    from scripts.backend_contract.application import workspace_recovery as wr
    from scripts.backend_contract.infrastructure.productization import RecoveryStaging

    base = tmp_path / (f".identity-create-{created_level}-{external_layout}.sqlite3.recovery")
    root = base / "recovery-00000000-0000-4000-8000-000000000216"
    if created_level == "child":
        base.mkdir()
    external = tmp_path / f"identity-create-external-{created_level}-{external_layout}"
    external.mkdir()
    sentinel = external / "external-sentinel.bin"
    sentinel.write_bytes(b"EXTERNAL-CREATION-TREE-MUST-NOT-CHANGE")
    if external_layout == "canonical-quarantine":
        (external / "RECOVERY_NOT_PROMOTABLE").write_bytes(b"RECOVERY_STAGING_V1\n")
    before = _external_tree_sha256(external)
    parked = tmp_path / f"identity-create-parked-{created_level}-{external_layout}"
    target = base if created_level == "base" else root
    original_open = wr._abrir_diretorio_windows_relativo
    attempted = False
    swapped = False
    swap_blocked = False

    def attempt_swap_while_created_handle_is_live(parent_handle, name, **kwargs):
        nonlocal attempted, swapped, swap_blocked
        result = original_open(parent_handle, name, **kwargs)
        if kwargs.get("create") and name == target.name and target.exists() and not attempted:
            attempted = True
            try:
                target.rename(parked)
                external.rename(target)
                swapped = True
            except OSError:
                swap_blocked = True
        return result

    monkeypatch.setattr(
        wr,
        "_abrir_diretorio_windows_relativo",
        attempt_swap_while_created_handle_is_live,
    )
    staging = None
    try:
        staging = RecoveryStaging.create(root)
    finally:
        monkeypatch.setattr(wr, "_abrir_diretorio_windows_relativo", original_open)
        if staging is not None:
            staging.close()

    assert attempted is True
    assert swap_blocked is True
    assert swapped is False
    assert parked.exists() is False
    assert external.exists()
    assert sentinel.read_bytes() == b"EXTERNAL-CREATION-TREE-MUST-NOT-CHANGE"
    assert _external_tree_sha256(external) == before
    assert not (external / "workspace.sqlite3").exists()
    assert not (external / "private").exists()
    assert not list(external.rglob("*.content"))
    assert not list(external.rglob(".recovery-cleanup-intent-*"))


def test_identity_continuity_creation_normal_control(tmp_path):
    """RED 10: sem ataque, child ligado recebe a primeira escrita e reabre."""

    from scripts.backend_contract.infrastructure.productization import (
        RecoveryStaging,
        abrir_staging_quarentenado,
    )

    root = tmp_path / ".identity-create-control.sqlite3.recovery" / "recovery-00000000-0000-4000-8000-000000000217"
    staging = RecoveryStaging.create(root)
    identity = staging.filesystem_identity
    staging.close()
    reopened = abrir_staging_quarentenado(root)
    try:
        assert reopened.filesystem_identity == identity
        assert (root / "RECOVERY_NOT_PROMOTABLE").read_bytes() == (b"RECOVERY_STAGING_V1\n")
        assert (root / "workspace.sqlite3").is_file()
        assert (root / "private").is_dir()
    finally:
        reopened.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows custody handle duplication")
def test_identity_continuity_duplicate_failure_closes_every_created_handle(
    tmp_path,
    monkeypatch,
):
    """Falha ABI/handle antes do binding não escreve nem deixa child inamovível."""

    from scripts.backend_contract.application import workspace_recovery as wr

    base = tmp_path / ".identity-duplicate-failure.sqlite3.recovery"
    root = base / "recovery-00000000-0000-4000-8000-000000000222"
    base.mkdir()
    base_custody = wr.RecoveryFilesystemCustody.acquire(base)
    assert base_custody is not None
    original_duplicate = wr._duplicar_handle_windows
    calls = 0

    def fail_after_one_duplicate(handle):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic DuplicateHandle failure")
        return original_duplicate(handle)

    monkeypatch.setattr(wr, "_duplicar_handle_windows", fail_after_one_duplicate)
    with pytest.raises(OSError, match="synthetic DuplicateHandle"):
        base_custody.create_child(root.name)
    base_custody.close()

    assert calls == 2
    assert root.exists()
    assert list(root.iterdir()) == []
    parked = tmp_path / "identity-duplicate-failure-parked"
    root.rename(parked)
    assert parked.exists()


class _SwapRecoveryAfterRealClose:
    """Probe B14: rebind exatamente depois de a custody da sessao sair."""

    def __init__(self, staging, parked: Path, replacement: Path):
        self._staging = staging
        self.root = staging.root
        self._parked = parked
        self._replacement = replacement

    @property
    def filesystem_identity(self):
        return self._staging.filesystem_identity

    def duplicar_custodia_filesystem(self):
        return self._staging.duplicar_custodia_filesystem()

    def discard(self):
        self._staging.discard()
        Path(self.root).rename(self._parked)
        self._replacement.rename(self.root)


@pytest.mark.skipif(os.name != "nt", reason="Windows recovery identity rebind")
@pytest.mark.parametrize("mode", ("DISCARD", "ABANDON"))
@pytest.mark.parametrize("logical_clone", (False, True), ids=("sentinel", "byte-identical-controls"))
def test_identity_continuity_removal_rejects_replacement_after_session_close(tmp_path, mode, logical_clone):
    """RED 13-18,20-23: retry conserva o objeto escolhido, nao o pathname.

    A recovery verdadeira e estacionada e uma arvore externa assume o nome. Ate
    com controles byte-identicos ela tem identidade fisica distinta. Cleanup
    deve reter, preservar bytes externos e o intent, repetir a mesma decisao e
    so convergir quando a identidade original volta ao namespace.
    """

    from scripts.backend_contract.application import workspace_recovery as wr
    from scripts.backend_contract.infrastructure.productization import RecoveryStaging

    recovery_id = "00000000-0000-4000-8000-000000000218"
    base = tmp_path / f".identity-remove-{mode}-{logical_clone}.sqlite3.recovery"
    root = base / f"recovery-{recovery_id}"
    staging = RecoveryStaging.create(root)
    if logical_clone:
        _ = staging.identidade
    expected_identity = staging.filesystem_identity
    parked = tmp_path / f"identity-remove-parked-{mode}-{logical_clone}"
    external = tmp_path / f"identity-remove-external-{mode}-{logical_clone}"
    external.mkdir()
    sentinel = external / "external-sentinel.bin"
    sentinel.write_bytes(b"EXTERNAL-REMOVAL-TREE-MUST-NOT-CHANGE")
    if logical_clone:
        for control in ("RECOVERY_NOT_PROMOTABLE", "STAGING_IDENTITY_V1"):
            source = root / control
            if source.exists():
                (external / control).write_bytes(source.read_bytes())
    external_custody = wr.RecoveryFilesystemCustody.acquire(external)
    assert external_custody is not None
    try:
        replacement_identity = external_custody.identity
    finally:
        external_custody.close()
    assert replacement_identity != expected_identity
    before = _external_tree_sha256(external)

    wrapper = _SwapRecoveryAfterRealClose(staging, parked, external)
    entry = {"staging": wrapper, "root": root, "disposition": None}
    wr._gravar_disposition(entry, recovery_id, mode)
    with pytest.raises(wr.RecoveryRetained):
        wr._remover_entry(entry, mode)

    assert entry["staging"] is None
    assert parked.exists(), "a recovery original deve permanecer recuperavel"
    assert root.exists(), "o replacement nunca pode ser apagado"
    assert (root / sentinel.name).read_bytes() == (b"EXTERNAL-REMOVAL-TREE-MUST-NOT-CHANGE")
    assert _external_tree_sha256(root) == before
    intent_path = base / f".recovery-cleanup-intent-{recovery_id}"
    intent = json.loads(intent_path.read_text(encoding="utf-8"))
    assert intent["mode"] == mode
    assert intent["filesystem_identity"]["parts"] == list(expected_identity)

    # Simula restart/memoria perdida: a decisao deve voltar do intent, nao ser
    # inferida da arvore substituta que agora ocupa o mesmo pathname.
    entry.pop("expected_filesystem_identity")
    with pytest.raises(wr.RecoveryRetained):
        wr._gravar_disposition(entry, recovery_id, mode)

    # Retry nao pode readquirir a identidade do replacement pelo mesmo pathname.
    with pytest.raises(wr.RecoveryRetained):
        wr._remover_entry(entry, mode)
    assert _external_tree_sha256(root) == before
    assert json.loads(intent_path.read_text(encoding="utf-8"))["mode"] == mode

    # O ambiente do teste restaura a identidade original ao nome canonico. O
    # mesmo intent agora converge sem nova decisao e sem tocar a arvore externa.
    root.rename(external)
    parked.rename(root)
    wr._remover_entry(entry, mode)
    assert not root.exists()
    assert not intent_path.exists()
    assert sentinel.read_bytes() == b"EXTERNAL-REMOVAL-TREE-MUST-NOT-CHANGE"
    assert _external_tree_sha256(external) == before


@pytest.mark.skipif(os.name != "nt", reason="Windows handle-bound final removal")
@pytest.mark.parametrize(
    "coordination_point",
    ("after-last-internal-unlink", "before-pathname-rmdir"),
)
def test_identity_continuity_final_removal_never_closes_before_commit(tmp_path, monkeypatch, coordination_point):
    """RED 11-17: o A14 late swap nao pode alcançar um `rmdir(path)`."""

    from scripts.backend_contract.application import workspace_recovery as wr
    from scripts.backend_contract.infrastructure.productization import RecoveryStaging

    recovery_id = "00000000-0000-4000-8000-000000000219"
    base = tmp_path / f".identity-final-{coordination_point}.sqlite3.recovery"
    root = base / f"recovery-{recovery_id}"
    staging = RecoveryStaging.create(root)
    expected_identity = staging.filesystem_identity
    staging.close()

    external_parent = tmp_path / f"identity-final-external-{coordination_point}"
    external_victim = external_parent / "external-empty-directory"
    external_victim.mkdir(parents=True)
    sentinel = external_parent / "external-sentinel.bin"
    sentinel.write_bytes(b"EXTERNAL-FINAL-RMDIR-MUST-NOT-CHANGE")
    before = _external_tree_sha256(external_parent)
    parked = tmp_path / f"identity-final-parked-{coordination_point}"
    original_rmdir = Path.rmdir
    swap_attempted = False
    swapped = False

    def swap_when_pathname_rmdir_is_reached(path, *args, **kwargs):
        nonlocal swap_attempted, swapped
        if Path(path) == root and not swap_attempted:
            swap_attempted = True
            root.rename(parked)
            external_victim.rename(root)
            swapped = True
        return original_rmdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "rmdir", swap_when_pathname_rmdir_is_reached)
    wr._remover_raiz_quarentenada(
        root,
        exigir_remocao=True,
        cleanup_mode="ABANDON",
        expected_filesystem_identity=expected_identity,
    )

    assert swap_attempted is False
    assert swapped is False
    assert not parked.exists()
    assert not root.exists()
    assert external_victim.exists()
    assert sentinel.read_bytes() == b"EXTERNAL-FINAL-RMDIR-MUST-NOT-CHANGE"
    assert _external_tree_sha256(external_parent) == before
    assert not (base / f".recovery-cleanup-intent-{recovery_id}").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows handle-bound final removal")
def test_identity_continuity_replacement_after_exact_close_blocks_intent_gc(
    tmp_path,
    monkeypatch,
):
    """RED 11-18,20-23: replacement presente antes do GC nunca vira sucesso."""

    from scripts.backend_contract.application import workspace_recovery as wr
    from scripts.backend_contract.infrastructure.productization import RecoveryStaging

    recovery_id = "00000000-0000-4000-8000-000000000221"
    base = tmp_path / ".identity-post-close.sqlite3.recovery"
    root = base / f"recovery-{recovery_id}"
    staging = RecoveryStaging.create(root)
    expected_identity = staging.filesystem_identity
    staging.close()

    external_parent = tmp_path / "identity-post-close-external"
    replacement = external_parent / "replacement"
    replacement.mkdir(parents=True)
    sentinel = replacement / "external-sentinel.bin"
    sentinel.write_bytes(b"EXTERNAL-POST-CLOSE-MUST-NOT-CHANGE")
    before = _external_tree_sha256(replacement)
    original_remove = wr._remover_diretorio_windows_ancorado
    injected = False

    def inject_after_exact_handle_close(node):
        nonlocal injected
        result = original_remove(node)
        if node.path == root and not injected:
            replacement.rename(root)
            injected = True
        return result

    monkeypatch.setattr(
        wr,
        "_remover_diretorio_windows_ancorado",
        inject_after_exact_handle_close,
    )
    with pytest.raises(wr.RecoveryRetained):
        wr._remover_raiz_quarentenada(
            root,
            exigir_remocao=True,
            cleanup_mode="DISCARD",
            expected_filesystem_identity=expected_identity,
        )

    assert injected is True
    assert root.exists()
    assert not replacement.exists()
    assert _external_tree_sha256(root) == before
    assert (root / sentinel.name).read_bytes() == (b"EXTERNAL-POST-CLOSE-MUST-NOT-CHANGE")
    intent_path = base / f".recovery-cleanup-intent-{recovery_id}"
    intent = json.loads(intent_path.read_text(encoding="utf-8"))
    assert intent["filesystem_identity"]["parts"] == list(expected_identity)

    with pytest.raises(wr.RecoveryRetained):
        wr._remover_raiz_quarentenada(
            root,
            exigir_remocao=True,
            cleanup_mode="DISCARD",
        )
    assert _external_tree_sha256(root) == before
    assert intent_path.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows handle-bound final removal")
def test_identity_continuity_ambiguous_exact_close_retains_intent(
    tmp_path,
    monkeypatch,
):
    """Close ambíguo consome o handle uma vez, sem converter ausência em sucesso."""

    from scripts.backend_contract.application import workspace_recovery as wr
    from scripts.backend_contract.infrastructure.productization import RecoveryStaging

    recovery_id = "00000000-0000-4000-8000-000000000223"
    base = tmp_path / ".identity-ambiguous-close.sqlite3.recovery"
    root = base / f"recovery-{recovery_id}"
    staging = RecoveryStaging.create(root)
    expected_identity = staging.filesystem_identity
    staging.close()
    original_remove = wr._remover_diretorio_windows_ancorado
    injected = False

    def close_exact_then_report_failure(node):
        nonlocal injected
        result = original_remove(node)
        if node.path == root and not injected:
            injected = True
            raise OSError("synthetic ambiguous exact close")
        return result

    monkeypatch.setattr(
        wr,
        "_remover_diretorio_windows_ancorado",
        close_exact_then_report_failure,
    )
    with pytest.raises(wr.RecoveryRetained):
        wr._remover_raiz_quarentenada(
            root,
            exigir_remocao=True,
            cleanup_mode="DISCARD",
            expected_filesystem_identity=expected_identity,
        )

    assert injected is True
    assert not root.exists()
    intent_path = base / f".recovery-cleanup-intent-{recovery_id}"
    intent = json.loads(intent_path.read_text(encoding="utf-8"))
    assert intent["filesystem_identity"]["parts"] == list(expected_identity)

    wr._coletar_cleanup_intent_apos_raiz_ausente(root, recovery_id)
    assert intent_path.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows handle-bound final removal")
def test_identity_continuity_collect_retry_uses_prior_intent_after_controls(
    tmp_path,
    monkeypatch,
):
    """Intent COLLECT preexistente substitui controles consumidos no retry."""

    from scripts.backend_contract.application import workspace_recovery as wr
    from scripts.backend_contract.infrastructure.productization import RecoveryStaging

    recovery_id = "00000000-0000-4000-8000-000000000224"
    base = tmp_path / ".identity-collect-retry.sqlite3.recovery"
    root = base / f"recovery-{recovery_id}"
    staging = RecoveryStaging.create(root)
    expected_identity = staging.filesystem_identity
    staging.close()
    original_remove = wr._remover_diretorio_windows_ancorado
    injected = False

    def fail_root_once_after_controls(node):
        nonlocal injected
        if node.path == root and not injected:
            injected = True
            raise PermissionError(13, "synthetic automatic collect interruption")
        return original_remove(node)

    monkeypatch.setattr(
        wr,
        "_remover_diretorio_windows_ancorado",
        fail_root_once_after_controls,
    )
    wr._remover_raiz_quarentenada(
        root,
        cleanup_mode="COLLECT",
        expected_filesystem_identity=expected_identity,
    )
    assert injected is True
    assert root.exists()
    assert list(root.iterdir()) == []
    intent_path = base / f".recovery-cleanup-intent-{recovery_id}"
    assert intent_path.exists()

    monkeypatch.setattr(
        wr,
        "_remover_diretorio_windows_ancorado",
        original_remove,
    )
    wr._remover_raiz_quarentenada(root, cleanup_mode="COLLECT")
    assert not root.exists()
    assert not intent_path.exists()


def test_identity_continuity_removal_normal_control(tmp_path):
    """RED 19: commit positivo remove a identidade exata e libera o intent."""

    from scripts.backend_contract.application import workspace_recovery as wr
    from scripts.backend_contract.infrastructure.productization import RecoveryStaging

    recovery_id = "00000000-0000-4000-8000-000000000220"
    base = tmp_path / ".identity-remove-control.sqlite3.recovery"
    root = base / f"recovery-{recovery_id}"
    staging = RecoveryStaging.create(root)
    expected_identity = staging.filesystem_identity
    staging.close()

    wr._remover_raiz_quarentenada(
        root,
        exigir_remocao=True,
        cleanup_mode="DISCARD",
        expected_filesystem_identity=expected_identity,
    )
    assert not root.exists()
    assert not (base / f".recovery-cleanup-intent-{recovery_id}").exists()


def test_posix_create_child_attack_path_is_unreachable(monkeypatch):
    """POSIX mutable recovery rejects before mkdirat/openat acquisition."""

    from scripts.backend_contract.application import workspace_recovery as wr

    directory = SimpleNamespace(st_dev=7, st_ino=11, st_mode=stat.S_IFDIR | 0o700)
    o_directory = 0x10000
    o_nofollow = 0x20000
    opened = []
    duplicated = []
    closed = []

    def fake_open(name, flags, mode=0o777, *, dir_fd=None):
        opened.append((name, flags, dir_fd))
        assert name == "recovery-00000000-0000-4000-8000-000000000301"
        assert dir_fd == 41
        return 42

    def fake_dup(descriptor):
        duplicated.append(descriptor)
        return 43

    def forbidden_acquire(cls, *_args, **_kwargs):
        raise AssertionError("global pathname reacquisition after parent dir_fd")

    fake_os = SimpleNamespace(
        name="posix",
        O_RDONLY=os.O_RDONLY,
        O_DIRECTORY=o_directory,
        O_NOFOLLOW=o_nofollow,
        mkdir=lambda name, mode, *, dir_fd: None,
        open=fake_open,
        fstat=lambda descriptor: directory,
        dup=fake_dup,
        close=closed.append,
    )
    monkeypatch.setattr(wr, "os", fake_os)
    monkeypatch.setattr(wr.RecoveryFilesystemCustody, "acquire", classmethod(forbidden_acquire))

    parent = wr.RecoveryFilesystemCustody(Path("C:/trusted/recovery"), [41], [(7, 10, stat.S_IFDIR)])
    with pytest.raises(wr.RecoveryPlatformUnsupported):
        parent.create_child("recovery-00000000-0000-4000-8000-000000000301")
    assert opened == []
    assert duplicated == []
    parent.close()
    assert closed == [41]


def test_posix_cleanup_root_acquisition_attack_path_is_unreachable(monkeypatch):
    """POSIX cleanup rejects before statat/openat root acquisition."""

    from scripts.backend_contract.application import workspace_recovery as wr

    directory = SimpleNamespace(st_dev=8, st_ino=21, st_mode=stat.S_IFDIR | 0o700)
    o_directory = 0x10000
    o_nofollow = 0x20000
    stat_calls = []
    open_calls = []
    closed = []
    def fake_stat(name, *, dir_fd, follow_symlinks):
        stat_calls.append((name, dir_fd, follow_symlinks))
        return directory

    def fake_open(name, flags, *, dir_fd):
        open_calls.append((name, flags, dir_fd))
        return 52

    fake_os = SimpleNamespace(
        name="posix",
        O_RDONLY=os.O_RDONLY,
        O_DIRECTORY=o_directory,
        O_NOFOLLOW=o_nofollow,
        stat=fake_stat,
        open=fake_open,
        fstat=lambda descriptor: directory,
        scandir=lambda descriptor: _EmptyScandir(),
        close=closed.append,
        lstat=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("global pathname reacquisition in POSIX cleanup")
        ),
    )
    monkeypatch.setattr(wr, "os", fake_os)

    with pytest.raises(wr.RecoveryPlatformUnsupported):
        wr._adquirir_custodia_cleanup(
            Path("C:/trusted/recovery/recovery-00000000-0000-4000-8000-000000000302"),
            parent_posix_fd=51,
            expected_filesystem_identity=(8, 21, stat.S_IFDIR),
        )
    assert stat_calls == []
    assert open_calls == []
    assert closed == []


def test_posix_child_rmdir_attack_path_is_unreachable(monkeypatch):
    """POSIX cleanup rejects before statat/fstat/rmdirat on a child."""

    from scripts.backend_contract.application import workspace_recovery as wr

    rmdir_calls = []
    expected = SimpleNamespace(st_dev=8, st_ino=21, st_mode=stat.S_IFDIR, st_nlink=2)
    substitute = SimpleNamespace(st_dev=8, st_ino=22, st_mode=stat.S_IFDIR, st_nlink=2)
    node = wr._CleanupNode(
        Path("/trusted/recovery/private"),
        "private",
        (8, 21, stat.S_IFDIR),
        52,
        None,
        [],
        [],
    )
    fake_os = SimpleNamespace(
        name="posix",
        stat=lambda name, *, dir_fd, follow_symlinks: substitute,
        fstat=lambda descriptor: expected,
        rmdir=lambda name, *, dir_fd: rmdir_calls.append((name, dir_fd)),
    )
    monkeypatch.setattr(wr, "os", fake_os)

    with pytest.raises(wr.RecoveryPlatformUnsupported):
        wr._remover_diretorio_posix_ancorado(
            51,
            node,
            "private",
            (8, 21, stat.S_IFDIR),
        )

    assert rmdir_calls == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX dir_fd namespace semantics")
def test_posix_first_writes_follow_child_fd_after_global_name_rebind(tmp_path, monkeypatch):
    """RED POSIX: quarentena/SQLite/private devem atingir o child_fd estacionado."""

    from scripts.backend_contract.application import workspace_recovery as wr
    from scripts.backend_contract.infrastructure.productization import RecoveryStaging

    base = tmp_path / ".posix-create-rebind.sqlite3.recovery"
    root = base / "recovery-00000000-0000-4000-8000-000000000303"
    parked = base / "parked-original"
    original = wr.RecoveryFilesystemCustody.create_child

    def create_then_rebind(self, name):
        custody = original(self, name)
        root.rename(parked)
        root.mkdir(mode=0o700)
        return custody

    monkeypatch.setattr(wr.RecoveryFilesystemCustody, "create_child", create_then_rebind)
    with pytest.raises(wr.RecoveryRetained):
        RecoveryStaging.create(root)

    assert tuple(root.iterdir()) == ()
    assert (parked / "RECOVERY_NOT_PROMOTABLE").read_bytes() == b"RECOVERY_STAGING_V1\n"
    assert not (parked / "workspace.sqlite3").exists()
    assert not (parked / "private").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX dir_fd namespace semantics")
def test_posix_sqlite_and_private_bootstrap_follow_child_fd_after_late_rebind(tmp_path, monkeypatch):
    """RED POSIX: SQLite/private nao podem atingir o substituto apos o bind."""

    from scripts.backend_contract.application import workspace_recovery as wr
    from scripts.backend_contract.infrastructure.productization import RecoveryStaging

    base = tmp_path / ".posix-bootstrap-rebind.sqlite3.recovery"
    root = base / "recovery-00000000-0000-4000-8000-000000000307"
    parked = base / "parked-original"
    original = wr.RecoveryFilesystemCustody.descriptor_relative_path
    rebound = False

    def descriptor_path_then_rebind(self, name):
        nonlocal rebound
        result = original(self, name)
        if self.path == root and name == "workspace.sqlite3" and not rebound:
            rebound = True
            root.rename(parked)
            root.mkdir(mode=0o700)
        return result

    monkeypatch.setattr(
        wr.RecoveryFilesystemCustody,
        "descriptor_relative_path",
        descriptor_path_then_rebind,
    )
    with pytest.raises(wr.RecoveryRetained):
        RecoveryStaging.create(root)

    assert rebound is True
    assert tuple(root.iterdir()) == ()
    assert (parked / "workspace.sqlite3").is_file()
    assert (parked / "private" / ".recovery-not-promotable").is_file()


@pytest.mark.skipif(os.name != "posix", reason="POSIX dir_fd namespace semantics")
def test_posix_session_identity_and_journal_follow_child_fd_after_rebind(tmp_path, monkeypatch):
    """RED POSIX: controles tardios nao podem voltar ao pathname de recovery."""

    from scripts.backend_contract.application import workspace_recovery as wr
    from scripts.backend_contract.infrastructure.productization import RecoveryStaging

    base = tmp_path / ".posix-controls-rebind.sqlite3.recovery"
    recovery_id = "00000000-0000-4000-8000-000000000304"
    root = base / f"recovery-{recovery_id}"
    staging = RecoveryStaging.create(root)
    summary = wr.BackupSummary(
        workspace_id="00000000-0000-4000-8000-000000000401",
        workspace_name="Synthetic",
        workspace_created_at="2026-09-08T00:00:00+00:00",
        product_release="0.11.0",
        storage_schema_version=1,
        artifact_revisions=0,
        private_contents=0,
        backup_sha256="a" * 64,
    )
    original_publish = wr.RecoveryFilesystemCustody.publish_immutable_file

    def exercise_immutable_control(control_name, operation, parked_name):
        parked = base / parked_name
        swapped = False

        def publish_after_rebind(self, name, payload):
            nonlocal swapped
            if self.path == root and name == control_name and not swapped:
                swapped = True
                root.rename(parked)
                root.mkdir(mode=0o700)
            return original_publish(self, name, payload)

        monkeypatch.setattr(
            wr.RecoveryFilesystemCustody,
            "publish_immutable_file",
            publish_after_rebind,
        )
        with pytest.raises(wr.RecoveryRetained):
            operation()
        assert swapped is True
        assert not (root / control_name).exists()
        assert (parked / control_name).is_file()
        monkeypatch.setattr(
            wr.RecoveryFilesystemCustody,
            "publish_immutable_file",
            original_publish,
        )
        root.rmdir()
        parked.rename(root)

    exercise_immutable_control(
        "STAGING_IDENTITY_V1",
        lambda: staging.identidade,
        "parked-identity",
    )
    identity = staging.identidade
    exercise_immutable_control(
        "RECOVERY_SESSION_V1",
        lambda: wr._gravar_session_descriptor(staging, recovery_id, summary, "b" * 64),
        "parked-session",
    )

    parked_journal = base / "parked-journal"
    original_write = wr.RecoveryFilesystemCustody.write_new_file
    swapped_journal = False

    def write_journal_after_rebind(self, name, payload):
        nonlocal swapped_journal
        if self.path == root and name.startswith(".PROMOTION_TRANSACTION_V1.") and not swapped_journal:
            swapped_journal = True
            root.rename(parked_journal)
            root.mkdir(mode=0o700)
        return original_write(self, name, payload)

    monkeypatch.setattr(wr.RecoveryFilesystemCustody, "write_new_file", write_journal_after_rebind)
    with pytest.raises(wr.RecoveryRetained):
        staging.gravar_transacao(
            {
                "version": wr.JOURNAL_VERSION,
                "phase": wr.PROMOTING,
                "staging_identity": identity,
            }
        )
    staging.close()

    assert swapped_journal is True
    assert not (root / "PROMOTION_TRANSACTION_V1").exists()
    assert (parked_journal / "PROMOTION_TRANSACTION_V1").is_file()


@pytest.mark.skipif(os.name != "posix", reason="POSIX dir_fd namespace semantics")
def test_posix_final_rmdir_preserves_rebound_substitute_and_cleanup_intent(tmp_path, monkeypatch):
    """RED POSIX: swap pre-rmdirat retem substituto, original e intent."""

    from scripts.backend_contract.application import workspace_recovery as wr
    from scripts.backend_contract.infrastructure.productization import RecoveryStaging

    recovery_id = "00000000-0000-4000-8000-000000000305"
    base = tmp_path / ".posix-cleanup-rebind.sqlite3.recovery"
    root = base / f"recovery-{recovery_id}"
    parked = base / "parked-original"
    staging = RecoveryStaging.create(root)
    expected_identity = staging.filesystem_identity
    staging.close()
    original = wr._adquirir_custodia_cleanup
    rebound = False

    def acquire_then_rebind(path, **kwargs):
        nonlocal rebound
        node = original(path, **kwargs)
        if not rebound and Path(path) == root:
            rebound = True
            root.rename(parked)
            root.mkdir(mode=0o700)
        return node

    monkeypatch.setattr(wr, "_adquirir_custodia_cleanup", acquire_then_rebind)
    with pytest.raises(wr.RecoveryRetained):
        wr._remover_raiz_quarentenada(
            root,
            exigir_remocao=True,
            cleanup_mode="DISCARD",
            expected_filesystem_identity=expected_identity,
        )

    assert rebound is True
    assert root.is_dir()
    assert parked.is_dir()
    assert (base / f".recovery-cleanup-intent-{recovery_id}").is_file()


@pytest.mark.skipif(os.name != "posix", reason="POSIX dir_fd namespace semantics")
def test_posix_child_rmdir_preserves_rebound_substitute_and_cleanup_intent(tmp_path, monkeypatch):
    """RED POSIX: swap do filho pre-rmdirat nao pode consumir o substituto."""

    from scripts.backend_contract.application import workspace_recovery as wr
    from scripts.backend_contract.infrastructure.productization import RecoveryStaging

    recovery_id = "00000000-0000-4000-8000-000000000306"
    base = tmp_path / ".posix-child-cleanup-rebind.sqlite3.recovery"
    root = base / f"recovery-{recovery_id}"
    parked = base / "parked-private"
    staging = RecoveryStaging.create(root)
    expected_identity = staging.filesystem_identity
    staging.close()
    original = wr._remover_diretorio_posix_ancorado
    rebound = False

    def remove_after_rebind(parent_directory_fd, node, name, expected):
        nonlocal rebound
        if not rebound and name == "private":
            rebound = True
            (root / "private").rename(parked)
            (root / "private").mkdir(mode=0o700)
        return original(parent_directory_fd, node, name, expected)

    monkeypatch.setattr(wr, "_remover_diretorio_posix_ancorado", remove_after_rebind)
    with pytest.raises(wr.RecoveryRetained):
        wr._remover_raiz_quarentenada(
            root,
            exigir_remocao=True,
            cleanup_mode="DISCARD",
            expected_filesystem_identity=expected_identity,
        )

    assert rebound is True
    assert (root / "private").is_dir()
    assert parked.is_dir()
    assert (base / f".recovery-cleanup-intent-{recovery_id}").is_file()


@pytest.mark.skipif(os.name != "posix", reason="POSIX dir_fd namespace semantics")
def test_posix_discard_keeps_child_fd_authoritative_through_cleanup(tmp_path):
    """RED POSIX: fechar stores não pode encerrar a custody antes do cleanup."""

    from scripts.backend_contract.application import workspace_recovery as wr
    from scripts.backend_contract.infrastructure.productization import RecoveryStaging

    recovery_id = "00000000-0000-4000-8000-000000000306"
    base = tmp_path / ".posix-lifecycle-rebind.sqlite3.recovery"
    root = base / f"recovery-{recovery_id}"
    parked = base / "parked-original"
    replacement = tmp_path / "external-substitute"
    replacement.mkdir(mode=0o700)
    (replacement / "external-sentinel.bin").write_bytes(b"DO-NOT-MUTATE")
    staging = RecoveryStaging.create(root)
    wrapper = _SwapRecoveryAfterRealClose(staging, parked, replacement)
    entry = {"staging": wrapper, "root": root, "disposition": None}
    wr._gravar_disposition(entry, recovery_id, "DISCARD")

    with pytest.raises(wr.RecoveryRetained):
        wr._remover_entry(entry, "DISCARD")

    assert (root / "external-sentinel.bin").read_bytes() == b"DO-NOT-MUTATE"
    assert parked.is_dir()
    assert (base / f".recovery-cleanup-intent-{recovery_id}").is_file()
