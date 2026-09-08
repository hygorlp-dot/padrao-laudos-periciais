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
import os
import subprocess
import threading
from pathlib import Path

import pytest

from tests.test_backup_recovery_reachability_v1 import (
    _api,
    _json,
    _pdf_grande,
    _runtime,
    _slow_request,
    _workspace_with_material,
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
    ),
)
def test_matriz_estado_comando_expoe_somente_acoes_seguras(
    tmp_path, state, disposition, discoverable, allowed
):
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
            runtime, "POST", f"/v1/workspaces/{workspace_id}/materials",
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
        runtime, "POST", "/v1/recovery/staging", body=package,
        headers={"Content-Type": "application/octet-stream"},
    )
    return status, staged


def _promote(runtime, recovery_id):
    return _json(
        runtime, "POST", f"/v1/recovery/{recovery_id}/promote", value={"confirm": True}
    )


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
        assert {i["content_id"] for i in itens} == {
            primeiro["content_id"], segundo["content_id"]
        }
        assert {i["checksum_sha256"] for i in itens} == {
            primeiro["checksum_sha256"], segundo["checksum_sha256"]
        }
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
        assert status == 200, (
            f"promoção interrompida não é retomável após reinício: {resultado}"
        )
        itens = _materiais(alvo2, workspace_id)
        assert itens is not None and len(itens) == 2, (
            f"conteúdo privado incompleto após reinício: {itens and len(itens)}/2"
        )
        assert {i["checksum_sha256"] for i in itens} == {
            primeiro["checksum_sha256"], segundo["checksum_sha256"]
        }
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
        resultados["discard"] = _json(
            runtime, "POST", f"/v1/recovery/{recovery_id}/discard"
        )[0]

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
            assert not (venceu_promote and venceu_discard), (
                f"[{atraso}ms] PROMOTE e DISCARD venceram juntos: {resultados}"
            )

            itens = _materiais(alvo, workspace_id)
            if venceu_promote:
                assert itens is not None and len(itens) == 2, (
                    f"[{atraso}ms] promoção venceu mas ficou parcial: {itens and len(itens)}/2"
                )
            else:
                assert itens is None, (
                    f"[{atraso}ms] workspace FANTASMA: promote={resultados.get('promote')} "
                    f"discard={resultados.get('discard')} materiais={len(itens)}"
                )
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
        assert itens is not None and len(itens) == 2, (
            f"estado final inconsistente: {itens and len(itens)}/2"
        )
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


def test_restage_concorrente_com_descarte_nunca_retorna_sessao_removida(
    tmp_path, monkeypatch
):
    """RED A8 — `201` precisa nomear uma sessão viva ao linearizar a resposta."""
    from scripts.backend_contract.application.workspace_recovery import (
        StageWorkspaceRecovery,
    )

    _workspace_id, _m, package = _origem_com_dois_privados(
        tmp_path, "origem-stage-discard"
    )
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

        discard_status, discard_body = _json(
            alvo, "POST", f"/v1/recovery/{recovery_id}/discard"
        )
        assert discard_status == 200, discard_body
        release.set()
        fio.join(timeout=60)
        assert not fio.is_alive()

        stage_status, stage_body = resultados[0]
        assert stage_status == 201, stage_body
        list_status, listing = _json(alvo, "GET", "/v1/recovery")
        assert list_status == 200, listing
        assert stage_body["recovery_id"] in {
            item["recovery_id"] for item in listing["recoveries"]
        }
        assert stage_body["recovery_id"] != recovery_id
    finally:
        release.set()
        alvo.close()


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
            assert not residuo, (
                "DISCARD respondeu 200 retendo conteúdo privado em claro: "
                f"{[p.name for p in residuo]}"
            )
        else:
            # falhou honestamente: a quarentena TEM de sobreviver ao material
            assert marcadores, (
                "descarte falhou mas removeu a quarentena antes do material privado"
            )
            assert isinstance(corpo, dict)

        preso.close()
        preso = None

        # com o obstáculo removido, a retentativa TEM de concluir
        status, _ = _json(alvo, "POST", f"/v1/recovery/{recovery_id}/discard")
        assert status == 200, "retentativa de descarte não converge após liberar o handle"
        assert not _sigilo_no_staging(), (
            "conteúdo privado sobreviveu ao descarte bem-sucedido"
        )
    finally:
        if preso is not None:
            preso.close()
        alvo.close()


def test_descarte_retido_sobrevive_ao_reinicio_e_repete_a_mesma_decisao(
    tmp_path, monkeypatch
):
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
        status, corpo = _json(
            reaberto, "POST", f"/v1/recovery/{recovery_id}/discard"
        )
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
            origem, "POST", f"/v1/workspaces/{workspace_id}/materials",
            body=pdf.read_bytes(),
            headers={"Content-Type": "application/pdf", "X-Document-Filename": "grande.pdf"},
        )
        assert status == 201, material
        status, package = _slow_request(
            origem, "POST", f"/v1/workspaces/{workspace_id}/backup", raw=True
        )
        assert status == 200
    finally:
        origem.close()

    tamanho = len(package)
    assert tamanho > 1_048_576, "o pacote precisa ultrapassar o teto JSON legado"

    alvo = _runtime(tmp_path, "alvo-f")
    try:
        from scripts.backend_contract.local_api.transport import LocalApi

        assert hasattr(LocalApi, "is_large_binary_upload"), (
            "não existe autoridade única de upload binário grande"
        )
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
            alvo, "POST", "/v1/recovery/verify", body=package,
            headers={"Content-Type": "application/octet-stream"},
        )
        pico_http = tracemalloc.get_traced_memory()[1] - b1
        tracemalloc.stop()
        assert status == 200

        transporte = (pico_http - pico_direto) / tamanho
        assert transporte <= 1.5, (
            f"o transporte acrescentou {transporte:.2f}x o pacote — mais de uma "
            f"materialização (http {pico_http} B vs direto {pico_direto} B)"
        )
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
            origem, "POST", f"/v1/workspaces/{workspace_id}/materials",
            body=pdf.read_bytes(),
            headers={"Content-Type": "application/pdf", "X-Document-Filename": "g.pdf"},
        )
        assert status == 201, material
        status, package = _slow_request(
            origem, "POST", f"/v1/workspaces/{workspace_id}/backup", raw=True
        )
        assert status == 200, "o produto recusou exportar"
    finally:
        origem.close()

    alvo = _runtime(tmp_path, "alvo-g")
    try:
        status, resumo = _slow_request(
            alvo, "POST", "/v1/recovery/verify", body=package,
            headers={"Content-Type": "application/octet-stream"},
        )
        assert status == 200, f"o produto não reingere o backup que ele mesmo produziu: {resumo}"
        status, staged = _slow_request(
            alvo, "POST", "/v1/recovery/staging", body=package,
            headers={"Content-Type": "application/octet-stream"},
        )
        assert status == 201, staged
        status, promovido = _slow_request(
            alvo, "POST", f"/v1/recovery/{staged['recovery_id']}/promote",
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
        assert staged["promotable"] is False, (
            "staging declarou promotable=True para identidade que já existe viva"
        )

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
        workspace_id, (primeiro, segundo), package = _origem_com_dois_privados(
            tmp_path, f"origem-j-{fase}"
        )
        alvo = _runtime(tmp_path, f"alvo-j-{fase}")
        criar = SQLiteWorkspaceRepository.create
        anexar = SQLiteArtifactRevisionRepository.append
        injecao = None
        try:
            status, staged = _stage(alvo, package)
            assert status == 201, staged

            if fase == "workspace":
                SQLiteWorkspaceRepository.create = lambda self, *a, **k: (
                    _ for _ in ()
                ).throw(OSError(5, "falha de I/O"))
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
            assert status == 200, (
                f"[{fase}] estado fantasma permanente após reabertura: "
                f"{len(itens)} materiais vivos, promoção {status} {resultado}"
            )
            finais = _materiais(alvo2, workspace_id)
            assert finais is not None and len(finais) == 2, (
                f"[{fase}] retomada não completou: {finais and len(finais)}/2"
            )
            assert {i["checksum_sha256"] for i in finais} == {
                primeiro["checksum_sha256"], segundo["checksum_sha256"]
            }
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
    return (
        tmp_path
        / f".{nome}.sqlite3.recovery"
        / f".recovery-cleanup-intent-{recovery_id}"
    )


def _cleanup_intent_payload(recovery_id, mode):
    return json.dumps(
        {
            "mode": mode,
            "recovery_id": recovery_id,
            "root_name": f"recovery-{recovery_id}",
            "version": 1,
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
        assert (externo / "RECOVERY_NOT_PROMOTABLE").read_bytes() == (
            b"RECOVERY_STAGING_V1\n"
        )
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
def test_cleanup_mantem_custodia_ate_o_ultimo_unlink(
    tmp_path, monkeypatch, swap_target
):
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
    _workspace_id, _materials, package = _origem_com_dois_privados(
        tmp_path, "b9-visible-source"
    )
    target = _runtime(tmp_path, "b9-visible-target")
    status, staged = _stage(target, package)
    assert status == 201, staged
    recovery_id = staged["recovery_id"]
    root = (
        tmp_path
        / ".b9-visible-target.sqlite3.recovery"
        / f"recovery-{recovery_id}"
    )
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
        item = next(
            recovery
            for recovery in listing["recoveries"]
            if recovery["recovery_id"] == recovery_id
        )
        assert item["state"] == "RECOVERY_UNRESUMABLE"
        assert item["allowed_actions"] == ["ABANDON"]
        assert sentinel.read_bytes() == b"EXTERNAL-MUST-SURVIVE"
        assert root.exists()
    finally:
        reopened.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows cleanup custody handle")
def test_custodia_cleanup_fecha_anchor_quando_validacao_pos_abertura_falha(
    tmp_path, monkeypatch
):
    """Sibling A9 — o anchor fecha sem conceder compartilhamento de remoção."""
    from scripts.backend_contract.application import workspace_recovery as wr

    root = tmp_path / "recovery-00000000-0000-4000-8000-000000000098"
    root.mkdir()
    real_lstat = wr.os.lstat
    real_open = wr.os.open
    root_calls = 0
    anchor_flags = []

    def record_anchor_flags(path, flags, mode=0o777, *, dir_fd=None):
        if ".recovery-cleanup-custody." in str(path):
            anchor_flags.append(flags)
        if dir_fd is None:
            return real_open(path, flags, mode)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    def fail_second_root_lstat(path):
        nonlocal root_calls
        if path == root:
            root_calls += 1
            if root_calls == 2:
                raise OSError("synthetic identity read failure")
        return real_lstat(path)

    monkeypatch.setattr(wr.os, "lstat", fail_second_root_lstat)
    monkeypatch.setattr(wr.os, "open", record_anchor_flags)
    with pytest.raises(OSError, match="synthetic identity"):
        wr._adquirir_custodia_cleanup(root)

    assert len(anchor_flags) == 1
    assert not (anchor_flags[0] & os.O_TEMPORARY)
    assert list(root.iterdir()) == []
    root.rmdir()


def test_falha_ao_soltar_anchor_raiz_preserva_disposition_para_restart(
    tmp_path, monkeypatch
):
    """RED B10 — falha terminal de anchor não pode apagar a decisão durável."""
    _workspace_id, _materials, package = _origem_com_dois_privados(
        tmp_path, "b10-anchor-source"
    )
    target = _runtime(tmp_path, "b10-anchor-target")
    status, staged = _stage(target, package)
    assert status == 201, staged
    recovery_id = staged["recovery_id"]
    root = (
        tmp_path
        / ".b10-anchor-target.sqlite3.recovery"
        / f"recovery-{recovery_id}"
    )

    original_unlink = Path.unlink
    injected = False

    def fail_after_controls_were_removed(path, *args, **kwargs):
        nonlocal injected
        is_root_anchor = (
            path.parent == root
            and path.name.startswith(".recovery-cleanup-custody.")
        )
        if is_root_anchor and not (root / "RECOVERY_DISPOSITION_V1").exists():
            injected = True
            raise PermissionError(13, "synthetic root anchor release failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_after_controls_were_removed)
    status, body = _json(
        target, "POST", f"/v1/recovery/{recovery_id}/discard"
    )
    assert status == 409, body
    assert body["error"]["code"] == "RECOVERY_RETAINED"
    assert injected is True
    monkeypatch.setattr(Path, "unlink", original_unlink)

    assert (root / "RECOVERY_DISPOSITION_V1").exists()
    assert (root / "RECOVERY_NOT_PROMOTABLE").exists()
    target.close()

    reopened = _runtime(tmp_path, "b10-anchor-target")
    try:
        status, listing = _json(reopened, "GET", "/v1/recovery")
        assert status == 200, listing
        item = next(
            recovery
            for recovery in listing["recoveries"]
            if recovery["recovery_id"] == recovery_id
        )
        assert item["state"] == "RECOVERY_RETAINED"
        assert item["allowed_actions"] == ["RETRY_DISCARD"]
    finally:
        reopened.close()


def test_intent_externo_sobrevive_falha_persistente_de_cleanup(
    tmp_path, monkeypatch
):
    """RED A12/B12 — a autoridade não pode morar na raiz destruída."""
    from scripts.backend_contract.application import workspace_recovery as wr

    _workspace_id, _materials, package = _origem_com_dois_privados(
        tmp_path, "protocol-discard-source"
    )
    target = _runtime(tmp_path, "protocol-discard-target")
    status, staged = _stage(target, package)
    assert status == 201, staged
    recovery_id = staged["recovery_id"]
    root = (
        tmp_path
        / ".protocol-discard-target.sqlite3.recovery"
        / f"recovery-{recovery_id}"
    )
    intent = _cleanup_intent_path(
        tmp_path, "protocol-discard-target", recovery_id
    )

    original_rmdir = Path.rmdir
    original_write = wr._gravar_controle_ancorado

    def fail_root_rmdir(path, *args, **kwargs):
        if path == root:
            raise PermissionError(13, "synthetic persistent root rmdir failure")
        return original_rmdir(path, *args, **kwargs)

    def fail_internal_disposition_restore(node, name, payload):
        if name == "RECOVERY_DISPOSITION_V1":
            raise PermissionError(13, "synthetic persistent disposition failure")
        return original_write(node, name, payload)

    monkeypatch.setattr(Path, "rmdir", fail_root_rmdir)
    monkeypatch.setattr(
        wr, "_gravar_controle_ancorado", fail_internal_disposition_restore
    )
    status, body = _json(
        target, "POST", f"/v1/recovery/{recovery_id}/discard"
    )
    assert status == 409, body
    assert body["error"]["code"] == "RECOVERY_RETAINED"
    monkeypatch.setattr(Path, "rmdir", original_rmdir)
    monkeypatch.setattr(wr, "_gravar_controle_ancorado", original_write)

    assert root.exists()
    assert intent.read_bytes() == _cleanup_intent_payload(recovery_id, "DISCARD")
    target.close()

    reopened = _runtime(tmp_path, "protocol-discard-target")
    try:
        status, listing = _json(reopened, "GET", "/v1/recovery")
        assert status == 200, listing
        item = next(
            recovery
            for recovery in listing["recoveries"]
            if recovery["recovery_id"] == recovery_id
        )
        assert item["state"] == "RECOVERY_RETAINED"
        assert item["allowed_actions"] == ["RETRY_DISCARD"]
    finally:
        reopened.close()


def test_intent_externo_preserva_abandono_apos_restart(tmp_path, monkeypatch):
    """RED protocolo — ABANDON persiste fora da raiz antes do primeiro unlink."""
    _workspace_id, _materials, package = _origem_com_dois_privados(
        tmp_path, "protocol-abandon-source"
    )
    target = _runtime(tmp_path, "protocol-abandon-target")
    status, staged = _stage(target, package)
    assert status == 201, staged
    recovery_id = staged["recovery_id"]
    root = (
        tmp_path
        / ".protocol-abandon-target.sqlite3.recovery"
        / f"recovery-{recovery_id}"
    )
    target.close()
    (root / "RECOVERY_NOT_PROMOTABLE").write_bytes(b"CORRUPTED")

    reopened = _runtime(tmp_path, "protocol-abandon-target")
    original_rmdir = Path.rmdir

    def fail_root_rmdir(path, *args, **kwargs):
        if path == root:
            raise PermissionError(13, "synthetic persistent root rmdir failure")
        return original_rmdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "rmdir", fail_root_rmdir)
    status, body = _json(
        reopened,
        "POST",
        f"/v1/recovery/{recovery_id}/abandon",
        value={"confirm_abandon": True},
    )
    assert status == 409, body
    assert body["error"]["code"] == "RECOVERY_RETAINED"
    monkeypatch.setattr(Path, "rmdir", original_rmdir)
    intent = _cleanup_intent_path(
        tmp_path, "protocol-abandon-target", recovery_id
    )
    assert intent.read_bytes() == _cleanup_intent_payload(recovery_id, "ABANDON")
    reopened.close()

    restarted = _runtime(tmp_path, "protocol-abandon-target")
    try:
        status, listing = _json(restarted, "GET", "/v1/recovery")
        assert status == 200, listing
        item = next(
            recovery
            for recovery in listing["recoveries"]
            if recovery["recovery_id"] == recovery_id
        )
        assert item["state"] == "RECOVERY_RETAINED"
        assert item["allowed_actions"] == ["RETRY_ABANDON"]
    finally:
        restarted.close()


@pytest.mark.parametrize("existing", ["exact", "divergent", "hardlink"])
def test_intent_externo_file_exists_exige_controle_regular_exato(
    tmp_path, existing
):
    """RED protocolo — FileExists só equivale a bytes canônicos exclusivos."""
    _workspace_id, _materials, package = _origem_com_dois_privados(
        tmp_path, f"intent-{existing}-source"
    )
    target_name = f"intent-{existing}-target"
    target = _runtime(tmp_path, target_name)
    status, staged = _stage(target, package)
    assert status == 201, staged
    recovery_id = staged["recovery_id"]
    root = (
        tmp_path
        / f".{target_name}.sqlite3.recovery"
        / f"recovery-{recovery_id}"
    )
    intent = _cleanup_intent_path(tmp_path, target_name, recovery_id)
    expected = _cleanup_intent_payload(recovery_id, "DISCARD")
    if existing == "exact":
        intent.write_bytes(expected)
    elif existing == "divergent":
        intent.write_bytes(b"{")
    else:
        outside = tmp_path / "foreign-intent.bin"
        outside.write_bytes(expected)
        os.link(outside, intent)

    status, body = _json(
        target, "POST", f"/v1/recovery/{recovery_id}/discard"
    )
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

    _workspace_id, _materials, package = _origem_com_dois_privados(
        tmp_path, "intent-create-source"
    )
    target = _runtime(tmp_path, "intent-create-target")
    status, staged = _stage(target, package)
    assert status == 201, staged
    recovery_id = staged["recovery_id"]
    root = (
        tmp_path
        / ".intent-create-target.sqlite3.recovery"
        / f"recovery-{recovery_id}"
    )
    before = sorted(path.relative_to(root) for path in root.rglob("*"))
    original_publish = wr._gravar_sidecar_imutavel
    injected = False

    def fail_cleanup_intent(base, name, record):
        nonlocal injected
        if name.startswith(".recovery-cleanup-intent-"):
            injected = True
            raise OSError("synthetic intent create failure")
        return original_publish(base, name, record)

    monkeypatch.setattr(wr, "_gravar_sidecar_imutavel", fail_cleanup_intent)
    status, body = _json(
        target, "POST", f"/v1/recovery/{recovery_id}/discard"
    )
    assert status != 200, body
    assert injected is True
    assert sorted(path.relative_to(root) for path in root.rglob("*")) == before
    target.close()


def test_escrita_parcial_do_intent_falha_antes_do_cleanup(tmp_path, monkeypatch):
    """RED protocolo — intent parcial não vira autoridade nem libera unlink."""
    from scripts.backend_contract.application import workspace_recovery as wr

    _workspace_id, _materials, package = _origem_com_dois_privados(
        tmp_path, "intent-partial-source"
    )
    target = _runtime(tmp_path, "intent-partial-target")
    status, staged = _stage(target, package)
    assert status == 201, staged
    recovery_id = staged["recovery_id"]
    root = (
        tmp_path
        / ".intent-partial-target.sqlite3.recovery"
        / f"recovery-{recovery_id}"
    )
    intent = _cleanup_intent_path(tmp_path, "intent-partial-target", recovery_id)
    before = sorted(path.relative_to(root) for path in root.rglob("*"))
    original_publish = wr._gravar_sidecar_imutavel
    injected = False

    def leave_partial_cleanup_intent(base, name, record):
        nonlocal injected
        if name.startswith(".recovery-cleanup-intent-"):
            injected = True
            (Path(base) / name).write_bytes(b"{")
            raise OSError("synthetic partial intent write")
        return original_publish(base, name, record)

    monkeypatch.setattr(
        wr, "_gravar_sidecar_imutavel", leave_partial_cleanup_intent
    )
    status, body = _json(
        target, "POST", f"/v1/recovery/{recovery_id}/discard"
    )
    assert status != 200, body
    assert injected is True
    assert intent.read_bytes() == b"{"
    assert sorted(path.relative_to(root) for path in root.rglob("*")) == before
    target.close()

    reopened = _runtime(tmp_path, "intent-partial-target")
    try:
        status, listing = _json(reopened, "GET", "/v1/recovery")
        assert status == 200, listing
        item = next(
            recovery
            for recovery in listing["recoveries"]
            if recovery["recovery_id"] == recovery_id
        )
        assert item["state"] == "RECOVERY_RETAINED"
        assert item["allowed_actions"] == ["RETRY_ABANDON"]
    finally:
        reopened.close()


@pytest.mark.parametrize(
    "failed_control",
    ["STAGING_IDENTITY_V1", "RECOVERY_SESSION_V1", "RECOVERY_NOT_PROMOTABLE"],
)
def test_intent_externo_sobrevive_falha_removendo_controle_interno(
    tmp_path, monkeypatch, failed_control
):
    """RED matriz — falha em controle interno não perde a decisão humana."""
    from scripts.backend_contract.application import workspace_recovery as wr

    _workspace_id, _materials, package = _origem_com_dois_privados(
        tmp_path, f"control-{failed_control}-source"
    )
    target_name = f"control-{failed_control}-target"
    target = _runtime(tmp_path, target_name)
    status, staged = _stage(target, package)
    assert status == 201, staged
    recovery_id = staged["recovery_id"]
    root = (
        tmp_path
        / f".{target_name}.sqlite3.recovery"
        / f"recovery-{recovery_id}"
    )
    original_unlink = wr._unlink_na_custodia

    def fail_selected_control(node, name):
        if name == failed_control:
            raise PermissionError(13, "synthetic control unlink failure")
        return original_unlink(node, name)

    monkeypatch.setattr(wr, "_unlink_na_custodia", fail_selected_control)
    status, body = _json(
        target, "POST", f"/v1/recovery/{recovery_id}/discard"
    )
    assert status == 409, body
    assert body["error"]["code"] == "RECOVERY_RETAINED"
    monkeypatch.setattr(wr, "_unlink_na_custodia", original_unlink)
    intent = _cleanup_intent_path(tmp_path, target_name, recovery_id)
    assert intent.read_bytes() == _cleanup_intent_payload(recovery_id, "DISCARD")
    assert root.exists()
    target.close()

    reopened = _runtime(tmp_path, target_name)
    try:
        status, listing = _json(reopened, "GET", "/v1/recovery")
        assert status == 200, listing
        item = next(
            recovery
            for recovery in listing["recoveries"]
            if recovery["recovery_id"] == recovery_id
        )
        assert item["state"] == "RECOVERY_RETAINED"
        assert item["allowed_actions"] == ["RETRY_DISCARD"]
    finally:
        reopened.close()


def test_root_ausente_permite_commit_com_gc_posterior_do_intent(
    tmp_path, monkeypatch
):
    """RED matriz — sidecar retido após rmdir não recria recovery fantasma."""
    _workspace_id, _materials, package = _origem_com_dois_privados(
        tmp_path, "intent-gc-source"
    )
    target = _runtime(tmp_path, "intent-gc-target")
    status, staged = _stage(target, package)
    assert status == 201, staged
    recovery_id = staged["recovery_id"]
    root = (
        tmp_path
        / ".intent-gc-target.sqlite3.recovery"
        / f"recovery-{recovery_id}"
    )
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
    status, body = _json(
        target, "POST", f"/v1/recovery/{recovery_id}/discard"
    )
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
        assert all(
            item["recovery_id"] != recovery_id
            for item in listing["recoveries"]
        )
        assert not intent.exists()
    finally:
        reopened.close()


@pytest.mark.parametrize(
    "failed_control",
    [
        "STAGING_IDENTITY_V1",
        "RECOVERY_SESSION_V1",
        "RECOVERY_DISPOSITION_V1",
        "RECOVERY_NOT_PROMOTABLE",
    ],
)
def test_falha_transitoria_na_restauracao_nao_apaga_decisao_de_discard(
    tmp_path, monkeypatch, failed_control
):
    """RED B11 + sibling sweep — controles são restaurados sem cascata."""
    from scripts.backend_contract.application import workspace_recovery as wr

    _workspace_id, _materials, package = _origem_com_dois_privados(
        tmp_path, "b11-control-source"
    )
    target = _runtime(tmp_path, "b11-control-target")
    status, staged = _stage(target, package)
    assert status == 201, staged
    recovery_id = staged["recovery_id"]
    root = (
        tmp_path
        / ".b11-control-target.sqlite3.recovery"
        / f"recovery-{recovery_id}"
    )

    original_unlink = Path.unlink
    original_write = wr._gravar_controle_ancorado
    anchor_failure = False
    control_failure = False

    def fail_root_anchor_after_controls(path, *args, **kwargs):
        nonlocal anchor_failure
        is_root_anchor = (
            path.parent == root
            and path.name.startswith(".recovery-cleanup-custody.")
        )
        if is_root_anchor and not (root / "RECOVERY_DISPOSITION_V1").exists():
            anchor_failure = True
            raise PermissionError(13, "synthetic root anchor release failure")
        return original_unlink(path, *args, **kwargs)

    def fail_control_restore_once(node, name, payload):
        nonlocal control_failure
        if name == failed_control and not control_failure:
            control_failure = True
            raise PermissionError(13, "synthetic control restore failure")
        return original_write(node, name, payload)

    monkeypatch.setattr(Path, "unlink", fail_root_anchor_after_controls)
    monkeypatch.setattr(wr, "_gravar_controle_ancorado", fail_control_restore_once)
    status, body = _json(
        target, "POST", f"/v1/recovery/{recovery_id}/discard"
    )
    assert status == 409, body
    assert body["error"]["code"] == "RECOVERY_RETAINED"
    assert anchor_failure is True
    assert control_failure is True
    monkeypatch.setattr(Path, "unlink", original_unlink)
    monkeypatch.setattr(wr, "_gravar_controle_ancorado", original_write)

    assert (root / "RECOVERY_DISPOSITION_V1").exists()
    assert (root / "RECOVERY_NOT_PROMOTABLE").exists()
    target.close()

    reopened = _runtime(tmp_path, "b11-control-target")
    try:
        status, listing = _json(reopened, "GET", "/v1/recovery")
        assert status == 200, listing
        item = next(
            recovery
            for recovery in listing["recoveries"]
            if recovery["recovery_id"] == recovery_id
        )
        assert item["state"] == "RECOVERY_RETAINED"
        assert item["allowed_actions"] == ["RETRY_DISCARD"]
    finally:
        reopened.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows cleanup custody handles")
def test_falha_ao_remover_anchor_filho_nao_vaza_handle_pai(tmp_path, monkeypatch):
    """RED A10 — erro num filho não interrompe o fechamento da árvore."""
    from scripts.backend_contract.application import workspace_recovery as wr

    root = tmp_path / "recovery-00000000-0000-4000-8000-000000000096"
    child = root / "child"
    child.mkdir(parents=True)
    custody = wr._adquirir_custodia_cleanup(root)
    descriptors = [custody.descriptor, custody.children[0].descriptor]
    assert all(descriptor is not None for descriptor in descriptors)

    original_unlink = Path.unlink

    def fail_child_anchor(path, *args, **kwargs):
        if (
            path.parent == child
            and path.name.startswith(".recovery-cleanup-custody.")
        ):
            raise PermissionError(13, "synthetic child anchor release failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_child_anchor)
    with pytest.raises(PermissionError, match="synthetic child anchor"):
        wr._fechar_custodia_cleanup(custody)

    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)


@pytest.mark.skipif(os.name != "nt", reason="Windows cleanup custody handles")
def test_falha_transitoria_ao_fechar_descritor_converge_sem_vazamento(
    tmp_path, monkeypatch
):
    """B11 — o segundo passe fecha o handle após uma falha transitória."""
    from scripts.backend_contract.application import workspace_recovery as wr

    root = tmp_path / "recovery-00000000-0000-4000-8000-000000000094"
    (root / "child").mkdir(parents=True)
    custody = wr._adquirir_custodia_cleanup(root)
    descriptors = [custody.descriptor, custody.children[0].descriptor]
    child_descriptor = custody.children[0].descriptor
    assert child_descriptor is not None
    original_close = wr.os.close
    injected = False

    def fail_child_close_once(descriptor):
        nonlocal injected
        if descriptor == child_descriptor and not injected:
            injected = True
            raise OSError("synthetic transient close failure")
        return original_close(descriptor)

    monkeypatch.setattr(wr.os, "close", fail_child_close_once)
    wr._fechar_custodia_cleanup(custody)

    assert injected is True
    assert custody.children[0].descriptor is None
    assert custody.children[0].anchor_path is None
    for descriptor in descriptors:
        assert descriptor is not None
        with pytest.raises(OSError):
            os.fstat(descriptor)


@pytest.mark.skipif(os.name != "nt", reason="Windows cleanup custody handles")
def test_close_ambiguo_nunca_fecha_descriptor_reutilizado(
    tmp_path, monkeypatch
):
    """RED A12 — erro depois do close consome o fd e nunca o fecha de novo."""
    from scripts.backend_contract.application import workspace_recovery as wr

    root = tmp_path / "recovery-00000000-0000-4000-8000-000000000095"
    (root / "child").mkdir(parents=True)
    custody = wr._adquirir_custodia_cleanup(root)
    child = custody.children[0]
    child_descriptor = child.descriptor
    assert child_descriptor is not None
    original_close = wr.os.close
    foreign = tmp_path / "foreign-descriptor.bin"
    foreign.write_bytes(b"FOREIGN")
    probes = []
    injected = False

    def close_then_reuse_and_fail(descriptor):
        nonlocal injected
        if descriptor == child_descriptor and not injected:
            injected = True
            original_close(descriptor)
            while child_descriptor not in probes:
                probes.append(os.open(foreign, os.O_RDONLY))
            raise OSError("synthetic ambiguous close failure")
        return original_close(descriptor)

    monkeypatch.setattr(wr.os, "close", close_then_reuse_and_fail)
    try:
        wr._fechar_custodia_cleanup(custody)
        assert injected is True
        os.fstat(child_descriptor)
    finally:
        monkeypatch.setattr(wr.os, "close", original_close)
        for descriptor in probes:
            try:
                original_close(descriptor)
            except OSError:
                pass


@pytest.mark.skipif(os.name != "nt", reason="Windows cleanup custody handles")
def test_close_ambiguo_antes_da_liberacao_nunca_repete_o_fd(tmp_path, monkeypatch):
    """RED protocolo — fd desconhecido não é ownership reutilizável."""
    from scripts.backend_contract.application import workspace_recovery as wr

    root = tmp_path / "recovery-00000000-0000-4000-8000-000000000093"
    root.mkdir()
    custody = wr._adquirir_custodia_cleanup(root)
    descriptor = custody.descriptor
    anchor = custody.anchor_path
    assert descriptor is not None and anchor is not None
    original_close = wr.os.close
    calls = 0

    def fail_before_release(candidate):
        nonlocal calls
        if candidate == descriptor:
            calls += 1
            raise OSError("synthetic close failure before release")
        return original_close(candidate)

    monkeypatch.setattr(wr.os, "close", fail_before_release)
    with pytest.raises(OSError, match="synthetic close failure"):
        wr._fechar_custodia_cleanup(custody)
    assert calls == 1
    assert custody.descriptor is None
    assert anchor.exists()
    os.fstat(descriptor)

    monkeypatch.setattr(wr.os, "close", original_close)
    original_close(descriptor)
    anchor.unlink()


@pytest.mark.parametrize("reparse_location", ["root", "nested"])
def test_abandono_de_raiz_reparse_nao_escreve_no_alvo_externo(
    tmp_path, reparse_location
):
    """RED B10 — decisão local não pode atravessar uma raiz reparse."""
    recovery_id = "00000000-0000-4000-8000-000000000097"
    external = tmp_path / "b10-unsafe-external"
    external.mkdir()
    (external / "sentinel.bin").write_bytes(b"EXTERNAL-MUST-NOT-CHANGE")

    base = tmp_path / ".b10-unsafe.sqlite3.recovery"
    base.mkdir()
    root = base / f"recovery-{recovery_id}"
    if reparse_location == "root":
        (external / "RECOVERY_NOT_PROMOTABLE").write_bytes(
            b"RECOVERY_STAGING_V1\n"
        )
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
    _workspace_id, _package, destino, recovery_id = _interromper_promocao(
        tmp_path, f"b8-{adulteracao}"
    )
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
        registro["private_contents"][0][0] = (
            ("0" if original[0] != "0" else "1") + original[1:]
        )
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
        assert corpo["recoveries"][0]["reason"] == (
            "promotion_journal_unreadable_or_unsupported"
        )
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
    raiz = (
        tmp_path
        / ".b7-destino.sqlite3.recovery"
        / f"recovery-{staged['recovery_id']}"
    )
    (raiz / "PROMOTION_TRANSACTION_V1").write_text(
        '{"version":1,"phase":"PROMOTED"}', encoding="utf-8"
    )
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
    raiz = (
        tmp_path
        / ".b8s-destino.sqlite3.recovery"
        / f"recovery-{staged['recovery_id']}"
    )
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
        raiz = (
            tmp_path
            / ".b7m-destino.sqlite3.recovery"
            / f"recovery-{staged['recovery_id']}"
        )
        (raiz / "RECOVERY_NOT_PROMOTABLE").write_bytes(b"CORRUPTED\n")

        status, corpo = _json(
            destino, "POST", f"/v1/recovery/{staged['recovery_id']}/discard"
        )
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
    raiz = (
        tmp_path
        / ".b7r-destino.sqlite3.recovery"
        / f"recovery-{staged['recovery_id']}"
    )
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
def test_disposition_corrompida_permite_novo_abandono_explicito(
    tmp_path, corromper_marcador, adulteracao_disposition
):
    """RED A7 — `RETRY_ABANDON` precisa executar a ação que anuncia."""
    _origem, _ids, package = _origem_com_dois_privados(tmp_path, "a7d-origem")
    destino = _runtime(tmp_path, "a7d-destino")
    status, staged = _stage(destino, package)
    assert status == 201, staged
    raiz = (
        tmp_path
        / ".a7d-destino.sqlite3.recovery"
        / f"recovery-{staged['recovery_id']}"
    )
    disposition = raiz / "RECOVERY_DISPOSITION_V1"
    if adulteracao_disposition != "json_invalido":
        disposition.write_text(
            json.dumps(
                {
                    "version": (
                        True if adulteracao_disposition == "version_booleana" else 1
                    ),
                    "recovery_id": staged["recovery_id"],
                    "mode": (
                        []
                        if adulteracao_disposition == "mode_nao_escalar"
                        else "ABANDON"
                    ),
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
    journal.write_text(
        json.dumps({**registro, "phase": "UNRESUMABLE"}), encoding="utf-8"
    )
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
            destino, "POST", f"/v1/workspaces/{origem}/artifacts/LAUDO/laudo/revisions",
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


def test_identidade_travada_nao_autoriza_destruir_a_retomada(tmp_path):
    """RED S1 — prova ilegível AGORA não é prova ausente PARA SEMPRE.

    O código nomeia a mesma condição como transitória para o journal (antivírus,
    indexador, placeholder do OneDrive) e a tratava como permanente para a
    identidade: `except OSError: return None`. Como `None` classifica a raiz
    como IRRETOMÁVEL, o descarte passava a ser autorizado e apagava a autoridade
    de retomada — sem sequer exigir a declaração consciente.
    """
    import pathlib as _pathlib

    import scripts.backend_contract.application.workspace_recovery as wr
    from scripts.backend_contract.infrastructure.productization import (
        abrir_staging_quarentenado,
    )

    _origem, _pkg, destino, _rid = _interromper_promocao(tmp_path, "s1")
    destino.close()
    journal = _journal_da_unica_raiz(tmp_path, "s1")
    alvo = journal.parent / "STAGING_IDENTITY_V1"
    assert alvo.exists()

    staging = abrir_staging_quarentenado(journal.parent)
    original = _pathlib.Path.read_bytes
    try:
        def _travado(self, *args, **kwargs):
            if _pathlib.Path(self) == alvo:
                raise PermissionError(13, "arquivo em uso")
            return original(self, *args, **kwargs)

        _pathlib.Path.read_bytes = _travado
        try:
            estado = wr._classificar_journal(staging)
        finally:
            _pathlib.Path.read_bytes = original
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
