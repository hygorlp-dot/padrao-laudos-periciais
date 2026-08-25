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
`LOCAL_IMPORT`. O store preserva bytes, tamanho, SHA-256, instante e filename.

As rotas permitidas são apenas:

- `POST /app-api/v1/workspaces/{workspace}/materials`;
- `GET /app-api/v1/workspaces/{workspace}/materials`;
- `GET /app-api/v1/workspaces/{workspace}/materials/{material}`.

O Bridge aceita mutação somente same-origin e injeta o token no upstream. A
Local API exige esse token inclusive nas leituras privadas. Respostas de
metadados omitem layout e paths; a leitura retorna somente os bytes PDF com
`no-store` e `nosniff`.

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
por identidade. Não há dashboard, classificação documental, interpretação
pericial ou path técnico na interface.

## Limites

Sem OCR, PJe automático, cloud, provider, endpoint genérico de filesystem,
preview sem identidade, telemetria ou egress. O reconhecimento estrutural
mínimo de PDF evita aceitar bytes evidentemente incompatíveis; não afirma
validade semântica, autenticidade ou ausência de conteúdo malicioso.
