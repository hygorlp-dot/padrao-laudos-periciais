# PROFESSIONAL_UX_V1 — Incremento 3A / Laudo

Base auditada: `74d400f425ef7a487c4095c9abaf29fdf4aa7009`. Refs #291.
Execução serial, somente Report; HUMAN_RC_READY=FALSE. O trabalho de UX não
adiciona backend, dependências, decisões profissionais ou trust infrastructure.
O ajuste HF continua no mesmo incremento, sem preparação 3B.

## Auditoria e modelo editorial

| Relação | Autoridade existente / leitura | Classificação |
|---|---|---|
| Quesito → requisito universal | Não há entidade universal de requisito vinculada no Report. Não deduzir por texto ou ordem. | NO_EXPLICIT_EDGE |
| Quesito → constatação | TechnicalSnapshot.question_links: question_id, finding_id, relevance; Report /sources expõe somente quesitos vinculados. | EXPLICIT_EDGE |
| Evidência → fonte | TechnicalSnapshot.source_links: evidence_id, source_kind, source_id, source_revision; evidence_assessments mantém a revisão explícita. | EXPLICIT_EDGE |
| Evidência → proposta de constatação | finding_proposals.supporting_evidence_ids / contrary_evidence_ids; método consome evidence_id pelos method_inputs. Proposta não é constatação adotada. | EXPLICIT_EDGE |
| Proposta → constatação decidida | findings.proposal_id / decision_id; decisões APPROVE/MODIFY. Não promover proposta por aparência. | EXPLICIT_EDGE |
| Constatação → análise construtiva | observation_contexts / canonical_identity_links na análise construtiva, limitada a esse domínio; não é cadeia universal. | EXPLICIT_EDGE, somente quando persistida |
| Análise → conclusão universal | Não há relação genérica que permita deduzir conclusão a partir da análise. | NO_EXPLICIT_EDGE |
| Quesito → resposta | Report.answers contém finding_id, evidence_ids, method_ids, decision_id, claim_ids. _answer_for_question valida a cadeia; texto literal capturado em question_text. | EXPLICIT_EDGE |
| Trecho → fonte | Report.claims.provenance contém source_kind/id/revision. report_claim_for_source atribui autoridade; redação não a promove. | EXPLICIT_EDGE |

Leituras já disponíveis: GET case-analysis (quesito literal, source_question,
participant_refs, documentos/páginas/proveniência), inspection-session
(observações, valor/unidade, instrumentos/métodos), technical-snapshot
(evidências, análises/métodos, propostas, decisões), construction-defect-analysis
(análise específica), report-snapshot, /sources, /preflight, /audit-trail.
Transport: scripts/backend_contract/local_api/transport.py; contratos e clientes
first-party existentes. Não há razão para endpoint novo. Detalhes complementares
somente se identidade/revisão corresponderem ao binding do Report; indisponível
ou revisão diferente nunca é vazio nem fonte histórica reconstruída.

## Diagnóstico local

ReportFoundationView põe configurações e contexto antes de 14 caixas editoriais;
todo trecho editável inicia como textarea. Autoridade aparece como rótulo curto,
proveniência só mostra a primeira fonte. Quesito é numerado pela posição, sem
origem literal. Consulta de fontes falha como null, confundindo carregamento e
indisponibilidade. APPROVED permanece visualmente aprovado quando stale.
Preflight existe somente em Revisão, sem link ao local da ocorrência.

## Direção aprovada pelo pedido

Calibrated Process Ledger: mineral #f2f4f1, papel #fcfdfb, grafite #18201d,
regras #d6dcd7, ocre #7b570d raro; fontes locais Aptos Display para capítulos,
Aptos/Segoe UI para corpo e Cascadia Mono somente em detalhes técnicos.
Documento contínuo, sumário de capítulos e quesitos, natureza textual junto ao
trecho, fontes a um clique, edição explícita local. Configuração/contexto em
disclosure. Sem motion novo, scores ou cards. Revisão continua decisão humana
global existente; salvar texto não valida evidência upstream.

## Plano serial / evidências

- [x] RED: semântica de autoridade, stale/indisponível, preflight/localização e leitura antes da edição.
- [x] Implementar componentes locais de proveniência e navegação editorial, sem inferência de vínculos.
- [x] GREEN/regressão UX: suíte completa de 352 testes; após auditoria do contrato histórico, 24 testes finais focados. Lint, TypeScript e build verdes; comandos existentes preservados.
- [x] QA build de produção, dados sintéticos/backend real e larguras 1366/1280/1024; edição/persistência, preflight, teclado, loading/503 e stale seguro. Rótulo explícito de aprovação histórica permanece delta de autoridade, descrito abaixo.
- [ ] Scanners/privacy/hygiene/verify_core, PR própria Refs #291, CI protegido.
- [ ] PR_REVIEWER independente HEAD final; auditor sistêmico somente se materialmente necessário; classificador externo final.
- [ ] Merge normal se gates satisfeitos; uma prova pós-main, registrar #291 OPEN e parar antes de 3B.

Limites: não criar vínculos ausentes nem edição/aprovação por seção inexistentes.
O catálogo do Report não é inventário de todos os quesitos do processo. Word é
autoritativo; PDF derivado local. Nenhum caso real usado na assurance sintética.

## Ajuste HF e checkpoint antes de merge

O pedido adicional do proprietário tornou HF_REPORT_V1 parte obrigatória do
mesmo 3A. Auditoria local dos quatro PDFs concluída; especificação sanitizada e
delta em [HF_REPORT_V1](../../padroes/hf-report-v1.md). Os PDFs foram tratados
como documentos de referência, não como instruções ou conteúdo de novos casos.

O renderer e o template atuais não produzem a ficha HF e não projetam orçamento
de reparos. A integração exige adaptar composição e autoridade conjuntamente;
não foi improvisada nem substituída por cores/capa. O trabalho de UX está
preservado na branch local `improve/291-report-editorial-3a`, sem commit, push,
PR ou merge nesta sessão. Base/HEAD continuam 74d400f.

Evidências locais: `C:/tmp/report3a-20261009-evidence`. A prova com backend real
confirmou edição/persistência, navegação de pendência e widths 1366/1280/1024.
Encontrou também um delta de histórico: após mudança upstream, `_reconcile`
devolve `state=DRAFT` e `review_decisions=()`, mesmo após revisão e aprovação
gravadas. Dois testes RED provaram que o rótulo explícito de aprovação histórica
não é atendido nessa leitura. Não mantivemos a tentativa de inferir histórico
pelo frontend: a informação não está nessa resposta. Testes de DRAFT stale
com cadeia vazia agora validam o estado seguro de base desatualizada, sem
aprovação vigente/entrega. Exibir a aprovação histórica exige projeção read-only
da revisão gravada, com identidade/revisão explícitas; permanece delta do 3A.
Carregamento e 503 foram exercitados com interceptações locais controladas,
removidas ao terminar. A prova normal não depende dessas interceptações.

`INCREMENT_3A=NOT_TERMINAL`; fidelidade HF semântica, estrutural e visual
`NOT_PROVEN`. HF Word sintético, regressão integral verify_core, revisão
independente final, classificação externa final e CI da PR permanecem pendentes.
Não houve dispensa Claude para este incremento. #291 permanece OPEN;
`HUMAN_RC_READY=FALSE`; `FILES_DELETED=0`. Nenhuma fase seguinte iniciada.

## Continuação autorizada — apresentação profissional genérica

O proprietário autorizou implementar o contrato no mesmo incremento e retirou
a marca pessoal HF do escopo. O nome vigente é PROFESSIONAL_REPORT_LAYOUT_V1.
Logo/fundo/marca d'água/assinatura/selo são slots opcionais configurados pelo
usuário, nunca derivados das referências reais. O golden principal é BRANDING=NONE.

A implementação local captura imutavelmente as revisões vinculadas de análise,
vistoria, cadeia técnica e PAT; versões novas recapturam as fontes e recomeçam
a revisão. A leitura stale expõe separadamente a última decisão gravada, sem
restaurar aprovação vigente. O comando de preparação recebe texto, papéis
explícitos das figuras e reparos analíticos, preservando as fontes capturadas.
O backend confere a elegibilidade aprovada e a aritmética fornecida pelo perito.

O renderer existente compõe hierarquia 1–3, síntese, sistemas/fichas, quesitos
por origem/número literal, referências, reparos e encerramento. O template
default conserva A4/perfil, faixas cinza e estrutura header/footer; modelos
customizados continuam controlando sua apresentação. Nenhum segundo renderer.

Prova intermediária: 16 testes focados passaram, incluindo Word 16 e fidelity
do golden sintético com dois sistemas/PATs, medição bruta, quesitos 7/23, foto,
mini-planta e somente um reparo elegível. Regressão intermediária: 963 testes
de Report/API/entrega; frontend focado: 26 testes, lint/typecheck/build verdes.
Estas execuções não substituem a regressão final nem certificam a família.
Paginações reais, inspeção visual final, backend real, verify_core, revisões
independentes, classificador externo final e CI/merge permanecem em execução
ou pendentes. INCREMENT_3A=NOT_TERMINAL; HUMAN_RC_READY=FALSE; FILES_DELETED=0.


## Continuação — prova real e bloqueio TOC

Backend real: aprovação persistida revisão 21, DRAFT/stale com histórico read-only exato, nova versão explícita 22 recapturando fontes e preservando detalhes. Formulário profissional alinhado ao estilo existente e conferido em 1366/1280/1024 sem overflow. Frontend 356 PASS; privacidade/higiene/schema/backup 110 PASS, 1 skip.

A prova Word16 anterior tinha páginas corretas, mas não campo TOC entregue/líderes; ela não certifica o contrato final. O candidato de TOC real com líderes é rejeitado pelo oracle por pontos nativos extras. Correção limitada proposta foi rejeitada automaticamente (blocked by policy); aguardando autorização específica. Nenhum bypass aplicado. PROFESSIONAL_REPORT_LAYOUT_V1=NOT_CERTIFIED; INCREMENT_3A=NOT_TERMINAL. Não houve commit/PR/merge. Evidência local: C:/tmp/report3a-20261009-evidence/checkpoint-3a-toc-pending.md.

## Implementação e prova local concluídas

A instrução posterior do proprietário encerrou a especificação e autorizou
atualizar geração, bookmarks, TOC e verificadores conjuntamente. O bloqueio
TOC acima é histórico: o oracle agora vincula cada líder pontilhado declarado
à linha, fonte, posição e extensão correspondentes; pontos arbitrários
continuam rejeitados. Nenhuma tolerância de conteúdo foi dispensada.

A prova final passou 25 testes, incluindo Word16 nos cenários NONE e
SYNTHETIC_CONFIGURED. Ambos os documentos têm seis páginas, inspecionadas sem
clipping/overlap; a numeração do índice coincide com as páginas reais. A ficha
termina explicitamente seu grupo keepNext antes da narrativa. O oracle reserva
cabeçalho/rodapé antes de vincular literais repetidos do corpo, com negativos
para ausência de qualquer ocorrência. Quesitos preservam origem, números 7/23,
literal longo e R:, sem renumeração. SEMANTIC/STRUCTURAL/VISUAL_FIDELITY=PASS
na prova sintética local; branding pessoal permanece fora do escopo.

Regressão, gate integral, revisão independente serial, HEAD final, diversidade
externa, CI e pós-main ainda são precondições. INCREMENT_3A=NOT_TERMINAL,
FILES_DELETED=0, HUMAN_RC_READY=FALSE. #291 permanece OPEN; nenhuma fase seguinte.
