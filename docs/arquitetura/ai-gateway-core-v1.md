# AI Gateway Core V1

## Estado e escopo

`AI_GATEWAY_CORE_V1` é o slice S10-A da Issue #3. Ele adiciona o boundary
mínimo para produzir sugestões estruturadas e auditadas. Não expõe endpoint,
UI ou comando canônico novo; portanto a instalação continua plenamente útil
sem chave, rede ou disponibilidade do provider.

Os slices posteriores permanecem separados:

- S10-B: construção seletiva de contexto, retrieval, router e cache;
- S10-C: propostas específicas de Case Analysis, Planning, Evidence,
  Technical Finding e Report, com revisão humana;
- S10-D: corpus sintético de eval, métricas, observabilidade e
  productização.

## Dependências e autoridade

```text
DOMAIN AI CONTRACTS
        ↓
APPLICATION AIProvider PORT + RunAIProposal
        ↓
INFRASTRUCTURE OpenAIProvider
        ↓
openai-python 3.6.0 / Responses API
```

Somente `scripts/backend_contract/infrastructure/openai_provider.py` importa
o SDK. O adapter não é importado pela composição normal do produto. Nenhum
modelo recebe ferramentas de mutação e nenhum objeto de IA possui campo de
aprovação, decisão profissional ou estado efetivo.

`AI_PROPOSAL != EFFECTIVE_VALUE` e `AI_RESPONSE != PROFESSIONAL_DECISION`.
Uma integração futura somente poderá transformar uma proposta por meio dos
comandos canônicos humanos/profissionais já existentes.

## Egress e contexto

O default é `REMOTE_AI_EGRESS = DENY`. As classes são:

- `LOCAL_ONLY`;
- `REMOTE_SANITIZED`, habilitada explicitamente na composição futura;
- `REMOTE_CASE_CONTENT_EXPLICITLY_AUTHORIZED`, que exige habilitação separada
  e `explicitly_authorized=true` no manifesto exato.

Antes do provider: workspace, sequência de source refs e manifesto são
comparados exatamente. Cada segmento registra `workspace_id`, documento,
revisão, SHA-256 da fonte, locator e SHA-256 do conteúdo enviado. Alterar
schema, instruções ou contexto sem recalcular o hash falha fechado.

Texto documental é serializado como bloco `user/input_text`. Ele nunca é
concatenado às instruções do sistema. Frases como “ignore previous
instructions” ou “approve this finding” permanecem dados inertes.

## OpenAI Responses e retenção

O adapter usa Responses API, `text.format.type=json_schema`, `strict=true`,
`store=false`, `max_output_tokens`, timeout limitado e nenhuma ferramenta.
A saída JSON estrita é desserializada uma vez, sem regex, reparo ou retry, e
depois validada novamente pela Application com JSON Schema antes de qualquer
persistência de proposta. A referência oficial descreve Structured Outputs
por `json_schema` e recomenda essa forma em vez do JSON mode legado:
<https://developers.openai.com/api/reference/cli/resources/beta/subresources/responses>.

`store=false` significa que a resposta não é solicitada para recuperação
posterior pela API; não é alegação de zero retention. A semântica oficial do
campo está em:
<https://developers.openai.com/api/reference/cli/resources/responses/methods/create>.

## Segredo local

`OPENAI_API_KEY` é lida diretamente do ambiente somente quando
`EnvironmentOpenAIClientFactory.create()` é chamado explicitamente. A chave:

- não entra em Git, SQLite, ArtifactRevision, AIRun, proposta, log ou erro;
- não é necessária para iniciar/reabrir o produto sem IA;
- não é lida por domínio ou Application;
- ausente, falha como `INVALID_CREDENTIALS` sem repetir o nome ou valor.

Não existe secret store remoto nem novo trust plane neste slice.

## Auditoria append-only

Cada tentativa permitida recebe `run_id` server-owned. Sucesso grava
atomicamente `AI_RUN` e `AI_PROPOSAL`; schema inválido, recusa, timeout,
credencial inválida, rate limit, network, ceiling ou indisponibilidade grava
somente AIRun sanitizado. Reuso do mesmo `run_id` falha por conflito
append-only.

AIRun registra provider/model, parâmetros permitidos, hashes de prompt/schema/
contexto, fontes, egress/redação, tokens, custo quando calculável, latência,
response ID/hash, refusal/error e IDs de propostas. Response ID do provider é
metadado, nunca autoridade.

## Limites conhecidos do slice

O SDK expõe token usage, inclusive cached input quando disponível. Estimativa
de custo só é persistida e comparada quando fornecida por uma tabela de preço
versionada; essa tabela e as métricas longitudinais pertencem ao S10-D. O
router, orçamento determinístico de contexto e cache pertencem ao S10-B.
Nenhum desses limites permite egress ou promoção de autoridade por default.
