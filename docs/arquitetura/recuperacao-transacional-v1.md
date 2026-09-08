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
intent externo imutável `.recovery-cleanup-intent-<uuid>`, irmão da raiz-alvo,
para que falha de limpeza seja retomada com a mesma decisão humana. Uma fase
`PROMOTED` só é terminal quando o journal
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

Antes de adquirir custódia ou iniciar qualquer remoção, o cleanup publica um
intent externo imutável no diretório-base já validado. Uma raiz ou membro reparse
continua recusado sem escrita no alvo externo. Se anchor, controle interno ou
`rmdir` falhar, o intent permanece fora da raiz e o restart reconstrói
`RECOVERY_RETAINED` com a mesma decisão. O fechamento percorre a árvore inteira
mesmo quando um filho falha, para que o primeiro erro não interrompa irmãos ou
ancestrais. Cada slot de descritor é consumido antes da única chamada de `close`:
um erro torna o estado do inteiro ambíguo e proíbe retry local, porque o número
pode já ter sido reutilizado por arquivo alheio. A prova terminal é a ausência da
raiz; só então o intent externo pode ser coletado.

Preservar sem publicar também é falha: uma raiz canônica que contenha reparse é
exposta de forma sanitizada como `RECOVERY_UNRESUMABLE`, sem percorrer o membro
inseguro, e oferece abandono explícito. Enquanto a contaminação persistir, o
cleanup responde `RECOVERY_RETAINED`; nunca apaga fora da raiz nem torna a sessão
invisível.

A rota global `/recuperacao` permanece alcançável também quando já existem
workspaces vivos. Assim uma promoção parcial não esconde sua sessão pendente atrás
do diretório não vazio.

---

## H.1 Reconciliação do protocolo de cleanup (A12/B12)

Status: **modelo normativo reconciliado**. O candidato
`52c565a` está invalidado. As correções sucessivas provaram que restauração de
controles depois da remoção não fecha o protocolo: a própria restauração pode
falhar, criar arquivo parcial ou observar `FileExists` divergente. Também provaram
que erro de `close(fd)` é ambíguo; repetir o mesmo inteiro pode fechar um arquivo
alheio que reutilizou o número.

### Autoridades únicas

| fato | autoridade | não é autoridade |
|---|---|---|
| identidade da recuperação | UUID no nome canônico `recovery-<uuid>` e no descriptor de sessão | endereço de objeto ou dict em memória |
| identidade do staging | token imutável `STAGING_IDENTITY_V1` | inode como identidade longitudinal |
| quarentena | `RECOVERY_NOT_PROMOTABLE` na raiz e marcadores próprios dos stores internos | estado da UI |
| plano/fase de promoção | `PROMOTION_TRANSACTION_V1`, validado integralmente contra a sessão | mera presença do journal ou nome da fase isolado |
| sessão publicada | `RECOVERY_SESSION_V1` imutável | referência forte em `WorkspaceRecoverySessions` |
| decisão `DISCARD`/`ABANDON` | **um único intent externo imutável**, `.recovery-cleanup-intent-<uuid>`, irmão da raiz-alvo | controle dentro da raiz, estado em memória ou inferência pela ausência de material |
| custódia de filesystem | árvore `_CleanupNode` desta chamada, com `dir_fd` no POSIX ou anchor sem delete-sharing no Windows | inventário anterior, pathname desacompanhado ou preflight concluído |
| ownership de descriptor | slot ainda não consumido antes da única chamada de `close` | o mesmo inteiro depois de qualquer retorno com erro |
| existência da raiz | observação estrutural do filho canônico direto sob a base de recovery | presença/ausência de controles internos isolados |
| cleanup committed | raiz-alvo comprovadamente ausente | ausência de material, `close` sem erro ou tentativa de `rmdir` |
| reconstrução no restart | intent externo primeiro; depois controles internos da raiz para estados sem cleanup iniciado | cache de processo |

O intent externo pertence ao **mesmo namespace local de recovery**, não a SQLite,
outro banco ou outro serviço. Ele não cria segunda autoridade: substitui
`RECOVERY_DISPOSITION_V1` interno como autoridade única da decisão de cleanup.
Seu registro canônico contém somente versão, `recovery_id`, modo e nome exato da
raiz. Publicação é create-only + fsync + link no-replace. `FileExists` equivale a
sucesso apenas quando o arquivo existente é regular, exclusivo e byte a byte
idêntico; conteúdo parcial, ilegível, link/reparse ou divergente falha fechado.

### Decisão entre as três alternativas

| alternativa | resultado | razão |
|---|---|---|
| A — intent/sidecar fora da raiz | **ESCOLHIDA** | preserva a decisão enquanto a raiz existir; root ausente permite concluir e coletar o sidecar |
| B — intenção no rename da raiz | rejeitada | no Windows, handles precisam ser liberados antes; pathname pode mudar nessa janela e não há no-replace ancorado portátil para diretórios |
| C — somente controles internos | rejeitada por prova | sempre há uma janela entre remover a última autoridade interna e provar `rmdir`; A12/B12 reproduziram perda de decisão nessa janela |

SQLite foi rejeitado como local do intent: recriaria uma transação distribuída
entre banco e filesystem justamente no protocolo que precisa remover uma raiz de
filesystem. O sidecar é o menor WAL local capaz de ordenar a única transição.

### Máquina de estados reconciliada

| estado | autoridade de entrada | ação permitida | ação proibida | transição durável |
|---|---|---|---|---|
| `STAGED` | sessão + quarentena válidas, journal ausente | `PROMOTE`, `DISCARD` | promoção automática | `DISCARD` publica intent externo antes de remover qualquer byte |
| `PROMOTING` | claim em processo + journal `PROMOTING` | nenhuma concorrente | `DISCARD` concorrente | falha/restart reconcilia journal + estado vivo |
| `FAILED_RECOVERABLE` | journal íntegro e estado vivo ainda prefixo exato | `PROMOTE`; `ABANDON` somente explícito | descarte implícito | divergência persistida no journal antes de virar irretomável |
| `RECOVERY_UNRESUMABLE` | journal/identidade não convergente, sem cleanup intent | `ABANDON` explícito | `PROMOTE` | `ABANDON` publica intent externo antes do cleanup |
| `DISCARDING` | claim em processo, antes do commit do intent | nenhuma concorrente | segundo cleanup | crash antes do intent volta ao estado anterior; depois do intent reconstrói `RECOVERY_RETAINED` |
| `RECOVERY_RETAINED` | intent externo válido + raiz presente | somente retry do mesmo modo | trocar `DISCARD` por `ABANDON` ou vice-versa por inferência | nova tentativa usa o mesmo intent; nunca o sobrescreve |
| `DISCARDED` | raiz ausente depois de intent válido | nenhuma | reabrir/promover | sidecar pode ser removido/garbage-collected somente agora |
| `PROMOTED` | vivo integral verificado + journal terminal | nenhuma | novo cleanup concorrente | resíduo de staging é coleta terminal, sem alterar o vivo |

Falha antes de publicar o intent não iniciou cleanup: nenhum material pode ter sido
removido e o estado anterior continua reconstruível. Falha depois da publicação
jamais volta a `STAGED`, mesmo se todos os controles internos já tiverem sumido.

### Mapa de crash/restart

| ponto de queda | fato durável | reconstrução obrigatória |
|---|---|---|
| antes do intent externo | raiz e controles originais | estado anterior (`STAGED`, recuperável ou irretomável) |
| depois do intent, antes do primeiro unlink | sidecar + raiz intacta | `RECOVERY_RETAINED`, retry do mesmo modo |
| durante remoção de material | sidecar + raiz + quarentena | `RECOVERY_RETAINED`; nunca sucesso com resíduo privado |
| depois do último material, antes dos controles | sidecar + raiz | `RECOVERY_RETAINED`; decisão humana preservada |
| depois dos controles/quarentena, antes de `rmdir` | sidecar + raiz possivelmente vazia | `RECOVERY_RETAINED`; sidecar substitui a autoridade já removida |
| depois de `rmdir`, antes de remover sidecar | sidecar + raiz ausente | cleanup committed; coletar sidecar sem recriar sessão |
| depois de remover sidecar | raiz ausente | terminal `DISCARDED` |

### Semântica de descriptors

```
CLOSE_SUCCESS => DESCRIPTOR_NO_LONGER_OWNED
CLOSE_ERROR => DESCRIPTOR_STATE_UNKNOWN
CLOSE_ERROR != DESCRIPTOR_STILL_OPEN
CLOSE_ERROR != DESCRIPTOR_CLOSED
AMBIGUOUS_FD_NUMBER_MUST_NEVER_BE_CLOSED_AGAIN
```

O slot é consumido **antes** da única chamada de `close`. Um erro nunca autoriza
segunda chamada com o mesmo inteiro. Todos os irmãos e ancestrais ainda são
processados. No Windows, remover o anchor depois do erro é uma prova separada e
segura: se o handle original continuou aberto sem delete-sharing, o unlink falha e
a raiz fica retida; se ele fechou de fato, o anchor pode sair. A decisão final não
é o retorno de `close`, mas a prova `root absent`. Handle ambíguo que permaneceu
aberto é liberado pelo encerramento do processo; o restart reencontra o intent e
converge sem reutilizar o fd.

### Invariantes fechadas

```
FILE_EXISTS != VALID_CONTROL_EXISTS
VALID_CONTROL_EXISTS <=> REGULAR_EXCLUSIVE_AND_EXACT_BYTES
DURABLE_DISPOSITION_OUTLIVES_DESTRUCTIVE_CLEANUP
QUARANTINE_OUTLIVES_PRIVATE_MATERIAL
ROOT_EXISTS_AFTER_INTENT => CLEANUP_INTENT_RECONSTRUCTIBLE
ROOT_ABSENT => CLEANUP_MAY_BE_COMMITTED
PRIVATE_RESIDUE + SUCCESS = PROHIBITED
FALSE_SUCCESS = PROHIBITED
NO_DOUBLE_CLOSE
NO_FOREIGN_FD_CLOSE
```

### H.2 Âncora de confiança do namespace de recovery (A13/B13)

Status: **modelo normativo reconciliado antes da implementação**. O candidato
`e5993c0f` está invalidado. A13 e B13 provaram independentemente que custodiar
somente `recovery-<uuid>` não protege a base `.sqlite3.recovery`: se a própria
base for uma junction, o startup enumera e remove uma árvore externa.

```text
SAFE_CHILD_ROOT != SAFE_RECOVERY_BASE_NAMESPACE
PATH_VALIDATED != PATH_CUSTODIED
CHECK_THEN_USE_BY_PATH = INSUFFICIENT_FOR_DESTRUCTIVE_RECOVERY
TRUSTED_CHILD_REQUIRES_TRUSTED_ANCESTRY
```

#### Primeira autoridade e cadeia física

O primeiro diretório confiável é a **raiz local do volume** que contém o banco
ativo. Caminhos UNC, device paths e volumes remotos continuam recusados. A raiz
do volume não autoriza seus descendentes por inferência: cada componente lexical
é aberto sem seguir reparse, validado como diretório local não-reparse e mantido
aberto até a última operação que depende dele.

```text
volume-root (trust anchor, handle H0)
  -> component-1 (H1)
  -> ...
  -> database-parent (Hn)
  -> .<database>.sqlite3.recovery (Hbase)
  -> recovery-<uuid> (Hchild)
  -> descendants necessários ao cleanup (Hdesc...)
```

Uma base ausente pode ser criada somente enquanto a cadeia até seu pai está
custodiada. Depois de `mkdir`, a base recém-observada é aberta sem seguir reparse
antes de qualquer enumeração ou escrita. Se outro ator ganhar a corrida e criar
uma junction, a aquisição abre o próprio reparse e o rejeita; nenhum byte é
criado no alvo.

#### Semântica por plataforma

No POSIX, a cadeia usa `open(..., O_DIRECTORY | O_NOFOLLOW)` e operações de
namespace relativas ao `dir_fd` custodiado. No Windows, a biblioteca padrão não
oferece `dir_fd` para essa fronteira. A implementação pode usar somente uma
primitiva Win32 estreita para recovery:

- `CreateFileW(..., OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS |
  FILE_FLAG_OPEN_REPARSE_POINT)` abre o diretório ou o próprio reparse;
- `desired_access=0` foi rejeitado por prova executável: nessa modalidade o
  rename Windows com semântica POSIX ainda conseguiu religar a base. A custódia
  solicita `FILE_LIST_DIRECTORY | FILE_READ_ATTRIBUTES | SYNCHRONIZE`;
- o share mode admite leitura/escrita, mas **não** `FILE_SHARE_DELETE`, mantendo
  o componente resistente a rename/delete/rebind, inclusive tentativas com
  semântica POSIX;
- `GetFileInformationByHandle` prova diretório, ausência de
  `FILE_ATTRIBUTE_REPARSE_POINT` e identidade estável de volume/arquivo;
- todos os handles da ancestry permanecem vivos durante enumeração, abertura,
  publicação/leitura/GC de intent e remoção;
- cada slot é consumido antes de uma única chamada a `CloseHandle`; erro de
  fechamento é ambíguo e nunca autoriza retry do mesmo valor.

Pathnames ainda podem ser usados no Windows **somente enquanto todos os seus
componentes estão presos por handles sem delete-sharing**. Eles não constituem
autoridade; os handles constituem. No POSIX, operações materiais usam o descritor
relativo sempre que a API o suporta. SQLite e o armazenamento privado continuam
com suas autoridades first-party, mas a raiz que recebem permanece presa pela
custódia da sessão inteira.

#### TOCTOU e operações abrangidas

Validação e uso compartilham a mesma custódia em:

- criação da base e de `recovery-<uuid>`;
- coleta de órfãos e reconstrução no startup;
- abertura/listagem de sessões;
- leitura, publicação, substituição controlada e GC do cleanup intent;
- `DISCARD`, `ABANDON` e suas retentativas;
- aquisição recursiva e cleanup de descendentes.

Junction existente, junction tardia, rename da base/raiz, rename Windows com
semântica POSIX e reparse descendente resultam em aquisição recusada ou sharing
violation antes da mutação. Uma ancestry não provada não é tratada como base
vazia e não produz sessão, intent ou coleta.

```text
RECOVERY_BASE_REPARSE = FAIL_CLOSED
RECOVERY_ANCESTOR_REPARSE = FAIL_CLOSED
REPARSE_ANCESTOR => NO_ENUMERATION + NO_INTENT_PUBLICATION + NO_OPEN
REPARSE_ANCESTOR => NO_DELETE + NO_GC
EXTERNAL_FILESYSTEM_MUTATION = 0
EXTERNAL_SENTINEL_BEFORE == EXTERNAL_SENTINEL_AFTER
EXTERNAL_TREE_HASH_BEFORE == EXTERNAL_TREE_HASH_AFTER
```

#### Alternativas

| alternativa | decisão | fundamento |
|---|---|---|
| somente `lstat`/`resolve` da ancestry | rejeitada | separa check e use; a base pode ser religada depois da validação |
| custodiar apenas o filho | rejeitada por A13/B13 | alcançar o filho já atravessou uma base potencialmente externa |
| arquivo-anchor criado dentro do diretório | rejeitada para aquisição Windows | a criação do anchor pode ser a primeira escrita no alvo externo |
| handles relativos puros via Python no Windows | indisponível | `dir_fd` não é suportado de forma suficiente nessa plataforma |
| fail-closed + custódia contínua híbrida | **escolhida** | usa `dir_fd` no POSIX e handles Win32 mínimos para impedir rebind sem novo framework |

#### Matriz adicional de falha

Cada combinação de base/parent junction com árvore vazia, marcador, descriptor,
journal, intent e sentinel precisa provar zero traversal autoritativo e zero
mutação. A matriz atravessa startup, list, stage, discard, abandon, retries e GC,
além de swaps entre validação/enumeração, rename concorrente, junction tardia e
reparse filho. Um namespace normal é o controle positivo. Hash da árvore externa,
bytes do sentinel, eventos de abertura para escrita, publicação de intent e
remoção são oráculos independentes.

### Matriz mínima de fault injection

| grupo | cenários determinísticos | oráculo comum |
|---|---|---|
| aquisição/custódia | criar anchor falha; identidade muda; root/nested reparse; sharing violation | nenhuma mutação externa, nenhuma autoridade falsa |
| fechamento | erro antes de fechar; fecha e retorna erro; inteiro reutilizado; unlink do anchor falha | nunca fechar fd alheio, processar toda a árvore, root presente nunca vira sucesso |
| material | unlink parcial; resíduo privado; segunda operação concorrente | quarentena sobrevive ao material, sem `200` falso |
| controles internos | falha removendo identidade, sessão, journal ou quarentena | intent externo continua exato e restart oferece somente o retry original |
| intent externo | create falha; write parcial; `FileExists` exato/divergente; ilegível/link/reparse | nenhum unlink antes do commit; equivalência somente por bytes exatos |
| raiz | `rmdir` transitório/persistente; morte antes/depois de cada fase | raiz presente retém intent; raiz ausente permite commit/GC |
| lifecycle | restart em cada fase; retry sem terminal; `DISCARD` e `ABANDON`; cleanup concorrente | ação válida, intenção preservada, vivo inalterado |

Cada linha exige conjuntamente `NO_FALSE_SUCCESS`, `NO_LOST_AUTHORITY`,
`NO_DOUBLE_CLOSE`, `NO_FOREIGN_FD_CLOSE`, `NO_PRIVATE_RESIDUE_WITH_SUCCESS`,
`RESTART_HAS_VALID_NEXT_ACTION` e `HUMAN_INTENT_PRESERVED`.

### H.3 Continuidade de identidade do namespace (A14/B14)

Status: **modelo normativo reconciliado antes do novo RED e antes de qualquer
mutacao de producao**. O candidato
`36dcfe9550ccb902bf1b5dd5dae37dca48fd11c2` esta invalidado. H.3 corrige duas
afirmacoes fortes demais de H.2: `mkdir` seguido de `open` nao e criacao
vinculada, e fechar o ultimo handle antes de `rmdir(path)` nao e remocao
vinculada.

```text
CHILD_CREATED != CHILD_IDENTITY_BOUND
IDENTITY_VALIDATED_BEFORE_DELETE != IDENTITY_BOUND_THROUGH_DELETE
PATH_ABSENT != EXPECTED_IDENTITY_REMOVED
LOGICAL_CONTROL_EQUALITY != PHYSICAL_FILESYSTEM_IDENTITY
```

#### DAG causal e caminho critico

```text
A14 post-create rebind + A14/B14 post-close rebind
  -> contrato de autoridade H.3
  -> REDs nos dois pontos de coordenacao
  -> primitivas Windows estreitas create/open/delete por handle
  -> identidade fisica no handoff e no cleanup intent duravel
  -> cleanup terminal vinculado ao mesmo handle
  -> matriz focada + sibling sweep
  -> unico HEAD terminal + CI protegida
  -> A15 e B15 independentes em paralelo
```

O caminho critico e `criacao vinculada -> primeiro write` e `identidade esperada
-> remocao terminal -> prova de commit`. Pesquisa oficial e modelagem dos REDs
podem ocorrer em lane somente leitura; existe um unico mutation owner para
`workspace_recovery.py`, `productization.py`, arquitetura e testes. A15/B15 nao
iniciam antes do HEAD terminal congelado.

#### Mapa das operacoes materiais

| boundary | cria/adquire/valida | primeira ou ultima mutacao | autoridade exigida |
|---|---|---|---|
| `RecoveryFilesystemCustody._acquire_*` | cria a base final ausente e adquire a cadeia | torna a base enumeravel | parent ja custodiado; criacao Windows devolve o primeiro handle |
| `RecoveryFilesystemCustody.create_child` | cria `recovery-<uuid>` | entrega a raiz a `RecoveryStaging` | parent custodiado; child handle nasce na mesma operacao de criacao |
| `RecoveryStaging.create` | recebe custody e valida identidade | grava quarentena, SQLite e private store | nenhum write antes da identidade fisica vinculada |
| `abrir_staging_quarentenado` | readquire a raiz e confere quarentena | abre SQLite/private para retomada | ancestry e child continuamente custodiados |
| journal/identity/descriptor | abre, grava, fsync, link/replace e le controles | publica autoridade duravel interna | custody da sessao permanece viva; bytes exatos continuam obrigatorios |
| `_persistir_cleanup_intent` | cria sidecar exclusivo na base e o rele | publica decisao antes de unlink | base custodiada + identidade fisica esperada no proprio registro |
| `_adquirir_custodia_cleanup` | abre e inventaria raiz/descendentes | prepara remocao | handle da raiz tem `DELETE`, nega delete-sharing e coincide com a identidade esperada |
| `_remover_material_ancorado` | remove arquivos e diretorios filhos | cleanup destrutivo | parent/child handles vivos; diretorio filho sai por seu proprio handle no Windows |
| `_remover_raiz_quarentenada` | remove controles por ultimo | remove o namespace raiz e libera GC | o mesmo handle esperado fica vivo ate disposition, prova e close consumido |
| `_encerrar_staging` / `_remover_entry` | captura a identidade antes de `discard/close` | transfere sessao para cleanup | identidade nao pode ser readquirida ou inferida pelo pathname |
| `recolher_stagings_orfaos` | enumera base e classifica roots/intents | coleta somente terminal/orfao provado | intent existente fixa modo e identidade para todo retry |
| `reconstruir_sessoes_recuperacao` | enumera/readquire/le controles | reabre staging, sem remover | base e child custodiados durante cada leitura |
| composition root | calcula `.sqlite3.recovery` e chama coleta/reconstrucao/stage | nenhuma autoridade propria | apenas encadeia as autoridades acima |

Pathnames reconstruidos por `Path(parent) / name` sao localizadores, nunca prova
de identidade. No Windows eles so podem ser usados enquanto a ancestry
correspondente esta presa sem delete-sharing. No POSIX, as operacoes de namespace
continuam relativas a `dir_fd` e recusam follow com `O_NOFOLLOW`.

#### Contrato de criacao

```text
TRUSTED_PARENT_CUSTODY
  -> CREATE CHILD AND RETURN ITS HANDLE
  -> READ/BIND PHYSICAL IDENTITY FROM THAT HANDLE
  -> KEEP CONTINUOUS CUSTODY
  -> FIRST WRITE
```

```text
CREATE_CHILD_WITHOUT_PARENT_CUSTODY = PROHIBITED
CHILD_CREATED => CHILD_IDENTITY_BOUND_BEFORE_ANY_WRITE
FIRST_WRITE_REQUIRES_BOUND_CHILD_IDENTITY
MKDIR_THEN_GLOBAL_PATH_REOPEN = PROHIBITED_ON_WINDOWS
```

No Windows, a primitiva escolhida e `NtCreateFile` documentada para user mode,
com nome de um unico componente relativo ao `OBJECT_ATTRIBUTES.RootDirectory`
do parent custodiado, `FILE_CREATE`, `FILE_DIRECTORY_FILE`, acesso minimo de
diretorio e nenhum `FILE_SHARE_DELETE`. A chamada cria e devolve o handle do
mesmo objeto; sua identidade `FILE_ID_INFO` (`volume serial`, `file id` de 128
bits) e lida antes de qualquer
write. Para transferir a ancestry a nova custody sem reabrir o filho por
pathname, `DuplicateHandle(..., DUPLICATE_SAME_ACCESS)` duplica os handles-pai
no mesmo processo; o handle-filho devolvido pela criacao e transferido sem
substituicao. Falha parcial fecha cada duplicata ja criada e o handle-filho sem
fazer rollback por pathname. Falha, simbolo indisponivel, status inesperado ou
objeto nao-diretorio falham fechados. As novas funcoes sao privadas e especificas
de recovery; nao expoem API generica de filesystem, processo, shell ou argv.

O handle de criacao nao solicita `DELETE`: a ausencia de `FILE_SHARE_DELETE` ja
bloqueia rename/delete por terceiros, enquanto pedir esse acesso faria aberturas
legitimas posteriores precisarem compartilhar delete. `DELETE` e adquirido
somente no cleanup, depois do fechamento da sessao, para o objeto cuja identidade
o intent fixou. Se a transferencia da custody falhar, os handles sao consumidos
e o diretorio vazio fica retido; nao existe rollback destrutivo por pathname.

No POSIX permanece `mkdirat(parent_fd, name)` seguido de
`openat(parent_fd, name, O_DIRECTORY | O_NOFOLLOW)` e toda operacao de namespace
subsequente permanece ancorada no descritor. H.3 nao introduz pathname global
como autoridade nessa plataforma.

#### Contrato de remocao e commit

```text
EXPECTED_CHILD_IDENTITY
  -> OPEN EXACT CHILD FOR DELETE UNDER TRUSTED PARENT
  -> DESTRUCTIVE CLEANUP WHILE HANDLE REMAINS OPEN
  -> HANDLE-BOUND FINAL DISPOSITION
  -> PROVE THAT HANDLE IS DELETE-PENDING
  -> CONSUME/CLOSE HANDLE ONCE
  -> PROVE THE EXPECTED NAME IS ABSENT (OR RETAIN ON REPLACEMENT/UNCERTAINTY)
  -> COMMIT / INTENT GC
```

```text
EXPECTED_FILESYSTEM_IDENTITY_MUST_SURVIVE_UNTIL_NAMESPACE_REMOVAL_COMMITTED
CLOSE_CUSTODY_BEFORE_FINAL_REMOVAL = PROHIBITED
PATHNAME_RMDIR_WITHOUT_EXPECTED_IDENTITY = PROHIBITED
EXPECTED_IDENTITY_MUST_NOT_BE_REINFERRED_FROM_PATH_ON_RETRY
```

O cleanup intent externo passa a carregar a identidade fisica esperada junto
de `mode`, `recovery_id` e `root_name`. Ele nao cria segunda autoridade: apenas
durabiliza qual objeto a decisao existente escolheu. `DISCARD`/`ABANDON` capturam
essa identidade antes de `staging.discard()`. Startup e retry devem comparar o
root aberto com o valor do intent; divergencia preserva o intent e nao toca o
substituto.
Se uma tentativa `COLLECT` ja consumiu os controles internos antes de falhar na
remocao terminal, o intent preexistente substitui essa autoridade no restart e
permite somente a mesma coleta da mesma identidade. Um intent criado na tentativa
corrente nao autoriza, sozinho, uma raiz que ja chegou com quarentena invalida.

No Windows, a raiz e cada diretorio filho a remover sao abertos com `DELETE` e
sem delete-sharing. A remocao terminal usa
`SetFileInformationByHandle(FileDispositionInfo)` no proprio handle, confirma
`FILE_STANDARD_INFO.DeletePending`, consome o slot antes da unica tentativa de
`CloseHandle` e entao verifica o namespace sob o parent ainda custodiado. Um
nome religado depois do delete exato e tratado como `RECOVERY_RETAINED`; nunca e
apagado para fazer o retry convergir.

O commit nao decorre apenas de `path.exists() == false`. Ele requer conjuntamente:

```text
OPEN_HANDLE_IDENTITY == EXPECTED_FILESYSTEM_IDENTITY
HANDLE_BOUND_DELETE_ACCEPTED = TRUE
HANDLE_DELETE_PENDING = TRUE
EXPECTED_NAMESPACE_ENTRY_ABSENT = TRUE
EXTERNAL_MUTATION = 0
ORIGINAL_RECOVERY_PARKED_WITH_SUCCESS = 0
DURABLE_INTENT_GC_ALLOWED = TRUE
```

Se qualquer prova estiver ausente, ambigua ou divergente, o estado terminal e
`RECOVERY_RETAINED` (ou falha fechada equivalente) e o intent nao sofre GC.
Se o processo morrer depois da remocao exata e antes do GC, o restart observa
somente pathname ausente, portanto preserva o sidecar nao privado e nao tenta
reconstruir a prova perdida. Esse residuo de controle e preferivel a converter
ausencia de nome em uma falsa prova de identidade.

#### Decisao de primitiva Windows

Fontes primarias: a documentacao Microsoft de
[`NtCreateFile`](https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntcreatefile)
define criacao de diretorio e nome relativo a `RootDirectory`; a de
[`SetFileInformationByHandle`](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-setfileinformationbyhandle)
vincula a disposition ao handle e exige `DELETE`; e
[`FILE_STANDARD_INFO`](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_standard_info)
expoe `DeletePending`; e
[`DuplicateHandle`](https://learn.microsoft.com/en-us/windows/win32/api/handleapi/nf-handleapi-duplicatehandle)
documenta que a duplicata referencia o mesmo objeto e, com
`DUPLICATE_SAME_ACCESS`, conserva o acesso da origem. `CreateDirectory2W`/`RemoveDirectory2W` tambem fecham
redirects, mas exigem Windows 11 24H2 e `RemoveDirectory2W` ainda recebe pathname,
nao handle/identidade.

A pesquisa independente de 24 criterios que antecedeu a implementacao ficou
registrada em
`%TEMP%/issue-183-windows-directory-handle-ranking-20260908.md`, SHA-256
`442DC35E5275F12C1DDE66C4F4633C1DFCD742B256A573D16772DCF3CD00E281`, com 14
fontes primarias oficiais Microsoft. O unico candidato elegivel obteve `78.95`;
os outros dois foram excluidos por gates de correctness/security/compatibility,
nao apenas por score.

| candidata | elegibilidade | decisao repository-specifica |
|---|---|---|
| `NtCreateFile` relativo + `SetFileInformationByHandle` | elegivel; API oficial user-mode, sem dependencia e compatibilidade Windows anterior a 24H2 | **escolhida** no menor wrapper ctypes privado |
| `CreateDirectory2W` + `RemoveDirectory2W` | create retorna handle, mas remove relê pathname; ambas exigem Windows 11 24H2 | inelegivel por correctness/security e compatibilidade |
| `mkdir/CreateDirectory` + reopen e `rmdir(path)` | reproduziu escrita e delecao externas, mais falso sucesso | inelegivel por correctness/security |

`FILE_DISPOSITION_INFO_EX` e um framework filesystem novo nao sao necessarios:
a classe classica por handle, mais `DeletePending` e verificacao parent-custodiada,
fecha o boundary reproduzido com menor superficie.

#### Matriz TOCTOU obrigatoria

| momento adversarial | resultado permitido |
|---|---|
| swap logo apos create ou antes do primeiro handle | rename bloqueado pelo handle retornado pela criacao; zero write externo |
| rename do child criado / replacement externo ou logico byte-identico | nenhuma adocao por pathname; identidade fisica continua a criada |
| race antes da quarentena/SQLite/private | first write somente depois do binding; replacement nunca recebe controle/material |
| swap apos ultimo unlink interno ou antes da remocao final | handle ainda vivo impede rename/rebind; delete mira esse handle |
| recovery verdadeira estacionada e substituto no nome | mismatch com intent; `RECOVERY_RETAINED`; sentinel e substituto intactos |
| substituto com mesmos controles/estrutura | igualdade logica nao vence identidade fisica divergente |
| intent existente + retry concorrente | claim serial existente + intent fixa modo/identidade; nenhum reselect por pathname |
| replacement depois do close exato, antes do GC | nome presente bloqueia commit/GC; replacement intacto; intent esperado permanece |
| close/disposition/prova ambigua | slot consumido uma vez; sem GC; restart/retry retidos |

Regra comum: `PATH_REBOUND => ZERO_EXTERNAL_MUTATION + ZERO_FALSE_SUCCESS`.

#### Invariantes preservadas

H.3 e aditiva ao modelo de disposition/quarentena; nao altera seu significado:

```text
DURABLE_DISPOSITION_OUTLIVES_DESTRUCTIVE_CLEANUP
QUARANTINE_OUTLIVES_PRIVATE_MATERIAL
ROOT_EXISTS => CLEANUP_INTENT_RECONSTRUCTIBLE
AMBIGUOUS_FD_NUMBER_MUST_NEVER_BE_CLOSED_AGAIN
FILE_EXISTS != VALID_CONTROL_EXISTS
EXISTING_CONTROL_BYTES == EXPECTED_CONTROL_BYTES
TRUSTED_CHILD_REQUIRES_TRUSTED_ANCESTRY
REPARSE_ANCESTOR => NO_TRAVERSAL
EXTERNAL_FILESYSTEM_MUTATION = 0
```

### H.4 Continuidade POSIX por `dir_fd` (A15/B15)

Status: **modelo normativo reconciliado antes dos REDs e antes da mutacao de
producao**. O candidato `f0ab793f63bb2db47ee4468c983f6b098b422a10` esta
invalidado. A15 demonstrou que `create_child` fazia `mkdirat` sob o parent
custodiado e, em seguida, readquiria o filho pelo pathname absoluto antes da
primeira escrita. B15 encontrou a mesma familia causal na aquisicao da raiz de
cleanup. Portanto, a frase de H.3 que dizia que toda operacao POSIX posterior
ja permanecia ancorada estava incorreta.

```text
DIR_FD_ACQUIRED => PATHNAME_AUTHORITY_ENDED
HANDLE_RELATIVE_CREATE -> GLOBAL_PATH_REACQUISITION = PROHIBITED
PATH_REBOUND => ZERO_EXTERNAL_MUTATION + ZERO_FALSE_SUCCESS
```

O pathname absoluto continua permitido apenas como identificador auxiliar para
mensagem sanitizada, UI e correlacao de sessao. Ele nao seleciona, valida,
enumera, escreve nem remove objetos depois que a cadeia de descritores foi
adquirida.

#### DAG causal e caminho critico POSIX

```text
A15 create rebind + B15 cleanup-root rebind
  -> contrato H.4
  -> RED de primeira escrita e RED de remocao terminal
  -> mkdirat + openat + fstat + child_fd transferido
  -> controles iniciais/SQLite/private relativos ao child_fd
  -> retomada e classificacao relativas ao child_fd
  -> cleanup interno relativo ao child_fd
  -> identidade esperada validada sob base_fd
  -> rmdirat relativo ao base_fd
  -> intent somente coletado apos prova do objeto esperado removido
  -> matriz focada + sibling sweep
  -> unico HEAD terminal + CI protegida
  -> A16/B16 independentes e concorrentes
```

O caminho critico e a continuidade de autoridade de `mkdirat` ate a primeira
escrita e, depois, da identidade duravel ate o commit da remocao. Ha um unico
mutation owner para `workspace_recovery.py`, `productization.py`, infraestrutura
SQLite/private, esta arquitetura e os testes. A16/B16 so iniciam no SHA exato
aprovado pela CI protegida.

#### Cadeia de autoridade e lifetime

| fase | nascimento/manutencao do descritor | operacoes autoritativas |
|---|---|---|
| base | abre cada componente a partir de `/`, sempre com `openat` e `O_NOFOLLOW` | `listdir/scandir(base_fd)`, sidecar por `openat/linkat/unlinkat`, filhos por `openat` |
| criacao | `mkdirat(parent_fd, child_name)`; imediatamente `openat(parent_fd, child_name, O_DIRECTORY|O_NOFOLLOW)` e `fstat(child_fd)` | nenhuma reconstrucao `/base/recovery-*` entre create, bind e primeiro write |
| staging | duplica a ancestry e transfere o `child_fd` ja aberto | quarentena, identidade, sessao e journal por nomes relativos; `fsync(child_fd)` |
| SQLite | conserva duplicata do `child_fd` durante toda a conexao | alvo e arquivos auxiliares derivados somente do alias de descritor validado; nunca do pathname global de recovery |
| privado | `mkdirat(child_fd, "private")`, `openat`, `fstat` e handoff do fd | controles e conteudo permanecem relativos ao `private_fd` |
| retomada | `openat(base_fd, child_name, O_DIRECTORY|O_NOFOLLOW)` e `fstat` | inventario, controles, SQLite e privado sob o fd adquirido |
| cleanup | abre a raiz relativamente ao `base_fd` e descendentes relativamente ao parent fd | `scandir(fd)`, `openat`, `unlinkat`; antes de cada `rmdirat`, `statat(parent_fd, name)` deve coincidir com `fstat(child_fd)` e com a identidade vinculada |
| remocao final | `base_fd` e `child_fd` permanecem vivos, e a identidade do nome sob a base deve coincidir com a esperada | `rmdir(child_name, dir_fd=base_fd)`; divergencia ou ambiguidade retem raiz e intent |

O adaptador SQLite da biblioteca padrao nao aceita um fd como filename. No
POSIX, a integracao de recovery usa somente um alias de namespace do proprio
descritor (por exemplo `/proc/self/fd/N`), valida que esse alias resolve para a
mesma identidade de `fstat(N)` e mantem uma duplicata viva ate fechar a conexao.
Esse alias e autoridade derivada do handle, nao uma reconstrucao do pathname
global. Plataforma sem alias validavel falha fechada; nao ha fallback para
`/base/recovery-*/workspace.sqlite3`.

#### Criacao, primeira escrita e crash

```text
TRUSTED_PARENT_FD
  -> mkdirat(parent_fd, child_name)
  -> openat(parent_fd, child_name, O_DIRECTORY | O_NOFOLLOW)
  -> fstat(child_fd)
  -> bind da identidade fisica
  -> transferir child_fd para RecoveryStaging
  -> publicar quarentena relativamente ao child_fd
  -> abrir SQLite relativamente ao child_fd
  -> provisionar private relativamente ao child_fd
```

Falha depois de `mkdirat` e antes do bind nunca autoriza rollback por pathname;
a raiz e retida para coleta posterior. Falha depois do bind usa apenas o fd
transferido. Em restart, a base e readquirida uma vez e cada candidata nasce por
`openat(base_fd, name)`: controles byte-identicos em um substituto nao vencem a
identidade fisica fixada pelo intent.

#### Cleanup e commit

```text
BASE_FD + EXPECTED_CHILD_IDENTITY
  -> openat(BASE_FD, child_name) + fstat(CHILD_FD)
  -> identidade exata ou RETAIN
  -> inventario e cleanup relativos a CHILD_FD
  -> controles saem por ultimo
  -> validar entrada child_name relativamente a BASE_FD
  -> rmdir(child_name, dir_fd=BASE_FD)
  -> fstat(CHILD_FD) prova nlink == 0 e identidade esperada
  -> somente entao GC do intent relativamente a BASE_FD
```

Se a raiz verdadeira for estacionada e um substituto ocupar o nome, a
identidade observada sob `base_fd` diverge antes da remocao: o substituto
sobrevive, a raiz original nao e falsamente declarada removida e o intent
permanece. Ausencia de nome em restart, sozinha, continua insuficiente para GC.

#### REDs e invariantes executaveis

Os REDs coordenam swaps deterministas depois da criacao e antes da primeira
escrita; antes do cleanup; depois do cleanup interno e antes do `rmdirat`; e
antes do GC. Cobrem quarentena, sessao, identidade, SQLite, private, substituto
com controles byte-identicos, estrutura equivalente e original estacionado.

```text
POSIX_RECOVERY_OPERATIONS_ARE_DIRFD_RELATIVE = TRUE
GLOBAL_PATH_REACQUISITION_AFTER_DIRFD = PROHIBITED
MKDIRAT_TO_FIRST_WRITE_HAS_NO_GLOBAL_PATH_WINDOW
CHILD_FD_IDENTITY_BINDS_FIRST_WRITE
CLEANUP_CHILD_FD_REMAINS_AUTHORITATIVE
FINAL_RMDIR_IS_BASE_FD_RELATIVE
EXPECTED_IDENTITY_SURVIVES_UNTIL_REMOVAL_COMMIT
PATH_REBOUND => ZERO_EXTERNAL_MUTATION
```

H.4 nao altera o branch Windows nem reduz seus handles, `FILE_ID_INFO`,
disposition por handle ou protecao contra reparse. As invariantes de intent
duravel, quarentena por ultimo, fechamento unico, bytes exatos e ancestry
confiavel permanecem cumulativas.

---

### H.5 Matriz de plataforma do Recovery V1 (decisao humana pos-A16/B16)

Status: **contrato normativo reconciliado antes dos REDs e antes da mutacao de
producao**. O candidato `846c9a5519955260e165f7367f89d3fad542815a` esta
invalidado. A16 demonstrou a janela `statat -> rmdirat`; B16 demonstrou a janela
`mkdirat -> openat`. A decisao de produto nao autoriza outra primitiva de trust
POSIX nesta Issue: Recovery V1 mutavel passa a ser suportado somente no Windows.

```text
WINDOWS_RECOVERY_V1 = SUPPORTED
POSIX_MUTABLE_RECOVERY_V1 = UNSUPPORTED_FAIL_CLOSED
RECOVERY_PLATFORM_UNSUPPORTED = BEFORE_FIRST_MUTATION
```

#### RECOVERY_V1_PLATFORM_MATRIX

| Capability | Windows | POSIX |
|---|---|---|
| Export backup | supported | supported quando independente da namespace mutavel de recovery |
| Verify backup | supported | supported; leitura estrutural sem efeito colateral |
| Stage restore | supported | unsupported fail-closed |
| Promote restore | supported | unsupported fail-closed |
| Discard / abandon | supported | unsupported fail-closed |
| Retry discard / abandon | supported | unsupported fail-closed |
| Startup reconstruction | supported | disabled; preserva material existente sem traversal mutavel |
| Orphan collection | supported | disabled; zero delete e zero intent publication |
| Recovery intent GC | supported | disabled; zero mutation |

O predicado de suporte pertence a application/backend. O transporte pode
consultar essa mesma autoridade para recusar um upload de staging antes de criar
spool, mas nao cria uma segunda regra de plataforma. A UI apenas traduz o erro
canonico; ela nao decide a capability.

No POSIX, qualquer entrada que possa criar staging, publicar controle ou intent,
promover, descartar, abandonar, repetir cleanup, recolher orphan ou executar GC
termina em `RecoveryPlatformUnsupported` / `RECOVERY_PLATFORM_UNSUPPORTED` antes
de abrir um caminho destrutivo ou criar arquivo. Exportacao, verificacao do pacote
e leitura estrutural independente permanecem disponiveis.

Os ataques A16/B16 continuam como regressao executavel, mas o oracle deixa de
pretender equivalencia POSIX e passa a exigir que suas primeiras primitivas
mutaveis sejam inalcancaveis pelo produto:

```text
B16_MKDIRAT_TO_OPENAT = NEVER_REACHED
A16_STATAT_TO_RMDIRAT = NEVER_REACHED
POSIX_EXTERNAL_MUTATION = 0
POSIX_FALSE_SUCCESS = 0
```

`POSIX_SUPPORT_MAY_BE_REOPENED_ONLY_BY_SEPARATE_PRODUCT_REQUIREMENT`. Uma futura
implementacao Linux/POSIX exige Issue propria; nao e continuacao da #183.

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
