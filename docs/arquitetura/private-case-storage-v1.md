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

O root, o arquivo regular `.store-lock` contendo `0`, o `.commit-log` e o
`.commit-anchor`, ambos regulares e inicialmente vazios, são uma precondição de
provisioning do runtime e devem existir antes da abertura do adapter. O adapter
nunca cria esses controles. Ele
os abre sem `O_CREAT`, adquire o singleton e confirma que a identidade do
diretório observada antes,
durante e depois da aquisição é a mesma. Isso impede que uma troca concorrente
do path redirecione a primeira escrita para outro namespace. A etapa de intake
deve fornecer esse provisioning local antes de compor o store.

Esta entrega não conecta a capability ao browser ou à Local API. A etapa de
document intake decidirá separadamente como o runtime recebe o root e o limite
de bytes e como o usuário seleciona um arquivo.

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
  <workspace-uuid>.<content-uuid>.content
  <workspace-uuid>.<content-uuid>.metadata
  <workspace-uuid>.<content-uuid>.metadata-sha256
  <workspace-uuid>.<content-uuid>.commit
```

No Windows, `.store-lock` permanece aberto e exclusivamente travado durante a
vida do adapter; o handle impede que o único diretório ancestral seja removido
ou renomeado. No POSIX, o root permanece aberto e todas as operações abaixo
dele usam `dir_fd` e `O_NOFOLLOW`. Arquivos são abertos somente após comparação
de identidade `lstat/fstat/lstat`, devem ser regulares, não-reparse e ter um
único hard link no estado confirmado. Nenhum metadado do chamador participa de
um nome físico.

## Escrita e duplicidade

Cada importação cria uma identidade nova e imutável. Mesmo filename ou mesmos
bytes resultam em registros distintos dentro do workspace; não há deduplicação
global nem compartilhamento físico entre workspaces. Não existe update/delete
no port V1 e uma colisão de UUID nunca sobrescreve o registro existente.

A instância adquire um singleton de processo por root; writers da mesma
instância são serializados. Antes da primeira mutação, a escrita sincroniza a
intenção no journal. Os nomes staging vinculam workspace, conteúdo e nonce no
mesmo root. Cada arquivo é publicado por hard link `no-replace`, mantendo o
staging como prova de identidade até a confirmação; nunca há rename que possa
sobrescrever:

`journal-intent fsync → exclusive write → fsync → hard-link no-replace
→ verificação integral → commit staging fsync → commit hard-link
→ anchor-confirmation fsync → limpeza dos aliases staging → retorno`

O marcador `.commit` também é escrito e fsynced em staging; somente depois de
todos os componentes finais terem sido verificados ele é publicado por hard
link atômico `no-replace`. A intenção já foi sincronizada antes de qualquer
staging existir. Sua
existência integral junto da confirmação independente é a transição de
visibilidade estável. A coleção em memória só é atualizada depois de o anchor
persistente ter sido sincronizado. Colisão de qualquer nome final falha sem
sobrescrever. Falha anterior ao commit remove somente nomes staging/finais
cuja identidade foi capturada pela operação. A limpeza primeiro move o nome
para uma quarentena aleatória `no-replace`, revalida a identidade e só então o
remove; uma substituição é restaurada e a operação falha fechada.

## Integridade e reopen

O manifesto JSON é canônico, versionado e contém workspace/content IDs,
filename literal, tamanho, SHA-256 dos bytes, media type opcional, instante e
origem controlada. `metadata.sha256` detecta alteração isolada do manifesto.
Toda leitura exige inventário exato do root, manifesto canônico, checksum
do manifesto, identidade, tamanho e SHA-256 do conteúdo. Ausência, truncamento,
campo desconhecido, substituição entre workspaces ou corrupção falha fechado e
nunca é reparada silenciosamente. O manifesto exige tipos exatos e UUIDs em
grafia canônica; `true` não equivale à versão inteira `1`.

Após morte abrupta, o lock do kernel é liberado. A próxima abertura exclusiva
primeiro analisa de forma limitada journal, anchor, staging e todos os registros
sem qualquer mutação. Somente depois de tudo ser válido, reconcilia aliases
staging→final que correspondem à única intenção durável pendente, remove staging
parcial vinculado a essa intenção e descarta seus componentes finais ainda não
visíveis. Um nome staging/final sem WAL correspondente nunca é adotado nem
apagado: bloqueia a abertura e preserva a evidência. O
journal é write-ahead: contém no máximo uma intenção além do anchor. Se a queda
ocorre depois do commit e antes da confirmação, somente esse registro integral,
único e inequivocamente vinculado pode concluir a confirmação. Se ocorre antes
do commit, a intenção e os componentes não visíveis são revertidos. Tail parcial
é aceito apenas nessa única transação pendente. Truncamento limpo do journal,
perda conjunta de journal e registros confirmados, múltiplas intenções,
divergência de ordem, linha grande, byte inválido ou duplicidade falham fechado
sem adoção. Ambos os ledgers têm limite explícito de 10.000 entradas e são lidos
em blocos limitados; o inventário físico também tem teto explícito antes de ser
ordenado em memória. A ausência de qualquer controle nunca é tratada como store
novo. A recuperação é executada antes de o adapter aceitar operações.

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
- Não há UI, endpoint de upload, OCR, preview, PJe/eproc, AI ou egress nesta
  entrega.
