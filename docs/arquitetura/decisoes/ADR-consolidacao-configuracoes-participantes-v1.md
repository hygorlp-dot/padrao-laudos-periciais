# ADR — Consolidação de autoridades: participantes, imóvel, configurações globais, identidade visual e perfil jurídico-editorial (V1)

## Status

Aceito para implementação. Escopo autorizado pelo titular no ciclo pós-Round 2 do
HUMAN_RC_WINDOWS_V2 (#238), sobre `main` `3d3528e`. Issues: #268 (P1), #269, #270,
#271 (identidade visual no Word), #272 (perfil jurídico-editorial e preflight) e #273
(refinamento visual com Impeccable).

## Contexto

O Round 2 parou no bloco D: o modelo processual guarda uma única
`parte_requerente` e uma única `parte_requerida` (#268), e a busca de dados do
imóvel só reconhece linhas `RÓTULO: valor` (#269). O titular também tornou
obrigatórias, antes do Round 3, uma Central de Configurações global (#270), a
identidade visual no Word e um perfil jurídico-editorial com preflight.

Regra dominante: **não criar sistemas paralelos**. Toda nova capacidade evolui uma
autoridade que já existe.

## Mapa de autoridades reutilizadas

| Necessidade | Autoridade existente | Decisão |
|---|---|---|
| Perfil profissional | `ExpertMasterProfile` (`report_foundation.py`), artefato `EXPERT_MASTER_PROFILE_V1` por perícia, `ExpertProfileSetup.tsx`, `expertIdentity.ts` | Evoluir o mesmo contrato de forma compatível. Sem segundo perfil. |
| Padrão editorial | `EditorialProfile` + `EditorialTypography`; `EditorialPanel` em `ReportFoundationView.tsx` | Evoluir com um value object opcional de layout; o mesmo painel serve à Central e ao Laudo. |
| Modelo Word | `report_default_template.py` (`PRODUCT-DEFAULT-REPORT-V1`), `report_template.py` (`TemplateBindingManifest`), `delivery_renderer.py`, `application/delivery_foundation.py` | Evoluir o template padrão e o renderer existentes. Sem segundo motor. |
| Upload de modelo | `POST …/delivery-templates` + validadores DOCX/DOCM | A Central seleciona e guarda o modelo com os mesmos validadores. |
| Participantes | `judicial_domain.py` (`ProcessPole`, `NormalizedProceduralRole`, `EntityKind`, `RepresentationLink`), `pje_party_table.py` | Reusar enums e a gramática da tabela PJe. Sem novo vocabulário de papéis. |
| Dados do imóvel | `property_record.py` (`PropertyRecord`, `PropertyEvidence`, `property_proposals`) | Evoluir o extrator em camadas; o nível 1 continua byte-idêntico. |
| Texto/OCR | `RevisionOcrPageCache` (`OCR_PAGE_CACHE_V1`), extração `PROCESS_METADATA_EXTRACTION`, inventário `PJE_INTAKE_V1` | Reusar o cache por `workspace + sha256`; o cache nunca é autoridade. |
| Papel de conteúdo (F8) | `PRIVATE_CONTENT_ROLE_V1` (`DELIVERY_SUPPORT`) | Novo papel `BRANDING_ASSET` para cópias de ativos dentro da perícia. |

Não existe hoje nenhuma autoridade de configuração de instalação nem armazenamento
de ativos de marca: o único armazenamento é por perícia (`artifact_revisions` e o
conteúdo privado do workspace).

## Decisões

### D1. Participantes processuais (#268)

- Novo artefato por perícia `PROCESS_PARTICIPANTS_V1` (id `PROCESS-PARTICIPANTS`),
  append-only, portável no backup.
- Cada participante tem `participant_id`, `name`, `pole` (`ACTIVE`, `PASSIVE`,
  `OTHER`), `procedural_role` (`NormalizedProceduralRole`), `source_role_label`
  (rótulo literal da fonte), `person_type` (`EntityKind`),
  `representatives[]` (vinculados ao participante), `provenance[]`, `origin`
  (`SOURCE`, `MANUAL`, `LEGACY_PROCESS_CASE`) e `review_state` (`PROPOSED`,
  `CONFIRMED`, `REJECTED`).
- Identidade: para fonte, derivada de workspace, conteúdo, página, span, polo e papel
  (nunca do nome); para entrada manual, UUID.
- Proveniência mínima: conteúdo, documento lógico PJe quando houver, página,
  span, modo de extração (`NATIVE_TEXT`/`OCR`) e SHA-256 da fonte.
- Autoridade: `SOURCE → PROPOSAL → CONFIRMAÇÃO PROFISSIONAL`. Proposta nunca se
  autoconfirma. Rejeição é registrada para que a proposta não reapareça.
- Peça excluída: deixa de gerar proposta; um participante já confirmado continua
  no histórico e aparece com a fonte marcada como excluída.
- Migração legada: sem registro de participantes, `parte_requerente` e
  `parte_requerida` não vazias são projetadas na leitura como um participante
  `ACTIVE` e um `PASSIVE` de origem `LEGACY_PROCESS_CASE`, com o texto exato, sem
  dividir strings concatenadas. A primeira gravação materializa a projeção.
  O texto legado nunca é cortado: o participante legado aceita até 4.000
  caracteres (o de fonte ou manual, 300). Valor maior que isso, ou com caractere
  que o Word não representa, não é projetado; a tela diz qual polo ficou de fora e
  pede o registro das partes uma a uma.
- Decisão sobre participantes exige os dados do processo já gravados
  (`PROCESS_RECORD_REQUIRED`, 409). Assim todo participante confirmado tem uma
  captura de processo que o leva ao laudo; registro sem processo no backup ou no
  banco faz a captura do laudo falhar fechada.
- Leitura da fonte: linha da tabela que não cabe num participante é ignorada e a
  página entra em "leitura interrompida", sem derrubar as demais propostas.
  Procurador em linha de continuação só se liga à parte da mesma seção. Tabela que
  continua na página seguinte sem cabeçalho também é sinalizada.
- Mesmo nome no mesmo polo (normalizado sem acento e pontuação) é sinalizado como
  possível repetição, nunca fundido.
- Restaurar um participante de fonte exige que a peça continue a mesma e não
  excluída, como confirmar.
- Qualquer decisão sobre participantes (inclusive descartar uma proposta) muda a
  revisão capturada e deixa o laudo aprovado `stale`. Decisão consciente: a captura
  fixa a revisão do registro inteiro para auditoria, e comparar só os confirmados
  abriria uma segunda regra de vínculo.
- O backup rederiva cada participante de fonte: relê a página dos bytes, reencontra
  a linha pelo span e exige o mesmo trecho e o mesmo nome (salvo nome corrigido pelo
  perito), e o mesmo procurador no span declarado.
- `ProcessCaseData` mantém os campos escalares para ler dados antigos. Eles deixam
  de ser a autoridade de partes e a UI para de editá-los.
- O laudo captura a coleção junto do processo (`ReportProcess.participants`, omitido
  quando ausente, para preservar mapping e digest de laudos antigos). A captura só
  passa a existir depois que o perito grava o registro, para que uma atualização
  do produto não torne laudos antigos `stale` sozinha.
- Word: a seção 1.1 relaciona todos os participantes confirmados, por polo. Os
  campos `[[PARTICIPANTS_ACTIVE]]`, `[[PARTICIPANTS_PASSIVE]]` e
  `[[PARTICIPANTS_OTHER]]` resumem cada polo para a capa (até três nomes e "e
  outros N"). Sem registro gravado, usam o texto legado exato, ou "—"; nunca
  falham a exportação de uma perícia antiga. O bookmark singular `POLOATIVO` de
  modelos antigos é preservado, mas o produto não o preenche: não há vínculo que
  represente vários participantes num campo singular sem omitir alguém.

### D2. Dados do imóvel em camadas (#269)

- Nível 1 (`LABEL_NATIVE_TEXT_V1`/`LABEL_OCR_V1`) fica byte-idêntico, porque o
  fecho do backup reextrai a evidência para conferi-la.
- Nível 2 (`DOCUMENT_PATTERN_*_V2`): padrões por tipo de peça (contrato, matrícula,
  termo de entrega, laudo técnico, petição).
- Nível 3 (`CONTEXT_BOUND_*_V2`): proposta só quando o contexto vincula o dado ao
  imóvel objeto (imóvel objeto da ação, unidade habitacional, imóvel financiado,
  objeto do contrato, apartamento vistoriado, empreendimento).
- `PARTY_ADDRESS != SUBJECT_PROPERTY_ADDRESS`: qualificação de parte
  ("residente e domiciliado"), endereço de advogado, de juízo ou de citação
  jurisprudencial bloqueiam a proposta. Os bloqueadores são avaliados na frase
  inteira, com limite de palavra; abreviações ("Av.", "Dr.", "Rel.", "Des.", "nº")
  não terminam a frase. Contatos de timbre (telefone, e-mail) também bloqueiam.
- Desde a #293, o vínculo de um endereço é decidido pela **oração**. O
  logradouro, e o número, bairro e CEP que o seguem na mesma cadeia, pertence ao
  marcador mais próximo antes dele. Há dois regimes, para nunca propor mais
  endereço de parte do que antes:
  - **Frase que a regra anterior aceitava.** Só sai o endereço introduzido por
    um verbo de residência, sede, trabalho ou deslocamento ("moradora da", "mora
    na", "estabelecida", "com domicílio", "cuja sede", "com matriz", "filial",
    "trabalha na", "mudou-se para/à", "transferida para"). Também sai o
    endereço introduzido por um particípio de parte ("a vendedora, localizada
    na"; "foi vendida a FULANA, situada na"). Comarca, testemunha, assistente
    e mudança, citados na narrativa, não apagam o endereço do imóvel; "foi
    para" também não. Sem marcador antes, decide o primeiro marcador depois da
    cadeia.
  - **Frase que a regra anterior bloqueava inteira** (CPF, telefone, advogado,
    juízo…). Só entra o endereço ligado diretamente a uma pista do imóvel
    objeto ("imóvel objeto da ação, situado na", "fica na"). Se o vínculo vem
    por particípio, ele precisa estar ancorado nessa pista. E não pode haver
    bloqueador depois do endereço.
  - "situado/localizado" segue o substantivo de imóvel que concorda com ele
    (alcance de 160 caracteres). O vínculo cai, fail-closed, quando aparece
    entre os dois:
    - uma parte que concorda e não é só agente de um particípio atributivo
      ("adquirida pela autora" e qualquer relativa aberta depois do imóvel, como
      "que/o qual (em 2015) foi adquirido pela autora", mantêm o
      vínculo; "foi entregue pela construtora" o tira). Onde a regra anterior
      bloqueava a frase, nenhuma isenção vale: uma parte que concorde tira a
      âncora;
    - CPF, CNPJ, OAB ou telefone;
    - um imóvel vizinho ou outro ("ao lado do", "nova unidade"), decidido uma
      vez para todo o sintagma da pista ("próximo ao imóvel objeto da ação").

    A pista "objeto" devolve o vínculo a uma unidade "nova".
  - "imóvel objeto, onde reside, …" fala do próprio imóvel só com a relativa
    colada à pista do imóvel, sem negação e sem deslocamento depois do verbo,
    e com no máximo um parentético de lista fechada ("financiada em 2015").
    "Mora no imóvel" também não apresenta endereço de parte.
  - Dois logradouros diferentes presos à mesma pista ficam "possíveis".
  - Precedente continua bloqueando a frase inteira.
  - Município/UF seguem a frase inteira (fail-closed).
  - A hifenização do PDF ("mora-\ndora", "resi- dente") não esconde o
    marcador.
  - Resíduos conhecidos:
    - frase sem nenhum marcador de parte;
    - relativa colada à pista com deslocamento implícito ("onde reside hoje
      em Recife");
    - erro de gênero do OCR no particípio, que perde o endereço (fail-closed);
    - agente atributivo seguido de particípio que concorda com os dois ("a
      unidade, vendida pela construtora, localizada na…"): o caso é lido como
      a unidade, igual à regra anterior.
  - `BACKUP_REPLAY_LEGACY = ALLOWED` e `NEW_PROPOSAL_FROM_PARTY_ADDRESS =
    PROHIBITED`: a reprodução do backup (`include_legacy_labels=True`) aceita
    a união da regra nova com a anterior. Toda proposta nova é reproduzível, e
    a evidência confirmada antes da #293 continua conferível.
- No nível 1, só rótulo de endereço genérico ("Logradouro:", "CEP:") depois de
  qualificação de parte ou timbre institucional deixa de ser proposto. Rótulo que
  nomeia o imóvel ("Logradouro do imóvel:") e rótulos que não são endereço
  (proprietário com CPF, construtora com CNPJ) continuam propostos.
- O tipo de peça pertinente vale só dentro da peça lógica do export PJe.
  "Residencial" só nomeia empreendimento seguido de nome próprio. Mais de uma
  unidade na mesma frase rebaixa a proposta para "possível".
- Cada achado olha uma vizinhança fixa (400 caracteres antes, 240 depois): o custo
  cresce com o texto, nunca com o quadrado dele.
- Conflitos aparecem lado a lado. Nada é escolhido em silêncio.
- A busca usa o cache OCR da perícia e respeita o ciclo `PROCESSING/READY` da #266.

### D3. Configurações de instalação (#270)

- Arquivo SQLite próprio da instalação, ao lado do banco das perícias
  (`.<banco>.installation.sqlite3`, schema 1), com a tabela append-only
  `installation_setting_revisions` (`setting_kind`, `setting_id`, `revision`,
  `revision_id`, `created_at`, `checksum_sha256`, `payload_json`) e a tabela
  `installation_assets` endereçada por SHA-256. Um arquivo separado não toca o
  schema do banco das perícias (nenhuma migração nele) e deixa claro que nada da
  instalação viaja no backup de uma perícia. Schema desconhecido, checksum ou
  sequência inválidos falham fechados na abertura. Não existe
  `workspace_id = GLOBAL`.
- Tipos: `EXPERT_PROFILE_DEFAULT_V1`, `EDITORIAL_PROFILE_DEFAULT_V1`,
  `BRANDING_PROFILE_V1`, `DOCUMENT_PRESENTATION_PROFILE_V1`,
  `LEGAL_EDITORIAL_PROFILE_V1`, `DEFAULT_TEMPLATE_SELECTION_V1` e
  `INSTALLATION_ASSET_V1` (um `setting_id` por papel do ativo).
- Restaurar uma revisão anterior grava uma nova revisão com o mesmo conteúdo.
- Ativos de instalação (PNG/JPEG; SVG fora até prova em Word 16) ficam na tabela
  `installation_assets` do arquivo da instalação, endereçados por SHA-256, locais e
  privados. Nunca entram em Materiais, Análise ou fontes do caso.
- Nova perícia: os padrões vigentes viram `WORKSPACE_SETTINGS_SNAPSHOT_V1`, com as
  revisões de origem. Os bytes dos ativos são copiados para o conteúdo privado da
  perícia com o papel `BRANDING_ASSET`. Assim o backup da perícia carrega o snapshot
  efetivo e a perícia reabre em máquina limpa sem a configuração global.
- O perfil global semeia a revisão 1 do `EXPERT_MASTER_PROFILE_V1` da perícia.
  "Atualizar a partir do perfil padrão" mostra as diferenças, pede confirmação e grava
  nova revisão. A identidade profissional só muda por esse comando explícito, e o laudo
  que fixou a revisão anterior fica `stale`.
- O backup da perícia não leva as configurações globais. Elas não são exportadas
  junto do workspace.
- Arquivo da instalação ilegível (schema, checksum ou sequência) falha fechado só para
  as configurações: a Central e o documento de teste respondem 503
  `SETTINGS_UNAVAILABLE`, e criar perícia é recusado **antes** de criar (nenhuma
  perícia pela metade). As perícias existentes abrem e entregam com o snapshot que
  cada uma capturou, porque nada do caso depende do arquivo da instalação.

### D4. Evolução compatível dos contratos

- `ExpertMasterProfile` ganha campos opcionais (`signature_name`,
  `professional_council`, `council_state`, `national_registration`,
  `court_registrations[]`, `professional_contact`, `presentation`), omitidos quando
  ausentes. Os campos legados continuam obrigatórios como linhas de exibição. O
  `court_registration` legado vira uma entrada de origem `LEGACY` sem perder o texto.
  CPF, RG e endereço residencial não são coletados.
- `EditorialProfile` ganha o value object opcional `layout`: distâncias de cabeçalho e
  rodapé, espaço antes do parágrafo, controle de viúvas/órfãs, manter com o próximo,
  caixa por nível de título, quebra antes do título 1 e citação longa. Ausente, o
  comportamento é exatamente o legado.

### D5. Geometria: divergência registrada, não escolhida em silêncio

- `padrao-visual-word.md` registra medidas **observadas** no laudo legado (margens
  ≈ 2,54/3/2,54/2,54 cm, cabeçalho ≈ 1,25 cm, rodapé ≈ 0,87 cm) com
  **PENDÊNCIA DE VALIDAÇÃO DO PERITO** sobre as medidas definitivas.
- A #131 registra **decisão humana posterior** para o preset
  (`margin_top 2 / left 3 / right 2 / bottom 2`).
- Decisão: o preset `JUSTICA_PLURAL_CHAPTER_4` mantém os valores da #131 (sua
  identidade nomeia exatamente esses valores). A Central oferece "Aplicar geometria
  do modelo legado aprovado", que preenche um perfil `CUSTOM` com as medidas
  observadas (2,54/3/2,54/2,54). As distâncias de cabeçalho/rodapé novas seguem o
  documento visual (1,25/0,87). Perfil sem `layout` mantém 1,25/1,25, como antes.
- Implementado: o botão chama-se "Aplicar geometria do laudo legado aprovado" e grava
  o perfil `CUSTOM` que o servidor fornece (`legacy_geometry`), sem valores na tela.

### D6. Caixa dos títulos

`section.title.upper()` sai do renderer. A política fica em
`HeadingCase = PRESERVE | UPPER | TITLE_CASE | SENTENCE_CASE` por nível. Perfil sem
`layout` mantém o comportamento legado (título 1 em caixa-alta). Para novos perfis, o
padrão segue `padrao-estrutura-laudo.md` (REGRA APROVADA): caixa-alta só no título de
capítulo (nível 1); subtítulos preservam a grafia.

### D7. DOCX × DOCM

`padrao-visual-word.md` diz "manter `.docm` nesta fase" e registra que os DOCM
analisados não têm `vbaProject.bin`. O modelo padrão gerado continua **DOCX**: sem
macro, o conteúdo é o mesmo e não há alerta de macro no Word. Modelos personalizados
**DOCM** continuam aceitos e validados, e o formato da saída segue o modelo. Nada
muda para quem já usa DOCM.

### D8. Modelo personalizado é autoridade visual

Com modelo Word personalizado selecionado, logo, marca d'água, fundo, cabeçalho e
rodapé globais **não** são aplicados por cima. A UI informa: "Modelos Word
personalizados preservam a identidade visual e a formatação existentes no arquivo."

- O modelo padrão da perícia sai do snapshot dela (#270), nunca do padrão global do
  dia: sem snapshot, V1 byte-idêntico; com snapshot, V2 (`PRODUCT-DEFAULT-REPORT-V2`)
  com a identidade capturada; com modelo próprio selecionado, o arquivo capturado
  volta como está.
- A seleção `CUSTOM` cita o SHA-256 do modelo guardado, e nenhuma gravação desfaz
  isso: com ela ativa, trocar, remover ou restaurar o modelo é recusado (409
  `TEMPLATE_IN_USE`, "escolha o modelo padrão do produto antes"), e restaurar uma
  seleção que cita outro arquivo também. A criação da perícia confere a seleção antes
  de copiar qualquer byte.
- O envio do modelo próprio faz uma vinculação de teste com o laudo fictício. Word
  válido que não vincula como modelo enviado é recusado na hora (`TEMPLATE_FIELDS`),
  e não na entrega.
- O modelo próprio declara o seu `TEMPLATE_ID` e vincula os campos dos modelos
  enviados (`EXPERT_FULL_NAME`, `EXPERT_REGISTRATION`, `REPORT_ID`). O identificador
  de um modelo do produto é recusado, porque implica outro conjunto de campos.
- O V2 tem conjunto fixo de campos (`PROCESS_NUMBER`, `COURT`,
  `PARTICIPANTS_ACTIVE`, `PARTICIPANTS_PASSIVE` e os três do perito). A capa sempre
  identifica processo, juízo e polos; as opções de capa escolhem logotipo, perito,
  cidade e ano.
- O texto fixo do cabeçalho vem do perfil profissional do laudo aprovado que gerou o
  modelo. O modelo carrega `EXPERT_PROFILE_DIGEST`, e a vinculação recusa um laudo
  com outro perfil: o cabeçalho nunca mostra outra identidade em silêncio.
- O que da identidade aparece (registro, cadastros, telefone, e-mail) é decidido só
  pelo `ProfilePresentation` do perfil profissional. As opções de cabeçalho e rodapé
  da instalação tratam apenas de disposição: uma só autoridade de exposição.

### D9. Marca d'água, fundo e imagens no Word

Marca d'água e fundo são desenhados como imagem ancorada atrás do texto na parte de
cabeçalho, para aparecer igual no Word e no PDF. A cor de fundo de página do Word não
é usada, porque não imprime por padrão. O padrão é sem fundo (branco) e marca d'água
no corpo, centralizada, em baixa opacidade. Opacidade acima do limite seguro gera
alerta.

- Fundo, marca d'água e linha separadora formam **uma** imagem de página PNG, opaca e
  pré-composta (a opacidade é aplicada na mistura com o fundo). O validador de
  fidelidade recusa transparência, máscara e recorte; uma imagem opaca não precisa de
  exceção.
- A linha separadora entra nessa imagem, e não como borda de parágrafo, porque o
  validador só aceita traços pintados vinculados a tabelas.
- Mudança no validador (área protegida, `word-trust-rebind`): só a imagem ancorada
  **atrás do texto** (`behindDoc="1"`) de cabeçalho/rodapé deixa de exigir a faixa
  superior/inferior da página. Em troca, ela fica presa à posição exata em cada página
  (±2 pt) e à **ordem de desenho**: tem de ser pintada antes de toda imagem e de todo
  caminho pintado (sombreamento e bordas de tabela) que cruza.
  O texto que ela cruza já é protegido pela checagem de oclusão por raster. A faixa
  sozinha não dizia nada sobre sobreposição; a ordem de desenho diz. Âncora na frente
  do texto e imagem em linha continuam presas à faixa. Testes provam:
  - aceitos: fundo claro atrás do texto; âncora atrás desenhada antes da foto; âncora
    que não cruza a foto;
  - recusados: imagem opaca por cima do texto; fundo escuro atrás do texto; imagem
    deslocada; âncora "atrás" pintada por cima de uma foto do corpo; âncora na frente
    fora da faixa.
- Marca d'água de texto é desenhada como imagem com fonte local; sem fonte TrueType
  disponível, a geração falha fechada com mensagem.
- Toda imagem tem descrição alternativa; a imagem de página é marcada como decorativa.
- A prova em Word 16 real (paginação, PDF derivado fiel) é do Human RC (passo W16); os testes
  nativos ficam pulados onde o Word não existe.

### D11. Citação longa

Parágrafo de afirmação que o perito inicia com "> " vira bloco `QUOTE`: estilo
"Quote" quando o modelo o tem; senão, formatação direta com recuo, redução de fonte e
entrelinha do `EditorialLayout`. O texto da afirmação não muda; só a apresentação.

### D12. Documento de teste

`GET /v1/installation/test-document` gera um Word com um laudo fictício
(`sample_report`), pelo mesmo caminho do laudo real (modelo V2 ou o modelo próprio,
vinculação e validação final). Nada é gravado; nada pertence a uma perícia.

### D10. Perfil jurídico-editorial

`LEGAL_EDITORIAL_PROFILE_V1` (rótulo "Sistema Pericial — CNJ/TRF5") é política
complementar ao `EditorialProfile` e ao `padrao-redacao.md`, não um segundo sistema de
texto. O preflight só **avisa** (sigla sem forma extensa na primeira ocorrência,
latinismo, estrangeirismo, expressão rebuscada, período e parágrafo longos) e nunca
reescreve texto técnico. Marcadores `[INFORMAÇÃO NECESSÁRIA` e `[VALIDAÇÃO DO PERITO`
bloqueiam a emissão final em qualquer texto que o Word apresentaria:
- afirmações e respostas;
- os demais textos do corpo (participantes, imóvel, referências, legendas, quesitos);
- os campos de capa e cabeçalho do modelo (juízo, polos, identidade do perito);
- o perfil profissional.

Cada pendência diz onde está. Na emissão, uma última barreira varre o Word já
vinculado (corpo, cabeçalhos e rodapés). O XML é lido pelo namespace, com qualquer
prefixo; o texto é juntado por parágrafo, com tabulação e quebra como espaço, e as
caixas de texto entram como parágrafos próprios. Ela cobre o texto fixo de um modelo
personalizado.

A captura das configurações na perícia, a atualização e o documento de teste leem a
instalação num único retrato: seleção do modelo, perfil e ativos do mesmo estado. Invariantes (`AI_PROPOSAL != PROFESSIONAL_DECISION`,
`ALLEGATION != FACT`, `DOCUMENTED_FACT != PERICIAL_FINDING`, proveniência, Word
autoritativo, PDF derivado, egress privado negado) **não** são preferências e não
aparecem como opção.

## Registro de fontes oficiais (consultadas em 2026-10-02)

| Fonte | URL | Data | Escopo | Regra usada | Natureza |
|---|---|---|---|---|---|
| Recomendação CNJ n. 144/2023 | https://atos.cnj.jus.br/atos/detalhar/5233 | 25/08/2023 (DJe/CNJ 206/2023) | Tribunais e Conselhos, exceto STF | Linguagem simples, clara e acessível nos atos; versão simplificada para conteúdo técnico-jurídico | Recomendatória |
| Lei n. 15.263/2025 — Política Nacional de Linguagem Simples | https://www.planalto.gov.br/ccivil_03/_ato2023-2026/2025/lei/l15263.htm | 14/11/2025 (DOU 17/11/2025) | Administração pública direta e indireta de todos os Poderes, na comunicação com a população | Art. 5º: ordem direta, frases curtas, uma ideia por parágrafo, explicar termos técnicos, evitar estrangeirismo não corrente, nome completo antes da sigla, voz ativa, evitar intercaladas e redundâncias | Obrigatória para a administração pública em textos dirigidos ao cidadão; para o laudo do perito, referência aplicada por analogia |
| Manual de Redação — Programa Justiça Plural (CNJ/PNUD), cap. 4 | https://www.cnj.jus.br/wp-content/uploads/2026/04/manual-de-redacao-justica-plural.pdf | 2026 | Publicações do Programa Justiça Plural | Sigla por extenso na 1ª ocorrência; citação direta acima de três linhas em bloco recuado com fonte 1 pt menor; itálico para estrangeirismo não incorporado; maiúsculas/minúsculas; atos normativos com "n." | Institucional (padronização editorial); adotado como perfil padrão por decisão humana na #131 |
| Pacto Nacional do Judiciário pela Linguagem Simples — referências | https://www.cnj.jus.br/gestao-da-justica/acessibilidade-e-inclusao/pacto-nacional-do-judiciario-pela-linguagem-simples/referencias-normativas/ | consultada em 2026-10-02 | Judiciário | Lista Rec. 144/2023, Portaria CNJ 351/2023 (selo) e Res. CNJ 376/2021 | Institucional |
| TRF5 — notícia sobre a Lei 15.263 | https://www.trf5.jus.br/index.php/noticias/leitura-de-noticias?%2Fid=327351 | 19/11/2025 | Comunicação do TRF5 | Confirma a adesão ao Pacto e a aplicação da Lei 15.263 | Institucional (secundária) |
| TRF5 — Orientação 01/2024 da Vice-Presidência | não localizada em fonte primária pública | 2024 | Documentos do Gabinete da Vice-Presidência | Citada em notícia e relatório de gestão: linguagem simples, inclusiva e acessível; explicar termos complexos | Institucional interna; **não** é norma obrigatória para o perito. Texto primário: `[INFORMAÇÃO NECESSÁRIA: localizar o ato oficial]` |

Nenhuma dessas fontes fixa formatação obrigatória (fonte, margens, entrelinha) para
laudo pericial. A UI usa "Perfil editorial de referência" e nunca "formatação
obrigatória CNJ".

## Consequências

- #268 é corrigido sem perder dados legados nem tornar laudos antigos `stale`
  apenas por atualização.
- A configuração global é auditável (histórico append-only) e nunca reescreve uma
  perícia existente.
- O banco das perícias não muda de schema. A instalação ganha um arquivo SQLite
  próprio (schema 1), que falha fechado com schema desconhecido.
- Pendência aberta no texto bloqueia a renderização do Word final em qualquer perfil.
