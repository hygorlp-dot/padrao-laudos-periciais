# PRIVATE_CASE_STORAGE_V1

## Decisão

Conteúdo binário privado associado a uma `PericiaWorkspace` usa uma boundary
Application própria (`PrivateContentRepository`) e um adapter de filesystem
local. Ele não usa `ArtifactRevisionRepository`, JSON genérico de artefato,
SQLite BLOB, browser storage, URL, log, telemetria ou serviço externo.

SQLite continua sendo a autoridade de existência do workspace. Os serviços
Application verificam essa existência antes de delegar qualquer escrita ou
leitura ao repositório privado.

## Configuração operacional

`LocalPrivateContentStore` exige um root absoluto fornecido pela composição de
runtime. A configuração de produção deve apontar para um diretório de dados do
usuário fora do checkout Git. Não existe fallback para um path específico de
máquina, para `referencias/privadas/` ou para o diretório atual. Testes usam
somente diretórios temporários e bytes sintéticos.

Em todo sistema operacional suportado, o root também deve pertencer ao mesmo
device/volume local confiável que contém o executável Python do runtime. A comparação por identidade é
feita antes da abertura dos controles; UNC, drive mapeado e volume divergente
falham fechados. Esta restrição deliberada evita que uma configuração com
aparência local envie bytes privados a um compartilhamento remoto. Suporte a
outro volume local exigiria uma autoridade de provisioning explícita posterior.
Todos os componentes ancestrais do path configurado também são inspecionados;
symlink, junction ou reparse em qualquer nível bloqueia a abertura.

O root, o arquivo regular `.store-lock` contendo `0`, o `.commit-log` e o
`.commit-anchor`, ambos regulares e inicialmente vazios, são uma precondição de
provisioning do runtime e devem existir antes da abertura do adapter. O adapter
nunca cria esses controles. Ele
os abre sem `O_CREAT`, adquire o singleton e confirma que a identidade do
diretório observada antes,
durante e depois da aquisição é a mesma. Isso impede que uma troca concorrente
do path redirecione a primeira escrita para outro namespace. A etapa de intake
fornece esse provisioning local explícito antes de compor o store; estado
parcial nunca é completado silenciosamente.

O `CASE_DOCUMENT_INTAKE_V1` posterior conecta essa capability somente por rotas
workspace-bound exatas e documenta separadamente como o runtime recebe o root,
o limite de bytes e a seleção do arquivo.

## Identidade, namespace ancorado e layout físico

A identidade pública é o par canônico:

`WorkspaceId + PrivateContentId`

Ambos são UUIDs técnicos. O filename original é metadado literal e nunca
participa do path. O layout interno V1 é deliberadamente plano. Isso elimina
diretórios internos que poderiam ser trocados entre validação e uso em Windows,
onde Python não oferece `dir_fd`/`O_NOFOLLOW`:

```text
<private-root>/
  .store-lock
  .commit-log
  .commit-anchor
  .intent.<workspace-uuid>.<content-uuid>.<nonce>
  .aborted.<nonce>                         # somente transação abortada
  .staging.<workspace-uuid>.<content-uuid>.<nonce>.<member>
  .retired.<nonce>                         # somente inode abortado
  <workspace-uuid>.<content-uuid>.content
  <workspace-uuid>.<content-uuid>.metadata
  <workspace-uuid>.<content-uuid>.metadata-sha256
  <workspace-uuid>.<content-uuid>.commit
```

No Windows, `.store-lock` permanece aberto e exclusivamente travado durante a
vida do adapter; o handle impede que o único diretório ancestral seja removido
ou renomeado. No POSIX, o root permanece aberto e todas as operações abaixo
dele usam `dir_fd` e `O_NOFOLLOW`. Arquivos são abertos somente após comparação
de identidade `lstat/fstat/lstat` e devem ser regulares e não-reparse. Controles
e intents confirmados têm um link; cada membro confirmado tem exatamente os
dois aliases staging/final. Objetos abortados reconciliam `st_nlink` com todos
os seus aliases observados dentro do root e rejeitam qualquer hardlink externo.
Nenhum metadado do chamador participa de um nome físico.

## Escrita e duplicidade

Cada importação cria uma identidade nova e imutável. Mesmo filename ou mesmos
bytes resultam em registros distintos dentro do workspace; não há deduplicação
global nem compartilhamento físico entre workspaces. Não existe update/delete
no port V1 e uma colisão de UUID nunca sobrescreve o registro existente.

A instância adquire um singleton de processo por root; writers da mesma
instância são serializados. Antes da primeira mutação de dados, a escrita cria
e sincroniza um intent físico vazio com workspace, conteúdo e nonce; depois
sincroniza a intenção no journal. Os nomes staging vinculam os mesmos valores no
mesmo root. Cada arquivo é publicado por hard link `no-replace`, mantendo o
staging como prova de identidade até a confirmação; nunca há rename que possa
sobrescrever:

`physical-intent fsync → journal-intent fsync → exclusive write → fsync → hard-link no-replace
→ fsync da identidade publicada → verificação integral → commit staging fsync
→ commit hard-link → fsync da identidade publicada
→ anchor-confirmation fsync → aliases staging preservados → retorno`

O marcador `.commit` também é escrito e fsynced em staging; somente depois de
todos os componentes finais terem sido verificados ele é publicado por hard
link atômico `no-replace`. A intenção já foi sincronizada antes de qualquer
staging existir. Os aliases staging confirmados permanecem como prova física
da identidade publicada: os quatro pares staging/final são obrigatórios,
apontam ao mesmo inode regular e possuem exatamente dois links. Sua
existência integral junto da confirmação independente é a transição de
visibilidade estável. A coleção em memória só é atualizada depois de o anchor
persistente ter sido sincronizado. Colisão de qualquer nome final falha sem
sobrescrever. Falha anterior ao commit não apaga nomes após uma verificação
separada. Em vez disso, cria um hardlink aleatório `.retired.*` com semântica
`no-replace` e confirma que ele aponta ao inode capturado. Qualquer inode assim
marcado fica permanentemente inerte para catálogo/leitura. Os nomes e bytes
permanecem preservados como evidência. Um hardlink `.aborted.*` no intent fixa
o estado abortado; marcadores `.retired.*` só são aceitos quando ligados a um
membro canônico dessa mesma transação. O WAL é append-only: depois que todos os
membros estão aposentados e o intent abortado está durável, sua entrada permanece
como evidência física e é excluída apenas da visão lógica de transações ativas.

## Integridade e reopen

O manifesto JSON é canônico, versionado e contém workspace/content IDs,
filename literal, tamanho, SHA-256 dos bytes, media type opcional, instante e
origem controlada. `metadata.sha256` detecta alteração isolada do manifesto.
Toda leitura exige inventário exato do root, manifesto canônico, checksum
do manifesto, identidade, tamanho e SHA-256 do conteúdo. Ausência, truncamento,
campo desconhecido, substituição entre workspaces ou corrupção falha fechado e
nunca é reparada silenciosamente. O manifesto exige tipos exatos e UUIDs em
grafia canônica; `true` não equivale à versão inteira `1`. A contagem exata de
hardlinks é revalidada depois do último byte lido, fechando a janela entre a
validação inicial e a conclusão da leitura.

Após morte abrupta, o lock do kernel é liberado. A próxima abertura exclusiva
primeiro analisa de forma limitada journal, anchor, staging e todos os registros
sem qualquer mutação. Somente depois de tudo ser válido, reconcilia aliases
staging→final que correspondem à única intenção durável pendente e aposenta
componentes ainda não visíveis por marcadores hardlink, sem `unlink`. Um crash
ou erro durante esse rollback mantém a intenção e permite repetição idempotente.
Uma intenção truncada é vinculada ao único intent físico ainda não confirmado
nem abortado, completada e fsyncada antes da primeira aposentadoria. Isso cobre
inclusive a queda no primeiro append, antes de qualquer staging existir. Antes
de selar o abort, a recuperação reabre todo o prefixo e exige que cada nome
existente esteja ligado a um marcador aposentado válido; depois reexecuta a
recuperação sobre o estado persistido. Um nome staging/final sem intent e estado
durável correspondente nunca é adotado nem
apagado: bloqueia a abertura e preserva a evidência. O
visão ativa do journal é write-ahead: contém no máximo uma intenção além do
anchor. Se a queda
ocorre depois do commit e antes da confirmação, somente esse registro integral,
único e inequivocamente vinculado pode concluir a confirmação. Se ocorre antes
do commit, a intenção e os componentes não visíveis são revertidos. Tail parcial
é aceito apenas nessa única transação pendente; grupos já confirmados nunca
competem pela atribuição do fragmento. Um grupo físico completo sem entrada WAL
é ambíguo/corrompido e bloqueia antes de qualquer mutação do anchor. Truncamento limpo do journal,
perda conjunta de journal e registros confirmados, múltiplas intenções,
divergência de ordem, linha grande, byte inválido ou duplicidade falham fechado
sem adoção. Ambos os ledgers têm limite explícito de 10.000 entradas e são lidos
em blocos limitados; o inventário físico também tem teto explícito antes de ser
ordenado em memória. Cada nova escrita reserva, antes do primeiro intent, as 18
entradas do pior rollback persistente (intent, aborted, oito aliases e oito
marcadores retired); assim uma falha não ultrapassa o próprio teto físico. A
ausência de qualquer controle nunca é tratada como store
novo. A recuperação é executada antes de o adapter aceitar operações.
Journal e anchor são abertos com append atômico do sistema operacional e nunca
são truncados pelo adapter. Um append parcial pertencente à transação é somente
completado e fsyncado; bytes concorrentes ou sem proveniência permanecem
preservados e bloqueiam a abertura. Marcadores `.retired` e `.aborted` recebem a
mesma barreira de identidade/fsync usada pelos aliases publicados antes de o
abort ser considerado estável.

SHA-256 aqui é evidência de integridade acidental e consistência local, não uma
assinatura nem prova de autenticidade contra um atacante com capacidade para
reescrever simultaneamente bytes, manifesto e hashes. Criptografia, key
management, ACL do sistema operacional, backup/restore e autenticação de
manifesto pertencem a milestones próprios.

## Privacidade e limites

- O adapter usa somente stdlib local e não importa cliente de rede.
- Conteúdo não é incluído em mensagens de erro ou logs.
- Falhas de I/O do sistema operacional nas operações públicas são traduzidas
  para `RepositoryError` controlado; paths e mensagens privadas do host ficam
  somente na causa técnica, não na mensagem do port.
- `StorePrivateContent` mantém seu limite explícito e o adapter reaplica um
  teto defensivo configurável (`max_content_bytes`, default documentado de
  64 MiB) em escrita e leitura. Manifestos têm teto independente de 64 KiB e
  falhas de profundidade do parser são convertidas em erro de integridade
  controlado.
- `list_all` valida conteúdo por chunks de 64 KiB sem materializá-lo; `get`
  acumula no máximo o teto configurado porque o port V1 retorna `bytes`.
- A única origem V1 é `LOCAL_IMPORT`; filename não é proveniência e nenhuma
  classificação documental/pericial é inferida.
- O fechamento invalida cada handle na instância antes da chamada de sistema.
  Uma falha ambígua de `close` torna a instância fechada/falha e nunca permite
  repetir um número de descritor que já possa ter sido reutilizado pelo processo.
  O handle do singleton é fechado mesmo se o unlock explícito falhar. A instância
  registra o PID proprietário; após `fork`, o filho não pode operar o store nem
  emitir `LOCK_UN` sobre o lock herdado.
- Não há UI, endpoint de upload, OCR, preview, PJe/eproc, AI ou egress nesta
  entrega.
