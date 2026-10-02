# CASE_DOCUMENT_INTAKE_V1

## Decisão

O produto importa inicialmente somente PDF pelo fluxo local:

`Frontend → Product Bridge → Local API → Application → Private Case Storage`.

O browser envia os bytes como body `application/pdf` para uma rota exata do
workspace. O nome original segue percent-encoded em um header dedicado e é
decodificado apenas como metadado literal. Ele nunca determina path, nome físico
ou autoridade. A identidade pública é sempre `WorkspaceId + PrivateContentId`.

## Casos de uso e contrato

`ImportCaseDocument`, `ListCaseDocuments` e `ReadCaseDocument` compõem os ports
privados já existentes. A importação exige assinatura inicial `%PDF-`, marcador
final `%%EOF`, limite explícito de 16 MiB no runtime de produto e provenance
`USER_IMPORT`. O store preserva bytes, tamanho, SHA-256, instante e filename.

As rotas permitidas são apenas:

- `POST /app-api/v1/workspaces/{workspace}/materials`;
- `GET /app-api/v1/workspaces/{workspace}/materials`;
- `GET /app-api/v1/workspaces/{workspace}/materials/{material}`;
- `GET /app-api/v1/workspaces/{workspace}/material-processing`;
- `POST /app-api/v1/workspaces/{workspace}/material-processing/{material}` (corpo `{}`).

O Bridge aceita mutação somente same-origin e injeta o token no upstream. A
Local API exige esse token inclusive nas leituras privadas. Respostas de
metadados omitem layout e paths; a leitura retorna somente os bytes PDF com
`no-store` e `nosniff`.

## Ciclo de vida da ingestão (#266)

A importação tem duas fases com autoridades distintas:

1. **Aceite durável** — validação e persistência dos bytes (`content_id`,
   SHA-256, tamanho, filename, origem, instante). É a autoridade física da fonte.
   O mesmo SHA-256 no mesmo workspace resolve sempre para a mesma fonte, inclusive
   com pedidos concorrentes; noutro workspace é outra fonte.
2. **Derivação** — extração/OCR local (somente quando necessário), inventário
   PJe ligado a `storage_content_id` + `source_sha256` e, por último,
   `PROCESS_METADATA_EXTRACTION`, única autoridade de "pronto". Roda num executor
   local de um worker que pertence ao runtime, não à conexão do navegador. As
   escritas finais reconferem a fonte sob a guarda de autoridade do store privado.

`POST /materials` responde `201`/`200` quando a derivação termina dentro de uma
janela menor que o timeout de transporte do Bridge; senão `202` (fonte aceita,
derivação não concluída). Falha real de armazenamento, antes de os bytes
existirem, continua sendo erro. Um timeout de transporte nunca decide o destino
de uma fonte já aceita.

`GET /material-processing` devolve, por documento do caso, um estado fechado:

| Estado | Significado |
|---|---|
| `READY` | metadados da derivação presentes |
| `PROCESSING` | derivação em curso neste runtime |
| `FAILED` | a última tentativa neste runtime falhou; bytes preservados |
| `INTERRUPTED` | bytes presentes sem metadados e nenhum job (ex.: após reinício ou restauração) |

`FAILED` e `INTERRUPTED` aceitam nova tentativa explícita em
`POST /material-processing/{material}`, sobre a mesma fonte, sem reenviar bytes.
Não há retomada automática no boot (um OCR que falhe sempre não pode prender a
inicialização). Enquanto a derivação não termina, a Análise do Caso trata a
fonte como `import_incomplete` e a cobertura não fecha; não existe inventário
lógico PJe sobre o qual exclusão/reabilitação possa agir. O backup leva a fonte e
o estado persistido; a restauração mostra `INTERRUPTED` e oferece a nova
tentativa. Arquivos de apoio à entrega (F8) não são documentos do caso e nunca
entram neste pipeline.

## Provisioning e lifecycle

O comando do runtime exige `--private-root` absoluto. Antes de compor o store,
`provision_private_content_root` cria uma raiz ausente e somente os três
controles protegidos. Uma raiz existente é aceita apenas com controles regulares
válidos; estado parcial não é preenchido ou reparado. O adapter continua sendo
a autoridade fail-closed sobre inventário, recovery e integridade. O runtime
fecha Bridge, Local API, private store e SQLite dentro do mesmo lifecycle.

## UI

A etapa contextual `/materiais` fica imediatamente após `Processo`. A tela
mantém uma ação primária de importação e estados loading, empty, ready e error.
Cada item mostra somente filename, tamanho, formato e data, com abertura local
por identidade. Enquanto a leitura local não termina, o item mostra
"Documento recebido. Processando conteúdo localmente…"; ao terminar, "Processamento
concluído."; em `FAILED`/`INTERRUPTED`, uma mensagem orientada à ação e
**Tentar novamente**. Uma importação sem resposta confirmada nunca é apresentada
como falha de armazenamento: a tela reconsulta a lista, e reimportar o mesmo PDF
não cria duplicata. Não há dashboard, classificação documental, interpretação
pericial ou path técnico na interface.

## Limites

Sem cloud, provider, endpoint genérico de filesystem,
preview sem identidade, telemetria ou egress. O reconhecimento estrutural
mínimo de PDF evita aceitar bytes evidentemente incompatíveis; não afirma
validade semântica, autenticidade ou ausência de conteúdo malicioso.
