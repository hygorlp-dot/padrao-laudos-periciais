# PROFESSIONAL_UX_V1 — Incremento 3D / Configurações (#291)

BASE: `5a81239168c87847dd542f8051d58b85383aa8bc`.
Estado: implementação e assurance em preparação para candidato final; este registro não declara merge, pós-main ou RC.
`FILES_DELETED=0`; `HUMAN_RC_READY=FALSE`; nenhuma alteração em branch protection, schemas, defaults, persistência ou renderer.

## Autoridades e correções causais

Configurações globais permanecem padrões para novas perícias. O resumo da perícia lê o snapshot e o expert-profile próprios; não preenche lacunas com o global. Atualização continua explícita, com confirmação e perfil opcional. Defaults globais não entram na recuperação de outra instalação.

RED → correção mínima → GREEN demonstrados para: draft obsoleto após conflito enquanto GET ainda está pendente; disputa entre save e geração; snapshot escondido quando global indisponível; resultado desconhecido de refresh apresentado como rollback; HTML 200 oferecido como Word; restauração de ativo existente no domínio, mas inacessível por HTTP (404).

A única ampliação de backend expõe `POST /installation/assets/<ROLE>/restore` pela allowlist da ponte para o comando append-only existente. DTO fechado, inteiros positivos, optimistic concurrency e guard de template em uso permanecem obrigatórios. Não há nova autoridade, storage ou default.

Adversariais cobrem resposta e observação indisponíveis (não repetir refresh antes de ler a autoridade), troca de perícia durante consulta/confirmacão, conflitos, DTO extra/inválido e restauração de modelo em uso. Detalhes técnicos e históricos ficam em disclosures nativos.

O primeiro PR_REVIEWER bloqueou o candidato por resultado desconhecido de mutação global: `run` só relia a autoridade em conflito, liberando comandos após falha de transporte. Dois testes montados reproduziram o defeito antes da correção. Agora falha de transporte ou resposta indisponível também aguarda GET, remonta drafts com a autoridade observada e pede conferência sem afirmar sucesso. Se GET falhar, formulários e geração permanecem inacessíveis até leitura manual bem-sucedida. Rejeições explícitas de validação preservam seus motivos. Um adversarial adicional cobre restauração de logotipo persistida sem resposta, observando rev3 com um único POST. O novo HEAD exige novo gate, CI e revisões finais; evidência anterior não aprova o candidato corrigido.

## Prova sintética no produto

Build de produção e navegador real, duas instalações locais distintas; somente perfil, imagens e modelo Word sintéticos. Evidência operacional fora do Git: `C:/tmp/settings3d-20261011-evidence`.

- Perfil profissional com cadastros em tribunais separados; seis papéis de imagem configurados; cores, apresentação e editorial próprios. Histórico de cores e logotipo: rev1 → rev2 → restore → rev3; a restauração preserva as anteriores.
- Imagens vazia, indecodificável e abaixo do limite são rejeitadas com motivo e recuperação. Logo anterior preservado. Nomes longos enviados como FilePayload do navegador: o caminho físico longo foi recusado pelo navegador antes do HTTP, sem mutação do backend.
- Custom template válido enviado, selecionado e usado na geração; substituição e remoção bloqueadas enquanto em uso; retorno ao modelo do sistema explícito.
- Documento de teste real A sem marca, B com seis ativos sintéticos e C custom, baixados pela UI. Word Desktop COM **16.0** abriu e derivou PDFs: 3, 4 e 3 páginas. PAGE/NUMPAGES presentes; Word autoritativo intacto por SHA-256. Inspeção visual de capa, sumário, corpo e fechamento; nenhuma corrupção ou texto fora da página detectado. Nenhum renderer alterado.
- CASE A capturou V1; alteração global V2 manteve A intacta; nova CASE B capturou V2. Atualização confirmada de A com perfil produziu snapshot rev2 e Report upstream-stale pelas regras existentes; não houve emissão automática.
- Word histórico SHA-256 `1b336df36a26a51d0873db281cd09fc1838599d02cc7e8199fbeb73f61e86ccb`; PDF histórico `2cdfffd6713c35f3b63d20e575d7a77dd4e1af6af2b317639ff1417639af4ded`. Após refresh e recuperação os bytes e metadados permaneceram iguais. Um timeout da renderização foi resolvido por leitura do resultado persistido, com **zero repetição** do comando.
- Backup A → verificação → staging → revisão → promoção → reopen pela UI real preservou snapshot, perfil, seis ativos e documentos. Padrões da instalação de destino, distintos dos de A, permaneceram iguais antes/depois.

## UX Auditor — Impeccable

`IMPECCABLE_NO_UPDATE_CHECK=1`; contexto e detector locais. Detector: `[]`. Sem provider, instalação ou update de skill. Hierarquia linear segundo DESIGN.md, seis seções ordenadas, uma ação primária por contexto, sem dashboard, wizard ou motion decorativo.

| Dimensão | Nota / 4 | Evidência e limite |
|---|---:|---|
| Acessibilidade | 3 | Labels, landmarks, headings, status/alert, disclosure Enter, foco visível 3px; confirmação foca checkbox e cancelamento retorna ao heading. Não é certificação WCAG integral. |
| Performance | 3 | Nenhuma dependência nova ou animação cara; artefatos sob demanda. Warning existente do bundle maior que 500 kB não foi tratado como regressão material. |
| Responsividade | 3 | Produção 1366/1280/1024, perfis longos, sete cadastros, arquivos longos, histórico, custom, diferenças e erro: overflow horizontal zero. Escopo desktop aprovado. |
| Theming | 3 | Tokens existentes, tipografia e ritmo do ledger; nenhum tema novo. |
| Integridade | 4 | Global != snapshot capturado; unavailable != default; decisões explícitas e histórico acessível. Detector sem findings. |
| Total | 16/20 | Good no escopo examinado; sem P0/P1 aberto nesta auditoria UX. |

Defeito reproduzido em 1024: coluna de conteúdo da imagem da marca d'água tinha 23px porque as duas ações ocupavam a terceira coluna auto. Correção mínima põe ações na linha seguinte. Confirmação proporcional: conteúdo passou a 557px em 1024 (788/856px em 1280/1366), sem overflow, texto legível em screenshot. Não houve rodada preventiva de polish.

Tracking P2: `CONTEXT_STALE design-sidecar-stale` — DESIGN.md é mais recente que `.impeccable/design.json`; o contexto canônico foi lido, sem refresh do sidecar nesta UOW. Não impede o fluxo nem autoriza alterar design. Nenhuma recomendação de expansão nesta execução.

Tracking do primeiro Reviewer: os controles de registro na capa/assinatura e de marca d'água nos anexos são salvos pelo contrato, mas não consumidos pelo renderer atual (P2). Permanecem registrados sem redesenhar o renderer ou reabrir fidelidade nesta UOW; não constituem prova de efeito visual.

## Assurance e sequência terminal

O SYSTEMIC_AUDITOR bloqueou o segundo candidato (`85533cf`) com P0=0/P1=1/P2=1. Uma perícia sintética real confirmou o P1: após aprovação, mudança global da capa e atualização explícita com `include_profile=false`, o perfil permanecia idêntico, mas o Report continuava APPROVED/non-stale e aceitava um template com apresentação diferente. O teste persistido falhou em `upstream_stale is True` antes da correção.

A correção vincula revisão/checksum do **snapshot existente da perícia** à autoridade capturada do Report. Get, Save, início e nova versão usam esse vínculo; a projeção de workflow também. Mudança explícita é observada pelas regras existentes como DRAFT/stale, com decisões atuais retiradas e revisão histórica preservada no registro original. Save inclui a captura validada no CAS; o verificador de backup exige sua dependência histórica. Não há nova tabela, storage, lifecycle, alteração de claims/answers, ProfessionalReportProjection ou renderer. Global não é consultado por essa reconciliação.

Compatibilidade: os dois metadados são opcionais e pareados; registros legados mantêm o mapping e os bytes exatos. Um Report legado sem vínculo permanece válido somente com captura rev1 cuja proveniência existente é `WORKSPACE_CREATED`. A primeira adoção explícita em uma perícia legada também produz rev1, mas tem razão `UPDATED_FROM_INSTALLATION_DEFAULTS` e exige nova versão/revisão. Captura posterior ou proveniência não comprovada também exige revisão, pois não prova qual atualização a aprovação cobriu. Essa regra conservadora não reescreve o histórico. Restaurar os mesmos padrões não ressuscita aprovação; a nova versão captura a revisão atual e inicia sem decisões.

O PR_REVIEWER do candidato `4194a78` reproduziu esse caminho de primeira adoção, P0=0/P1=1/P2=1. Cinco casos RED demonstraram manutenção indevida da aprovação e aceitação pelo consumidor antes da correção. O Report usa a proveniência da mesma leitura validada de Settings; o consumidor também confere essa proveniência na segunda leitura. Nove cenários focais passaram após a correção, incluindo captura ausente antes da atualização real, preservação do registro aprovado histórico e bloqueio de template após a adoção explícita. Regressão ampliada de Settings, Report, Delivery, backup e recovery: **865 PASS / 8 skips**, 190,81 s. A revisão bloqueada e o CI/gate desse HEAD não autorizam o candidato corrigido; novas evidências finais são obrigatórias.

Regressão causal: **73 testes PASS** em Settings/Report, incluindo atualização global isolada, atualização explícita sem perfil, leitura repetida stale, restore sem promoção da aprovação, nova versão e reaprovação explícita, Word anterior/histórico preservados no backup, compatibilidade legada, identidade de perícia, pares inválidos e CAS SQLite com alteração concorrente. Um teste de backup também falhou antes de adicionar a exigência da dependência capturada. Regressão ampliada de Report/Delivery/Word nativo/Recovery/SQLite: **1.178 PASS, 8 skips**, 475,29 s. Complemento após correção da segunda leitura do consumidor: **50 PASS**, 58,66 s, incluindo quatro cenários RED de captura divergente/ausente e recovery real do Report com o novo vínculo, sem alterar os padrões globais do destino. O consumidor confere revisão/checksum antes da geração; a mesma captura imutável é usada até o fim. Logs intermediários de montagem de fixtures não são evidência GREEN. Novos gates/reviews permanecem necessários; nenhum resultado do candidato bloqueado autoriza merge do novo HEAD.

Frontend integral após a correção do P1: **411 testes / 47 arquivos PASS**. Regressão focal e demais gates terão os recibos anexados à PR no HEAD final.

Sequência restante obrigatória: gate integral fresco único → CI protegido → PR_REVIEWER independente → SYSTEMIC_AUDITOR independente → classificador first-party → Claude se requerido ou dispensa específica do proprietário → merge normal → uma prova pós-main → reconciliação da #291 se todos os incrementos terminais → parar.

Nenhuma dispensa Claude anterior se transfere ao 3D. Este documento não declara reviews independentes nem autorização externa antes de seus recibos. Não iniciar RC, caso real, packaging, installer ou release.
