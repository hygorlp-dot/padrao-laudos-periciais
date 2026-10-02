# Dicionário canônico de campos do Word

## Status

**REGRA APROVADA.** Manter `.docm` e preservar os recursos Word úteis. Este
documento não é schema nem especificação de automação.

## Recursos preservados

- bookmarks;
- `REF`;
- `PAGEREF`;
- `TOC`;
- `SEQ`;
- `PAGE`;
- `NUMPAGES`;
- estilos;
- controles de conteúdo.

Os DOCM analisados não contêm `vbaProject.bin`. Não desenvolver VBA nesta
etapa.

## Bookmarks canônicos existentes

| Bookmark | Finalidade | Status |
|---|---|---|
| `PROCESSO` | Número do processo | Existente; preservar |
| `POLOATIVO` | Parte ou polo ativo | Existente; preservar |
| `LOGRADOURO` | Logradouro do imóvel | Existente; preservar |
| `MUNICÍPIO` | Município | Existente; preservar |
| `BAIRRO` | Bairro | Existente; preservar |
| `COMPLEMENTO` | Complemento do endereço | Existente; preservar |
| `DATAVISTORIA` | Data da vistoria | Existente; preservar |
| `HORARIO` | Horário da vistoria | Existente; preservar |
| `LATITUDE` | Latitude | Existente; preservar |
| `LONGITUDE` | Longitude | Existente; preservar |
| `JUIZO` / `VARA` | Órgão julgador | Nomenclatura divergente; validar |
| `CEP` | CEP do imóvel | Ausente em parte dos arquivos; validar |

## Participantes processuais (#268)

O PJe admite várias partes em cada polo, outros participantes e representantes
vinculados a cada parte. A autoridade é a lista de participantes confirmada pelo
perito (`PROCESS_PARTICIPANTS_V1`), não um campo singular.

| Campo do modelo | Conteúdo | Observação |
|---|---|---|
| `[[PARTICIPANTS_ACTIVE]]` | Resumo do polo ativo para a capa | Até três nomes; acima disso, "e outros N (relação completa no item 1)" |
| `[[PARTICIPANTS_PASSIVE]]` | Resumo do polo passivo para a capa | Mesma regra |
| `[[PARTICIPANTS_OTHER]]` | Resumo de outros participantes | Mesma regra |

- A relação completa, com papel e representantes de cada participante, é escrita
  no item de identificação do laudo. Nenhum participante confirmado é omitido.
- Perícia sem lista de participantes gravada: os campos usam o texto antigo de
  "Parte requerente"/"Parte requerida", exato, ou "—". A exportação nunca falha
  por isso.
- O bookmark legado `POLOATIVO` (singular) continua preservado nos modelos antigos,
  mas não é autoridade e o produto não o preenche: um campo singular não
  representa vários participantes sem omitir alguém. Use `[[PARTICIPANTS_ACTIVE]]`.
- Participante descartado ou removido pelo perito não aparece no documento; a
  decisão fica no histórico do registro.

## Campos Word

| Campo | Uso canônico |
|---|---|
| `REF` | Repetir valor de bookmark sem duplicar a fonte |
| `PAGEREF` | Exibir página de destino interno |
| `TOC` | Gerar sumário pela hierarquia de estilos |
| `SEQ` | Numerar tabelas, figuras e fotografias |
| `PAGE` | Exibir página atual |
| `NUMPAGES` | Exibir quantidade total de páginas |
| `TIME` | Usar somente quando a data dinâmica for intencional |
| `FORMTEXT` | Campo legado; não ampliar antes da decisão de automação |
| `BIBLIOGRAPHY` | Usar somente se compatível com a matriz normativa validada |

## Identificadores lógicos futuros

Sem criar schema, reservar as seguintes chaves conceituais:

- `PAT-NNN`: manifestação;
- `FOT-NNN`: fotografia vinculada a uma manifestação;
- `QUE-NNN`: quesito;
- `ORC-NNN`: item de orçamento.

Esses identificadores devem sustentar a cadeia de rastreabilidade definida em
`docs/padroes/padrao-patologia.md`.

## Regras de fonte única

- Não digitar manualmente valor que já possua fonte estruturada.
- Não manter duas fontes concorrentes para processo, parte, endereço, data,
  classificação, valor ou total.
- Atualizar todos os campos antes da emissão e conferir o PDF final.
- Não usar controles de conteúdo sem `alias` ou `tag` como campo semântico
  confiável até futura normalização.

## Pendências de validação do perito

- **PENDÊNCIA DE VALIDAÇÃO DO PERITO:** escolher entre `JUIZO` e `VARA` e
  padronizar acentuação dos nomes internos.
- **PENDÊNCIA DE VALIDAÇÃO DO PERITO:** aprovar o conjunto completo de campos.
- **PENDÊNCIA DE VALIDAÇÃO DO PERITO:** definir bookmarks, controles de
  conteúdo ou outra tecnologia para os blocos repetíveis.
- **PENDÊNCIA DE VALIDAÇÃO DO PERITO:** decidir como atualizar campos no Word
  sem VBA.
