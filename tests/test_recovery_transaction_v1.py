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

import threading

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
        # Simula a QUEDA do processo: os handles do sistema operacional somem
        # (é o que a morte do processo faz) e a raiz permanece no disco, sem
        # sessão. Só limpar o registro em memória deixaria os arquivos abertos
        # neste mesmo processo — artefato do harness, não do produto.
        for entrada in destino._recovery_sessions._sessions.values():
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
        status, retomada = _stage(reaberto, package)
        assert status == 201, retomada
        status, corpo = _promote(reaberto, retomada["recovery_id"])
        assert status == 200, corpo
        assert len(_materiais(reaberto, origem)) == 2
    finally:
        reaberto.close()

# ------------------------------------------------------------------ Q
# SELF_PRODUCED_BACKUP MUST_BE REINGESTIBLE


def test_backup_grande_demais_e_recusado_em_vez_de_prometer_seguranca_falsa(tmp_path):
    """RED Q — o produto não pode entregar 200 num pacote que ele não restaura.

    O teto de ingestão da recuperação é finito. Um pacote acima dele é um
    arquivo que dá sensação de segurança e falha no dia em que for preciso. É
    melhor recusar dizendo por quê do que prometer o que não se sustenta.
    """
    from scripts.backend_contract.application import workspace_recovery as wr

    runtime = _runtime(tmp_path, "q-origem")
    try:
        workspace_id, _material = _workspace_with_material(runtime, tmp_path, name="Caso enorme")
        original = wr.ExportWorkspaceBackup.execute

        def _gigante(self, ws):  # o pacote real é pequeno; o teto é que baixa
            return original(self, ws)

        # Baixa o teto para a fronteira ficar alcançável no teste, sem fabricar
        # centenas de MB em disco.
        anterior = wr.MAX_BACKUP_PACKAGE_BYTES
        wr.MAX_BACKUP_PACKAGE_BYTES = 128
        try:
            status, corpo = _json(runtime, "POST", f"/v1/workspaces/{workspace_id}/backup")
        finally:
            wr.MAX_BACKUP_PACKAGE_BYTES = anterior
        assert status == 413, corpo
        assert corpo["error"]["code"] == "BACKUP_TOO_LARGE"
    finally:
        runtime.close()
