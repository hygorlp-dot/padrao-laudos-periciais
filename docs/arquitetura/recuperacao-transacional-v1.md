# Recuperação transacional de perícia — nota de arquitetura (#183)

Status: **nota de arquitetura**, escrita antes de qualquer edição de produção, após
`AUTONOMOUS_CAUSAL_REPAIR_LOOP_V1` ser acionado. `251bf29` está permanentemente
invalidado como candidato a merge.

Implementação atual (#183): além do journal exclusivo da promoção, cada
staging publicado possui `RECOVERY_SESSION_V1` imutável. Esse descriptor liga
`recovery_id`, identidade da raiz, resumo verificado e hash do pacote antes da
resposta `201`. Ele também fixa `promotion_plan_sha256`, derivado do workspace,
das revisões ordenadas e dos conteúdos privados verificados. Isso permite
reconstruir `STAGED` depois de fechar/reabrir o
produto, mas **não autoriza mutação viva**. `PROMOTION_TRANSACTION_V1` continua
sendo a única autoridade de promoção. Descarte/abandono publicam antes um
`RECOVERY_DISPOSITION_V1` imutável, para que falha de limpeza seja retomada com
a mesma decisão humana. Uma fase `PROMOTED` só é terminal quando o journal
completo produz o mesmo hash de plano fixado no descriptor publicado; fase
isolada, tipo não escalar, identidade adulterada ou journal parcial nunca
autoriza coleta automática nem derruba o startup.

A classe causal `PARTIAL_PROMOTION_NOT_RECOVERABLE` sobreviveu a três estratégias de
reparo local — ordem privado-primeiro (`8d611a3`), reversão para privado-último
(`994cf41`) e retomada em memória (`251bf29`). O problema deixou de ser ordem de
escrita. Esta nota descreve o alvo antes de implementar.

Princípio que governa o desenho:

> Um sistema de recuperação não é seguro porque seu caminho feliz é correto. Ele é
> seguro apenas se **toda transição autoritativa interrompida for atômica ou
> duravelmente retomável**.

---

## A. Grafo de autoridade atual

A promoção cria UMA perícia autoritativa atravessando DUAS autoridades de
persistência independentes, sem transação que as abranja.

```
                    PromoteWorkspaceRecovery            (aplicação)
                              │
              ┌───────────────┴────────────────┐
              ▼                                ▼
   SQLiteApplicationStore              LocalPrivateContentStore
   ─────────────────────               ────────────────────────
   workspaces                          conteúdo privado (bytes)
   artifact_revisions                  journal / intent / âncora
   FK ON DELETE RESTRICT               _committed      (universo 1)
   PRAGMA foreign_keys = ON            _known_prefixes (universo 2)
   BEGIN IMMEDIATE por chamada         .aborted.<nonce> duráveis
   (sem transação multi-statement      retired markers
    exposta)
```

Estado de sessão hoje (`application/workspace_recovery.py`):

- `WorkspaceRecoverySessions._sessions` — **dict em memória**;
- `entry["promotion_started"]` — **booleano em memória**;
- `_AUTHORIZED_RECOVERY_STAGING` — `WeakKeyDictionary` em memória
  (`infrastructure/productization.py`).

Duas assimetrias documentadas no próprio código privado
(`infrastructure/private_filesystem.py`):

- invariante explícita na linha 1377:
  `_known_prefixes == _committed | aborted_prefixes`;
- `open_content` (linha ~1917) consulta **`_committed`** e devolve `None` fora dele;
- `store` (linha 1764) recusa por **`_known_prefixes`**, e adiciona o prefixo na
  linha 1786 **antes** de gravar o conteúdo.

`list_all()` expõe `_committed`. Logo:

```
PRIVATE list_all()  ≠  PRIVATE _known_prefixes
```

Transporte (`local_api/server.py`):

- teto de corpo: `api.request_body_limit(...)` (linha ~200) — correto e único;
- **spool para arquivo**: condicionado a `api.is_document_upload(...)` (linha 207),
  que exclui `/v1/recovery/*`. Corpo lido inteiro por `self.rfile.read(length)`.
  Duas autoridades distintas descrevendo a mesma decisão.

---

## B. Grafo de falha confirmado (reprodução executável, PASS A3/B3)

```
(1) CORRIDA PROMOTE × DISCARD                        — sem injeção de falha
    STAGED ──promote──▶ cria workspace vivo
           ──discard──▶ fecha/apaga staging por baixo
    promote morre 503 ▶ perícia fantasma 0/N materiais
                      ▶ re-staging diz promotable=True
                      ▶ nova promoção 409 WORKSPACE_CONFLICT (permanente)
                      ▶ DELETE workspace → 405 (não existe rota)

(2) FALHA TRANSITÓRIA NA PERNA PRIVADA               — uma única OSError
    store() registra prefixo em _known_prefixes (1786)
      ▶ grava conteúdo → falha
      ▶ prefixo fica em _known_prefixes, ausente de _committed
    retomada: ja_gravados vem de list_all() (=_committed) → não vê o abortado
      ▶ chama store() de novo → RepositoryConflict (1764)
      ▶ aquele content_id é PERMANENTEMENTE ingravável
    reinício: promotion_started some → 409 WORKSPACE_CONFLICT (permanente)

    Contraprova: falha na perna de REVISÕES retoma e converge (200, N/N).
    O defeito é específico da fronteira privada.

(3) DISCARD MENTIROSO
    rmtree(ignore_errors=True) remove o marcador de quarentena ANTES do
    conteúdo privado; handle preso (antivírus/indexador) deixa PDF em claro
      ▶ API responde 200 "descartado"
      ▶ quarentena apagada, material sigiloso retido, sem retentativa
```

Causa-raiz comum: **memória de processo usada como autoridade de uma transição que
atravessa duas autoridades duráveis.**

```
PROCESS MEMORY            ≠  DURABLE PROMOTION AUTHORITY
SQLITE PREFIX COMPLETE    ≠  PRIVATE STORE COMMIT COMPLETE
IN_MEMORY_RESUMABILITY    ≠  RECOVERY TRANSACTIONALITY
```

---

## C. Grafo de autoridade alvo

Introduzir **uma** autoridade durável de transação de recuperação, que passa a ser a
única fonte de verdade sobre a fase da promoção. Ela não substitui nem duplica as
autoridades de armazenamento — ela as **ordena**.

```
            RecoveryTransactionJournal          (durável, primeira classe)
            ── fase + progresso + identidades ──
                          │  serializa e torna idempotente
              ┌───────────┴───────────┐
              ▼                       ▼
    SQLiteApplicationStore    LocalPrivateContentStore
    (inalterado)              (+ continuação exata de intent abortado,
                                 dentro da própria fronteira)
```

Regras de fronteira:

- a aplicação **orquestra**; não manipula journal/ledger privado por dentro;
- a continuação de conteúdo privado é uma operação **da camada de armazenamento
  privado**, não da aplicação;
- nenhum segundo motor de backup, nenhum coordenador genérico, nenhum plano de
  controle, nenhum serviço novo.

---

## D. Estado durável mínimo

A transação liga, no mínimo:

| campo | por quê |
|---|---|
| `recovery_id` | identidade da transação |
| `backup_sha256` | prova de que a retomada é do MESMO pacote |
| `workspace_id` | alvo vivo |
| identidade da raiz de staging | `os.lstat` — impede adotar raiz alheia |
| identidade esperada do workspace | nome + `created_at` |
| revisões: id, kind, artifact_id, checksum, **ordem** | prefixo verificável |
| conteúdos privados: `content_id` + hash | progresso verificável |
| fase atual | serialização |
| progresso para continuação idempotente | retomada exata |
| estado terminal | `PROMOTED` / `DISCARDED` / `FAILED_RECOVERABLE` |

Onde vive: ao lado da base viva, fora da trilha append-only de perícia (não é
artefato de perícia; é estado operacional de recuperação). Fail-closed: journal
ilegível ⇒ nenhuma promoção.

---

## E. Máquina de estados e reinício

```
VERIFIED_STAGING
      │ prepare (grava journal ANTES da 1ª mutação viva)
      ▼
PROMOTION_PREPARED ──────────────┐
      │ claim                    │ discard
      ▼                          ▼
  PROMOTING                  DISCARDING
      │ escrituras                │ remoção provada
      ▼                          ▼
 VERIFYING_LIVE              DISCARDED
      │ conferência
      ▼
  PROMOTED
```

Falha em `PROMOTING`/`VERIFYING_LIVE` ⇒ **não** apaga o journal: fica
`FAILED_RECOVERABLE`, com o progresso registrado.

Na reabertura do produto, a aplicação reconstrói sessões a partir do journal +
raízes quarentenadas e classifica cada uma como:

- **preparada** — descriptor íntegro e ausência de journal; continua `STAGED`,
  visível e promovível/descartável pelo caminho normal;
- **retomável** — journal íntegro, digest do pacote confere, identidade da raiz de
  staging confere, vivo é prefixo exato do registrado;
- **irretomável** — descriptor/journal desconhecido, ilegível ou divergente ⇒
  fail-closed, sem promoção e com abandono explícito disponível;
- **limpeza retida** — disposition durável presente ⇒ somente retentar a mesma
  decisão (`DISCARD` ou `ABANDON`); disposition ilegível nunca infere descarte e
  oferece apenas um novo `ABANDON` explicitamente confirmado.

Nunca promove sozinho no startup. **Promoção explícita humana continua obrigatória.**
Isso torna `promotion_started` desnecessário: a autoridade deixa de ser um booleano de
processo e passa a ser o journal.

---

## F. Intent abortado no armazenamento privado

O store **já** distingue durávelmente `committed`, `aborted` (`.aborted.<nonce>`) e
`retired`. Não falta modelo — falta **operação de continuação exata exposta**.

Propriedade exigida, dentro da fronteira do armazenamento privado:

```
importação de recuperação para o conteúdo X falha após registrar intent
   │
   ├─ A. X já está committed byte-a-byte  ─────▶ tratar como completo
   ├─ B. X é intent ABORTADO desta MESMA
   │     transação de recuperação        ─────▶ continuar/finalizar por
   │                                            mecanismo explícito
   └─ C. identidade pertence a outra coisa ────▶ conflito / fail-closed
```

Proibido, e não faremos: apagar `_known_prefixes`, resetar journal, reaproveitar
identidade às cegas, ou enfraquecer a proveniência de crash/replay.
`ABORTED_INTENT ≠ COMMITTED_CONTENT` — mas
`ABORTED_INTENT_OWNED_BY_EXACT_RECOVERY` não pode tornar a perícia inteira
irrecuperável.

---

## G. Concorrência

Autoridade no **backend**, não na UI.

- transição de estado por `recovery_id` é **atômica** (compare-and-set sob lock
  estreito por sessão) — `STAGED → PROMOTING` **ou** `STAGED → DISCARDING`, nunca
  ambas;
- quem perde a transição recebe erro honesto, não um segundo `200`;
- `discard` não pode fechar o staging sob uma promoção em curso;
- dois stagings concorrentes do mesmo pacote são serializados na publicação e
  convergem para uma única sessão/raiz;
- depois de qualquer I/O fora do mutex, a sessão observada é revalidada sob lock;
  re-stage concorrente com descarte cria/retorna uma sessão atual, nunca um ID já
  removido;
- `runtime.close` não invalida um commit ativo de forma insegura.

A UI desabilita ações incompatíveis como **defesa em profundidade**, nunca como
autoridade. Sem framework de lock distribuído.

---

### E.1 Descarte NÃO é saída depois da primeira mutação viva

`PREPARADO != MEIO-ESCRITO NO VIVO`. Os dois estados foram colapsados em
`FAILED_RECOVERABLE`, e o descarte era legal a partir dele — apagando a raiz inteira,
journal incluído. Como o armazenamento é append-only e não há remoção de workspace, a
perícia parcial ficava visível e insanável.

Regra: enquanto existir journal na raiz, a recuperação **não é descartável**. A única
saída é retomar (`RecoveryPromotionIncomplete` → `409`). O journal é AUTORIDADE, não
material: sai por último, depois de provado que o conteúdo privado sumiu, junto do
marcador de quarentena.

A fase gravada no journal passa a ser LIDA: `PROMOTING` significa retomável e é
preservada; `PROMOTED` significa que não há mais nada a concluir. Na reabertura do
produto, raiz **sem descriptor e sem journal** é queda anterior à publicação e
pode ser recolhida; raiz publicada (`RECOVERY_SESSION_V1`) nunca é abandonada por
inferência. Ela reaparece na UI e só sai por promoção terminal ou comando humano
explícito. Journal/descriptor corrompido ou de versão desconhecida também é
preservado e exposto como irretomável, nunca tratado como autoridade ausente.

---

## H. Ciclo de vida do descarte

Propriedade nova: **`QUARANTINE_OUTLIVES_PRIVATE_MATERIAL`**.

```
entra em DISCARDING (atômico)
  → fecha handles com segurança
  → remove payload privado
  → VERIFICA ausência do payload privado
  → remove marcador de quarentena aninhado só quando seguro
  → remove payload SQLite/recuperação
  → VERIFICA que a raiz não contém material
  → remove RECOVERY_NOT_PROMOTABLE da raiz POR ÚLTIMO
  → remove a raiz
  → só então reporta DISCARDED
```

Falha em qualquer ponto: mantém/reestabelece quarentena, mantém identidade durável,
retorna estado explícito `RETAINED` / `DISCARD_FAILED`, e **permite retentativa**.
`ignore_errors=True` deixa de ser autoridade de sucesso. Nunca `200` com material
privado presente. Se marcador ou disposition estiverem corrompidos, a coleta de
startup continua proibida; somente um novo abandono humano confirmado pode remover
a raiz canônica dedicada. Um inventário desacompanhado de custódia não autoriza
remoção: a árvore pode ser religada entre `lstat` e `unlink`. Antes do primeiro
`unlink`, cada diretório fica ancorado até sua última operação destrutiva — por
`dir_fd` + `O_NOFOLLOW` no POSIX e por handle sem delete-sharing que impede
rename no Windows. `O_TEMPORARY` não é usado como trava, pois pode admitir
rename em hosts com semântica POSIX. Qualquer dúvida retém a árvore inteira
sem atravessar o namespace.

A disposition também é publicada sob essa custódia, antes de qualquer cleanup:
uma raiz ou membro reparse é recusado sem escrita no alvo externo. Se a liberação
de um anchor falhar depois da remoção dos controles, a decisão e a quarentena são
reestabelecidas na mesma identidade antes de retornar `RECOVERY_RETAINED`. O
fechamento percorre a árvore inteira mesmo quando um filho falha, para que o
primeiro erro nunca deixe handles de irmãos ou ancestrais vazados. Um descritor
só deixa de pertencer à custódia depois de `close` confirmado; se o fechamento
falhar antes de liberar o handle, sua referência permanece disponível para a
retentativa local. A restauração escreve primeiro disposition e quarentena,
tenta cada controle de forma independente e repete uma vez apenas os writes que
falharam, impedindo que uma falha transitória auxiliar apague a decisão durável.

Preservar sem publicar também é falha: uma raiz canônica que contenha reparse é
exposta de forma sanitizada como `RECOVERY_UNRESUMABLE`, sem percorrer o membro
inseguro, e oferece abandono explícito. Enquanto a contaminação persistir, o
cleanup responde `RECOVERY_RETAINED`; nunca apaga fora da raiz nem torna a sessão
invisível.

A rota global `/recuperacao` permanece alcançável também quando já existem
workspaces vivos. Assim uma promoção parcial não esconde sua sessão pendente atrás
do diretório não vazio.

---

## I. Transporte de binário grande

Uma **única** política de corpo por rota, descrevendo em conjunto: tamanho máximo,
binário vs JSON, se exige streaming/spool, e media type permitido.

Hoje há duas autoridades divergentes (`request_body_limit` diz "binário grande";
`is_document_upload` diz "spool só para documentos"). Passam a ser uma só.

**O que foi entregue, com honestidade sobre o limite** — o transporte passou a ter
autoridade única (`is_large_binary_upload`) e o corpo é spoolado para disco em vez de
ser acumulado na memória do handler. Mas o pacote **continua sendo materializado por
inteiro** depois disso: o formato é um JSON com o conteúdo privado em base64, e
verificar a integridade exige tê-lo completo. Chamar isso de "streaming" seria
descrever a intenção, não o código. Streaming real exige trocar o FORMATO do pacote
(container com quadros e digests por membro), não o transporte — e essa troca fica
para depois do teste humano.

Consequência aceita e declarada: existe teto finito de reingestão
(`MAX_BACKUP_PACKAGE_BYTES`), e é ele que a exportação verifica.

Provar também:

```
SELF_PRODUCED_BACKUP  MUST_BE  REINGESTIBLE_BY_RECOVERY
```

Resolvido pela segunda via: a exportação **falha explicitamente antes** de afirmar que
a perícia está protegida (`BackupTooLarge` → `413 BACKUP_TOO_LARGE`). Não produzir em
silêncio backup que o produto não restaura.

---

## J. Autoridade de custo de IA

Defeito de contrato semântico já provado: pacote com `AI_COST_LEDGER_V1` responde
`VERIFY=200`, `STAGING=201 promotable=True` e depois `PROMOTE=409`.

```
VERIFIED  ≠  PROMOTABLE
```

`promotable` nunca deve ser literal: só é `True` depois de checadas as restrições
canônicas de promoção conhecidas no staging (colisão de identidade, kind não
promovível). Caso contrário, motivo honesto de não-promovibilidade.

Sobre a autoridade de custo em si: reutilizar o mecanismo de recuperação de custo já
existente no Stage 10. Não apagar autoridade de custo, não confiar em ledger portátil
obsoleto, não resetar acumulado, não contornar o ledger vivo. Se workspaces tocados
por IA já forem alcançáveis ao usuário normal, sua recuperação é P1 bloqueante de
#183; se ainda não forem, retornar razão honesta e levar a prova final de
alcançabilidade para `FULL_PRODUCT_REACHABILITY_MATRIX_V1`.

---

## Invariantes que o reparo deve preservar

```
RESTORE_MODEL = VERIFIED_STAGING_THEN_EXPLICIT_HUMAN_PROMOTION
RECOVERY_NOT_PROMOTABLE                            enforced
NO_SILENT_OVERWRITE
FAILED_RESTORE_PRESERVES_EXISTING_WORK
FAILED_PROMOTION_MUST_NOT_LEAVE_UNRECOVERABLE_LIVE_PREFIX   (novo)
QUARANTINE_OUTLIVES_PRIVATE_MATERIAL                        (novo)
PARTIAL_PROMOTION_MUST_BE_RECOVERABLE_OR_ATOMIC
CONCURRENT_COMMANDS_CANNOT_CREATE_DOUBLE_AUTHORITY
PRIVATE_EGRESS = FALSE
NORMAL_USER_REQUIRES_TERMINAL = FALSE
AI_COST_AUTHORITY_CANNOT_DECAY
PROCESS_NAMESPACE_ACQUISITION                      inalterado
```

Uma promoção falha pode deixar o armazenamento vivo **inalterado**, ou deixar uma
transação durável **precisamente identificada e continuável pelo produto normal**.
Nunca: workspace visível + revisões/privado parciais + nenhuma sessão válida +
nenhuma rota de continuação ou remoção.

---

## Escopo do reparo

Construir apenas a capacidade de transação de recuperação exigida por #183. Sem
framework genérico de transação, coordenador distribuído, plano de controle, sistema
de confiança novo, banco externo, serviço novo ou daemon de fundo. Sem sacrificar
correção para manter o diff pequeno — este é um reparo arquitetural.
