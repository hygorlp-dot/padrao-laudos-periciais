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

Esta entrega não conecta a capability ao browser ou à Local API. A etapa de
document intake decidirá separadamente como o runtime recebe o root e o limite
de bytes e como o usuário seleciona um arquivo.

## Identidade e layout físico

A identidade pública é o par canônico:

`WorkspaceId + PrivateContentId`

Ambos são UUIDs técnicos. O filename original é metadado literal e nunca
participa do path. O layout interno V1 é:

```text
<private-root>/
  workspaces/<workspace-uuid>/contents/<content-uuid>/
    content.bin
    metadata.json
    metadata.sha256
```

O modelo Application não expõe esse layout ou qualquer path. Identidades
malformadas/não canônicas falham antes da resolução física. Cada leitura
revalida contenção e rejeita symlink/reparse points nos componentes sob o root.

## Escrita e duplicidade

Cada importação cria uma identidade nova e imutável. Mesmo filename ou mesmos
bytes resultam em registros distintos dentro do workspace; não há deduplicação
global nem compartilhamento físico entre workspaces. Não existe update/delete
no port V1 e uma colisão de UUID nunca sobrescreve o registro existente.

A escrita adquire um lease exclusivo por `workspace + content`, usa staging
fora da coleção enumerável e finaliza no mesmo filesystem:

`exclusive write → flush/fsync → verificação integral → os.replace → retorno`

O lease impede que writers cooperantes atravessem juntos o precheck e
sobrescrevam a mesma identidade. Metadados somente são retornados após a
finalização atômica. Falha controlada
remove apenas os três arquivos e o diretório temporário criados pela operação;
nenhum record final parcial é listado como sucesso.

## Integridade e reopen

O manifesto JSON é canônico, versionado e contém workspace/content IDs,
filename literal, tamanho, SHA-256 dos bytes, media type opcional, instante e
origem controlada. `metadata.sha256` detecta alteração isolada do manifesto.
Toda leitura exige inventário exato de arquivos, manifesto canônico, checksum
do manifesto, identidade, tamanho e SHA-256 do conteúdo. Ausência, truncamento,
campo desconhecido, substituição entre workspaces ou corrupção falha fechado e
nunca é reparada silenciosamente.

SHA-256 aqui é evidência de integridade acidental e consistência local, não uma
assinatura nem prova de autenticidade contra um atacante com capacidade para
reescrever simultaneamente bytes, manifesto e hashes. Criptografia, key
management, ACL do sistema operacional, backup/restore e autenticação de
manifesto pertencem a milestones próprios.

## Privacidade e limites

- O adapter usa somente stdlib local e não importa cliente de rede.
- Conteúdo não é incluído em mensagens de erro ou logs.
- O limite de bytes em memória é configuração obrigatória de
  `StorePrivateContent`; não há limite oculto ou porcentagem fabricada.
- A única origem V1 é `LOCAL_IMPORT`; filename não é proveniência e nenhuma
  classificação documental/pericial é inferida.
- Não há UI, endpoint de upload, OCR, preview, PJe/eproc, AI ou egress nesta
  entrega.
